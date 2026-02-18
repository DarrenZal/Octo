"""P2 Conformance Tests — koi-net Package as Oracle

Validates that Octo's KOI-net wire format is cross-compatible with the
BlockScience koi-net reference package (>= 1.2.4).

Two tiers:
  - Offline model conformance (Groups 1-3): no server needed
  - Live endpoint conformance (Group 4): requires --live-url

Run:
    # Offline only (default)
    venv-conformance/bin/python -m pytest tests/test_koi_conformance.py -v

    # With live endpoint tests
    venv-conformance/bin/python -m pytest tests/test_koi_conformance.py -v \
        --live-url http://127.0.0.1:8351
"""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from base64 import b64encode

# --- koi-net reference imports ---
from koi_net.protocol.api_models import (
    PollEvents,
    FetchRids,
    FetchBundles,
    EventsPayload,
    RidsPayload,
    ManifestsPayload,
    BundlesPayload,
    ErrorResponse,
)
from koi_net.protocol.envelope import (
    SignedEnvelope as KoiSignedEnvelope,
    UnsignedEnvelope as KoiUnsignedEnvelope,
)
from koi_net.protocol.secure import (
    PrivateKey as KoiPrivateKey,
    PublicKey as KoiPublicKey,
)
from koi_net.protocol.event import Event as KoiEvent, EventType as KoiEventType
from koi_net.protocol.errors import ErrorType as KoiErrorType
from rid_lib.types import KoiNetNode
from rid_lib.ext import Manifest as KoiManifest

# --- Octo imports ---
from api.koi_envelope import (
    sign_envelope,
    verify_envelope,
    _unsigned_envelope_bytes,
)
from api.koi_protocol import (
    EventsPayloadResponse,
    RidsPayloadResponse,
    ManifestsPayloadResponse,
    BundlesPayloadResponse,
    WireEvent,
    WireManifest,
    PollEventsRequest,
    FetchRidsRequest,
    FetchBundlesRequest,
    EventType as OctoEventType,
)
from api.node_identity import derive_node_rid, derive_node_rid_hash


# =============================================================================
# Shared helpers
# =============================================================================

def _keypair():
    """Generate ECDSA P-256 keypair."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _octo_node_rid(public_key):
    """Derive Octo-style node RID string (b64_64 canonical)."""
    return derive_node_rid("conformance-test", public_key, hash_mode="b64_64")


def _koi_net_private_key(private_key) -> KoiPrivateKey:
    """Wrap a cryptography private key as koi-net PrivateKey."""
    return KoiPrivateKey(private_key)


def _koi_net_public_key(public_key) -> KoiPublicKey:
    """Wrap a cryptography public key as koi-net PublicKey."""
    return KoiPublicKey(public_key)


_TARGET_RID = "orn:koi-net.node:target+" + "f" * 64


# =============================================================================
# Group 1: Wire Format Roundtrip (offline)
# =============================================================================


class TestWireFormatRoundtrip:
    """Validate Octo JSON ↔ koi-net model parsing."""

    def test_octo_events_payload_parses_as_koi_net_events_payload(self):
        """Octo EventsPayloadResponse JSON → koi-net EventsPayload."""
        octo_resp = EventsPayloadResponse(events=[
            WireEvent(
                rid="orn:koi-net.practice:herring-monitoring+abcd1234",
                event_type=OctoEventType.NEW,
                manifest=WireManifest(
                    rid="orn:koi-net.practice:herring-monitoring+abcd1234",
                    timestamp="2026-02-12T00:00:00Z",
                    sha256_hash="a" * 64,
                ),
                contents={"name": "Herring Monitoring"},
            ),
        ])
        octo_json = octo_resp.model_dump_json(exclude_none=True)
        parsed = EventsPayload.model_validate_json(octo_json)

        assert parsed.type == "events_payload"
        assert len(parsed.events) == 1
        assert str(parsed.events[0].rid) == "orn:koi-net.practice:herring-monitoring+abcd1234"
        assert parsed.events[0].event_type == KoiEventType.NEW
        assert parsed.events[0].manifest is not None
        assert parsed.events[0].contents == {"name": "Herring Monitoring"}

    def test_koi_net_poll_events_parses_as_octo_request(self):
        """koi-net PollEvents JSON → Octo PollEventsRequest."""
        koi_poll = PollEvents(limit=25)
        koi_json = koi_poll.model_dump_json()
        parsed = PollEventsRequest.model_validate_json(koi_json)

        assert parsed.type == "poll_events"
        assert parsed.limit == 25

    def test_octo_rids_payload_parses_as_koi_net_rids_payload(self):
        """Octo RidsPayloadResponse JSON → koi-net RidsPayload."""
        octo_resp = RidsPayloadResponse(rids=[
            "orn:koi-net.practice:foo+abc123",
            "orn:koi-net.organization:bar+def456",
        ])
        parsed = RidsPayload.model_validate_json(octo_resp.model_dump_json())

        assert parsed.type == "rids_payload"
        assert len(parsed.rids) == 2
        assert str(parsed.rids[0]) == "orn:koi-net.practice:foo+abc123"

    def test_octo_manifests_payload_parses_as_koi_net_manifests_payload(self):
        """Octo ManifestsPayloadResponse JSON → koi-net ManifestsPayload."""
        octo_resp = ManifestsPayloadResponse(manifests=[
            WireManifest(
                rid="orn:koi-net.practice:foo+abc123",
                timestamp="2026-02-12T00:00:00Z",
                sha256_hash="b" * 64,
            ),
        ])
        parsed = ManifestsPayload.model_validate_json(
            octo_resp.model_dump_json(exclude_none=True)
        )

        assert parsed.type == "manifests_payload"
        assert len(parsed.manifests) == 1
        assert str(parsed.manifests[0].rid) == "orn:koi-net.practice:foo+abc123"
        assert parsed.manifests[0].sha256_hash == "b" * 64

    def test_octo_bundles_payload_parses_as_koi_net_bundles_payload(self):
        """Octo BundlesPayloadResponse JSON → koi-net BundlesPayload."""
        octo_resp = BundlesPayloadResponse(
            bundles=[{
                "manifest": {
                    "rid": "orn:koi-net.practice:foo+abc123",
                    "timestamp": "2026-02-12T00:00:00Z",
                    "sha256_hash": "c" * 64,
                },
                "contents": {"name": "Test Practice"},
            }],
            not_found=["orn:koi-net.practice:missing+xyz789"],
        )
        parsed = BundlesPayload.model_validate_json(
            octo_resp.model_dump_json(exclude_none=True)
        )

        assert parsed.type == "bundles_payload"
        assert len(parsed.bundles) == 1
        assert str(parsed.not_found[0]) == "orn:koi-net.practice:missing+xyz789"

    def test_octo_error_response_parses_as_koi_net_error_response(self):
        """Octo error dict → koi-net ErrorResponse (ignoring extra fields)."""
        # Octo's _protocol_error adds extra fields (error_code, message)
        octo_error = {
            "type": "error_response",
            "error": "unknown_node",
            "error_code": "UNKNOWN_SOURCE_NODE",
            "message": "No public key for orn:koi-net.node:x+abc",
        }
        # koi-net ErrorResponse has model_config default (no extra="forbid")
        parsed = ErrorResponse.model_validate(octo_error)
        assert parsed.error == KoiErrorType.UnknownNode

    def test_koi_net_fetch_rids_parses_as_octo_request(self):
        """koi-net FetchRids JSON → Octo FetchRidsRequest."""
        koi_fetch = FetchRids()
        koi_json = koi_fetch.model_dump_json()
        parsed = FetchRidsRequest.model_validate_json(koi_json)
        assert parsed.type == "fetch_rids"

    def test_koi_net_fetch_bundles_parses_as_octo_request(self):
        """koi-net FetchBundles JSON → Octo FetchBundlesRequest."""
        koi_fetch = FetchBundles(rids=["orn:koi-net.practice:foo+abc123"])
        koi_json = koi_fetch.model_dump_json()
        parsed = FetchBundlesRequest.model_validate_json(koi_json)
        assert parsed.type == "fetch_bundles"
        assert parsed.rids == ["orn:koi-net.practice:foo+abc123"]


# =============================================================================
# Group 2: Signed Envelope Cross-Verification (offline)
# =============================================================================


class TestSignedEnvelopeCrossVerification:
    """Envelopes signed by one implementation are verifiable by the other."""

    def test_octo_signed_envelope_verifiable_by_koi_net(self):
        """Sign with Octo → verify with koi-net PublicKey.verify()."""
        priv_key, pub_key = _keypair()
        source_rid = _octo_node_rid(pub_key)

        payload = {"type": "poll_events", "limit": 50}
        octo_env = sign_envelope(payload, source_rid, _TARGET_RID, priv_key)

        # koi-net verification: rebuild unsigned envelope bytes and verify
        koi_pub = _koi_net_public_key(pub_key)
        unsigned_bytes = _unsigned_envelope_bytes(payload, source_rid, _TARGET_RID)
        # This raises InvalidSignature on failure
        koi_pub.verify(octo_env["signature"], unsigned_bytes)

    def test_koi_net_signed_envelope_verifiable_by_octo(self):
        """Sign with koi-net → verify with Octo verify_envelope()."""
        priv_key, pub_key = _keypair()
        source_rid = _octo_node_rid(pub_key)

        koi_priv = _koi_net_private_key(priv_key)
        koi_source = KoiNetNode.from_string(source_rid)
        koi_target = KoiNetNode.from_string(_TARGET_RID)

        payload = PollEvents(limit=50)
        unsigned = KoiUnsignedEnvelope[PollEvents](
            payload=payload,
            source_node=koi_source,
            target_node=koi_target,
        )
        signed = unsigned.sign_with(koi_priv)

        # Convert to dict for Octo's verify_envelope
        envelope_dict = {
            "payload": json.loads(payload.model_dump_json()),
            "source_node": str(signed.source_node),
            "target_node": str(signed.target_node),
            "signature": signed.signature,
        }
        result_payload, result_source = verify_envelope(envelope_dict, pub_key)
        assert result_payload["type"] == "poll_events"
        assert result_source == source_rid

    def test_cross_signed_envelope_semantic_equivalence(self):
        """Both implementations produce semantically equivalent unsigned JSON."""
        priv_key, pub_key = _keypair()
        source_rid = _octo_node_rid(pub_key)

        payload_dict = {"type": "poll_events", "limit": 50}

        # Octo's unsigned envelope bytes
        octo_bytes = _unsigned_envelope_bytes(payload_dict, source_rid, _TARGET_RID)

        # koi-net's unsigned envelope bytes
        koi_unsigned = KoiUnsignedEnvelope[PollEvents](
            payload=PollEvents(**payload_dict),
            source_node=KoiNetNode.from_string(source_rid),
            target_node=KoiNetNode.from_string(_TARGET_RID),
        )
        koi_bytes = koi_unsigned.model_dump_json(exclude_none=True).encode()

        # Parse both as dicts to compare semantically
        octo_parsed = json.loads(octo_bytes)
        koi_parsed = json.loads(koi_bytes)
        assert octo_parsed == koi_parsed

    def test_cross_signed_envelope_with_none_fields(self):
        """FORGET events have manifest=None, contents=None — both omit nulls."""
        priv_key, pub_key = _keypair()
        source_rid = _octo_node_rid(pub_key)

        # Octo side: build events_payload with FORGET event
        forget_event = WireEvent(
            rid="orn:koi-net.practice:foo+abc123",
            event_type=OctoEventType.FORGET,
        )
        octo_payload = EventsPayloadResponse(events=[forget_event])
        octo_payload_dict = json.loads(octo_payload.model_dump_json(exclude_none=True))

        # Sign with Octo
        octo_env = sign_envelope(octo_payload_dict, source_rid, _TARGET_RID, priv_key)

        # Verify with koi-net
        koi_pub = _koi_net_public_key(pub_key)
        unsigned_bytes = _unsigned_envelope_bytes(
            octo_payload_dict, source_rid, _TARGET_RID
        )
        koi_pub.verify(octo_env["signature"], unsigned_bytes)

        # Also verify the payload parses correctly — no null fields present
        parsed = EventsPayload.model_validate(octo_payload_dict)
        assert parsed.events[0].manifest is None
        assert parsed.events[0].contents is None
        # Verify exclude_none worked: no "manifest" or "contents" key in wire JSON
        event_json = json.loads(octo_payload.model_dump_json(exclude_none=True))
        assert "manifest" not in event_json["events"][0]
        assert "contents" not in event_json["events"][0]


# =============================================================================
# Group 3: Node Identity Cross-Verification (offline)
# =============================================================================


class TestNodeIdentityCrossVerification:
    """Node RID derivation matches between implementations."""

    def test_octo_node_rid_hash_matches_koi_net_sha256_hash(self):
        """Same keypair → same RID hash from both implementations."""
        priv_key, pub_key = _keypair()

        # Octo
        octo_hash = derive_node_rid_hash(pub_key, "b64_64")

        # koi-net
        koi_pub = _koi_net_public_key(pub_key)
        koi_node_rid = koi_pub.to_node_rid("conformance-test")
        koi_hash = str(koi_node_rid).rsplit("+", 1)[1]

        assert octo_hash == koi_hash
        assert len(octo_hash) == 64

    def test_koi_net_node_rid_type_accepts_octo_rid_string(self):
        """Octo RID string parses as KoiNetNode and roundtrips."""
        _, pub_key = _keypair()
        octo_rid_str = _octo_node_rid(pub_key)

        # Parse as KoiNetNode
        koi_node = KoiNetNode.from_string(octo_rid_str)
        assert str(koi_node) == octo_rid_str

        # Verify it's the right RID type
        assert isinstance(koi_node, KoiNetNode)


# =============================================================================
# Group 4: Live Endpoint Conformance (optional, requires --live-url)
# =============================================================================


@pytest.mark.live
class TestLiveEndpointConformance:
    """Send requests to a running Octo instance, validate responses parse
    into koi-net models."""

    def _post(self, live_url, path, payload):
        """Send unsigned POST and return JSON response."""
        import httpx
        resp = httpx.post(
            f"{live_url}/koi-net{path}",
            json=payload,
            timeout=10.0,
        )
        return resp.status_code, resp.json()

    def test_live_poll_response_parses_as_koi_net_events_payload(self, live_url):
        status, body = self._post(live_url, "/events/poll", {
            "type": "poll_events",
            "limit": 5,
            "node_id": "orn:koi-net.node:conformance-test+" + "0" * 64,
        })
        if status == 401:
            pytest.skip("Strict mode enabled — unsigned requests rejected")
        assert status == 200
        parsed = EventsPayload.model_validate(body)
        assert parsed.type == "events_payload"

    def test_live_rids_response_parses_as_koi_net_rids_payload(self, live_url):
        status, body = self._post(live_url, "/rids/fetch", {
            "type": "fetch_rids",
        })
        if status == 401:
            pytest.skip("Strict mode enabled")
        assert status == 200
        parsed = RidsPayload.model_validate(body)
        assert parsed.type == "rids_payload"

    def test_live_manifests_response_parses_as_koi_net_manifests_payload(self, live_url):
        # First get some RIDs to query
        _, rids_body = self._post(live_url, "/rids/fetch", {"type": "fetch_rids"})
        rids = rids_body.get("rids", [])[:3]
        if not rids:
            pytest.skip("No RIDs available on server")

        status, body = self._post(live_url, "/manifests/fetch", {
            "type": "fetch_manifests",
            "rids": rids,
        })
        if status == 401:
            pytest.skip("Strict mode enabled")
        assert status == 200
        parsed = ManifestsPayload.model_validate(body)
        assert parsed.type == "manifests_payload"

    def test_live_bundles_response_parses_as_koi_net_bundles_payload(self, live_url):
        _, rids_body = self._post(live_url, "/rids/fetch", {"type": "fetch_rids"})
        rids = rids_body.get("rids", [])[:3]
        if not rids:
            pytest.skip("No RIDs available on server")

        status, body = self._post(live_url, "/bundles/fetch", {
            "type": "fetch_bundles",
            "rids": rids,
        })
        if status == 401:
            pytest.skip("Strict mode enabled")
        assert status == 200
        parsed = BundlesPayload.model_validate(body)
        assert parsed.type == "bundles_payload"

    def test_live_error_response_parses_as_koi_net_error_response(self, live_url):
        """Trigger an error and verify it parses as koi-net ErrorResponse."""
        # Send invalid payload to broadcast endpoint (missing events)
        status, body = self._post(live_url, "/events/broadcast", {
            "type": "events_payload",
        })
        # Accept either a proper error response or a 401 (strict mode)
        if status == 401:
            # Strict mode — the 401 itself should be a valid error response
            if body.get("type") == "error_response":
                parsed = ErrorResponse.model_validate(body)
                assert parsed.error in list(KoiErrorType)
            else:
                pytest.skip("Strict mode — non-standard 401 response")
        elif status >= 400:
            if body.get("type") == "error_response":
                parsed = ErrorResponse.model_validate(body)
                assert parsed.error in list(KoiErrorType)
