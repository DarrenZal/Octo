"""
KOI-net Polling Client

Background asyncio task that polls peer nodes for events.
Integrates into FastAPI startup as a background task.

Flow:
1. Read configured edges from koi_net_edges table
2. For each POLL edge where we are the target:
   - POST /koi-net/events/poll to source node
   - For each event: resolve entity, create cross-reference
   - Confirm after successful processing
3. Sleep poll_interval seconds, repeat
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import httpx

from api.koi_envelope import sign_envelope, is_signed_envelope, verify_envelope, load_public_key_from_der_b64
from api.koi_protocol import timestamp_to_z_format

logger = logging.getLogger(__name__)

# Default polling interval (seconds)
DEFAULT_POLL_INTERVAL = int(os.getenv("KOI_POLL_INTERVAL", "60"))

# Max consecutive failures before exponential backoff caps
MAX_BACKOFF = 600  # 10 minutes


class KOIPoller:
    """Background poller for KOI-net federation."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        node_rid: str,
        private_key=None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ):
        self.pool = pool
        self.node_rid = node_rid
        self.private_key = private_key
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._backoff: Dict[str, int] = {}  # node_rid -> consecutive failures

    async def start(self):
        """Start the background polling task."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Poller started (interval={self.poll_interval}s)")

    async def stop(self):
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Poller stopped")

    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all_peers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poller error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _poll_all_peers(self):
        """Poll all configured peer nodes."""
        async with self.pool.acquire() as conn:
            # Find POLL edges where we are the target (we poll from source)
            edges = await conn.fetch(
                """
                SELECT e.source_node, e.rid_types, e.metadata,
                       n.base_url, n.public_key
                FROM koi_net_edges e
                JOIN koi_net_nodes n ON n.node_rid = e.source_node
                WHERE e.target_node = $1
                  AND e.edge_type = 'POLL'
                  AND e.status = 'APPROVED'
                """,
                self.node_rid,
            )

        for edge in edges:
            source_node = edge["source_node"]
            base_url = edge["base_url"]
            if not base_url:
                logger.warning(f"No base_url for {source_node}, skipping")
                continue

            # Check backoff
            failures = self._backoff.get(source_node, 0)
            if failures > 0:
                backoff_time = min(30 * (2 ** (failures - 1)), MAX_BACKOFF)
                logger.debug(f"Backoff for {source_node}: {backoff_time}s (failures={failures})")
                # Skip this cycle if still in backoff
                # (simplified: we just skip, the sleep handles timing)
                if failures > 3:
                    continue

            try:
                await self._poll_peer(
                    source_node=source_node,
                    base_url=base_url,
                    rid_types=edge["rid_types"],
                    peer_public_key_b64=edge["public_key"],
                )
                # Reset backoff on success
                self._backoff[source_node] = 0
            except httpx.ConnectError:
                self._backoff[source_node] = failures + 1
                logger.warning(
                    f"Peer {source_node} unreachable (failure #{failures + 1})"
                )
            except Exception as e:
                self._backoff[source_node] = failures + 1
                logger.warning(f"Poll failed for {source_node}: {e}")

    async def _poll_peer(
        self,
        source_node: str,
        base_url: str,
        rid_types: List[str],
        peer_public_key_b64: Optional[str] = None,
    ):
        """Poll a single peer node for events."""
        poll_payload = {"type": "poll_events", "limit": 50}

        # Sign if we have a private key
        if self.private_key:
            request_body = sign_envelope(
                poll_payload, self.node_rid, source_node, self.private_key
            )
        else:
            request_body = poll_payload
            request_body["node_id"] = self.node_rid

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/koi-net/events/poll", json=request_body
            )

        if resp.status_code != 200:
            logger.warning(f"Poll {source_node}: HTTP {resp.status_code}")
            return

        result = resp.json()

        # Unwrap signed response if present
        if is_signed_envelope(result) and peer_public_key_b64:
            pub_key = load_public_key_from_der_b64(peer_public_key_b64)
            payload, _ = verify_envelope(result, pub_key)
            events = payload.get("events", [])
        else:
            events = result.get("events", [])

        if not events:
            return

        logger.info(f"Received {len(events)} events from {source_node}")

        # Process each event
        confirm_batch = []
        for event in events:
            event_id = event.get("event_id")
            rid = event.get("rid")
            event_type = event.get("event_type", "NEW")
            contents = event.get("contents", {})

            if not rid:
                continue

            try:
                await self._process_event(
                    rid=rid,
                    event_type=event_type,
                    contents=contents,
                    source_node=source_node,
                )
                if event_id:
                    confirm_batch.append(event_id)
            except Exception as e:
                logger.warning(f"Failed to process event {rid}: {e}")
                # Don't confirm — will re-deliver on next poll

        # Confirm processed events
        if confirm_batch:
            await self._confirm_events(
                base_url=base_url,
                source_node=source_node,
                event_ids=confirm_batch,
            )

    async def _process_event(
        self,
        rid: str,
        event_type: str,
        contents: Dict[str, Any],
        source_node: str,
    ):
        """Process a single event from a peer.

        Resolves the entity and creates a cross-reference.
        """
        if event_type == "FORGET":
            # Mark cross-reference as removed
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM koi_net_cross_refs WHERE remote_rid = $1 AND remote_node = $2",
                    rid,
                    source_node,
                )
            logger.info(f"Removed cross-ref for forgotten RID {rid}")
            return

        # Extract entity info from contents
        entity_name = contents.get("name", "")
        entity_type = contents.get("@type", contents.get("entity_type", ""))
        # Strip bkc: prefix if present
        if entity_type.startswith("bkc:"):
            entity_type = entity_type[4:]

        if not entity_name:
            logger.debug(f"Event {rid} has no name in contents, storing cross-ref only")

        # Try to resolve against local registry
        local_uri = None
        confidence = None

        if entity_name:
            async with self.pool.acquire() as conn:
                # Tier 1: Exact match
                row = await conn.fetchrow(
                    """
                    SELECT fuseki_uri FROM entity_registry
                    WHERE normalized_text = $1 AND entity_type = $2
                    """,
                    entity_name.lower().strip(),
                    entity_type,
                )
                if row:
                    local_uri = row["fuseki_uri"]
                    confidence = 1.0

        # Create cross-reference (idempotent via ON CONFLICT)
        async with self.pool.acquire() as conn:
            if local_uri:
                relationship = "same_as" if confidence == 1.0 else "related_to"
            else:
                # No local match — store as unresolved cross-ref
                local_uri = f"unresolved:{entity_type}:{entity_name}"
                relationship = "unresolved"
                confidence = 0.0

            await conn.execute(
                """
                INSERT INTO koi_net_cross_refs
                    (local_uri, remote_rid, remote_node, relationship, confidence)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (local_uri, remote_rid) DO NOTHING
                """,
                local_uri,
                rid,
                source_node,
                relationship,
                confidence,
            )

        logger.info(
            f"Cross-ref: {rid} -> {local_uri} ({relationship}, conf={confidence})"
        )

    async def _confirm_events(
        self,
        base_url: str,
        source_node: str,
        event_ids: List[str],
    ):
        """Confirm receipt of events with the source node."""
        confirm_payload = {
            "type": "confirm_events",
            "event_ids": event_ids,
        }

        if self.private_key:
            request_body = sign_envelope(
                confirm_payload, self.node_rid, source_node, self.private_key
            )
        else:
            request_body = confirm_payload
            request_body["node_id"] = self.node_rid

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{base_url}/koi-net/events/confirm", json=request_body
                )
            if resp.status_code == 200:
                logger.info(f"Confirmed {len(event_ids)} events with {source_node}")
            else:
                logger.warning(
                    f"Confirm failed: HTTP {resp.status_code} from {source_node}"
                )
        except Exception as e:
            # Confirm failure is harmless — events will re-deliver
            logger.debug(f"Confirm call failed for {source_node}: {e}")
