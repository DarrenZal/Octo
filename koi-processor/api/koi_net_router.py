"""
KOI-net Protocol Router

FastAPI APIRouter implementing the KOI-net protocol endpoints.
Mounted conditionally via feature flag (KOI_NET_ENABLED=true).

Endpoints:
    POST /koi-net/handshake           — Exchange NodeProfile, establish edges
    POST /koi-net/events/broadcast    — Receive events from peers
    POST /koi-net/events/poll         — Serve queued events to polling nodes
    POST /koi-net/events/confirm      — Acknowledge receipt of events
    POST /koi-net/manifests/fetch     — Serve manifests by RID
    POST /koi-net/bundles/fetch       — Serve bundles by RID
    POST /koi-net/rids/fetch          — List available RIDs
    GET  /koi-net/health              — Node identity and status
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.koi_protocol import (
    BundlesPayloadResponse,
    ConfirmEventsRequest,
    ConfirmEventsResponse,
    EventsPayloadRequest,
    EventsPayloadResponse,
    EventType,
    FetchBundlesRequest,
    FetchManifestsRequest,
    FetchRidsRequest,
    HandshakeRequest,
    HandshakeResponse,
    ManifestsPayloadResponse,
    NodeProfile,
    PollEventsRequest,
    RidsPayloadResponse,
    WireEvent,
    WireManifest,
    timestamp_to_z_format,
)
from api.koi_poller import KOIPoller
from api.koi_envelope import (
    EnvelopeError,
    is_signed_envelope,
    load_public_key_from_der_b64,
    sign_envelope,
    verify_envelope,
)
from api.node_identity import load_or_create_identity
from api.event_queue import EventQueue

logger = logging.getLogger(__name__)

koi_net_router = APIRouter(tags=["koi-net"])

# Module-level state (initialized in setup_koi_net)
_private_key = None
_node_profile: Optional[NodeProfile] = None
_event_queue: Optional[EventQueue] = None
_db_pool: Optional[asyncpg.Pool] = None
_poller: Optional[KOIPoller] = None


async def setup_koi_net(pool: asyncpg.Pool):
    """Initialize KOI-net subsystem. Called from app startup."""
    global _private_key, _node_profile, _event_queue, _db_pool, _poller
    _db_pool = pool

    node_name = os.getenv("KOI_NODE_NAME", "octo-salish-sea")
    base_url = os.getenv("KOI_BASE_URL")  # e.g. http://127.0.0.1:8351

    _private_key, _node_profile = load_or_create_identity(
        node_name=node_name,
        base_url=base_url,
        node_type="FULL",
    )
    _event_queue = EventQueue(pool, _node_profile.node_rid)

    # Start background poller
    _poller = KOIPoller(
        pool=pool,
        node_rid=_node_profile.node_rid,
        private_key=_private_key,
        node_profile=_node_profile,
    )
    await _poller.start()

    logger.info(f"KOI-net initialized: {_node_profile.node_rid}")


async def shutdown_koi_net():
    """Stop poller and clean up. Called from app shutdown."""
    global _poller
    if _poller:
        await _poller.stop()
        _poller = None


# =============================================================================
# Envelope helpers
# =============================================================================

async def _get_peer_public_key(source_node: str):
    """Look up a peer's public key from koi_net_nodes table."""
    if not _db_pool:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
            source_node,
        )
        if row and row["public_key"]:
            return load_public_key_from_der_b64(row["public_key"])
    return None


async def _refresh_peer_public_key(source_node: str):
    """Best-effort key refresh from peer /koi-net/health when key is missing."""
    if not _db_pool:
        return None

    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT base_url FROM koi_net_nodes WHERE node_rid = $1",
            source_node,
        )
    if not row or not row["base_url"]:
        return None

    base_url = row["base_url"].rstrip("/")
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
    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO koi_net_nodes
                (node_rid, node_name, node_type, base_url, public_key, status, last_seen)
            VALUES ($1, $2, $3, $4, $5, 'active', NOW())
            ON CONFLICT (node_rid) DO UPDATE SET
                node_name = EXCLUDED.node_name,
                node_type = EXCLUDED.node_type,
                base_url = EXCLUDED.base_url,
                public_key = EXCLUDED.public_key,
                status = 'active',
                last_seen = NOW()
            """,
            source_node,
            node_name,
            node_type,
            base_url,
            public_key,
        )

    logger.info(f"Refreshed public key for {source_node} from {base_url}/koi-net/health")
    return load_public_key_from_der_b64(public_key)


async def _unwrap_request(request: Request):
    """Parse request body, optionally unwrapping SignedEnvelope.

    Returns (payload_dict, source_node_or_none, was_signed).
    """
    try:
        body = await request.json()
    except Exception:
        return None, None, False

    if is_signed_envelope(body):
        source_node = body.get("source_node")
        public_key = await _get_peer_public_key(source_node)
        if not public_key:
            public_key = await _refresh_peer_public_key(source_node)
        if not public_key:
            raise EnvelopeError(f"No public key for {source_node}")
        payload, source = verify_envelope(body, public_key)
        return payload, source, True

    return body, None, False


def _wrap_response(payload: Dict[str, Any], target_node: Optional[str], signed: bool):
    """Optionally sign a response payload."""
    if signed and _private_key and target_node and _node_profile:
        return sign_envelope(payload, _node_profile.node_rid, target_node, _private_key)
    return payload


# =============================================================================
# Endpoints
# =============================================================================

@koi_net_router.post("/handshake")
async def handshake(request: Request):
    """Exchange NodeProfile and establish edges."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if not payload or "profile" not in payload:
        return JSONResponse(status_code=400, content={"error": "Missing profile"})

    try:
        req = HandshakeRequest(**payload)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Invalid handshake: {exc}"})

    peer = req.profile

    # Store/update peer in koi_net_nodes
    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO koi_net_nodes
                (node_rid, node_name, node_type, base_url, public_key,
                 provides_event, provides_state, last_seen, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), 'active')
            ON CONFLICT (node_rid) DO UPDATE SET
                node_name = EXCLUDED.node_name,
                node_type = EXCLUDED.node_type,
                base_url = EXCLUDED.base_url,
                public_key = EXCLUDED.public_key,
                provides_event = EXCLUDED.provides_event,
                provides_state = EXCLUDED.provides_state,
                last_seen = NOW(),
                status = 'active'
            """,
            peer.node_rid,
            peer.node_name,
            peer.node_type,
            peer.base_url,
            peer.public_key,
            peer.provides.event,
            peer.provides.state,
        )

    logger.info(f"Handshake with {peer.node_rid} ({peer.node_name})")

    response = HandshakeResponse(
        profile=_node_profile,
        accepted=True,
    )
    return JSONResponse(
        content=_wrap_response(response.model_dump(), peer.node_rid, signed)
    )


@koi_net_router.post("/events/broadcast")
async def events_broadcast(request: Request):
    """Receive events from peers."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if not payload:
        return JSONResponse(status_code=400, content={"error": "Empty payload"})

    events = payload.get("events", [])
    if not isinstance(events, list):
        return JSONResponse(status_code=400, content={"error": "events must be a list"})

    queued = 0
    for event_data in events:
        if not isinstance(event_data, dict):
            continue
        rid = event_data.get("rid")
        event_type = event_data.get("event_type", "NEW")
        if not rid:
            continue

        try:
            await _event_queue.add(
                event_type=event_type,
                rid=rid,
                manifest=event_data.get("manifest"),
                contents=event_data.get("contents"),
                source_node=source_node or "unknown",
            )
            queued += 1
        except Exception as exc:
            logger.warning(f"Failed to queue event {rid}: {exc}")

    logger.info(f"Broadcast: queued {queued}/{len(events)} events from {source_node}")
    resp = {"status": "ok", "queued": queued}
    return JSONResponse(content=_wrap_response(resp, source_node, signed))


@koi_net_router.post("/events/poll")
async def events_poll(request: Request):
    """Serve queued events to a polling node."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if not payload:
        return JSONResponse(status_code=400, content={"error": "Empty payload"})

    # The requesting node is identified by source_node (from envelope) or payload
    requesting_node = source_node or payload.get("node_id")
    if not requesting_node:
        return JSONResponse(
            status_code=400,
            content={"error": "Cannot identify requesting node (use SignedEnvelope or include node_id)"},
        )

    limit = payload.get("limit", 50)
    if not isinstance(limit, int) or limit <= 0:
        limit = 50

    # Check which rid_types this node should receive (from edge config)
    rid_types = None
    async with _db_pool.acquire() as conn:
        edge = await conn.fetchrow(
            """
            SELECT rid_types FROM koi_net_edges
            WHERE target_node = $1 AND source_node = $2 AND status = 'APPROVED'
            """,
            requesting_node,
            _node_profile.node_rid,
        )
        if edge and edge["rid_types"]:
            rid_types = edge["rid_types"]

    events = await _event_queue.poll(requesting_node, limit, rid_types)

    # Convert to wire format
    wire_events = []
    for ev in events:
        manifest = None
        if ev.get("manifest"):
            m = ev["manifest"]
            manifest = {
                "rid": m.get("rid", ev["rid"]),
                "timestamp": timestamp_to_z_format(m.get("timestamp", "")),
                "sha256_hash": m.get("sha256_hash", ""),
            }
        wire_events.append({
            "rid": ev["rid"],
            "event_type": ev["event_type"],
            "event_id": ev.get("event_id"),
            "manifest": manifest,
            "contents": ev.get("contents"),
        })

    resp = EventsPayloadResponse(events=[
        WireEvent(**we) for we in wire_events
    ])
    return JSONResponse(
        content=_wrap_response(resp.model_dump(exclude_none=True), requesting_node, signed)
    )


@koi_net_router.post("/events/confirm")
async def events_confirm(request: Request):
    """Acknowledge receipt of events."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if not payload:
        return JSONResponse(status_code=400, content={"error": "Empty payload"})

    confirming_node = source_node or payload.get("node_id")
    event_ids = payload.get("event_ids", [])

    if not confirming_node:
        return JSONResponse(status_code=400, content={"error": "Cannot identify confirming node"})

    confirmed = await _event_queue.confirm(event_ids, confirming_node)
    resp = ConfirmEventsResponse(confirmed=confirmed)
    return JSONResponse(
        content=_wrap_response(resp.model_dump(), confirming_node, signed)
    )


@koi_net_router.post("/manifests/fetch")
async def manifests_fetch(request: Request):
    """Serve manifests by RID."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    rids = payload.get("rids", []) if payload else []

    manifests = []
    async with _db_pool.acquire() as conn:
        for rid in rids:
            # Look up the most recent event for this RID
            row = await conn.fetchrow(
                """
                SELECT manifest FROM koi_net_events
                WHERE rid = $1 AND manifest IS NOT NULL
                ORDER BY queued_at DESC LIMIT 1
                """,
                rid,
            )
            if row and row["manifest"]:
                m = json.loads(row["manifest"]) if isinstance(row["manifest"], str) else row["manifest"]
                manifests.append(WireManifest(
                    rid=m.get("rid", rid),
                    timestamp=timestamp_to_z_format(m.get("timestamp", "")),
                    sha256_hash=m.get("sha256_hash", ""),
                ))

    resp = ManifestsPayloadResponse(manifests=manifests)
    return JSONResponse(
        content=_wrap_response(resp.model_dump(exclude_none=True), source_node, signed)
    )


@koi_net_router.post("/bundles/fetch")
async def bundles_fetch(request: Request):
    """Serve bundles by RID."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    rids = payload.get("rids", []) if payload else []

    bundles = []
    not_found = []

    async with _db_pool.acquire() as conn:
        for rid in rids:
            row = await conn.fetchrow(
                """
                SELECT manifest, contents FROM koi_net_events
                WHERE rid = $1 AND contents IS NOT NULL
                ORDER BY queued_at DESC LIMIT 1
                """,
                rid,
            )
            if row:
                m = json.loads(row["manifest"]) if isinstance(row["manifest"], str) else (row["manifest"] or {})
                c = json.loads(row["contents"]) if isinstance(row["contents"], str) else (row["contents"] or {})
                bundles.append({
                    "manifest": {
                        "rid": m.get("rid", rid),
                        "timestamp": timestamp_to_z_format(m.get("timestamp", "")),
                        "sha256_hash": m.get("sha256_hash", ""),
                    },
                    "contents": c,
                })
            else:
                not_found.append(rid)

    resp = BundlesPayloadResponse(bundles=bundles, not_found=not_found)
    return JSONResponse(
        content=_wrap_response(resp.model_dump(exclude_none=True), source_node, signed)
    )


@koi_net_router.post("/rids/fetch")
async def rids_fetch(request: Request):
    """List available RIDs, optionally filtered by type."""
    try:
        payload, source_node, signed = await _unwrap_request(request)
    except EnvelopeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    rid_types = (payload or {}).get("rid_types")

    async with _db_pool.acquire() as conn:
        if rid_types:
            # Filter by entity type from entity_registry
            rows = await conn.fetch(
                """
                SELECT DISTINCT er.koi_rid
                FROM entity_registry er
                WHERE er.koi_rid IS NOT NULL
                  AND er.entity_type = ANY($1)
                ORDER BY er.koi_rid
                """,
                rid_types,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT DISTINCT koi_rid
                FROM entity_registry
                WHERE koi_rid IS NOT NULL
                ORDER BY koi_rid
                """
            )

    rids = [row["koi_rid"] for row in rows]
    resp = RidsPayloadResponse(rids=rids)
    return JSONResponse(
        content=_wrap_response(resp.model_dump(), source_node, signed)
    )


@koi_net_router.get("/health")
async def koi_net_health():
    """Node identity, connected peers, capabilities."""
    peers = []
    queue_size = 0

    if _db_pool:
        async with _db_pool.acquire() as conn:
            peer_rows = await conn.fetch(
                "SELECT node_rid, node_name, status, last_seen FROM koi_net_nodes WHERE status = 'active'"
            )
            peers = [
                {
                    "node_rid": r["node_rid"],
                    "node_name": r["node_name"],
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                }
                for r in peer_rows
            ]

    if _event_queue:
        queue_size = await _event_queue.get_queue_size()

    return {
        "status": "healthy",
        "node": _node_profile.model_dump() if _node_profile else None,
        "peers": peers,
        "event_queue_size": queue_size,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
