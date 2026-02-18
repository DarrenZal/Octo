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
from api.node_identity import (
    derive_node_rid_hash,
    load_or_create_identity,
    node_rid_matches_public_key,
    node_rid_suffix,
)
from api.event_queue import EventQueue

logger = logging.getLogger(__name__)

from rid_lib.ext.utils import sha256_hash_json as rid_sha256_hash_json

koi_net_router = APIRouter(tags=["koi-net"])

# Module-level state (initialized in setup_koi_net)
_private_key = None
_node_profile: Optional[NodeProfile] = None
_event_queue: Optional[EventQueue] = None
_db_pool: Optional[asyncpg.Pool] = None
_poller: Optional[KOIPoller] = None


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _security_policy() -> Dict[str, bool]:
    strict_mode = _bool_env("KOI_STRICT_MODE", False)
    require_signed = _bool_env("KOI_REQUIRE_SIGNED_ENVELOPES", strict_mode)
    enforce_target = _bool_env("KOI_ENFORCE_TARGET_MATCH", strict_mode)
    enforce_source_binding = _bool_env(
        "KOI_ENFORCE_SOURCE_KEY_RID_BINDING",
        strict_mode,
    )
    allow_legacy16 = _bool_env("KOI_ALLOW_LEGACY16_NODE_RID", True)
    allow_der64 = _bool_env("KOI_ALLOW_DER64_NODE_RID", True)
    allow_b64_64 = _bool_env("KOI_ALLOW_B64_64_NODE_RID", True)
    require_approved_edge_for_poll = _bool_env(
        "KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL", strict_mode,
    )
    return {
        "strict_mode": strict_mode,
        "require_signed": require_signed,
        "enforce_target": enforce_target,
        "enforce_source_binding": enforce_source_binding,
        "allow_legacy16": allow_legacy16,
        "allow_der64": allow_der64,
        "allow_b64_64": allow_b64_64,
        "require_approved_edge_for_poll": require_approved_edge_for_poll,
    }


# BlockScience ErrorType mapping (api_models.py:55-57)
# Octo error codes → BlockScience ErrorType values
# IMPORTANT: "unknown_node" triggers handshake retry in BlockScience clients
# (error_handler.py:44-47), so only use it for genuinely unknown nodes.
# Pre-authentication / parse errors use "invalid_signature" to signal
# "don't retry with handshake, the request itself is malformed."
_ERROR_TYPE_MAP = {
    "UNKNOWN_SOURCE_NODE": "unknown_node",
    "SOURCE_NODE_KEY_BINDING_FAILED": "invalid_key",
    "INVALID_SIGNATURE": "invalid_signature",
    "INVALID_SIGNATURE_FORMAT": "invalid_signature",
    "TARGET_NODE_MISMATCH": "invalid_target",
    "SOURCE_NODE_MISMATCH": "invalid_target",
    # Pre-auth / parse errors → invalid_signature (not unknown_node)
    "INVALID_JSON": "invalid_signature",
    "INVALID_PAYLOAD": "invalid_signature",
    "UNSIGNED_ENVELOPE_REQUIRED": "invalid_signature",
    "MISSING_ENVELOPE_FIELDS": "invalid_signature",
    "ENVELOPE_ERROR": "invalid_signature",
    "CRYPTO_UNAVAILABLE": "invalid_signature",
}

# Fallback for unmapped codes — invalid_signature is safer than unknown_node
# because it won't trigger handshake retries in BlockScience clients
_DEFAULT_ERROR_TYPE = "invalid_signature"


def _protocol_error(
    status_code: int,
    code: str,
    message: str,
    **extra: Any,
) -> JSONResponse:
    # BlockScience clients expect: {"type": "error_response", "error": <ErrorType>}
    error_type = _ERROR_TYPE_MAP.get(code, _DEFAULT_ERROR_TYPE)
    body = {
        "type": "error_response",
        "error": error_type,
        "error_code": code,
        "message": message,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def _envelope_error_response(exc: EnvelopeError) -> JSONResponse:
    code = getattr(exc, "code", "ENVELOPE_ERROR")
    status_code = 400
    if code in {"INVALID_SIGNATURE", "UNSIGNED_ENVELOPE_REQUIRED"}:
        status_code = 401
    return _protocol_error(status_code, code, str(exc))


def _canonical_sha256_json(data: Any) -> str:
    """Compute JCS-canonical sha256 hash using rid-lib."""
    return rid_sha256_hash_json(data)


def _manifest_sha256_hash(manifest: Dict[str, Any], contents: Optional[Dict[str, Any]] = None) -> str:
    """Return manifest sha256 hash, deriving a canonical value when absent."""
    existing = manifest.get("sha256_hash")
    if existing:
        return existing
    if contents is not None:
        return _canonical_sha256_json(contents)
    return _canonical_sha256_json(
        {
            "rid": manifest.get("rid", ""),
            "timestamp": manifest.get("timestamp", ""),
        }
    )


async def setup_koi_net(pool: asyncpg.Pool, embed_fn=None):
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
    _node_profile.ontology_uri = os.getenv(
        "KOI_ONTOLOGY_URI", "http://bkc.regen.network/ontology"
    )
    _node_profile.ontology_version = os.getenv("KOI_ONTOLOGY_VERSION", "1.0.0")
    _event_queue = EventQueue(pool, _node_profile.node_rid)

    # Build pipeline if feature-flagged
    use_pipeline = _bool_env("KOI_USE_PIPELINE", False)
    pipeline = None
    if use_pipeline:
        from api.pipeline import KnowledgePipeline, OctoHandlerContext, _default_handlers
        pipeline_ctx = OctoHandlerContext(
            pool=pool, node_rid=_node_profile.node_rid,
            node_profile=_node_profile, event_queue=_event_queue,
            embed_fn=embed_fn,
        )
        pipeline = KnowledgePipeline(ctx=pipeline_ctx, handlers=_default_handlers())
        logger.info("KOI pipeline enabled (KOI_USE_PIPELINE=true)")

    # Start background poller
    _poller = KOIPoller(
        pool=pool,
        node_rid=_node_profile.node_rid,
        private_key=_private_key,
        node_profile=_node_profile,
        pipeline=pipeline,
        use_pipeline=use_pipeline,
        event_queue=_event_queue,
    )
    await _poller.start()

    policy = _security_policy()
    logger.info(
        "KOI-net validation policy: strict_mode=%s require_signed=%s "
        "enforce_target=%s enforce_source_binding=%s allow_legacy16=%s "
        "allow_der64=%s allow_b64_64=%s require_approved_edge_for_poll=%s",
        policy["strict_mode"],
        policy["require_signed"],
        policy["enforce_target"],
        policy["enforce_source_binding"],
        policy["allow_legacy16"],
        policy["allow_der64"],
        policy["allow_b64_64"],
        policy["require_approved_edge_for_poll"],
    )
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

async def _get_peer_key_record(source_node: str):
    """Look up a peer key record from koi_net_nodes.

    Returns dict with:
      - der_b64: DER-encoded public key (base64)
      - public_key: loaded key object
    """
    if not _db_pool:
        return None
    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
            source_node,
        )
        if row and row["public_key"]:
            return {
                "der_b64": row["public_key"],
                "public_key": load_public_key_from_der_b64(row["public_key"]),
            }
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
    ontology_uri = node.get("ontology_uri")
    ontology_version = node.get("ontology_version")
    async with _db_pool.acquire() as conn:
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
                public_key = EXCLUDED.public_key,
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

    logger.info(f"Refreshed public key for {source_node} from {base_url}/koi-net/health")
    return {
        "der_b64": public_key,
        "public_key": load_public_key_from_der_b64(public_key),
    }


def _extract_bootstrap_key(
    body: Dict[str, Any], source_node: str
) -> Optional[Dict[str, Any]]:
    """Extract and validate a bootstrap key from a broadcast payload.

    BlockScience nodes self-introduce by broadcasting FORGET+NEW events where
    the NEW event carries a NodeProfile with a public_key. We validate that
    the source_node RID hash matches sha256(base64(DER(pubkey))) before
    returning the key material.

    Does NOT persist anything to the database — that happens after envelope
    signature verification succeeds (see _persist_bootstrap_peer).

    Returns a key_record dict (with extra "bootstrap_contents") or None.
    """
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return None

    events = payload.get("events")
    if not isinstance(events, list):
        return None

    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") != "NEW":
            continue
        if ev.get("rid") != source_node:
            continue
        contents = ev.get("contents")
        if not isinstance(contents, dict):
            continue
        public_key_b64 = contents.get("public_key")
        if not public_key_b64:
            continue

        # Validate key-RID binding: source_node hash suffix must match
        # sha256(base64(DER(pubkey))) — prevents forged self-introductions
        try:
            pub_key = load_public_key_from_der_b64(public_key_b64)
        except Exception:
            logger.warning(
                f"Bootstrap: invalid public key in NEW event for {source_node}"
            )
            return None

        suffix = node_rid_suffix(source_node)
        if not suffix:
            return None

        # Check against b64_64 (canonical) and legacy16
        b64_hash = derive_node_rid_hash(pub_key, "b64_64")
        legacy_hash = derive_node_rid_hash(pub_key, "legacy16")
        if suffix != b64_hash and suffix != legacy_hash:
            logger.warning(
                f"Bootstrap: RID hash mismatch for {source_node} — "
                f"expected {b64_hash[:16]}... or {legacy_hash}, got {suffix}"
            )
            return None

        # Key-RID binding verified — return key record (no DB write yet)
        return {
            "der_b64": public_key_b64,
            "public_key": pub_key,
            "bootstrap_contents": contents,
        }

    return None


async def _persist_bootstrap_peer(
    source_node: str, key_record: Dict[str, Any]
) -> None:
    """Persist a bootstrapped peer to koi_net_nodes after signature verification.

    Only call this after verify_envelope has succeeded — the key_record
    must have been returned by _extract_bootstrap_key.
    """
    contents = key_record.get("bootstrap_contents")
    if not contents or not _db_pool:
        return

    node_name = contents.get("node_name") or source_node
    node_type = contents.get("node_type") or "FULL"
    base_url = contents.get("base_url")
    public_key_b64 = key_record["der_b64"]
    ontology_uri = contents.get("ontology_uri")
    ontology_version = contents.get("ontology_version")

    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO koi_net_nodes
                (node_rid, node_name, node_type, base_url,
                 public_key, ontology_uri, ontology_version,
                 status, last_seen)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', NOW())
            ON CONFLICT (node_rid) DO UPDATE SET
                node_name = EXCLUDED.node_name,
                node_type = EXCLUDED.node_type,
                base_url = EXCLUDED.base_url,
                public_key = EXCLUDED.public_key,
                ontology_uri = COALESCE(EXCLUDED.ontology_uri, koi_net_nodes.ontology_uri),
                ontology_version = COALESCE(EXCLUDED.ontology_version, koi_net_nodes.ontology_version),
                status = 'active',
                last_seen = NOW()
            """,
            source_node,
            node_name,
            node_type,
            base_url,
            public_key_b64,
            ontology_uri,
            ontology_version,
        )
    logger.info(
        f"Bootstrap: registered new peer {source_node} ({node_name}) "
        f"via broadcast NEW event"
    )


async def _unwrap_request(request: Request, allow_unsigned: bool = False):
    """Parse request body, optionally unwrapping SignedEnvelope.

    Returns (payload_dict, source_node_or_none, was_signed).
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise EnvelopeError("Invalid JSON payload", code="INVALID_JSON") from exc

    if not isinstance(body, dict):
        raise EnvelopeError("Payload must be a JSON object", code="INVALID_PAYLOAD")

    policy = _security_policy()
    if not is_signed_envelope(body):
        if policy["require_signed"] and not allow_unsigned:
            raise EnvelopeError(
                "Signed envelope required by KOI policy",
                code="UNSIGNED_ENVELOPE_REQUIRED",
            )
        return body, None, False

    source_node = body.get("source_node")
    target_node = body.get("target_node")
    if not source_node:
        raise EnvelopeError("Signed envelope missing source_node", code="MISSING_ENVELOPE_FIELDS")

    if policy["enforce_target"] and _node_profile and target_node != _node_profile.node_rid:
        raise EnvelopeError(
            f"Envelope target_node mismatch: expected {_node_profile.node_rid}, got {target_node}",
            code="TARGET_NODE_MISMATCH",
        )

    key_record = await _get_peer_key_record(source_node)
    if not key_record:
        key_record = await _refresh_peer_public_key(source_node)
    is_bootstrap = False
    if not key_record or not key_record.get("public_key"):
        # Attempt bootstrap: extract key from NodeProfile NEW event in payload
        # (BlockScience-style self-introduction via broadcast).
        # Does NOT persist to DB yet — we verify the signature first.
        key_record = _extract_bootstrap_key(body, source_node)
        is_bootstrap = True
    if not key_record or not key_record.get("public_key"):
        raise EnvelopeError(f"No public key for {source_node}", code="UNKNOWN_SOURCE_NODE")

    if policy["enforce_source_binding"]:
        bound = node_rid_matches_public_key(
            source_node,
            key_record["public_key"],
            allow_legacy16=policy["allow_legacy16"],
            allow_der64=policy["allow_der64"],
            allow_b64_64=policy["allow_b64_64"],
        )
        if not bound:
            raise EnvelopeError(
                f"Source node RID does not match stored public key: {source_node}",
                code="SOURCE_NODE_KEY_BINDING_FAILED",
            )

    payload, source = verify_envelope(
        body,
        key_record["public_key"],
        expected_target_node=_node_profile.node_rid
        if policy["enforce_target"] and _node_profile
        else None,
    )

    # Signature verified — now safe to persist the bootstrapped peer
    if is_bootstrap:
        await _persist_bootstrap_peer(source_node, key_record)

    return payload, source, True


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
        payload, source_node, signed = await _unwrap_request(request, allow_unsigned=True)
    except EnvelopeError as exc:
        return _envelope_error_response(exc)

    if not payload or "profile" not in payload:
        return _protocol_error(400, "MISSING_PROFILE", "Missing profile")

    try:
        req = HandshakeRequest(**payload)
    except Exception as exc:
        return _protocol_error(400, "INVALID_HANDSHAKE", f"Invalid handshake: {exc}")

    peer = req.profile

    # Store/update peer in koi_net_nodes
    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO koi_net_nodes
                (node_rid, node_name, node_type, base_url, public_key,
                 provides_event, provides_state, ontology_uri, ontology_version,
                 last_seen, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), 'active')
            ON CONFLICT (node_rid) DO UPDATE SET
                node_name = EXCLUDED.node_name,
                node_type = EXCLUDED.node_type,
                base_url = EXCLUDED.base_url,
                public_key = EXCLUDED.public_key,
                provides_event = EXCLUDED.provides_event,
                provides_state = EXCLUDED.provides_state,
                ontology_uri = COALESCE(EXCLUDED.ontology_uri, koi_net_nodes.ontology_uri),
                ontology_version = COALESCE(EXCLUDED.ontology_version, koi_net_nodes.ontology_version),
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
            peer.ontology_uri,
            peer.ontology_version,
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
        return _envelope_error_response(exc)

    if not payload:
        return _protocol_error(400, "EMPTY_PAYLOAD", "Empty payload")

    events = payload.get("events", [])
    if not isinstance(events, list):
        return _protocol_error(400, "INVALID_EVENTS", "events must be a list")

    queued = 0
    for event_data in events:
        if not isinstance(event_data, dict):
            continue
        rid = event_data.get("rid")
        event_type = event_data.get("event_type", "NEW")
        if not rid:
            continue

        try:
            result = await _event_queue.add(
                event_type=event_type,
                rid=rid,
                manifest=event_data.get("manifest"),
                contents=event_data.get("contents"),
                source_node=source_node or "unknown",
                event_id=event_data.get("event_id"),
            )
            if result is not None:
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
        return _envelope_error_response(exc)

    if not payload:
        return _protocol_error(400, "EMPTY_PAYLOAD", "Empty payload")

    # The requesting node is identified by source_node (from envelope) or payload
    requesting_node = source_node or payload.get("node_id")
    if not requesting_node:
        return _protocol_error(
            400,
            "MISSING_REQUESTING_NODE",
            "Cannot identify requesting node (use SignedEnvelope or include node_id)",
        )

    limit = payload.get("limit", 50)
    if not isinstance(limit, int) or limit <= 0:
        limit = 50

    # Check which rid_types this node should receive (from edge config)
    rid_types = None
    has_approved_edge = False
    async with _db_pool.acquire() as conn:
        edge = await conn.fetchrow(
            """
            SELECT rid_types FROM koi_net_edges
            WHERE target_node = $1 AND source_node = $2 AND status = 'APPROVED'
            """,
            requesting_node,
            _node_profile.node_rid,
        )
        if edge:
            has_approved_edge = True
            if edge["rid_types"]:
                rid_types = edge["rid_types"]

    # In strict mode (or when explicitly configured), unapproved peers get nothing
    policy = _security_policy()
    if not has_approved_edge and policy["require_approved_edge_for_poll"]:
        logger.info(
            f"Poll: no approved edge for {requesting_node}, returning empty (strict)"
        )
        resp = EventsPayloadResponse(events=[])
        return JSONResponse(
            content=_wrap_response(resp.model_dump(exclude_none=True), requesting_node, signed)
        )

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
                "sha256_hash": _manifest_sha256_hash(m, ev.get("contents")),
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
        return _envelope_error_response(exc)

    if not payload:
        return _protocol_error(400, "EMPTY_PAYLOAD", "Empty payload")

    confirming_node = source_node or payload.get("node_id")
    event_ids = payload.get("event_ids", [])

    if not confirming_node:
        return _protocol_error(400, "MISSING_CONFIRMING_NODE", "Cannot identify confirming node")

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
        return _envelope_error_response(exc)

    rids = payload.get("rids", []) if payload else []

    manifests = []
    async with _db_pool.acquire() as conn:
        for rid in rids:
            # Look up the most recent event for this RID
            row = await conn.fetchrow(
                """
                SELECT manifest, contents FROM koi_net_events
                WHERE rid = $1 AND manifest IS NOT NULL
                ORDER BY queued_at DESC LIMIT 1
                """,
                rid,
            )
            if row and row["manifest"]:
                m = json.loads(row["manifest"]) if isinstance(row["manifest"], str) else row["manifest"]
                c = json.loads(row["contents"]) if isinstance(row["contents"], str) else (row["contents"] or None)
                manifests.append(WireManifest(
                    rid=m.get("rid", rid),
                    timestamp=timestamp_to_z_format(m.get("timestamp", "")),
                    sha256_hash=_manifest_sha256_hash(m, c),
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
        return _envelope_error_response(exc)

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
                        "sha256_hash": _manifest_sha256_hash(m, c),
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
        return _envelope_error_response(exc)

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
    policy = _security_policy()

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
        "pipeline_enabled": _poller is not None and _poller.use_pipeline and _poller.pipeline is not None,
        "protocol": {
            "strict_mode": policy["strict_mode"],
            "require_signed_envelopes": policy["require_signed"],
            "enforce_target_match": policy["enforce_target"],
            "enforce_source_key_rid_binding": policy["enforce_source_binding"],
            "core_endpoints": [
                "/koi-net/events/broadcast",
                "/koi-net/events/poll",
                "/koi-net/manifests/fetch",
                "/koi-net/bundles/fetch",
                "/koi-net/rids/fetch",
            ],
            "extensions": [
                "/koi-net/handshake",
                "/koi-net/events/confirm",
                "/koi-net/health",
            ],
        },
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
