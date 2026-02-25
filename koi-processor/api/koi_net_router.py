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
    GET  /koi-net/edges              — Active federation edges (dashboard)
"""

from __future__ import annotations

import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel as _ShareBaseModel

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
        existing_key = await conn.fetchval(
            "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
            source_node,
        )
        if existing_key and existing_key != public_key:
            logger.warning(
                "KEY MISMATCH during key refresh for %s — pinned key starts with: %s... "
                "refreshed key starts with: %s... refusing update",
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
        existing_key = await conn.fetchval(
            "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
            source_node,
        )
        if existing_key and existing_key != public_key_b64:
            logger.warning(
                "KEY MISMATCH during bootstrap for %s — pinned key starts with: %s... "
                "bootstrap key starts with: %s... refusing update",
                source_node, existing_key[:20], public_key_b64[:20],
            )
            return

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


def _read_admin_token() -> Optional[str]:
    """Read admin token from env or state dir file."""
    admin_token = os.getenv("KOI_ADMIN_TOKEN")
    if admin_token:
        return admin_token

    state_dir = os.getenv("KOI_STATE_DIR", "")
    token_path = os.path.join(state_dir, "admin_token") if state_dir else ""
    if token_path and os.path.exists(token_path):
        with open(token_path) as f:
            return f.read().strip()
    return None


def _enforce_local_admin(request: Request) -> Optional[JSONResponse]:
    """Return protocol error response if request is not localhost/admin, else None."""
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        return _protocol_error(403, "FORBIDDEN", "Endpoint is localhost-only")

    admin_token = _read_admin_token()
    if admin_token:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != admin_token:
            return _protocol_error(401, "UNAUTHORIZED", "Invalid or missing admin token")
    return None


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
        # Key pinning check: reject if peer presents a different key than what's pinned
        if peer.public_key:
            existing_key = await conn.fetchval(
                "SELECT public_key FROM koi_net_nodes WHERE node_rid = $1",
                peer.node_rid,
            )
            if existing_key and existing_key != peer.public_key:
                logger.warning(
                    "KEY ROTATION REJECTED: node %s (%s) presented different public key. "
                    "Existing key starts with: %s... New key starts with: %s... "
                    "Manual re-approval required.",
                    peer.node_rid, peer.node_name, existing_key[:20], peer.public_key[:20],
                )
                return _protocol_error(
                    403,
                    "KEY_MISMATCH",
                    f"Public key for {peer.node_rid} does not match pinned key. Manual re-approval required.",
                )

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
            peer.provides.event if peer.provides else [],
            peer.provides.state if peer.provides else [],
            peer.ontology_uri,
            peer.ontology_version,
        )

        # Inbound edge: we can poll them immediately.
        edge_rid_inbound = f"orn:koi-net.edge:{peer.node_rid}>{_node_profile.node_rid}:poll"
        await conn.execute(
            """
            INSERT INTO koi_net_edges
                (edge_rid, source_node, target_node, edge_type, status, rid_types)
            VALUES ($1, $2, $3, 'POLL', 'APPROVED', $4)
            ON CONFLICT (edge_rid) DO UPDATE SET updated_at = NOW()
            """,
            edge_rid_inbound,
            peer.node_rid,
            _node_profile.node_rid,
            peer.provides.event if peer.provides else [],
        )

        # Outbound edge: peer polling us requires explicit local approval.
        edge_rid_outbound = f"orn:koi-net.edge:{_node_profile.node_rid}>{peer.node_rid}:poll"
        await conn.execute(
            """
            INSERT INTO koi_net_edges
                (edge_rid, source_node, target_node, edge_type, status, rid_types)
            VALUES ($1, $2, $3, 'POLL', 'PROPOSED', $4)
            ON CONFLICT (edge_rid) DO NOTHING
            """,
            edge_rid_outbound,
            _node_profile.node_rid,
            peer.node_rid,
            _node_profile.provides.event if _node_profile.provides else [],
        )

        if peer.node_name:
            try:
                await conn.execute(
                    """
                    INSERT INTO koi_net_peer_aliases (alias, node_rid)
                    VALUES ($1, $2)
                    ON CONFLICT (alias) DO UPDATE SET node_rid = $2
                    """,
                    peer.node_name.lower(),
                    peer.node_rid,
                )
            except asyncpg.PostgresError as exc:
                if isinstance(exc, asyncpg.exceptions.UndefinedTableError):
                    logger.warning("koi_net_peer_aliases table missing; skipping alias auto-create")
                else:
                    raise

    logger.info(
        "Handshake with %s (%s) — inbound edge APPROVED, outbound edge PROPOSED",
        peer.node_rid,
        peer.node_name,
    )

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


@koi_net_router.get("/edges")
async def koi_net_edges():
    """Active federation edges (for dashboard visualization)."""
    if not _db_pool:
        return {"edges": []}
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT edge_rid, source_node, target_node, edge_type, status "
            "FROM koi_net_edges WHERE status = 'APPROVED'"
        )
    return {"edges": [dict(r) for r in rows]}


@koi_net_router.post("/edges/approve")
async def approve_edge(request: Request):
    """Approve a PROPOSED edge to allow a peer to poll our events."""
    auth_err = _enforce_local_admin(request)
    if auth_err:
        return auth_err

    try:
        body = await request.json()
    except Exception:
        return _protocol_error(400, "INVALID_JSON", "Invalid JSON body")

    edge_rid = body.get("edge_rid")
    if not edge_rid:
        return _protocol_error(400, "MISSING_EDGE_RID", "edge_rid is required")

    if not _db_pool:
        return _protocol_error(503, "NOT_INITIALIZED", "KOI-net not initialized")

    async with _db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE koi_net_edges SET status = 'APPROVED', updated_at = NOW()
            WHERE edge_rid = $1 AND status = 'PROPOSED'
            """,
            edge_rid,
        )
        count = int(result.split()[-1])

    if count == 0:
        return _protocol_error(404, "EDGE_NOT_FOUND", f"No PROPOSED edge found with rid '{edge_rid}'")

    logger.info("Approved edge: %s", edge_rid)
    return {"status": "approved", "edge_rid": edge_rid}


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
                "/koi-net/share",
                "/koi-net/shared-with-me",
                "/koi-net/commons/intake",
                "/koi-net/commons/intake/decide",
            ],
        },
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


class ShareDocumentRequest(_ShareBaseModel):
    """Request to share a document with a peer or commons node."""
    document_rid: str
    recipient: str
    recipient_type: str = "peer"  # peer | commons
    message: Optional[str] = None
    share_mode: str = "root_plus_required"  # root_only | root_plus_required | context_pack
    context_depth: Optional[int] = None
    references: Optional[List[Dict[str, Any]]] = None
    contents: Optional[Dict[str, Any]] = None


class ShareDocumentResponse(_ShareBaseModel):
    status: str
    event_id: str
    document_rid: str
    recipient_node_rid: str
    recipient_type: str = "peer"
    share_mode: str
    context_depth: int = 1
    references_total: int = 0
    references_included: int = 0
    references_missing: int = 0
    references_excluded: int = 0
    message: Optional[str] = None


class CommonsIntakeDecisionRequest(_ShareBaseModel):
    share_id: Optional[int] = None
    event_id: Optional[str] = None
    action: str  # approve | reject
    reviewer: Optional[str] = None
    note: Optional[str] = None


@koi_net_router.post("/share")
async def share_document(req: ShareDocumentRequest):
    """Share a document by queueing a recipient-scoped FUN event."""
    allowed_modes = {"root_only", "root_plus_required", "context_pack"}
    allowed_recipient_types = {"peer", "commons"}
    share_mode = (req.share_mode or "root_plus_required").strip().lower()
    recipient_type = (req.recipient_type or "peer").strip().lower()
    if share_mode not in allowed_modes:
        return _protocol_error(
            400,
            "INVALID_SHARE_MODE",
            f"Invalid share_mode '{req.share_mode}'. Valid modes: root_only, root_plus_required, context_pack",
        )
    if recipient_type not in allowed_recipient_types:
        return _protocol_error(
            400,
            "INVALID_RECIPIENT_TYPE",
            f"Invalid recipient_type '{req.recipient_type}'. Valid types: peer, commons",
        )
    default_context_depth = 2 if share_mode == "context_pack" else 1
    context_depth = req.context_depth if req.context_depth is not None else default_context_depth
    if context_depth < 1 or context_depth > 4:
        return _protocol_error(400, "INVALID_CONTEXT_DEPTH", "context_depth must be an integer between 1 and 4")

    if not _db_pool:
        return _protocol_error(503, "NOT_INITIALIZED", "KOI-net not initialized")
    if not _event_queue:
        return _protocol_error(503, "NOT_INITIALIZED", "Event queue not initialized")
    if not _node_profile:
        return _protocol_error(503, "NOT_INITIALIZED", "Node identity not initialized")

    async with _db_pool.acquire() as conn:
        recipient_node_rid = await _resolve_recipient(conn, req.recipient)
        if not recipient_node_rid:
            return _protocol_error(
                404,
                "RECIPIENT_NOT_FOUND",
                f"No peer found for '{req.recipient}'. Register peer via /koi-net/handshake first.",
            )

        prev = await conn.fetchrow(
            """
            SELECT id FROM koi_net_events
            WHERE rid = $1 AND source_node = $2 AND target_node = $3
            ORDER BY queued_at DESC LIMIT 1
            """,
            req.document_rid,
            _node_profile.node_rid,
            recipient_node_rid,
        )
        event_type = EventType.UPDATE if prev else EventType.NEW

        now_z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        contents_payload = req.contents or {"message": req.message or "", "document_rid": req.document_rid}
        if req.message and not contents_payload.get("message"):
            contents_payload["message"] = req.message

        references_payload: List[Dict[str, Any]] = []
        if req.references:
            references_payload = [r for r in req.references if isinstance(r, dict)]
        elif isinstance(contents_payload.get("references"), list):
            references_payload = [r for r in contents_payload.get("references", []) if isinstance(r, dict)]

        refs_total = len(references_payload)
        refs_included = 0
        refs_required = 0
        refs_missing = 0
        refs_excluded = 0
        for ref in references_payload:
            if bool(ref.get("required")):
                refs_required += 1
            if bool(ref.get("included")) or bool(ref.get("include")):
                refs_included += 1
            if not bool(ref.get("exists")):
                refs_missing += 1
            elif not (bool(ref.get("included")) or bool(ref.get("include"))):
                refs_excluded += 1

        dependency_graph = contents_payload.get("dependency_graph")
        dependency_graph_summary: Optional[Dict[str, Any]] = None
        missing_references: List[Dict[str, Any]] = []
        if isinstance(dependency_graph, dict):
            maybe_summary = dependency_graph.get("summary")
            if isinstance(maybe_summary, dict):
                dependency_graph_summary = maybe_summary
            maybe_missing = dependency_graph.get("missing_references")
            if isinstance(maybe_missing, list):
                missing_references = [m for m in maybe_missing if isinstance(m, dict)]

        if dependency_graph_summary:
            try:
                refs_missing = int(dependency_graph_summary.get("unresolved_references", refs_missing))
            except Exception:
                pass
            try:
                refs_excluded = int(
                    dependency_graph_summary.get("missing_references", refs_missing + refs_excluded)
                ) - refs_missing
                refs_excluded = max(refs_excluded, 0)
            except Exception:
                pass

        contents_payload["_koi_share"] = True
        contents_payload["_koi_share_meta"] = {
            "recipient_type": recipient_type,
            "share_mode": share_mode,
            "context_depth": context_depth,
            "references_total": refs_total,
            "references_included": refs_included,
            "references_missing": refs_missing,
            "references_excluded": refs_excluded,
        }
        content_hash = _canonical_sha256_json(contents_payload)

        manifest_data = {
            "rid": req.document_rid,
            "timestamp": now_z,
            "sha256_hash": content_hash,
            "kind": "document_share",
            "recipient_type": recipient_type,
            "share_mode": share_mode,
            "context_depth": context_depth,
            "references_summary": {
                "total": refs_total,
                "required": refs_required,
                "included": refs_included,
                "missing_unresolved": refs_missing,
                "excluded_not_included": refs_excluded,
                "optional": max(refs_total - refs_required, 0),
            },
        }
        if references_payload:
            manifest_data["references"] = references_payload
        if dependency_graph_summary:
            manifest_data["dependency_graph_summary"] = dependency_graph_summary
        if missing_references:
            manifest_data["missing_references"] = missing_references[:200]
        if recipient_type == "commons":
            manifest_data["intake_policy"] = {
                "mode": "staged",
                "requires_manual_approval": True,
            }

        event_id = str(_uuid.uuid4())
        await _event_queue.add(
            event_type=event_type.value,
            rid=req.document_rid,
            manifest=manifest_data,
            contents=contents_payload,
            ttl_hours=168,
            event_id=event_id,
            target_node=recipient_node_rid,
        )

        try:
            await conn.execute(
                """
                INSERT INTO koi_outbound_shares (document_rid, target_node)
                VALUES ($1, $2)
                ON CONFLICT (document_rid, target_node)
                DO UPDATE SET shared_at = NOW(), retracted_at = NULL
                """,
                req.document_rid,
                recipient_node_rid,
            )
        except Exception as ledger_err:
            logger.warning("Could not record outbound share in ledger: %s", ledger_err)

    return ShareDocumentResponse(
        status="queued",
        event_id=event_id,
        document_rid=req.document_rid,
        recipient_node_rid=recipient_node_rid,
        recipient_type=recipient_type,
        share_mode=share_mode,
        context_depth=context_depth,
        references_total=refs_total,
        references_included=refs_included,
        references_missing=refs_missing,
        references_excluded=refs_excluded,
        message=f"Document queued for delivery to {req.recipient} ({event_type.value})",
    )


@koi_net_router.get("/shared-with-me")
async def shared_with_me(
    since: Optional[str] = None,
    from_peer: Optional[str] = None,
    limit: int = 50,
):
    """List documents shared with this node by peers."""
    if not _db_pool:
        return _protocol_error(503, "NOT_INITIALIZED", "KOI-net not initialized")
    if not _node_profile:
        return _protocol_error(503, "NOT_INITIALIZED", "Node identity not initialized")

    async with _db_pool.acquire() as conn:
        conditions = ["status != 'retracted'"]
        params: list = []
        idx = 1

        if since:
            conditions.append(f"received_at >= ${idx}::timestamptz")
            params.append(since)
            idx += 1

        if from_peer:
            resolved = await _resolve_recipient(conn, from_peer)
            if not resolved:
                return {"documents": [], "count": 0, "error": f"Unknown peer: {from_peer}"}
            conditions.append(f"sender_node = ${idx}")
            params.append(resolved)
            idx += 1

        where = " AND ".join(conditions)
        try:
            rows = await conn.fetch(
                f"""SELECT event_id, event_type, document_rid, sender_node, sender_name,
                           manifest, contents, message, received_at, status,
                           recipient_type, intake_status, reviewed_at, reviewed_by, review_notes
                    FROM koi_shared_documents
                    WHERE {where}
                    ORDER BY received_at DESC
                    LIMIT ${idx}""",
                *params, limit,
            )
        except asyncpg.PostgresError as exc:
            if isinstance(exc, asyncpg.exceptions.UndefinedTableError):
                return _protocol_error(
                    503,
                    "SHARED_DOCUMENTS_SCHEMA_MISSING",
                    "Shared documents table is missing. Apply migration 050_shared_documents.sql",
                )
            if "recipient_type" not in str(exc) and "intake_status" not in str(exc):
                raise
            rows = await conn.fetch(
                f"""SELECT event_id, event_type, document_rid, sender_node, sender_name,
                           manifest, contents, message, received_at, status
                    FROM koi_shared_documents
                    WHERE {where}
                    ORDER BY received_at DESC
                    LIMIT ${idx}""",
                *params, limit,
            )

        items = []
        for r in rows:
            contents = json.loads(r["contents"]) if isinstance(r["contents"], str) else r["contents"]
            manifest = json.loads(r["manifest"]) if isinstance(r["manifest"], str) else r["manifest"]
            share_meta = contents.get("_koi_share_meta", {}) if isinstance(contents, dict) else {}
            share_mode = (
                share_meta.get("share_mode") if isinstance(share_meta, dict) else None
            ) or ((manifest or {}).get("share_mode") if isinstance(manifest, dict) else None)
            context_depth = (
                share_meta.get("context_depth") if isinstance(share_meta, dict) else None
            ) or ((manifest or {}).get("context_depth") if isinstance(manifest, dict) else None)
            recipient_type = (
                share_meta.get("recipient_type") if isinstance(share_meta, dict) else None
            ) or ((manifest or {}).get("recipient_type") if isinstance(manifest, dict) else None)
            if not recipient_type:
                recipient_type = r.get("recipient_type") or "peer"
            references_summary = (manifest or {}).get("references_summary") if isinstance(manifest, dict) else None
            dependency_graph_summary = (
                (manifest or {}).get("dependency_graph_summary") if isinstance(manifest, dict) else None
            )
            missing_references = (manifest or {}).get("missing_references") if isinstance(manifest, dict) else None
            if not missing_references and isinstance(manifest, dict):
                dep_graph = manifest.get("dependency_graph")
                if isinstance(dep_graph, dict):
                    maybe_missing = dep_graph.get("missing_references")
                    if isinstance(maybe_missing, list):
                        missing_references = maybe_missing

            items.append(
                {
                    "event_id": str(r["event_id"]) if r["event_id"] else None,
                    "event_type": r["event_type"],
                    "document_rid": r["document_rid"],
                    "sender": r["sender_name"] or r["sender_node"],
                    "sender_node_rid": r["sender_node"],
                    "manifest": manifest,
                    "recipient_type": recipient_type,
                    "share_mode": share_mode,
                    "context_depth": context_depth,
                    "references_summary": references_summary,
                    "dependency_graph_summary": dependency_graph_summary,
                    "missing_references_count": len(missing_references) if isinstance(missing_references, list) else 0,
                    "missing_references": missing_references[:50] if isinstance(missing_references, list) else [],
                    "has_contents": contents is not None,
                    "message": r["message"],
                    "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                    "status": r["status"],
                    "intake_status": r.get("intake_status"),
                    "reviewed_at": r["reviewed_at"].isoformat() if r.get("reviewed_at") else None,
                    "reviewed_by": r.get("reviewed_by"),
                    "review_notes": r.get("review_notes"),
                }
            )

    return {"documents": items, "count": len(items)}


@koi_net_router.get("/commons/intake")
async def commons_intake(
    status: str = "staged",
    from_peer: Optional[str] = None,
    limit: int = 50,
):
    """List incoming commons shares and their intake status."""
    if not _db_pool:
        return _protocol_error(503, "NOT_INITIALIZED", "KOI-net not initialized")

    normalized_status = (status or "staged").strip().lower()
    allowed_status = {"staged", "approved", "rejected", "all"}
    if normalized_status not in allowed_status:
        return _protocol_error(
            400,
            "INVALID_INTAKE_STATUS",
            f"Invalid status '{status}'. Valid statuses: staged, approved, rejected, all",
        )

    async with _db_pool.acquire() as conn:
        conditions = ["recipient_type = 'commons'", "status != 'retracted'"]
        params: list = []
        idx = 1

        if normalized_status != "all":
            conditions.append(f"intake_status = ${idx}")
            params.append(normalized_status)
            idx += 1

        if from_peer:
            resolved = await _resolve_recipient(conn, from_peer)
            if not resolved:
                return {"documents": [], "count": 0, "error": f"Unknown peer: {from_peer}"}
            conditions.append(f"sender_node = ${idx}")
            params.append(resolved)
            idx += 1

        where = " AND ".join(conditions)
        try:
            rows = await conn.fetch(
                f"""SELECT id, event_id, event_type, document_rid, sender_node, sender_name,
                           manifest, contents, message, received_at, status,
                           intake_status, reviewed_at, reviewed_by, review_notes
                    FROM koi_shared_documents
                    WHERE {where}
                    ORDER BY received_at DESC
                    LIMIT ${idx}""",
                *params, limit,
            )
        except asyncpg.PostgresError as exc:
            if isinstance(
                exc,
                (asyncpg.exceptions.UndefinedColumnError, asyncpg.exceptions.UndefinedTableError),
            ):
                return _protocol_error(
                    503,
                    "COMMONS_INTAKE_SCHEMA_MISSING",
                    "Commons intake fields are missing. Apply migration 051_shared_documents_intake.sql",
                )
            raise

    docs = []
    for r in rows:
        manifest = json.loads(r["manifest"]) if isinstance(r["manifest"], str) else r["manifest"]
        contents = json.loads(r["contents"]) if isinstance(r["contents"], str) else r["contents"]
        docs.append(
            {
                "id": r["id"],
                "event_id": str(r["event_id"]) if r["event_id"] else None,
                "event_type": r["event_type"],
                "document_rid": r["document_rid"],
                "sender": r["sender_name"] or r["sender_node"],
                "sender_node_rid": r["sender_node"],
                "message": r["message"],
                "recipient_type": "commons",
                "status": r["status"],
                "intake_status": r["intake_status"],
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                "reviewed_by": r["reviewed_by"],
                "review_notes": r["review_notes"],
                "manifest": manifest,
                "has_contents": contents is not None,
            }
        )

    return {"documents": docs, "count": len(docs), "status_filter": normalized_status}


@koi_net_router.post("/commons/intake/decide")
async def commons_intake_decide(request: Request):
    """Approve/reject a staged commons share entry (localhost admin only)."""
    auth_err = _enforce_local_admin(request)
    if auth_err:
        return auth_err

    if not _db_pool:
        return _protocol_error(503, "NOT_INITIALIZED", "KOI-net not initialized")

    try:
        raw = await request.json()
    except Exception:
        return _protocol_error(400, "INVALID_JSON", "Invalid JSON body")

    try:
        req = CommonsIntakeDecisionRequest(**raw)
    except Exception as exc:
        return _protocol_error(400, "INVALID_REQUEST", f"Invalid request: {exc}")

    if not req.share_id and not req.event_id:
        return _protocol_error(400, "MISSING_IDENTIFIER", "Provide either share_id or event_id")

    parsed_event_id: Optional[str] = None
    if req.event_id:
        try:
            parsed_event_id = str(_uuid.UUID(req.event_id))
        except Exception:
            return _protocol_error(400, "INVALID_EVENT_ID", "event_id must be a valid UUID")

    action = (req.action or "").strip().lower()
    if action not in {"approve", "reject"}:
        return _protocol_error(400, "INVALID_ACTION", "action must be 'approve' or 'reject'")

    next_intake_status = "approved" if action == "approve" else "rejected"
    next_status = "ingested" if action == "approve" else "received"

    async with _db_pool.acquire() as conn:
        try:
            if req.share_id:
                row = await conn.fetchrow(
                    """
                    UPDATE koi_shared_documents
                    SET intake_status = $2,
                        status = $3,
                        reviewed_at = NOW(),
                        reviewed_by = COALESCE($4, reviewed_by),
                        review_notes = $5
                    WHERE id = $1
                      AND recipient_type = 'commons'
                      AND status != 'retracted'
                    RETURNING id, event_id, document_rid, sender_node, intake_status, status
                    """,
                    req.share_id,
                    next_intake_status,
                    next_status,
                    req.reviewer,
                    req.note,
                )
            else:
                row = await conn.fetchrow(
                    """
                    UPDATE koi_shared_documents
                    SET intake_status = $2,
                        status = $3,
                        reviewed_at = NOW(),
                        reviewed_by = COALESCE($4, reviewed_by),
                        review_notes = $5
                    WHERE event_id = $1::UUID
                      AND recipient_type = 'commons'
                      AND status != 'retracted'
                    RETURNING id, event_id, document_rid, sender_node, intake_status, status
                    """,
                    parsed_event_id,
                    next_intake_status,
                    next_status,
                    req.reviewer,
                    req.note,
                )
        except asyncpg.PostgresError as exc:
            if isinstance(
                exc,
                (asyncpg.exceptions.UndefinedColumnError, asyncpg.exceptions.UndefinedTableError),
            ):
                return _protocol_error(
                    503,
                    "COMMONS_INTAKE_SCHEMA_MISSING",
                    "Commons intake fields are missing. Apply migration 051_shared_documents_intake.sql",
                )
            raise

    if not row:
        return _protocol_error(404, "INTAKE_NOT_FOUND", "No matching commons intake entry found")

    return {
        "status": "ok",
        "action": action,
        "id": row["id"],
        "event_id": str(row["event_id"]) if row["event_id"] else None,
        "document_rid": row["document_rid"],
        "sender_node": row["sender_node"],
        "intake_status": row["intake_status"],
        "record_status": row["status"],
    }


async def _resolve_recipient(conn: asyncpg.Connection, recipient: str) -> Optional[str]:
    """Resolve alias/node name/full node_rid to node_rid."""
    alias_rid = None
    try:
        alias_rid = await conn.fetchval(
            "SELECT node_rid FROM koi_net_peer_aliases WHERE LOWER(alias) = LOWER($1)",
            recipient,
        )
    except asyncpg.PostgresError as exc:
        if not isinstance(exc, asyncpg.exceptions.UndefinedTableError):
            raise
    if alias_rid:
        return alias_rid

    node_rid = await conn.fetchval(
        "SELECT node_rid FROM koi_net_nodes WHERE LOWER(node_name) = LOWER($1) AND status = 'active'",
        recipient,
    )
    if node_rid:
        return node_rid

    if recipient.startswith("orn:koi-net.node:"):
        exists = await conn.fetchval(
            "SELECT 1 FROM koi_net_nodes WHERE node_rid = $1",
            recipient,
        )
        if exists:
            return recipient

    return None
