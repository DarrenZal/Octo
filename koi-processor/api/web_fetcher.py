"""
Web Fetcher — URL validation, fetching, and content extraction for Octo.

Extracts content extraction patterns from RegenAI's website_sensor.py into
a lightweight module for on-demand URL preview and ingestion.
"""

import re
import hashlib
import logging
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from datetime import datetime, timezone

import asyncio

import aiohttp
from bs4 import BeautifulSoup

# Playwright is optional — used as fallback for JS-rendered pages
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None

logger = logging.getLogger(__name__)

# Limits
MAX_HTML_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_TEXT_CHARS = 100_000           # 100 KB extracted text
FETCH_TIMEOUT = 30                 # seconds
USER_AGENT = "Octo/1.0 (Salish Sea Knowledge Agent; bioregional knowledge commons)"

# Playwright fallback
PLAYWRIGHT_WORD_THRESHOLD = 50  # If aiohttp gets fewer words, retry with Playwright
PLAYWRIGHT_TIMEOUT = 30000      # ms
PLAYWRIGHT_WAIT = 3             # seconds after networkidle

# Rate limits
RATE_LIMIT_PER_USER_HOUR = 5
RATE_LIMIT_GLOBAL_HOUR = 20


# =============================================================================
# URL Validation (SSRF Protection)
# =============================================================================

class URLValidationError(Exception):
    pass


class URLValidator:
    """Validate URLs with SSRF protection."""

    BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript"}
    BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254", "metadata.aws"}

    def validate(self, url: str) -> str:
        """Validate and normalize a URL. Returns normalized URL or raises."""
        parsed = urlparse(url)

        # Scheme check
        if not parsed.scheme:
            url = f"https://{url}"
            parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            raise URLValidationError(f"Blocked scheme: {parsed.scheme}")

        # Host check
        if not parsed.hostname:
            raise URLValidationError("No hostname in URL")

        hostname = parsed.hostname.lower()
        if hostname in self.BLOCKED_HOSTS:
            raise URLValidationError(f"Blocked host: {hostname}")

        # Block private/reserved IPs
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                raise URLValidationError(f"Blocked private IP: {hostname}")
        except ValueError:
            # Not an IP literal — resolve and check
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for family, _, _, _, sockaddr in resolved:
                    addr = sockaddr[0]
                    ip = ipaddress.ip_address(addr)
                    if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                        raise URLValidationError(
                            f"DNS rebinding: {hostname} resolves to private IP {addr}"
                        )
            except socket.gaierror:
                raise URLValidationError(f"Cannot resolve hostname: {hostname}")

        return url


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class PageMetadata:
    """Extracted page metadata."""
    title: str = ""
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    author: str = ""
    published_date: str = ""
    og_image: str = ""
    site_name: str = ""


@dataclass
class MatchingEntity:
    """An entity from entity_registry found in the page text."""
    name: str
    uri: str
    entity_type: str
    match_context: str = ""  # snippet where the entity was found


@dataclass
class WebPreview:
    """Structured result from URL preview."""
    url: str
    rid: str
    domain: str
    title: str
    description: str
    content_text: str
    content_hash: str
    word_count: int
    metadata: PageMetadata
    matching_entities: List[MatchingEntity] = field(default_factory=list)
    fetch_error: Optional[str] = None
    rendered_with: str = "aiohttp"  # "aiohttp" or "playwright"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "rid": self.rid,
            "domain": self.domain,
            "title": self.title,
            "description": self.description,
            "content_summary": self.content_text[:2000],
            "content_hash": self.content_hash,
            "word_count": self.word_count,
            "rendered_with": self.rendered_with,
            "metadata": {
                "title": self.metadata.title,
                "description": self.metadata.description,
                "keywords": self.metadata.keywords,
                "author": self.metadata.author,
                "published_date": self.metadata.published_date,
                "og_image": self.metadata.og_image,
                "site_name": self.metadata.site_name,
            },
            "matching_entities": [
                {
                    "name": e.name,
                    "uri": e.uri,
                    "type": e.entity_type,
                    "context": e.match_context,
                }
                for e in self.matching_entities
            ],
            "fetch_error": self.fetch_error,
        }


# =============================================================================
# RID Generation
# =============================================================================

def generate_web_rid(url: str) -> str:
    """Generate a KOI-compatible RID for a web page.

    Format: orn:web.page:{domain}/{sha256(url)[:16]}
    Compatible with RegenAI's WebPageRID scheme.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.replace(".", "_").replace(":", "_")
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"orn:web.page:{domain}/{url_hash}"


# =============================================================================
# Content Extraction (ported from RegenAI website_sensor.py)
# =============================================================================

def extract_page_metadata(soup: BeautifulSoup) -> PageMetadata:
    """Extract structured metadata from HTML head."""
    meta = PageMetadata()

    # Title
    title_tag = soup.find("title")
    if title_tag:
        meta.title = title_tag.get_text().strip()

    # Meta tags
    for tag in soup.find_all("meta"):
        name = (tag.get("name") or tag.get("property") or "").lower()
        content = tag.get("content", "")
        if not content:
            continue

        if name in ("description", "og:description"):
            meta.description = meta.description or content
        elif name == "keywords":
            meta.keywords = [k.strip() for k in content.split(",") if k.strip()]
        elif name in ("author", "article:author"):
            meta.author = content
        elif name in ("article:published_time", "date", "dc.date"):
            meta.published_date = content
        elif name == "og:image":
            meta.og_image = content
        elif name == "og:site_name":
            meta.site_name = content

    return meta


def extract_clean_content(soup: BeautifulSoup) -> str:
    """Extract clean text content from HTML.

    Ported from RegenAI website_sensor.py extract_clean_content().
    Finds main content container, strips nav/scripts, deduplicates text.
    """
    # Find main content container
    content_container = None
    for finder in [
        lambda: soup.find("main"),
        lambda: soup.find("article"),
        lambda: soup.find(class_=lambda x: x and "content" in str(x).lower()),
    ]:
        content_container = finder()
        if content_container:
            break

    if not content_container:
        content_container = soup

    # Strip non-content elements
    for tag in content_container(["script", "style", "nav", "footer", "aside", "header"]):
        tag.decompose()

    # Extract text with deduplication (same pattern as sensor)
    seen_texts = set()
    paragraphs = []

    for element in content_container.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "article", "section"]
    ):
        text = element.get_text(separator=" ", strip=True)
        if text and len(text) > 5:
            text = re.sub(r"\s+", " ", text).strip()
            if text not in seen_texts:
                is_subset = any(text in seen for seen in seen_texts)
                if not is_subset:
                    paragraphs.append(text)
                    seen_texts.add(text)

    # List items
    for element in content_container.find_all("li"):
        text = "".join(str(s) for s in element.stripped_strings)
        if text and len(text) > 10:
            text = re.sub(r"\s+", " ", text).strip()
            if text not in seen_texts:
                paragraphs.append(f"- {text}")
                seen_texts.add(text)

    text_content = "\n".join(paragraphs)

    # Collapse multiple blank lines
    text_content = re.sub(r"\n{3,}", "\n\n", text_content).strip()

    # Prepend title if not already present
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text().strip()
        if title and title not in text_content[:200]:
            text_content = f"# {title}\n\n{text_content}"

    # Enforce size limit
    if len(text_content) > MAX_TEXT_CHARS:
        text_content = text_content[:MAX_TEXT_CHARS] + "\n\n[content truncated]"

    return text_content


# =============================================================================
# Entity Scanning
# =============================================================================

async def scan_for_known_entities(
    text: str, db_pool
) -> List[MatchingEntity]:
    """Search extracted text for entity names already in entity_registry.

    Uses case-insensitive word-boundary matching. Returns matches with
    context snippets showing where each entity appears.
    """
    matches = []
    text_lower = text.lower()

    async with db_pool.acquire() as conn:
        # Get all entities with at least 3 chars to avoid noise
        rows = await conn.fetch("""
            SELECT entity_text, fuseki_uri, entity_type
            FROM entity_registry
            WHERE LENGTH(entity_text) >= 3
            ORDER BY LENGTH(entity_text) DESC
        """)

    for row in rows:
        name = row["entity_text"]
        name_lower = name.lower()

        # Word-boundary match to avoid partial matches
        pattern = re.compile(r"\b" + re.escape(name_lower) + r"\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            # Extract context snippet (50 chars before/after)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            context = text[start:end].strip()
            if start > 0:
                context = "..." + context
            if end < len(text):
                context = context + "..."

            matches.append(MatchingEntity(
                name=name,
                uri=row["fuseki_uri"],
                entity_type=row["entity_type"] or "Unknown",
                match_context=context,
            ))

    return matches


# =============================================================================
# Rate Limiting
# =============================================================================

async def check_rate_limit(
    db_pool, submitted_by: Optional[str] = None
) -> Optional[str]:
    """Check rate limits. Returns error message if exceeded, None if OK."""
    async with db_pool.acquire() as conn:
        # Global rate limit
        global_count = await conn.fetchval("""
            SELECT COUNT(*) FROM web_submissions
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
        if global_count >= RATE_LIMIT_GLOBAL_HOUR:
            return f"Global rate limit exceeded ({RATE_LIMIT_GLOBAL_HOUR}/hour)"

        # Per-user rate limit
        if submitted_by:
            user_count = await conn.fetchval("""
                SELECT COUNT(*) FROM web_submissions
                WHERE submitted_by = $1
                AND created_at > NOW() - INTERVAL '1 hour'
            """, submitted_by)
            if user_count >= RATE_LIMIT_PER_USER_HOUR:
                return f"Per-user rate limit exceeded ({RATE_LIMIT_PER_USER_HOUR}/hour)"

    return None


# =============================================================================
# Playwright Rendering (fallback for JS-heavy pages)
# =============================================================================

async def fetch_html_with_playwright(url: str) -> Optional[str]:
    """Fetch a page using Playwright for JavaScript rendering.

    Launches a headless Chromium browser, navigates to the URL,
    waits for network idle, then extracts rendered HTML.
    Handles shadow DOM by flattening shadow roots into the document.
    Returns None if Playwright is not available or fails.
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not installed, cannot render JS pages")
        return None

    pw = None
    browser = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT)
        await asyncio.sleep(PLAYWRIGHT_WAIT)

        # First try: get page.content() (works for normal JS-rendered pages)
        html = await page.content()

        # Check if the page uses shadow DOM (web components) —
        # if body.innerText is empty but shadow roots have content,
        # extract text via JS and build a synthetic HTML document.
        body_text = await page.evaluate("() => document.body.innerText || ''")
        if len(body_text.strip()) < 20:
            shadow_text = await page.evaluate("""() => {
                function getAllText(root) {
                    let text = "";
                    if (root.shadowRoot) {
                        text += getAllText(root.shadowRoot);
                    }
                    for (const child of root.childNodes) {
                        if (child.nodeType === Node.TEXT_NODE) {
                            const t = child.textContent.trim();
                            if (t) text += t + " ";
                        } else if (child.nodeType === Node.ELEMENT_NODE) {
                            text += getAllText(child);
                        }
                    }
                    return text;
                }
                return getAllText(document.body);
            }""")
            if len(shadow_text.strip()) > len(body_text.strip()):
                logger.info(
                    f"Shadow DOM detected, extracted {len(shadow_text)} chars "
                    f"from shadow roots for {url}"
                )
                # Get title from the original HTML
                title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
                title = title_match.group(1) if title_match else ""
                # Build synthetic HTML with the shadow DOM text
                paragraphs = [
                    f"<p>{line.strip()}</p>"
                    for line in shadow_text.split("\n")
                    if line.strip()
                ]
                html = (
                    f"<html><head><title>{title}</title></head>"
                    f"<body>{''.join(paragraphs)}</body></html>"
                )

        await context.close()
        await browser.close()
        await pw.stop()

        logger.info(f"Playwright rendered {len(html)} chars for {url}")
        return html

    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        # Ensure cleanup
        try:
            if browser:
                await browser.close()
            if pw:
                await pw.stop()
        except Exception:
            pass
        return None


# =============================================================================
# Main Fetch + Preview
# =============================================================================

async def _fetch_html_aiohttp(url: str) -> Optional[str]:
    """Fetch raw HTML with aiohttp. Returns HTML string or None on error."""
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                max_redirects=5,
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get("Content-Type", "")
                if not any(ct in content_type for ct in ("text/html", "application/xhtml")):
                    return None

                html_bytes = await response.content.read(MAX_HTML_BYTES)
                return html_bytes.decode("utf-8", errors="replace")

    except Exception as e:
        logger.warning(f"aiohttp fetch failed for {url}: {e}")
        return None


async def fetch_and_preview(
    url: str, db_pool=None
) -> WebPreview:
    """Fetch a URL and return a structured preview.

    1. Validate URL (SSRF protection)
    2. HTTP fetch with aiohttp
    3. Parse HTML with BeautifulSoup
    4. Extract clean content and metadata
    5. If content is sparse (< 50 words), retry with Playwright
    6. Scan for known entities (if db_pool provided)
    7. Return WebPreview
    """
    validator = URLValidator()
    url = validator.validate(url)

    parsed = urlparse(url)
    domain = parsed.netloc
    rid = generate_web_rid(url)

    def _make_error(msg: str) -> WebPreview:
        return WebPreview(
            url=url, rid=rid, domain=domain,
            title="", description="", content_text="",
            content_hash="", word_count=0,
            metadata=PageMetadata(),
            fetch_error=msg,
        )

    # Step 1: Try aiohttp (fast, lightweight)
    html = await _fetch_html_aiohttp(url)
    rendered_with = "aiohttp"

    if html is None:
        # aiohttp failed entirely — try Playwright directly
        if PLAYWRIGHT_AVAILABLE:
            logger.info(f"aiohttp failed for {url}, trying Playwright")
            html = await fetch_html_with_playwright(url)
            rendered_with = "playwright"

        if html is None:
            return _make_error("Failed to fetch URL")

    soup = BeautifulSoup(html, "html.parser")
    metadata = extract_page_metadata(soup)
    content_text = extract_clean_content(soup)
    word_count = len(content_text.split())

    # Step 2: If content is sparse, retry with Playwright
    if word_count < PLAYWRIGHT_WORD_THRESHOLD and rendered_with == "aiohttp" and PLAYWRIGHT_AVAILABLE:
        logger.info(
            f"Sparse content ({word_count} words) from aiohttp, "
            f"retrying {url} with Playwright"
        )
        pw_html = await fetch_html_with_playwright(url)
        if pw_html:
            pw_soup = BeautifulSoup(pw_html, "html.parser")
            pw_metadata = extract_page_metadata(pw_soup)
            pw_content = extract_clean_content(pw_soup)
            pw_word_count = len(pw_content.split())

            # Only use Playwright result if it got more content
            if pw_word_count > word_count:
                logger.info(
                    f"Playwright got {pw_word_count} words vs aiohttp's {word_count}"
                )
                soup = pw_soup
                metadata = pw_metadata
                content_text = pw_content
                word_count = pw_word_count
                rendered_with = "playwright"

    content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()

    # Scan for known entities
    matching_entities = []
    if db_pool and content_text:
        matching_entities = await scan_for_known_entities(content_text, db_pool)

    return WebPreview(
        url=url,
        rid=rid,
        domain=domain,
        title=metadata.title or metadata.site_name or domain,
        description=metadata.description,
        content_text=content_text,
        content_hash=content_hash,
        word_count=word_count,
        metadata=metadata,
        matching_entities=matching_entities,
        rendered_with=rendered_with,
    )
