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

from api.koi_envelope import (
    sign_envelope,
    is_signed_envelope,
    verify_envelope,
    load_public_key_from_der_b64,
    unwrap_and_verify_response,
    EnvelopeError,
)
from api.koi_protocol import NodeProfile, timestamp_to_z_format

logger = logging.getLogger(__name__)

# Default polling interval (seconds)
DEFAULT_POLL_INTERVAL = int(os.getenv("KOI_POLL_INTERVAL", "60"))

# Max consecutive failures before exponential backoff caps
MAX_BACKOFF = 600  # 10 minutes


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


REQUIRE_SIGNED_REQUESTS = _bool_env(
    "KOI_REQUIRE_SIGNED_ENVELOPES",
    _bool_env("KOI_STRICT_MODE", False),
)
REQUIRE_SIGNED_RESPONSES = _bool_env(
    "KOI_REQUIRE_SIGNED_RESPONSES",
    _bool_env("KOI_STRICT_MODE", False),
)
COMMONS_INTAKE_ENABLED = _bool_env("KOI_COMMONS_INTAKE_ENABLED", False)
COMMONS_AUTO_APPROVE = _bool_env("KOI_COMMONS_AUTO_APPROVE", False)


class KOIPoller:
    """Background poller for KOI-net federation."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        node_rid: str,
        private_key=None,
        node_profile: Optional[NodeProfile] = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        pipeline=None,
        use_pipeline: bool = False,
        event_queue=None,
    ):
        self.pool = pool
        self.node_rid = node_rid
        self.private_key = private_key
        self.node_profile = node_profile
        self.poll_interval = poll_interval
        self.pipeline = pipeline
        self.use_pipeline = use_pipeline
        self.event_queue = event_queue
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._backoff: Dict[str, int] = {}  # node_rid -> consecutive failures (POLL)
        self._webhook_backoff: Dict[str, int] = {}  # node_rid -> consecutive failures (WEBHOOK)

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
                await self._push_webhook_peers()
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

    async def _push_webhook_peers(self):
        """Push events to WEBHOOK subscribers."""
        if not self.event_queue:
            return

        async with self.pool.acquire() as conn:
            # WEBHOOK: source = us (provider), target = subscriber
            edges = await conn.fetch(
                """SELECT e.target_node, e.rid_types, n.base_url, n.public_key
                   FROM koi_net_edges e
                   JOIN koi_net_nodes n ON n.node_rid = e.target_node
                   WHERE e.source_node = $1
                     AND e.edge_type = 'WEBHOOK'
                     AND e.status = 'APPROVED'""",
                self.node_rid,
            )

        for edge in edges:
            target_node = edge["target_node"]
            base_url = edge["base_url"]
            if not base_url:
                continue

            # Check backoff
            failures = self._webhook_backoff.get(target_node, 0)
            if failures > 3:
                backoff_time = min(30 * (2 ** (failures - 1)), MAX_BACKOFF)
                logger.debug(f"WEBHOOK backoff for {target_node}: {backoff_time}s (failures={failures})")
                continue

            # Phase 1: Peek (no side effects)
            events = await self.event_queue.peek_undelivered(
                target_node, limit=50, rid_types=edge["rid_types"]
            )
            if not events:
                continue

            # Phase 2: Push to target's /events/broadcast
            try:
                payload = {"type": "events_payload", "events": events}
                url = f"{base_url.rstrip('/')}/koi-net/events/broadcast"

                if self.private_key:
                    signed_payload = sign_envelope(
                        payload, self.node_rid, target_node, self.private_key
                    )
                else:
                    signed_payload = payload

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=signed_payload)

                if resp.status_code == 200:
                    raw_body = resp.json()
                    peer_key = edge["public_key"]

                    # Attempt 1: verify with cached key (may be None or stale)
                    try:
                        body = unwrap_and_verify_response(
                            raw_body, target_node, peer_key,
                            expected_target_node=self.node_rid,
                        )
                    except EnvelopeError:
                        # Attempt 2: refresh key from peer's /koi-net/health and retry
                        refreshed_key = await self._learn_peer_public_key(target_node, base_url)
                        if refreshed_key and refreshed_key != peer_key:
                            try:
                                body = unwrap_and_verify_response(
                                    raw_body, target_node, refreshed_key,
                                    expected_target_node=self.node_rid,
                                )
                            except EnvelopeError as e:
                                self._webhook_backoff[target_node] = failures + 1
                                logger.warning(
                                    f"WEBHOOK push to {target_node}: response verification failed after key refresh: {e}"
                                )
                                continue
                        else:
                            self._webhook_backoff[target_node] = failures + 1
                            logger.warning(
                                f"WEBHOOK push to {target_node}: response verification failed, key refresh unsuccessful"
                            )
                            continue

                    queued_count = body.get("queued", 0)

                    if queued_count == len(events):
                        # Full success: mark all delivered
                        event_ids = [e["event_id"] for e in events]
                        await self.event_queue.mark_delivered(event_ids, target_node)
                        logger.info(f"WEBHOOK push to {target_node}: {len(events)} events delivered")
                        self._webhook_backoff[target_node] = 0
                    else:
                        # Partial or zero success: mark NONE, retry all next cycle
                        logger.warning(
                            f"WEBHOOK push to {target_node}: {queued_count}/{len(events)} queued — "
                            f"marking none delivered, will retry all"
                        )
                else:
                    self._webhook_backoff[target_node] = failures + 1
                    logger.warning(f"WEBHOOK push to {target_node} failed: HTTP {resp.status_code}")

            except httpx.ConnectError:
                self._webhook_backoff[target_node] = failures + 1
                logger.warning(f"WEBHOOK push to {target_node}: connection failed")
            except Exception as e:
                self._webhook_backoff[target_node] = failures + 1
                logger.warning(f"WEBHOOK push to {target_node} error: {e}")

    async def _learn_peer_public_key(
        self,
        source_node: str,
        base_url: str,
    ) -> Optional[str]:
        """Fetch a peer public key from /koi-net/health and persist it locally."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/koi-net/health")
            if resp.status_code != 200:
                return None
            health = resp.json()
        except Exception:
            return None

        node = health.get("node") if isinstance(health, dict) else None
        if not isinstance(node, dict):
            return None

        detected_rid = node.get("node_rid")
        if detected_rid and detected_rid != source_node:
            logger.warning(
                f"Peer health RID mismatch for {base_url}: expected {source_node}, got {detected_rid}"
            )
            return None

        public_key = node.get("public_key")
        if not public_key:
            return None

        node_name = node.get("node_name") or source_node
        node_type = node.get("node_type") or "FULL"
        ontology_uri = node.get("ontology_uri")
        ontology_version = node.get("ontology_version")
        async with self.pool.acquire() as conn:
            # Key pinning: reject silent key rotation
            existing_key = await conn.fetchval(
                "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
                source_node,
            )
            if existing_key and existing_key != public_key:
                logger.warning(
                    "KEY MISMATCH for %s — pinned key starts with: %s... new key starts with: %s... "
                    "Refusing to update and skipping this peer.",
                    source_node, existing_key[:20], public_key[:20],
                )
                return None

            await conn.execute(
                """
                INSERT INTO koi_net_nodes
                    (node_rid, node_name, node_type, base_url, public_key,
                     ontology_uri, ontology_version, status, last_seen)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', NOW())
                ON CONFLICT (node_rid) DO UPDATE SET
                    node_name = EXCLUDED.node_name,
                    node_type = EXCLUDED.node_type,
                    base_url = EXCLUDED.base_url,
                    ontology_uri = COALESCE(EXCLUDED.ontology_uri, koi_net_nodes.ontology_uri),
                    ontology_version = COALESCE(EXCLUDED.ontology_version, koi_net_nodes.ontology_version),
                    status = 'active',
                    last_seen = NOW()
                """,
                source_node,
                node_name,
                node_type,
                base_url,
                public_key,
                ontology_uri,
                ontology_version,
            )

        logger.info(f"Learned public key for {source_node} from {base_url}/koi-net/health")
        return public_key

    async def _send_handshake(self, source_node: str, base_url: str) -> bool:
        """Send unsigned handshake so peers can register our public key/profile."""
        if not self.node_profile:
            return False

        payload = {
            "type": "handshake",
            "profile": self.node_profile.model_dump(exclude_none=True),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{base_url}/koi-net/handshake", json=payload)
        except Exception as exc:
            logger.warning(f"Handshake to {source_node} failed: {exc}")
            return False

        if resp.status_code == 200:
            logger.info(f"Handshake accepted by {source_node}; peer should now have our public key")
            return True

        logger.warning(
            f"Handshake to {source_node} failed: HTTP {resp.status_code} {resp.text[:200]}"
        )
        return False

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
            if REQUIRE_SIGNED_REQUESTS:
                logger.warning(
                    f"Poll {source_node}: KOI policy requires signed envelopes but no private key is loaded"
                )
                return
            request_body = poll_payload
            request_body["node_id"] = self.node_rid

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/koi-net/events/poll", json=request_body
            )

        if resp.status_code != 200:
            # Common first-run failure: remote peer doesn't yet have our public key.
            # Attempt a handshake and retry once before giving up.
            if (
                resp.status_code == 400
                and "No public key for" in resp.text
                and self.node_profile is not None
            ):
                logger.info(
                    f"Poll {source_node}: missing key on peer, attempting handshake self-heal"
                )
                if await self._send_handshake(source_node, base_url):
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"{base_url}/koi-net/events/poll", json=request_body
                        )

            if resp.status_code != 200:
                logger.warning(
                    f"Poll {source_node}: HTTP {resp.status_code} {resp.text[:200]}"
                )
                return

        result = resp.json()

        # Unwrap signed response if present
        if is_signed_envelope(result):
            effective_peer_key = peer_public_key_b64
            if not effective_peer_key:
                effective_peer_key = await self._learn_peer_public_key(source_node, base_url)
            if not effective_peer_key:
                logger.warning(
                    f"Poll {source_node}: signed response but no peer public key is available"
                )
                return
            pub_key = load_public_key_from_der_b64(effective_peer_key)
            payload, _ = verify_envelope(
                result,
                pub_key,
                expected_source_node=source_node,
                expected_target_node=self.node_rid,
            )
            events = payload.get("events", [])
        else:
            if REQUIRE_SIGNED_RESPONSES:
                logger.warning(
                    f"Poll {source_node}: unsigned response rejected by KOI policy"
                )
                return
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
            manifest = event.get("manifest")

            if not rid:
                continue

            try:
                await self._process_event(
                    rid=rid,
                    event_type=event_type,
                    contents=contents,
                    manifest=manifest,
                    source_node=source_node,
                    event_id=event_id,
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
        manifest: Optional[Dict[str, Any]],
        source_node: str,
        event_id: Optional[str] = None,
    ):
        """Process a single event from a peer.

        Resolves the entity and creates a cross-reference.
        """
        share_meta = contents.get("_koi_share_meta", {}) if isinstance(contents, dict) else {}
        recipient_type = (
            share_meta.get("recipient_type")
            if isinstance(share_meta, dict)
            else None
        ) or ((manifest or {}).get("recipient_type") if isinstance(manifest, dict) else None) or "peer"
        recipient_type = str(recipient_type).strip().lower()
        is_commons_share = recipient_type == "commons"
        is_staged_commons_intake = (
            event_type != "FORGET"
            and is_commons_share
            and COMMONS_INTAKE_ENABLED
            and not COMMONS_AUTO_APPROVE
        )

        # Persist inbound shares for receiver UX/intake flow.
        # FORGET is always persisted as retraction (marker may be absent).
        if contents.get("_koi_share") or event_type == "FORGET":
            await self._persist_shared_document(
                rid=rid,
                event_type=event_type,
                contents=contents,
                manifest=manifest,
                source_node=source_node,
                event_id=event_id,
                recipient_type=recipient_type,
                intake_status="staged" if is_staged_commons_intake else None,
            )
            if is_staged_commons_intake:
                logger.info(
                    "Staged commons share %s from %s for manual intake approval",
                    rid,
                    source_node,
                )
                return

        if self.pipeline and self.use_pipeline:
            from api.pipeline import KnowledgeObject
            kobj = KnowledgeObject(
                rid=rid, event_type=event_type,
                contents=contents, source_node=source_node,
            )
            await self.pipeline.process(kobj)
            return

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

        # Create or update cross-reference
        async with self.pool.acquire() as conn:
            if local_uri:
                relationship = "same_as" if confidence == 1.0 else "related_to"
            else:
                # No local match — store as unresolved cross-ref
                local_uri = f"unresolved:{entity_type}:{entity_name}"
                relationship = "unresolved"
                confidence = 0.0

            # Check for existing cross-ref by remote_rid (may be unresolved)
            existing = await conn.fetchrow(
                "SELECT id, local_uri, relationship FROM koi_net_cross_refs WHERE remote_rid = $1 AND remote_node = $2",
                rid, source_node,
            )

            if existing:
                if existing["relationship"] == "unresolved" and relationship != "unresolved":
                    # Upgrade from unresolved to resolved
                    await conn.execute(
                        "UPDATE koi_net_cross_refs SET local_uri = $1, relationship = $2, confidence = $3 WHERE id = $4",
                        local_uri, relationship, confidence, existing["id"],
                    )
                    logger.info(f"Upgraded cross-ref {rid}: unresolved -> {relationship}")
                # else: already exists with same or better resolution, skip
            else:
                await conn.execute(
                    """
                    INSERT INTO koi_net_cross_refs
                        (local_uri, remote_rid, remote_node, relationship, confidence)
                    VALUES ($1, $2, $3, $4, $5)
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

    async def _persist_shared_document(
        self,
        rid: str,
        event_type: str,
        contents: Dict[str, Any],
        manifest: Optional[Dict[str, Any]],
        source_node: str,
        event_id: Optional[str] = None,
        recipient_type: str = "peer",
        intake_status: Optional[str] = None,
    ):
        """Persist inbound shared docs for shared_with_me / commons intake workflows."""
        async with self.pool.acquire() as conn:
            sender_name = await conn.fetchval(
                "SELECT node_name FROM koi_net_nodes WHERE node_rid = $1",
                source_node,
            )

            if event_type == "FORGET":
                await conn.execute(
                    """
                    UPDATE koi_shared_documents SET status = 'retracted'
                    WHERE document_rid = $1 AND sender_node = $2 AND status != 'retracted'
                    """,
                    rid,
                    source_node,
                )
                logger.info(f"Retracted shared document {rid} from {source_node}")
                return

            if event_id:
                exists = await conn.fetchval(
                    "SELECT 1 FROM koi_shared_documents WHERE event_id = $1::UUID",
                    event_id,
                )
                if exists:
                    logger.debug(
                        f"Shared document {rid} already persisted (event_id={event_id}), skipping"
                    )
                    return

            effective_recipient_type = recipient_type if recipient_type in {"peer", "commons"} else "peer"
            effective_intake_status = (
                intake_status
                if intake_status in {"staged", "approved", "rejected"}
                else ("none" if effective_recipient_type == "peer" else "approved")
            )
            row_status = "staged" if effective_intake_status == "staged" else "received"

            try:
                await conn.execute(
                    """
                    INSERT INTO koi_shared_documents
                        (event_id, document_rid, sender_node, sender_name, event_type,
                         manifest, contents, message, received_at, status,
                         recipient_type, intake_status)
                    VALUES ($1::UUID, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10, $11)
                    """,
                    event_id,
                    rid,
                    source_node,
                    sender_name,
                    event_type,
                    json.dumps(manifest) if manifest is not None else None,
                    json.dumps(contents),
                    contents.get("message", ""),
                    row_status,
                    effective_recipient_type,
                    effective_intake_status,
                )
            except Exception as exc:
                if "recipient_type" not in str(exc) and "intake_status" not in str(exc):
                    raise
                await conn.execute(
                    """
                    INSERT INTO koi_shared_documents
                        (event_id, document_rid, sender_node, sender_name, event_type,
                         manifest, contents, message, received_at)
                    VALUES ($1::UUID, $2, $3, $4, $5, $6, $7, $8, NOW())
                    """,
                    event_id,
                    rid,
                    source_node,
                    sender_name,
                    event_type,
                    json.dumps(manifest) if manifest is not None else None,
                    json.dumps(contents),
                    contents.get("message", ""),
                )
            logger.info(
                f"Persisted shared document {rid} from {source_node} "
                f"({sender_name}), recipient_type={effective_recipient_type}, intake={effective_intake_status}"
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
            if REQUIRE_SIGNED_REQUESTS:
                logger.warning(
                    f"Confirm {source_node}: KOI policy requires signed envelopes but no private key is loaded"
                )
                return
            request_body = confirm_payload
            request_body["node_id"] = self.node_rid

        confirm_url = f"{base_url}/koi-net/events/confirm"
        logger.debug(f"Confirming {len(event_ids)} events at {confirm_url}: {event_ids}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(confirm_url, json=request_body)
            if resp.status_code == 200:
                result = resp.json()
                if is_signed_envelope(result):
                    async with self.pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
                            source_node,
                        )
                    if row and row["public_key"]:
                        pub_key = load_public_key_from_der_b64(row["public_key"])
                        verify_envelope(
                            result,
                            pub_key,
                            expected_source_node=source_node,
                            expected_target_node=self.node_rid,
                        )
                        result = result.get("payload", {})
                    else:
                        logger.warning(
                            f"Confirm {source_node}: signed response cannot be verified (missing peer key)"
                        )
                        return
                elif REQUIRE_SIGNED_RESPONSES:
                    logger.warning(
                        f"Confirm {source_node}: unsigned response rejected by KOI policy"
                    )
                    return
                logger.info(
                    f"Confirmed {len(event_ids)} events with {source_node}: {result}"
                )
            else:
                logger.warning(
                    f"Confirm failed: HTTP {resp.status_code} from {source_node}: {resp.text}"
                )
        except Exception as e:
            # Confirm failure is harmless — events will re-deliver
            logger.warning(f"Confirm call failed for {source_node}: {e}")
