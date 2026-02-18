"""
KOI-net Protocol Models

Pydantic models matching the BlockScience wire format for KOI-net interoperability.
Uses rid-lib types where possible for JCS-canonical hashing.

Reference: BlockScience koi-net protocol/
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Event Types
# =============================================================================

class EventType(StrEnum):
    NEW = "NEW"
    UPDATE = "UPDATE"
    FORGET = "FORGET"


# =============================================================================
# Wire Models (strict P1a/P1b format)
# =============================================================================

class WireManifest(BaseModel):
    """Strict KOI-net wire manifest: {rid, timestamp, sha256_hash} only."""
    rid: str
    timestamp: str  # ISO 8601 UTC with Z suffix
    sha256_hash: str  # JCS-canonical hash via rid-lib


class WireEvent(BaseModel):
    """Strict KOI-net wire event."""
    model_config = ConfigDict(extra="forbid")

    rid: str
    event_type: EventType
    event_id: Optional[str] = None
    manifest: Optional[WireManifest] = None
    contents: Optional[Dict[str, Any]] = None


# =============================================================================
# Node Capability Declaration
# =============================================================================

class NodeProvides(BaseModel):
    """What RID types this node broadcasts events for and serves state queries for."""
    event: List[str] = []   # RID types this node broadcasts events for
    state: List[str] = []   # RID types this node serves state queries for


class NodeProfile(BaseModel):
    """Node identity and capability declaration."""
    node_rid: str
    node_name: str
    node_type: str          # "FULL" or "PARTIAL"
    base_url: Optional[str] = None  # None for PARTIAL nodes
    provides: NodeProvides
    public_key: Optional[str] = None  # DER-encoded, base64
    ontology_uri: Optional[str] = None
    ontology_version: Optional[str] = None


# =============================================================================
# Request Models
# =============================================================================

class PollEventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["poll_events"] = "poll_events"
    limit: int = 50


class FetchRidsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_rids"] = "fetch_rids"
    rid_types: Optional[List[str]] = None  # Filter by RID type


class FetchManifestsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_manifests"] = "fetch_manifests"
    rids: List[str]


class FetchBundlesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_bundles"] = "fetch_bundles"
    rids: List[str]


class EventsPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["events_payload"] = "events_payload"
    events: List[WireEvent]


class HandshakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["handshake"] = "handshake"
    profile: NodeProfile


class ConfirmEventsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["confirm_events"] = "confirm_events"
    event_ids: List[str]


# =============================================================================
# Response Models
# =============================================================================

class EventsPayloadResponse(BaseModel):
    type: Literal["events_payload"] = "events_payload"
    events: List[WireEvent]


class RidsPayloadResponse(BaseModel):
    type: Literal["rids_payload"] = "rids_payload"
    rids: List[str]


class ManifestsPayloadResponse(BaseModel):
    type: Literal["manifests_payload"] = "manifests_payload"
    manifests: List[WireManifest]


class BundlesPayloadResponse(BaseModel):
    type: Literal["bundles_payload"] = "bundles_payload"
    bundles: List[Dict[str, Any]]
    not_found: List[str] = []   # RIDs that don't exist
    deferred: List[str] = []    # RIDs not yet available


class HandshakeResponse(BaseModel):
    type: Literal["handshake_response"] = "handshake_response"
    profile: NodeProfile
    accepted: bool


class ConfirmEventsResponse(BaseModel):
    type: Literal["confirm_events_response"] = "confirm_events_response"
    confirmed: int


# =============================================================================
# Signed Envelope
# =============================================================================

class SignedEnvelope(BaseModel):
    """Signed envelope for wire transmission."""
    model_config = ConfigDict(exclude_none=True)

    payload: Dict[str, Any]
    source_node: str
    target_node: str
    signature: str


# =============================================================================
# Utilities
# =============================================================================

def timestamp_to_z_format(ts: str) -> str:
    """Convert timestamp to Z suffix format for KOI-net compatibility.

    Returns a valid ISO 8601 UTC timestamp with Z suffix. If the input is
    empty or falsy, returns the current UTC time (koi-net Manifest requires
    a valid datetime for the timestamp field).
    """
    if not ts:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if ts.endswith("+00:00"):
        return ts[:-6] + "Z"
    if "+00:00" in ts:
        return ts.replace("+00:00", "Z")
    return ts
