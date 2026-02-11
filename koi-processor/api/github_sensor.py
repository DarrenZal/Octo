"""
GitHub Sensor — Background task for indexing Git repositories

Clones/pulls monitored repositories, extracts code entities via tree-sitter,
loads them into Apache AGE graph, generates vault notes, and links to known
entities in entity_registry.

Follows the KOIPoller pattern: asyncio background task with start/stop lifecycle.
"""

import asyncio
import hashlib
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import json as json_module
import uuid

import asyncpg

from api.chunker import SentenceAwareChunker
from api.tree_sitter_extractor import (
    TreeSitterExtractor,
    CodeEntity,
    CodeEdge,
    generate_entity_id,
)
from api.code_graph import (
    setup_age,
    ensure_graph,
    load_code_entities,
    load_code_edges,
    sweep_old_entities,
)

logger = logging.getLogger(__name__)

# Default scan interval: 6 hours
DEFAULT_SCAN_INTERVAL = int(os.getenv("GITHUB_SCAN_INTERVAL", "21600"))
CLONE_DIR = os.getenv("GITHUB_CLONE_DIR", "/tmp/github_sensor")
VAULT_PATH = os.getenv("VAULT_PATH", "/root/.openclaw/workspace/vault")

# File extensions to process
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
DOC_EXTENSIONS = {".md", ".yaml", ".yml", ".json", ".toml", ".sql", ".sh"}
ALL_EXTENSIONS = CODE_EXTENSIONS | DOC_EXTENSIONS | {
    ".css", ".html", ".env.example", ".cfg", ".ini",
}

# Directories/patterns to exclude
EXCLUDE_PATTERNS = {
    "node_modules", "venv", ".venv", "__pycache__", ".git",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
    "egg-info", ".eggs",
}

# Language detection
LANG_MAP = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".sql": "sql",
}


class GitHubSensor:
    """Background task that indexes Git repositories into Octo's knowledge graph."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        event_queue=None,
    ):
        self.pool = pool
        self.scan_interval = scan_interval
        self.event_queue = event_queue
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._extractor: Optional[TreeSitterExtractor] = None
        self._chunker = SentenceAwareChunker(chunk_size=500, chunk_overlap=50, min_chunk_size=100)
        self._last_scan: Optional[datetime] = None
        self._scan_count = 0
        self._embed_fn = None  # Set by caller (generate_embedding from personal_ingest_api)

    async def start(self):
        """Start the background scan loop."""
        self._running = True
        self._extractor = TreeSitterExtractor()
        os.makedirs(CLONE_DIR, exist_ok=True)
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(f"GitHub sensor started (interval={self.scan_interval}s)")

    async def stop(self):
        """Stop the background scan loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GitHub sensor stopped")

    async def _scan_loop(self):
        """Main loop: scan all repos, then sleep."""
        while self._running:
            try:
                await self._scan_all_repos()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"GitHub sensor scan error: {e}", exc_info=True)

            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                raise

    async def _scan_all_repos(self):
        """Scan all active repositories."""
        async with self.pool.acquire() as conn:
            repos = await conn.fetch(
                "SELECT * FROM github_repos WHERE status = 'active'"
            )

        if not repos:
            logger.info("GitHub sensor: no active repos to scan")
            return

        for repo_row in repos:
            try:
                result = await self._scan_repo(dict(repo_row))
                logger.info(
                    f"Scanned {repo_row['repo_name']}: "
                    f"{result.get('files_processed', 0)} files, "
                    f"{result.get('code_entities', 0)} code entities"
                )
            except Exception as e:
                logger.error(f"Error scanning {repo_row['repo_name']}: {e}", exc_info=True)
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE github_repos SET status='error', error_message=$1, updated_at=NOW() WHERE id=$2",
                        str(e)[:500],
                        repo_row["id"],
                    )

        self._last_scan = datetime.now(timezone.utc)
        self._scan_count += 1

    async def _scan_repo(self, repo: dict) -> dict:
        """Core scan pipeline for one repository."""
        repo_url = repo["repo_url"]
        repo_name = repo["repo_name"]
        branch = repo.get("branch", "main")
        repo_id = repo["id"]

        # 1. Clone or pull
        clone_path = os.path.join(CLONE_DIR, repo_name.replace("/", "_"))
        head_sha = await asyncio.to_thread(
            self._clone_or_pull, repo_url, clone_path, branch
        )

        # 2. Find processable files
        all_files = await asyncio.to_thread(self._find_files, clone_path)

        # 3. Compute content hashes for change detection
        existing_hashes = {}
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT file_path, content_hash FROM github_file_state WHERE repo_id = $1",
                repo_id,
            )
            existing_hashes = {r["file_path"]: r["content_hash"] for r in rows}

        # 4. Process changed files
        all_code_entities: List[CodeEntity] = []
        all_code_edges: List[CodeEdge] = []
        file_results: List[dict] = []
        files_processed = 0

        for file_path in all_files:
            try:
                rel_path = str(Path(file_path).relative_to(clone_path))
                content = await asyncio.to_thread(self._read_file, file_path)
                if content is None:
                    continue

                content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

                # Skip unchanged files
                if existing_hashes.get(rel_path) == content_hash:
                    continue

                ext = os.path.splitext(file_path)[1].lower()
                language = LANG_MAP.get(ext)

                code_entities = []
                code_edges = []
                if language and ext in CODE_EXTENSIONS and self._extractor:
                    code_entities, code_edges = self._extractor.extract(
                        language, content, rel_path, repo_name
                    )
                elif language == "sql":
                    code_entities, code_edges = self._extractor.extract(
                        "sql", content, rel_path, repo_name
                    )

                all_code_entities.extend(code_entities)
                all_code_edges.extend(code_edges)

                # Get git metadata for this file
                git_meta = await asyncio.to_thread(
                    self._get_file_git_meta, clone_path, rel_path
                )

                file_results.append({
                    "rel_path": rel_path,
                    "content": content,
                    "content_hash": content_hash,
                    "ext": ext,
                    "language": language or ext.lstrip("."),
                    "line_count": content.count("\n") + 1,
                    "byte_size": len(content.encode()),
                    "code_entity_count": len(code_entities),
                    "git_meta": git_meta,
                })
                files_processed += 1

            except Exception as e:
                logger.warning(f"Error processing {file_path}: {e}")

        # 5. Store code artifacts in relational table
        async with self.pool.acquire() as conn:
            await self._store_code_artifacts(conn, all_code_entities, head_sha)

        # 6. Load to AGE graph
        run_id = hashlib.sha256(
            f"{repo_name}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]

        async with self.pool.acquire() as conn:
            await setup_age(conn)
            await ensure_graph(conn)

            if all_code_entities:
                e_ok, e_fail = await load_code_entities(conn, all_code_entities, run_id)
                logger.info(f"Graph entities: {e_ok} loaded, {e_fail} failed")

            if all_code_edges:
                ed_ok, ed_fail = await load_code_edges(conn, all_code_edges, run_id)
                logger.info(f"Graph edges: {ed_ok} loaded, {ed_fail} failed")

            # Sweep old entities from previous runs (only if we loaded new ones)
            if all_code_entities:
                await sweep_old_entities(conn, repo_name, run_id)

        # 7. Store file state + generate vault notes + entity links
        async with self.pool.acquire() as conn:
            for fr in file_results:
                await self._store_file_state(conn, repo_id, fr, head_sha)
                vault_path = await self._generate_vault_note(conn, fr, repo_name)
                if vault_path:
                    await conn.execute(
                        "UPDATE github_file_state SET vault_note_path=$1 WHERE repo_id=$2 AND file_path=$3",
                        vault_path, repo_id, fr["rel_path"],
                    )
                # Link entities
                await self._link_entities(conn, fr, repo_name)

        # 8. Store documents in koi_memories + embed + chunk (for RAG)
        if file_results:
            await self._ingest_documents(
                file_results, repo_name, existing_hashes, all_code_entities
            )

        # 9. Emit KOI-net events for changed files
        if self.event_queue and file_results:
            for fr in file_results:
                rid = f"github:{repo_name}:{fr['rel_path']}"
                event_type = "NEW" if fr["rel_path"] not in existing_hashes else "UPDATE"
                try:
                    await self.event_queue.add(
                        event_type=event_type,
                        rid=rid,
                        manifest={"file_path": fr["rel_path"], "language": fr["language"]},
                        contents={"content_hash": fr["content_hash"]},
                    )
                except Exception as e:
                    logger.warning(f"Event emit failed for {rid}: {e}")

        # 10. Update repo metadata
        async with self.pool.acquire() as conn:
            total_files = await conn.fetchval(
                "SELECT COUNT(*) FROM github_file_state WHERE repo_id = $1", repo_id
            )
            total_code = await conn.fetchval(
                "SELECT COUNT(*) FROM koi_code_artifacts WHERE repo_key = $1", repo_name
            )
            await conn.execute(
                """UPDATE github_repos
                   SET last_commit_sha=$1, last_scan_at=NOW(), file_count=$2,
                       code_entity_count=$3, status='active', error_message=NULL, updated_at=NOW()
                   WHERE id=$4""",
                head_sha, total_files, total_code, repo_id,
            )

        return {
            "repo": repo_name,
            "head_sha": head_sha,
            "files_processed": files_processed,
            "total_files": len(all_files),
            "code_entities": len(all_code_entities),
            "code_edges": len(all_code_edges),
        }

    # ========== File operations ==========

    def _clone_or_pull(self, repo_url: str, clone_path: str, branch: str) -> str:
        """Clone or pull a repository. Returns HEAD SHA."""
        if os.path.exists(os.path.join(clone_path, ".git")):
            subprocess.run(
                ["git", "-C", clone_path, "fetch", "origin"],
                check=True, capture_output=True, timeout=120,
            )
            subprocess.run(
                ["git", "-C", clone_path, "reset", "--hard", f"origin/{branch}"],
                check=True, capture_output=True, timeout=30,
            )
        else:
            os.makedirs(clone_path, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1", repo_url, clone_path],
                check=True, capture_output=True, timeout=300,
            )

        result = subprocess.run(
            ["git", "-C", clone_path, "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()

    def _find_files(self, repo_path: str) -> List[str]:
        """Find all processable files in the repository."""
        files = []
        for root, dirs, filenames in os.walk(repo_path):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_PATTERNS and not d.startswith(".")]

            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in ALL_EXTENSIONS or fname in ("Dockerfile", "Makefile", "Procfile"):
                    files.append(os.path.join(root, fname))
        return files

    def _read_file(self, path: str) -> Optional[str]:
        """Read file content, skipping binary files."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # Skip very large files (>500KB)
            if len(content) > 500_000:
                return None
            return content
        except Exception:
            return None

    def _get_file_git_meta(self, repo_path: str, rel_path: str) -> dict:
        """Get git metadata for a specific file."""
        try:
            result = subprocess.run(
                [
                    "git", "-C", repo_path, "log", "-1",
                    "--format=%H|%an|%aI|%s",
                    "--", rel_path,
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split("|", 3)
                if len(parts) == 4:
                    return {
                        "sha": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3][:200],
                    }
        except Exception:
            pass
        return {}

    # ========== Storage ==========

    async def _store_code_artifacts(
        self, conn, entities: List[CodeEntity], commit_sha: str
    ):
        """Upsert code artifacts to koi_code_artifacts table."""
        for entity in entities:
            code_uri = f"code:{entity.repo}:{entity.file_path}:{entity.name}"
            try:
                await conn.execute(
                    """INSERT INTO koi_code_artifacts
                       (code_uri, kind, repo_key, file_path, symbol, language,
                        signature, docstring, line_start, line_end, commit_sha, extraction_run_id)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                       ON CONFLICT (code_uri) DO UPDATE SET
                         kind=EXCLUDED.kind, signature=EXCLUDED.signature,
                         docstring=EXCLUDED.docstring, line_start=EXCLUDED.line_start,
                         line_end=EXCLUDED.line_end, commit_sha=EXCLUDED.commit_sha,
                         extraction_run_id=EXCLUDED.extraction_run_id, updated_at=NOW()
                    """,
                    code_uri,
                    entity.entity_type,
                    entity.repo,
                    entity.file_path,
                    entity.name,
                    entity.language,
                    (entity.signature or "")[:500],
                    (entity.docstring or "")[:500],
                    entity.line_start,
                    entity.line_end,
                    commit_sha,
                    entity.entity_id,  # use entity_id as run_id for tracking
                )
            except Exception as e:
                logger.warning(f"Failed to store artifact {code_uri}: {e}")

    async def _store_file_state(self, conn, repo_id: int, fr: dict, head_sha: str):
        """Upsert file state for change detection."""
        rid = f"github:{fr['rel_path']}"
        git_meta = fr.get("git_meta", {})

        # Parse git date string to datetime (asyncpg requires datetime for TIMESTAMPTZ)
        commit_date = None
        if git_meta.get("date"):
            try:
                commit_date = datetime.fromisoformat(git_meta["date"])
            except (ValueError, TypeError):
                pass

        await conn.execute(
            """INSERT INTO github_file_state
               (repo_id, file_path, content_hash, rid, line_count, byte_size,
                file_type, last_commit_sha, last_commit_author, last_commit_date,
                last_commit_message, code_entity_count, scanned_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
               ON CONFLICT (repo_id, file_path) DO UPDATE SET
                 content_hash=EXCLUDED.content_hash,
                 line_count=EXCLUDED.line_count, byte_size=EXCLUDED.byte_size,
                 last_commit_sha=EXCLUDED.last_commit_sha,
                 last_commit_author=EXCLUDED.last_commit_author,
                 last_commit_date=EXCLUDED.last_commit_date,
                 last_commit_message=EXCLUDED.last_commit_message,
                 code_entity_count=EXCLUDED.code_entity_count,
                 scanned_at=NOW()
            """,
            repo_id,
            fr["rel_path"],
            fr["content_hash"],
            rid,
            fr["line_count"],
            fr["byte_size"],
            fr["language"],
            git_meta.get("sha", head_sha),
            git_meta.get("author"),
            commit_date,
            git_meta.get("message"),
            fr["code_entity_count"],
        )

    async def _generate_vault_note(self, conn, fr: dict, repo_name: str) -> Optional[str]:
        """Generate a vault note for a GitHub file in Sources/GitHub/."""
        # Only generate notes for documentation and significant code files
        ext = fr["ext"]
        if ext not in (".md", ".py", ".ts", ".sql", ".yaml", ".yml", ".json", ".sh"):
            return None

        # Skip very short files
        if fr["line_count"] < 5:
            return None

        rel_path = fr["rel_path"]
        safe_name = rel_path.replace("/", "_").replace(".", "_")
        if len(safe_name) > 80:
            safe_name = safe_name[:80]

        vault_rel = f"Sources/GitHub/{safe_name}.md"
        vault_full = os.path.join(VAULT_PATH, vault_rel)
        os.makedirs(os.path.dirname(vault_full), exist_ok=True)

        git_meta = fr.get("git_meta", {})
        rid = f"github:{repo_name}:{rel_path}"

        lines = [
            "---",
            '"@type": GitHubFile',
            f'name: "{os.path.basename(rel_path)}"',
            f'repo: "{repo_name}"',
            f'path: "{rel_path}"',
            f'language: "{fr["language"]}"',
            f'rid: "{rid}"',
        ]
        if git_meta.get("sha"):
            lines.append(f'commitSha: "{git_meta["sha"][:12]}"')
        if git_meta.get("author"):
            lines.append(f'lastAuthor: "{git_meta["author"]}"')
        if git_meta.get("date"):
            lines.append(f'lastModified: "{git_meta["date"]}"')
        lines.append(f"lineCount: {fr['line_count']}")
        if fr["code_entity_count"] > 0:
            lines.append(f"codeEntities: {fr['code_entity_count']}")
        lines.append(f'scannedAt: "{datetime.now(timezone.utc).isoformat()}"')
        lines.append("---")
        lines.append("")
        lines.append(f"# {os.path.basename(rel_path)}")
        lines.append("")
        lines.append(f"**Repository:** {repo_name}")
        lines.append(f"**Path:** `{rel_path}`")
        lines.append(f"**Language:** {fr['language']}")
        lines.append(f"**Lines:** {fr['line_count']}")
        lines.append("")

        if git_meta.get("message"):
            lines.append(f"**Last commit:** {git_meta['message']}")
            lines.append("")

        # Add first few lines as preview (for non-binary content)
        content_lines = fr["content"].split("\n")
        preview = "\n".join(content_lines[:30])
        if len(content_lines) > 30:
            preview += "\n..."
        lines.append("## Preview")
        lines.append("")
        lines.append(f"```{fr['language']}")
        lines.append(preview)
        lines.append("```")

        try:
            with open(vault_full, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return vault_rel
        except Exception as e:
            logger.warning(f"Failed to write vault note {vault_rel}: {e}")
            return None

    async def _ingest_documents(
        self,
        file_results: list,
        repo_name: str,
        existing_hashes: dict,
        code_entities: List[CodeEntity] = None,
    ):
        """Store files in koi_memories with embeddings and chunks for RAG.

        For code files: chunks at entity boundaries (one chunk per function/class/module)
        using tree-sitter entities — signature + docstring + body as embed text.

        For non-code files (docs, markdown, configs): sentence-aware 500-token chunking.
        """
        doc_count = 0
        chunk_count = 0
        embed_count = 0

        # Group code entities by file path for entity-level chunking
        entities_by_file: Dict[str, List[CodeEntity]] = {}
        if code_entities:
            for entity in code_entities:
                entities_by_file.setdefault(entity.file_path, []).append(entity)

        for fr in file_results:
            rid = f"github:{repo_name}:{fr['rel_path']}"
            content_text = fr["content"]
            git_meta = fr.get("git_meta", {})
            is_code = fr["ext"] in CODE_EXTENSIONS

            # Build document content JSON
            title = fr["rel_path"]
            doc_content = {
                "title": title,
                "text": content_text,
                "file_path": fr["rel_path"],
                "language": fr["language"],
                "line_count": fr["line_count"],
            }
            if fr.get("code_entity_count"):
                doc_content["code_entities"] = fr["code_entity_count"]

            doc_metadata = {
                "repo": repo_name,
                "content_hash": fr["content_hash"],
            }
            if git_meta.get("sha"):
                doc_metadata["commit_sha"] = git_meta["sha"]
            if git_meta.get("author"):
                doc_metadata["author"] = git_meta["author"]

            event_type = "NEW" if fr["rel_path"] not in existing_hashes else "UPDATE"

            try:
                async with self.pool.acquire() as conn:
                    # Upsert into koi_memories
                    memory_id = await conn.fetchval("""
                        INSERT INTO koi_memories (id, rid, event_type, source_sensor, content, metadata)
                        VALUES ($1, $2, $3, 'github-sensor', $4::jsonb, $5::jsonb)
                        ON CONFLICT (rid) DO UPDATE SET
                            event_type = EXCLUDED.event_type,
                            content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            updated_at = NOW()
                        RETURNING id
                    """, uuid.uuid4(), rid, event_type,
                        json_module.dumps(doc_content),
                        json_module.dumps(doc_metadata))

                    doc_count += 1

                    # Delete old chunks for this document
                    await conn.execute(
                        "DELETE FROM koi_memory_chunks WHERE document_rid = $1", rid
                    )

                    if is_code:
                        # === CODE FILES: entity-level chunking ===
                        file_entities = entities_by_file.get(fr["rel_path"], [])
                        # Filter to meaningful entities (skip File-level, skip Imports)
                        meaningful = [
                            e for e in file_entities
                            if e.entity_type in ("Function", "Class", "Module", "Interface")
                        ]

                        if meaningful:
                            # Doc-level embedding: file path + all entity signatures
                            summary_parts = [title]
                            for e in meaningful:
                                sig = e.signature[:200] if e.signature else e.name
                                if e.docstring:
                                    sig += f" — {e.docstring[:100]}"
                                summary_parts.append(f"{e.entity_type} {sig}")
                            embed_text = "\n".join(summary_parts)

                            if self._embed_fn:
                                embedding = await self._embed_fn(embed_text[:2000])
                                if embedding:
                                    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                                    await conn.execute("""
                                        INSERT INTO koi_embeddings (memory_id, dim_1536)
                                        VALUES ($1, $2::vector)
                                        ON CONFLICT (memory_id) DO UPDATE SET dim_1536 = EXCLUDED.dim_1536
                                    """, memory_id, embedding_str)
                                    embed_count += 1

                            # One chunk per entity
                            content_lines = content_text.split("\n")
                            for idx, entity in enumerate(meaningful):
                                # Extract the entity's source code from the file
                                start = max(0, entity.line_start - 1)
                                end = min(len(content_lines), entity.line_end)
                                entity_source = "\n".join(content_lines[start:end])

                                # Build rich embed text: type + name + signature + docstring + source
                                embed_parts = [
                                    f"{entity.entity_type}: {entity.name}",
                                    f"File: {fr['rel_path']}",
                                ]
                                if entity.signature:
                                    embed_parts.append(f"Signature: {entity.signature[:300]}")
                                if entity.docstring:
                                    embed_parts.append(f"Docstring: {entity.docstring[:500]}")
                                if entity.params:
                                    embed_parts.append(f"Parameters: {entity.params[:200]}")
                                if entity.return_type:
                                    embed_parts.append(f"Returns: {entity.return_type}")
                                # Include source but cap at 1500 chars to stay within embedding limits
                                embed_parts.append(f"Source:\n{entity_source[:1500]}")
                                entity_embed_text = "\n".join(embed_parts)

                                chunk_rid = f"{rid}#entity:{entity.name}"
                                chunk_content = json_module.dumps({
                                    "text": entity_embed_text,
                                    "file_path": fr["rel_path"],
                                    "entity_name": entity.name,
                                    "entity_type": entity.entity_type,
                                    "line_start": entity.line_start,
                                    "line_end": entity.line_end,
                                    "signature": entity.signature[:300] if entity.signature else "",
                                    "docstring": entity.docstring[:500] if entity.docstring else "",
                                })

                                chunk_embedding = None
                                if self._embed_fn:
                                    emb = await self._embed_fn(entity_embed_text[:2000])
                                    if emb:
                                        chunk_embedding = '[' + ','.join(str(x) for x in emb) + ']'

                                total = len(meaningful)
                                if chunk_embedding:
                                    await conn.execute("""
                                        INSERT INTO koi_memory_chunks
                                            (chunk_rid, document_rid, chunk_index, total_chunks, content, embedding)
                                        VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
                                        ON CONFLICT (chunk_rid) DO UPDATE SET
                                            content = EXCLUDED.content,
                                            embedding = EXCLUDED.embedding
                                    """, chunk_rid, rid, idx, total, chunk_content, chunk_embedding)
                                else:
                                    await conn.execute("""
                                        INSERT INTO koi_memory_chunks
                                            (chunk_rid, document_rid, chunk_index, total_chunks, content)
                                        VALUES ($1, $2, $3, $4, $5::jsonb)
                                        ON CONFLICT (chunk_rid) DO UPDATE SET content = EXCLUDED.content
                                    """, chunk_rid, rid, idx, total, chunk_content)

                                chunk_count += 1
                        else:
                            # Code file with no meaningful entities (e.g. just imports)
                            # Still embed the doc-level summary
                            if self._embed_fn:
                                embed_text = f"{title}\n\n{' '.join(content_text.split()[:500])}"
                                embedding = await self._embed_fn(embed_text[:2000])
                                if embedding:
                                    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                                    await conn.execute("""
                                        INSERT INTO koi_embeddings (memory_id, dim_1536)
                                        VALUES ($1, $2::vector)
                                        ON CONFLICT (memory_id) DO UPDATE SET dim_1536 = EXCLUDED.dim_1536
                                    """, memory_id, embedding_str)
                                    embed_count += 1

                    else:
                        # === NON-CODE FILES: sentence-aware chunking ===
                        # Doc-level embedding
                        if self._embed_fn:
                            embed_text = f"{title}\n\n{' '.join(content_text.split()[:500])}"
                            embedding = await self._embed_fn(embed_text[:2000])
                            if embedding:
                                embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
                                await conn.execute("""
                                    INSERT INTO koi_embeddings (memory_id, dim_1536)
                                    VALUES ($1, $2::vector)
                                    ON CONFLICT (memory_id) DO UPDATE SET dim_1536 = EXCLUDED.dim_1536
                                """, memory_id, embedding_str)
                                embed_count += 1

                        # Sentence-aware chunks
                        chunks = self._chunker.chunk_text(content_text)
                        for chunk in chunks:
                            chunk_rid = f"{rid}#chunk{chunk['index']}"
                            chunk_content = json_module.dumps({
                                "text": chunk["text"],
                                "file_path": fr["rel_path"],
                                "chunk_index": chunk["index"],
                            })

                            chunk_embedding = None
                            if self._embed_fn and chunk["text"].strip():
                                emb = await self._embed_fn(chunk["text"][:2000])
                                if emb:
                                    chunk_embedding = '[' + ','.join(str(x) for x in emb) + ']'

                            if chunk_embedding:
                                await conn.execute("""
                                    INSERT INTO koi_memory_chunks
                                        (chunk_rid, document_rid, chunk_index, total_chunks, content, embedding)
                                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
                                    ON CONFLICT (chunk_rid) DO UPDATE SET
                                        content = EXCLUDED.content,
                                        embedding = EXCLUDED.embedding
                                """, chunk_rid, rid, chunk["index"], chunk["total_chunks"],
                                    chunk_content, chunk_embedding)
                            else:
                                await conn.execute("""
                                    INSERT INTO koi_memory_chunks
                                        (chunk_rid, document_rid, chunk_index, total_chunks, content)
                                    VALUES ($1, $2, $3, $4, $5::jsonb)
                                    ON CONFLICT (chunk_rid) DO UPDATE SET content = EXCLUDED.content
                                """, chunk_rid, rid, chunk["index"], chunk["total_chunks"],
                                    chunk_content)

                            chunk_count += 1

            except Exception as e:
                logger.warning(f"Document ingest failed for {rid}: {e}")

        logger.info(
            f"Document ingestion: {doc_count} docs, {embed_count} embeddings, {chunk_count} chunks"
        )

    async def _link_entities(self, conn, fr: dict, repo_name: str):
        """Scan file content for known entities and create document_entity_links."""
        content = fr["content"]
        if len(content) < 50:
            return

        # Get all entities for word-boundary matching
        rows = await conn.fetch(
            "SELECT entity_text, fuseki_uri, entity_type FROM entity_registry WHERE LENGTH(entity_text) >= 3 ORDER BY LENGTH(entity_text) DESC"
        )

        document_rid = f"github:{repo_name}:{fr['rel_path']}"

        for row in rows:
            name = row["entity_text"]
            pattern = re.compile(r"\b" + re.escape(name.lower()) + r"\b", re.IGNORECASE)
            if pattern.search(content):
                try:
                    await conn.execute(
                        """INSERT INTO document_entity_links (document_rid, entity_uri, mention_count)
                           VALUES ($1, $2, 1)
                           ON CONFLICT (document_rid, entity_uri) DO UPDATE
                           SET mention_count = document_entity_links.mention_count + 1""",
                        document_rid,
                        row["fuseki_uri"],
                    )
                except Exception:
                    pass

    # ========== API support ==========

    async def trigger_scan(self, repo_name: Optional[str] = None) -> dict:
        """Manually trigger a scan (called from API endpoint)."""
        async with self.pool.acquire() as conn:
            if repo_name:
                repos = await conn.fetch(
                    "SELECT * FROM github_repos WHERE repo_name=$1 AND status='active'",
                    repo_name,
                )
            else:
                repos = await conn.fetch(
                    "SELECT * FROM github_repos WHERE status='active'"
                )

        if not repos:
            return {"status": "no_repos", "message": "No active repos found"}

        results = []
        for repo_row in repos:
            try:
                result = await self._scan_repo(dict(repo_row))
                results.append(result)
            except Exception as e:
                results.append({"repo": repo_row["repo_name"], "error": str(e)})

        self._last_scan = datetime.now(timezone.utc)
        self._scan_count += 1

        return {"status": "completed", "results": results}

    async def get_status(self) -> dict:
        """Get sensor status."""
        async with self.pool.acquire() as conn:
            repo_count = await conn.fetchval(
                "SELECT COUNT(*) FROM github_repos WHERE status='active'"
            )
            file_count = await conn.fetchval(
                "SELECT COUNT(*) FROM github_file_state"
            )
            code_count = await conn.fetchval(
                "SELECT COUNT(*) FROM koi_code_artifacts"
            )
            doc_count = await conn.fetchval(
                "SELECT COUNT(*) FROM koi_memories WHERE source_sensor='github-sensor'"
            )
            chunk_count = await conn.fetchval(
                "SELECT COUNT(*) FROM koi_memory_chunks mc "
                "JOIN koi_memories m ON m.rid = mc.document_rid "
                "WHERE m.source_sensor='github-sensor'"
            )
            embed_count = await conn.fetchval(
                "SELECT COUNT(*) FROM koi_embeddings ke "
                "JOIN koi_memories m ON m.id = ke.memory_id "
                "WHERE m.source_sensor='github-sensor' AND ke.dim_1536 IS NOT NULL"
            )
            repos = await conn.fetch(
                "SELECT repo_name, last_scan_at, last_commit_sha, file_count, code_entity_count, status "
                "FROM github_repos ORDER BY repo_name"
            )

        return {
            "running": self._running,
            "scan_interval_seconds": self.scan_interval,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "total_scans": self._scan_count,
            "active_repos": repo_count,
            "total_files": file_count,
            "total_code_entities": code_count,
            "total_documents": doc_count,
            "total_chunks": chunk_count,
            "total_embeddings": embed_count,
            "repos": [dict(r) for r in repos],
        }
