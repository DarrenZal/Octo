"""
Web Source Monitor — Background task for periodically checking monitored URLs

Follows the same pattern as GitHubSensor: asyncio background task with
start/stop lifecycle. Periodically checks monitored web sources for content
changes, re-runs LLM extraction + entity ingestion when content changes.

URLs are tracked via the web_submissions table (status='monitoring').
Content changes are detected by comparing content_hash values.
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

import asyncpg

from api.web_fetcher import fetch_and_preview
from api.llm_enricher import extract_from_content, is_enrichment_available

logger = logging.getLogger(__name__)

# Default scan interval: 24 hours
DEFAULT_SCAN_INTERVAL = int(os.getenv("WEB_SENSOR_INTERVAL", "86400"))


class WebSensor:
    """Background task that monitors web URLs for content changes."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        event_queue=None,
        ingest_fn=None,  # async function to call for re-ingestion
    ):
        self.pool = pool
        self.scan_interval = scan_interval
        self.event_queue = event_queue
        self.ingest_fn = ingest_fn
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_scan: Optional[datetime] = None
        self._scan_count = 0

    async def start(self):
        """Start the background monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(f"Web sensor started (interval={self.scan_interval}s)")

    async def stop(self):
        """Stop the background monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Web sensor stopped")

    async def _scan_loop(self):
        """Main loop: check all monitored URLs, then sleep."""
        # Initial delay to let the API fully start
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._check_all_sources()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Web sensor scan error: {e}", exc_info=True)

            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                raise

    async def _check_all_sources(self):
        """Check all monitored URLs for content changes."""
        async with self.pool.acquire() as conn:
            sources = await conn.fetch(
                """SELECT id, url, title, content_hash, content_text, fetched_at
                   FROM web_submissions
                   WHERE status = 'monitoring'
                   ORDER BY fetched_at ASC NULLS FIRST"""
            )

        if not sources:
            logger.info("Web sensor: no monitored URLs")
            return

        logger.info(f"Web sensor: checking {len(sources)} monitored URLs")
        updated = 0
        errors = 0

        for source in sources:
            try:
                changed = await self._check_source(dict(source))
                if changed:
                    updated += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Web sensor error for {source['url']}: {e}")
                errors += 1
                # Don't stop checking other URLs
                continue

            # Small delay between checks to be polite
            await asyncio.sleep(2)

        self._last_scan = datetime.now(timezone.utc)
        self._scan_count += 1
        logger.info(
            f"Web sensor scan #{self._scan_count}: "
            f"{len(sources)} checked, {updated} updated, {errors} errors"
        )

    async def _check_source(self, source: dict) -> bool:
        """Check a single URL for content changes. Returns True if content changed."""
        url = source["url"]
        old_hash = source["content_hash"]

        # Fetch fresh content
        try:
            preview = await fetch_and_preview(url)
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return False

        if not preview.content_text or not preview.content_text.strip():
            logger.warning(f"Empty content from {url}")
            return False

        # Compute content hash
        new_hash = hashlib.sha256(preview.content_text.encode()).hexdigest()[:16]

        if new_hash == old_hash:
            # No change — just update fetched_at
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE web_submissions SET fetched_at = NOW() WHERE id = $1",
                    source["id"]
                )
            logger.debug(f"No change: {url}")
            return False

        logger.info(f"Content changed: {url} (hash {old_hash} → {new_hash})")

        # Store updated content
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE web_submissions
                   SET content_text = $1, content_hash = $2, title = $3,
                       fetched_at = NOW(), word_count = $4
                   WHERE id = $5""",
                preview.content_text,
                new_hash,
                preview.title or source["title"],
                len(preview.content_text.split()),
                source["id"],
            )

        # Run LLM extraction if available
        if is_enrichment_available():
            await self._extract_and_update(url, preview.content_text, preview.title or source["title"])

        # Emit KOI-net event if available
        if self.event_queue:
            try:
                await self.event_queue.add({
                    "type": "UPDATE",
                    "rid_type": "web_source",
                    "rid": f"web:{url}",
                    "data": {"url": url, "title": preview.title, "content_changed": True},
                })
            except Exception as e:
                logger.warning(f"Failed to emit event for {url}: {e}")

        return True

    async def _extract_and_update(self, url: str, content_text: str, title: str):
        """Run LLM extraction on changed content and update entity descriptions."""
        try:
            # Get existing entities for matching context
            async with self.pool.acquire() as conn:
                existing = await conn.fetch(
                    """SELECT er.entity_text as name, er.entity_type as type
                       FROM entity_registry er
                       JOIN document_entity_links del ON del.entity_uri = er.fuseki_uri
                       JOIN web_submissions ws ON ws.rid = REPLACE(del.document_rid, 'web:', '')
                       WHERE ws.url = $1""",
                    url
                )
                existing_entities = [dict(r) for r in existing]

            result = await extract_from_content(
                source_content=content_text,
                source_title=title,
                source_url=url,
                existing_entities=existing_entities,
            )

            # Update descriptions for matched entities
            updated = 0
            async with self.pool.acquire() as conn:
                for extracted in result.entities:
                    if not extracted.description:
                        continue

                    # Find matching entity by name (exact + fuzzy)
                    row = await conn.fetchrow(
                        """SELECT fuseki_uri FROM entity_registry
                           WHERE LOWER(entity_text) = LOWER($1)""",
                        extracted.name.strip()
                    )
                    if row:
                        await conn.execute(
                            "UPDATE entity_registry SET description = $1 WHERE fuseki_uri = $2",
                            extracted.description, row["fuseki_uri"]
                        )
                        updated += 1

            if updated > 0:
                logger.info(f"Updated {updated} entity descriptions from {url}")

        except Exception as e:
            logger.error(f"Extraction failed for {url}: {e}")

    async def add_url(self, url: str, title: str = "") -> dict:
        """Add a URL to the monitoring list."""
        async with self.pool.acquire() as conn:
            # Check if already monitored
            existing = await conn.fetchrow(
                "SELECT id, status FROM web_submissions WHERE url = $1", url
            )
            if existing and existing["status"] == "monitoring":
                return {"status": "already_monitoring", "id": existing["id"]}

            if existing:
                # Upgrade existing submission to monitoring
                await conn.execute(
                    "UPDATE web_submissions SET status = 'monitoring' WHERE id = $1",
                    existing["id"]
                )
                return {"status": "upgraded_to_monitoring", "id": existing["id"]}

            # Fetch initial content
            try:
                preview = await fetch_and_preview(url)
                content_text = preview.content_text or ""
                content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16] if content_text else ""
                title = title or preview.title or ""
                word_count = len(content_text.split()) if content_text else 0
            except Exception as e:
                logger.warning(f"Failed initial fetch for {url}: {e}")
                content_text = ""
                content_hash = ""
                word_count = 0

            rid = hashlib.sha256(url.encode()).hexdigest()[:12]
            row = await conn.fetchrow(
                """INSERT INTO web_submissions
                   (url, rid, domain, status, title, content_text, content_hash,
                    word_count, fetched_at, created_at)
                   VALUES ($1, $2, $3, 'monitoring', $4, $5, $6, $7, NOW(), NOW())
                   RETURNING id""",
                url,
                rid,
                url.split("/")[2] if "/" in url else url,
                title,
                content_text,
                content_hash,
                word_count,
            )
            return {"status": "added", "id": row["id"], "words": word_count}

    async def remove_url(self, url: str) -> dict:
        """Remove a URL from monitoring (set status back to 'ingested')."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE web_submissions SET status = 'ingested' WHERE url = $1 AND status = 'monitoring'",
                url
            )
            if "UPDATE 0" in result:
                return {"status": "not_found"}
            return {"status": "removed"}

    async def get_status(self) -> dict:
        """Get monitoring status."""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM web_submissions WHERE status = 'monitoring'"
            )
            sources = await conn.fetch(
                """SELECT url, title, fetched_at, content_hash
                   FROM web_submissions WHERE status = 'monitoring'
                   ORDER BY url"""
            )

        return {
            "enabled": True,
            "running": self._running,
            "monitored_urls": count,
            "scan_interval_seconds": self.scan_interval,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "scan_count": self._scan_count,
            "sources": [
                {
                    "url": s["url"],
                    "title": s["title"],
                    "last_checked": s["fetched_at"].isoformat() if s["fetched_at"] else None,
                    "content_hash": s["content_hash"],
                }
                for s in sources
            ],
        }
