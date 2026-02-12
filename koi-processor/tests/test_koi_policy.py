from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from api.koi_envelope import EnvelopeError, sign_envelope, verify_envelope
from api.koi_net_router import _manifest_sha256_hash, _security_policy
from api.node_identity import derive_node_rid, node_rid_matches_public_key


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

