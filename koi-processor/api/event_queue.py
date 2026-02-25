"""
Database-backed KOI-net Event Queue

Uses the koi_net_events table (migration 039) for event persistence.
Supports add, poll, peek, mark_delivered, confirm, and cleanup operations with per-edge TTL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from api.koi_protocol import EventType, WireEvent, WireManifest, timestamp_to_z_format

logger = logging.getLogger(__name__)

# Default TTL for events (hours)
DEFAULT_TTL_HOURS = 24
REMOTE_TTL_HOURS = 72


class EventQueue:
    """Database-backed event queue for KOI-net protocol."""

    def __init__(self, pool: asyncpg.Pool, node_rid: str):
        self.pool = pool
        self.node_rid = node_rid

    async def add(
        self,
        event_type: str,
        rid: str,
        manifest: Optional[Dict[str, Any]] = None,
        contents: Optional[Dict[str, Any]] = None,
        source_node: Optional[str] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        event_id: Optional[str] = None,
        target_node: Optional[str] = None,
    ) -> Optional[str]:
        """Add an event to the queue. Returns the event_id.

        If event_id is provided (inbound from a peer), it is preserved and
        used for dedup via the UNIQUE(source_node, event_id) index.
        Returns None if the event was a duplicate (ON CONFLICT DO NOTHING).
        """
        effective_source = source_node or self.node_rid
        async with self.pool.acquire() as conn:
            if event_id:
                # Inbound event with sender-assigned event_id — dedup on insert
                row = await conn.fetchrow(
                    """
                    INSERT INTO koi_net_events
                        (event_id, event_type, rid, manifest, contents, source_node, target_node, expires_at)
                    VALUES
                        ($1::UUID, $2, $3, $4, $5, $6, $7, NOW() + ($8 || ' hours')::INTERVAL)
                    ON CONFLICT (source_node, event_id) WHERE event_id IS NOT NULL DO NOTHING
                    RETURNING event_id::TEXT
                    """,
                    event_id,
                    event_type,
                    rid,
                    json.dumps(manifest) if manifest else None,
                    json.dumps(contents) if contents else None,
                    effective_source,
                    target_node,
                    str(ttl_hours),
                )
                if row is None:
                    logger.debug(f"Duplicate event {event_id} from {effective_source}, skipped")
                    return None
                logger.info(f"Queued {event_type} event for {rid} (id={event_id}, target={target_node})")
                return event_id
            else:
                # Locally generated event — DB assigns event_id
                row = await conn.fetchrow(
                    """
                    INSERT INTO koi_net_events
                        (event_type, rid, manifest, contents, source_node, target_node, expires_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, NOW() + ($7 || ' hours')::INTERVAL)
                    RETURNING event_id::TEXT
                    """,
                    event_type,
                    rid,
                    json.dumps(manifest) if manifest else None,
                    json.dumps(contents) if contents else None,
                    effective_source,
                    target_node,
                    str(ttl_hours),
                )
                new_id = row["event_id"]
                logger.info(f"Queued {event_type} event for {rid} (id={new_id}, target={target_node})")
                return new_id

    async def poll(
        self,
        requesting_node: str,
        limit: int = 50,
        rid_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Poll for events not yet delivered to the requesting node.

        Returns list of event dicts with event_id, event_type, rid, manifest, contents.
        Marks events as delivered_to this node.
        """
        async with self.pool.acquire() as conn:
            # Fetch events not yet delivered to this node and not expired.
            # target_node scoping: NULL = broadcast (visible to all), non-NULL = unicast.
            rows = await conn.fetch(
                """
                SELECT id, event_id::TEXT, event_type, rid, manifest, contents, source_node, queued_at
                FROM koi_net_events
                WHERE NOT ($1 = ANY(delivered_to))
                  AND expires_at > NOW()
                  AND (target_node IS NULL OR target_node = $1)
                ORDER BY queued_at ASC
                LIMIT $2
                """,
                requesting_node,
                limit,
            )

            if not rows:
                return []

            events = []
            ids_to_mark = []

            for row in rows:
                # If rid_types filter specified, check entity type from RID
                if rid_types:
                    # RID format: orn:koi-net.{type}:{slug}+{hash}
                    rid = row["rid"]
                    rid_type = extract_rid_type(rid)
                    if rid_type and rid_type not in rid_types:
                        continue

                event = {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "rid": row["rid"],
                    "manifest": json.loads(row["manifest"]) if row["manifest"] else None,
                    "contents": json.loads(row["contents"]) if row["contents"] else None,
                    "source_node": row["source_node"],
                    "queued_at": row["queued_at"].isoformat() if row["queued_at"] else None,
                }
                events.append(event)
                ids_to_mark.append(row["id"])

            # Mark as delivered to this node
            if ids_to_mark:
                await conn.execute(
                    """
                    UPDATE koi_net_events
                    SET delivered_to = array_append(delivered_to, $1)
                    WHERE id = ANY($2)
                    """,
                    requesting_node,
                    ids_to_mark,
                )
                logger.info(
                    f"Delivered {len(events)} events to {requesting_node}"
                )

            return events

    async def peek_undelivered(
        self,
        target_node: str,
        limit: int = 50,
        rid_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get events not yet delivered to target_node WITHOUT marking them.

        Returns list of event dicts with event_id for later marking.
        Used by WEBHOOK push delivery (peek -> push -> mark pattern).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, event_id::TEXT, event_type, rid, manifest, contents, source_node, queued_at
                FROM koi_net_events
                WHERE NOT ($1 = ANY(delivered_to))
                  AND expires_at > NOW()
                  AND (target_node IS NULL OR target_node = $1)
                ORDER BY queued_at ASC
                LIMIT $2
                """,
                target_node,
                limit,
            )

            if not rows:
                return []

            events = []
            for row in rows:
                if rid_types:
                    rid = row["rid"]
                    rid_type = extract_rid_type(rid)
                    if rid_type and rid_type not in rid_types:
                        continue

                events.append({
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "rid": row["rid"],
                    "manifest": json.loads(row["manifest"]) if row["manifest"] else None,
                    "contents": json.loads(row["contents"]) if row["contents"] else None,
                    "source_node": row["source_node"],
                    "queued_at": row["queued_at"].isoformat() if row["queued_at"] else None,
                })

            return events

    async def mark_delivered(self, event_ids: List[str], target_node: str) -> int:
        """Mark specific events as delivered to target_node.

        Returns count of events actually marked (for verification).
        Idempotent — marking an already-delivered event is a no-op.
        """
        if not event_ids:
            return 0

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE koi_net_events
                SET delivered_to = array_append(delivered_to, $1)
                WHERE event_id::TEXT = ANY($2)
                  AND NOT ($1 = ANY(delivered_to))
                  AND expires_at > NOW()
                """,
                target_node,
                event_ids,
            )
            count = int(result.split()[-1])
            if count > 0:
                logger.info(f"Marked {count} events as delivered to {target_node}")
            return count

    async def confirm(
        self,
        event_ids: List[str],
        confirming_node: str,
    ) -> int:
        """Confirm receipt of events by a node. Returns count confirmed."""
        if not event_ids:
            return 0

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE koi_net_events
                SET confirmed_by = array_append(confirmed_by, $1)
                WHERE event_id::TEXT = ANY($2)
                  AND NOT ($1 = ANY(confirmed_by))
                """,
                confirming_node,
                event_ids,
            )
            count = int(result.split()[-1])
            logger.info(f"Confirmed {count} events from {confirming_node}")
            return count

    async def cleanup(self) -> int:
        """Delete expired events. Returns count deleted."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM koi_net_events
                WHERE expires_at < NOW()
                """
            )
            count = int(result.split()[-1])
            if count > 0:
                logger.info(f"Cleaned up {count} expired events")
            return count

    async def get_queue_size(self) -> int:
        """Get current number of active (non-expired) events."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM koi_net_events WHERE expires_at > NOW()"
            )
            return row["cnt"]


def extract_rid_type(rid: str) -> Optional[str]:
    """Extract entity type from RID string.

    Expected formats:
    - orn:koi-net.practice:slug+hash -> Practice
    - orn:entity:practice/slug+hash -> Practice
    """
    if "koi-net." in rid:
        # orn:koi-net.{type}:{slug}+{hash}
        try:
            type_part = rid.split("koi-net.")[1].split(":")[0]
            return type_part.capitalize()
        except (IndexError, AttributeError):
            return None
    if "entity:" in rid:
        # orn:entity:{type}/{slug}+{hash}
        try:
            type_part = rid.split("entity:")[1].split("/")[0]
            return type_part.capitalize()
        except (IndexError, AttributeError):
            return None
    return None
