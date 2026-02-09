#!/usr/bin/env python3
"""
KOI-net Interop Test for Octo

Tests the KOI-net protocol endpoints against a running Octo instance.
Ported from RegenAI's koi_net_interop_test.py and adapted for Octo.

Usage:
    python tests/test_koi_interop.py [--url http://127.0.0.1:8351]

Tests:
    1. Generate test keypair
    2. Handshake (register test node)
    3. Poll events (signed)
    4. Fetch RIDs
    5. Fetch manifests (if events exist)
    6. Fetch bundles (if events exist)
    7. Verify signature round-trip
"""

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)


class UnsignedEnvelope(BaseModel):
    payload: dict
    source_node: str
    target_node: str


def generate_test_keypair():
    """Generate an ECDSA P-256 keypair for the test node."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Derive node RID
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    der_b64 = base64.b64encode(der_bytes).decode()
    pubkey_hash = hashlib.sha256(der_b64.encode()).hexdigest()[:16]
    node_id = f"orn:koi-net.node:test-interop+{pubkey_hash}"

    return private_key, public_key, node_id, der_b64


def sign_envelope(payload, source_node, target_node, private_key):
    """Sign an envelope using raw r||s format."""
    unsigned = UnsignedEnvelope(
        payload=payload,
        source_node=source_node,
        target_node=target_node,
    )
    data_to_sign = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

    der_signature = private_key.sign(data_to_sign, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    byte_length = 32  # P-256
    raw_signature = r.to_bytes(byte_length, "big") + s.to_bytes(byte_length, "big")

    return {
        "payload": payload,
        "source_node": source_node,
        "target_node": target_node,
        "signature": base64.b64encode(raw_signature).decode(),
    }


def verify_envelope(envelope, public_key):
    """Verify an envelope signature."""
    unsigned = UnsignedEnvelope(
        payload=envelope["payload"],
        source_node=envelope["source_node"],
        target_node=envelope["target_node"],
    )
    data_to_verify = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

    raw_sig = base64.b64decode(envelope["signature"])
    byte_length = 32
    r = int.from_bytes(raw_sig[:byte_length], "big")
    s = int.from_bytes(raw_sig[byte_length:], "big")
    der_signature = encode_dss_signature(r, s)

    public_key.verify(der_signature, data_to_verify, ec.ECDSA(hashes.SHA256()))
    return True


def run_interop_test(base_url: str):
    print("=" * 60)
    print("Octo KOI-net Interop Test")
    print(f"Target: {base_url}")
    print("=" * 60)

    client = httpx.Client(timeout=30.0)
    passed = 0
    failed = 0

    # Test 0: Check KOI-net health
    print("\n[0] Checking /koi-net/health...")
    try:
        resp = client.get(f"{base_url}/koi-net/health")
        if resp.status_code == 200:
            health = resp.json()
            target_node_id = health.get("node", {}).get("node_rid", "unknown")
            print(f"    Node: {target_node_id}")
            print(f"    Queue size: {health.get('event_queue_size', 0)}")
            print(f"    Peers: {len(health.get('peers', []))}")
            passed += 1
        else:
            print(f"    FAIL: status {resp.status_code}")
            print("    Is KOI_NET_ENABLED=true?")
            failed += 1
            return False
    except Exception as e:
        print(f"    FAIL: {e}")
        failed += 1
        return False

    # Test 1: Generate keypair
    print("\n[1] Generating test node keypair...")
    private_key, public_key, test_node_id, public_der_b64 = generate_test_keypair()
    print(f"    Node ID: {test_node_id}")
    passed += 1

    # Test 2: Handshake (registers our test node + public key)
    print("\n[2] Testing /koi-net/handshake...")
    handshake_payload = {
        "type": "handshake",
        "profile": {
            "node_rid": test_node_id,
            "node_name": "test-interop",
            "node_type": "PARTIAL",
            "base_url": None,
            "provides": {"event": [], "state": []},
            "public_key": public_der_b64,
        },
    }
    try:
        resp = client.post(f"{base_url}/koi-net/handshake", json=handshake_payload)
        if resp.status_code == 200:
            result = resp.json()
            accepted = result.get("accepted", False)
            print(f"    Accepted: {accepted}")
            if accepted:
                passed += 1
            else:
                print("    FAIL: handshake not accepted")
                failed += 1
        else:
            print(f"    FAIL: status {resp.status_code} - {resp.text}")
            failed += 1
    except Exception as e:
        print(f"    FAIL: {e}")
        failed += 1

    # Test 3: Signed poll request
    print("\n[3] Testing signed /koi-net/events/poll...")
    poll_payload = {"type": "poll_events", "limit": 5}
    signed_poll = sign_envelope(poll_payload, test_node_id, target_node_id, private_key)

    try:
        resp = client.post(f"{base_url}/koi-net/events/poll", json=signed_poll)
        if resp.status_code == 200:
            result = resp.json()

            # Check if response is signed
            if "signature" in result:
                try:
                    # Load target's public key from health response
                    target_pub_b64 = health.get("node", {}).get("public_key")
                    if target_pub_b64:
                        target_pub = serialization.load_der_public_key(
                            base64.b64decode(target_pub_b64)
                        )
                        verify_envelope(result, target_pub)
                        print("    Response signature verified!")
                    events = result.get("payload", {}).get("events", [])
                except Exception as e:
                    print(f"    Signature verification failed: {e}")
                    failed += 1
                    events = []
            else:
                events = result.get("events", [])

            print(f"    Events received: {len(events)}")
            passed += 1
        else:
            print(f"    FAIL: status {resp.status_code} - {resp.text}")
            failed += 1
            events = []
    except Exception as e:
        print(f"    FAIL: {e}")
        failed += 1
        events = []

    # Test 4: Fetch RIDs
    print("\n[4] Testing /koi-net/rids/fetch...")
    rids_payload = {"type": "fetch_rids"}
    try:
        resp = client.post(f"{base_url}/koi-net/rids/fetch", json=rids_payload)
        if resp.status_code == 200:
            result = resp.json()
            rids = result.get("rids", [])
            print(f"    RIDs available: {len(rids)}")
            if rids:
                print(f"    First: {rids[0][:60]}...")
            passed += 1
        else:
            print(f"    FAIL: status {resp.status_code}")
            failed += 1
            rids = []
    except Exception as e:
        print(f"    FAIL: {e}")
        failed += 1
        rids = []

    # Test 5: Fetch manifests (if we have RIDs)
    if rids:
        test_rid = rids[0]
        print(f"\n[5] Testing /koi-net/manifests/fetch for {test_rid[:50]}...")
        fetch_payload = {"type": "fetch_manifests", "rids": [test_rid]}
        try:
            resp = client.post(f"{base_url}/koi-net/manifests/fetch", json=fetch_payload)
            if resp.status_code == 200:
                result = resp.json()
                manifests = result.get("manifests", [])
                print(f"    Manifests: {len(manifests)}")
                if manifests:
                    m = manifests[0]
                    ts = m.get("timestamp", "")
                    print(f"    Timestamp: {ts}")
                    if ts.endswith("Z"):
                        print("    Z suffix: OK")
                    else:
                        print(f"    WARNING: timestamp should end with Z")
                passed += 1
            else:
                print(f"    FAIL: status {resp.status_code}")
                failed += 1
        except Exception as e:
            print(f"    FAIL: {e}")
            failed += 1

        # Test 6: Fetch bundles
        print(f"\n[6] Testing /koi-net/bundles/fetch...")
        fetch_payload = {"type": "fetch_bundles", "rids": [test_rid]}
        try:
            resp = client.post(f"{base_url}/koi-net/bundles/fetch", json=fetch_payload)
            if resp.status_code == 200:
                result = resp.json()
                bundles = result.get("bundles", [])
                not_found = result.get("not_found", [])
                print(f"    Bundles: {len(bundles)}, Not found: {len(not_found)}")
                passed += 1
            else:
                print(f"    FAIL: status {resp.status_code}")
                failed += 1
        except Exception as e:
            print(f"    FAIL: {e}")
            failed += 1
    else:
        print("\n[5-6] Skipping manifest/bundle tests (no RIDs available)")

    # Test 7: Unsigned poll (should also work)
    print("\n[7] Testing unsigned /koi-net/events/poll...")
    unsigned_poll = {"type": "poll_events", "node_id": test_node_id, "limit": 1}
    try:
        resp = client.post(f"{base_url}/koi-net/events/poll", json=unsigned_poll)
        if resp.status_code == 200:
            print("    Unsigned poll works")
            passed += 1
        else:
            print(f"    FAIL: status {resp.status_code}")
            failed += 1
    except Exception as e:
        print(f"    FAIL: {e}")
        failed += 1

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"PASSED: {passed}/{total} tests")
    else:
        print(f"FAILED: {failed}/{total} tests failed")
    print("=" * 60)

    client.close()
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Octo KOI-net Interop Test")
    parser.add_argument("--url", default="http://127.0.0.1:8351", help="KOI API base URL")
    args = parser.parse_args()

    success = run_interop_test(args.url)
    sys.exit(0 if success else 1)
