from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from api.koi_envelope import EnvelopeError, sign_envelope, verify_envelope
from api.koi_protocol import NodeProfile, NodeProvides
from api.koi_net_router import (
    _ERROR_TYPE_MAP,
    _DEFAULT_ERROR_TYPE,
    _canonical_sha256_json,
    _extract_bootstrap_key,
    _manifest_sha256_hash,
    _security_policy,
)
from api.node_identity import (
    derive_node_rid,
    derive_node_rid_hash,
    node_rid_matches_public_key,
)


def _keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def test_node_rid_binding_accepts_legacy_and_der64_hashes():
    _, public_key = _keypair()

    rid_legacy = derive_node_rid("test-node", public_key, hash_mode="legacy16")
    rid_der64 = derive_node_rid("test-node", public_key, hash_mode="der64")

    assert node_rid_matches_public_key(rid_legacy, public_key)
    assert node_rid_matches_public_key(rid_der64, public_key)


def test_node_rid_binding_rejects_wrong_key():
    _, public_key_a = _keypair()
    _, public_key_b = _keypair()

    rid_legacy = derive_node_rid("test-node", public_key_a, hash_mode="legacy16")
    rid_der64 = derive_node_rid("test-node", public_key_a, hash_mode="der64")

    assert not node_rid_matches_public_key(rid_legacy, public_key_b)
    assert not node_rid_matches_public_key(rid_der64, public_key_b)


def test_verify_envelope_enforces_expected_nodes():
    private_key, public_key = _keypair()
    envelope = sign_envelope(
        payload={"type": "poll_events", "limit": 5},
        source_node="orn:koi-net.node:source+abc123abc123abcd",
        target_node="orn:koi-net.node:target+def456def456def4",
        private_key=private_key,
    )

    payload, source = verify_envelope(
        envelope,
        public_key,
        expected_source_node="orn:koi-net.node:source+abc123abc123abcd",
        expected_target_node="orn:koi-net.node:target+def456def456def4",
    )
    assert payload["type"] == "poll_events"
    assert source == "orn:koi-net.node:source+abc123abc123abcd"

    with pytest.raises(EnvelopeError) as exc:
        verify_envelope(
            envelope,
            public_key,
            expected_target_node="orn:koi-net.node:other+ffffffffffffffff",
        )
    assert exc.value.code == "TARGET_NODE_MISMATCH"


def test_security_policy_defaults_to_strict_when_enabled(monkeypatch):
    monkeypatch.setenv("KOI_STRICT_MODE", "true")
    monkeypatch.delenv("KOI_REQUIRE_SIGNED_ENVELOPES", raising=False)
    monkeypatch.delenv("KOI_ENFORCE_TARGET_MATCH", raising=False)
    monkeypatch.delenv("KOI_ENFORCE_SOURCE_KEY_RID_BINDING", raising=False)

    policy = _security_policy()
    assert policy["strict_mode"] is True
    assert policy["require_signed"] is True
    assert policy["enforce_target"] is True
    assert policy["enforce_source_binding"] is True


def test_security_policy_allows_explicit_override(monkeypatch):
    monkeypatch.setenv("KOI_STRICT_MODE", "true")
    monkeypatch.setenv("KOI_REQUIRE_SIGNED_ENVELOPES", "false")
    monkeypatch.setenv("KOI_ENFORCE_TARGET_MATCH", "false")
    monkeypatch.setenv("KOI_ENFORCE_SOURCE_KEY_RID_BINDING", "true")

    policy = _security_policy()
    assert policy["strict_mode"] is True
    assert policy["require_signed"] is False
    assert policy["enforce_target"] is False
    assert policy["enforce_source_binding"] is True


def test_manifest_hash_derived_when_missing():
    manifest = {"rid": "orn:koi-net.practice:foo+abcd", "timestamp": "2026-02-12T00:00:00Z"}
    contents = {"@type": "bkc:Practice", "name": "Foo Practice"}

    digest_a = _manifest_sha256_hash(manifest, contents)
    digest_b = _manifest_sha256_hash(manifest, contents)

    assert len(digest_a) == 64
    assert digest_a == digest_b


# =============================================================================
# GAP 1: b64_64 hash mode — BlockScience canonical
# =============================================================================


def test_b64_64_matches_blockscience_canonical():
    """Verify b64_64 produces the same hash as BlockScience's sha256_hash(pub_key.to_der())."""
    _, public_key = _keypair()
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # BlockScience: sha256_hash(pub_key.to_der()) where to_der() returns base64
    bs_b64_str = base64.b64encode(der_bytes).decode()
    bs_hash = hashlib.sha256(bs_b64_str.encode()).hexdigest()

    octo_hash = derive_node_rid_hash(public_key, "b64_64")
    assert octo_hash == bs_hash
    assert len(octo_hash) == 64


def test_b64_64_is_default_hash_mode():
    """Confirm b64_64 is the default when no mode is specified."""
    _, public_key = _keypair()
    default_hash = derive_node_rid_hash(public_key)
    explicit_hash = derive_node_rid_hash(public_key, "b64_64")
    assert default_hash == explicit_hash
    assert len(default_hash) == 64


def test_node_rid_matches_b64_64():
    """Verify node_rid_matches_public_key accepts b64_64 RIDs."""
    _, public_key = _keypair()
    rid = derive_node_rid("test-node", public_key, hash_mode="b64_64")
    assert node_rid_matches_public_key(rid, public_key)


def test_legacy16_is_prefix_of_b64_64():
    """legacy16 is the first 16 chars of the b64_64 hash (same input)."""
    _, public_key = _keypair()
    b64_hash = derive_node_rid_hash(public_key, "b64_64")
    legacy_hash = derive_node_rid_hash(public_key, "legacy16")
    assert b64_hash[:16] == legacy_hash


# =============================================================================
# GAP 3: Error response schema
# =============================================================================


def test_error_type_map_covers_identity_errors():
    """Verify the four BlockScience ErrorType values are mapped."""
    assert _ERROR_TYPE_MAP["UNKNOWN_SOURCE_NODE"] == "unknown_node"
    assert _ERROR_TYPE_MAP["SOURCE_NODE_KEY_BINDING_FAILED"] == "invalid_key"
    assert _ERROR_TYPE_MAP["INVALID_SIGNATURE"] == "invalid_signature"
    assert _ERROR_TYPE_MAP["TARGET_NODE_MISMATCH"] == "invalid_target"


def test_pre_auth_errors_do_not_map_to_unknown_node():
    """Pre-authentication errors must NOT map to unknown_node (triggers handshake retry)."""
    pre_auth_codes = [
        "INVALID_JSON", "INVALID_PAYLOAD", "UNSIGNED_ENVELOPE_REQUIRED",
        "MISSING_ENVELOPE_FIELDS", "ENVELOPE_ERROR", "CRYPTO_UNAVAILABLE",
    ]
    for code in pre_auth_codes:
        error_type = _ERROR_TYPE_MAP.get(code, _DEFAULT_ERROR_TYPE)
        assert error_type != "unknown_node", (
            f"{code} maps to 'unknown_node' — would trigger handshake retry"
        )


def test_default_error_type_is_not_unknown_node():
    """The fallback for unmapped codes must not be unknown_node."""
    assert _DEFAULT_ERROR_TYPE != "unknown_node"


# =============================================================================
# GAP 2: Bootstrap key extraction (no DB, pure logic)
# =============================================================================


def _make_bootstrap_envelope(private_key, public_key, source_rid, target_rid):
    """Build a signed broadcast envelope with FORGET+NEW bootstrap events."""
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_b64 = base64.b64encode(der_bytes).decode()

    payload = {
        "type": "events_payload",
        "events": [
            {"rid": source_rid, "event_type": "FORGET"},
            {
                "rid": source_rid,
                "event_type": "NEW",
                "contents": {
                    "node_rid": source_rid,
                    "node_name": "bootstrap-test",
                    "node_type": "PARTIAL",
                    "public_key": public_b64,
                },
            },
        ],
    }
    return sign_envelope(payload, source_rid, target_rid, private_key)


def test_extract_bootstrap_key_succeeds_with_valid_payload():
    """Bootstrap extraction succeeds when key-RID binding matches."""
    private_key, public_key = _keypair()
    source_rid = derive_node_rid("bootstrap-test", public_key, hash_mode="b64_64")
    target_rid = "orn:koi-net.node:target+ffffffffffffffff"

    envelope = _make_bootstrap_envelope(private_key, public_key, source_rid, target_rid)
    result = _extract_bootstrap_key(envelope, source_rid)

    assert result is not None
    assert result["der_b64"] is not None
    assert result["public_key"] is not None
    assert "bootstrap_contents" in result


def test_extract_bootstrap_key_rejects_wrong_key():
    """Bootstrap extraction rejects when the public key doesn't match the RID hash."""
    private_key_a, public_key_a = _keypair()
    _, public_key_b = _keypair()

    # Create RID from key A, but put key B in the bootstrap payload
    source_rid = derive_node_rid("bootstrap-test", public_key_a, hash_mode="b64_64")
    target_rid = "orn:koi-net.node:target+ffffffffffffffff"

    # Manually construct a bad envelope (key B in contents but RID from key A)
    der_b = public_key_b.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    payload = {
        "type": "events_payload",
        "events": [
            {
                "rid": source_rid,
                "event_type": "NEW",
                "contents": {
                    "node_rid": source_rid,
                    "node_name": "forged",
                    "public_key": base64.b64encode(der_b).decode(),
                },
            },
        ],
    }
    envelope = sign_envelope(payload, source_rid, target_rid, private_key_a)
    result = _extract_bootstrap_key(envelope, source_rid)
    assert result is None


def test_extract_bootstrap_key_returns_none_for_non_bootstrap():
    """Non-bootstrap payloads return None."""
    body = {
        "payload": {"type": "poll_events", "limit": 5},
        "source_node": "orn:koi-net.node:x+abc",
        "target_node": "orn:koi-net.node:y+def",
        "signature": "fake",
    }
    assert _extract_bootstrap_key(body, "orn:koi-net.node:x+abc") is None


# =============================================================================
# GAP 4: POLL edge enforcement policy
# =============================================================================


def test_strict_mode_enables_require_approved_edge_for_poll(monkeypatch):
    """When KOI_STRICT_MODE=true, poll edge enforcement is auto-enabled."""
    monkeypatch.setenv("KOI_STRICT_MODE", "true")
    monkeypatch.delenv("KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL", raising=False)
    policy = _security_policy()
    assert policy["require_approved_edge_for_poll"] is True


def test_poll_edge_enforcement_can_be_explicit(monkeypatch):
    """KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL can be set independently."""
    monkeypatch.setenv("KOI_STRICT_MODE", "false")
    monkeypatch.setenv("KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL", "true")
    policy = _security_policy()
    assert policy["strict_mode"] is False
    assert policy["require_approved_edge_for_poll"] is True


# =============================================================================
# P1: Manifest canonicalization — JCS conformance tests
# =============================================================================


def test_manifest_hash_uses_jcs_not_json_dumps():
    """JCS serializes 1.0 as '1', json.dumps keeps '1.0'. Hashes must differ."""
    # json.dumps({"score":1.0}, sort_keys=True, separators=(",",":")) → '{"score":1.0}'
    # sha256 of that string:
    json_dumps_hash = "4a0efab20925fd0974dc33fca675fbb5bca3c0138daee2f824241ef89e0a9a18"
    jcs_hash = _canonical_sha256_json({"score": 1.0})
    assert jcs_hash != json_dumps_hash, (
        "Hash matches json.dumps output — JCS canonicalization is not active"
    )


def test_manifest_hash_matches_blockscience_reference():
    """Assert against a frozen reference vector from BlockScience rid-lib 3.2.14."""
    data = {
        "@type": "bkc:Practice",
        "name": "Herring Monitoring",
        "score": 1.0,
        "tags": ["marine", "monitoring"],
        "nested": {"b": 2, "a": 1},
    }
    expected = "5ca5beab92e32909ebf181d674f58e74d18858ea78ef1e33b40ffdbafa9db4c8"
    assert _canonical_sha256_json(data) == expected


def test_manifest_hash_deterministic_across_key_order():
    """Key order must not affect the hash (both JCS and json.dumps handle this)."""
    hash_a = _canonical_sha256_json({"z": 1, "a": 2})
    hash_b = _canonical_sha256_json({"a": 2, "z": 1})
    assert hash_a == hash_b


# =============================================================================
# P5: NodeProfile ontology fields
# =============================================================================


def test_node_profile_ontology_fields():
    """NodeProfile with ontology fields serializes/deserializes correctly."""
    profile = NodeProfile(
        node_rid="orn:koi-net.node:test+abc123",
        node_name="test-node",
        node_type="FULL",
        provides=NodeProvides(event=["Practice"], state=["Practice"]),
        ontology_uri="http://bkc.regen.network/ontology",
        ontology_version="1.0.0",
    )
    data = profile.model_dump()
    assert data["ontology_uri"] == "http://bkc.regen.network/ontology"
    assert data["ontology_version"] == "1.0.0"

    # Round-trip
    restored = NodeProfile(**data)
    assert restored.ontology_uri == "http://bkc.regen.network/ontology"
    assert restored.ontology_version == "1.0.0"


def test_node_profile_ontology_optional():
    """NodeProfile without ontology fields works (backwards compat)."""
    profile = NodeProfile(
        node_rid="orn:koi-net.node:test+abc123",
        node_name="test-node",
        node_type="FULL",
        provides=NodeProvides(),
    )
    data = profile.model_dump()
    assert data["ontology_uri"] is None
    assert data["ontology_version"] is None

    # Deserialize from dict without ontology fields (simulating old peer)
    old_peer_data = {
        "node_rid": "orn:koi-net.node:old+def456",
        "node_name": "old-peer",
        "node_type": "FULL",
        "provides": {"event": [], "state": []},
    }
    old_profile = NodeProfile(**old_peer_data)
    assert old_profile.ontology_uri is None
    assert old_profile.ontology_version is None

