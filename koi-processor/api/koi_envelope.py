"""
KOI SignedEnvelope utilities for Octo.

Ported from RegenAI's shared/koi_envelope.py — ECDSA P-256 with raw r||s
base64 signatures matching KOI-net reference behavior.

Key difference from RegenAI version: public keys loaded from koi_net_nodes
database table instead of env/JSON file.
"""

from __future__ import annotations

import json
import os
import hashlib
from base64 import b64decode, b64encode
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
        encode_dss_signature,
    )
    _CRYPTO_AVAILABLE = True
except Exception:
    _CRYPTO_AVAILABLE = False
    InvalidSignature = Exception
    ec = None


class EnvelopeError(Exception):
    """Raised when envelope validation fails."""

    def __init__(self, message: str, code: str = "ENVELOPE_ERROR"):
        super().__init__(message)
        self.code = code


# =============================================================================
# Pydantic models matching KOI-net protocol/envelope.py
# CRITICAL: exclude_none=True ensures FORGET events (manifest=None) serialize
# correctly — omitting the field rather than emitting "manifest": null
# =============================================================================

class UnsignedEnvelope(BaseModel):
    """Unsigned envelope for signature computation."""
    model_config = ConfigDict(extra="forbid")

    payload: Dict[str, Any]
    source_node: str
    target_node: str


# =============================================================================
# Signature helpers
# =============================================================================

def _unsigned_envelope_bytes(
    payload: Dict[str, Any], source_node: str, target_node: str
) -> bytes:
    """Compute the bytes to sign/verify using Pydantic serialization.

    Uses model_dump_json(exclude_none=True) to match KOI-net exactly.
    """
    unsigned = UnsignedEnvelope(
        payload=payload,
        source_node=source_node,
        target_node=target_node,
    )
    return unsigned.model_dump_json(exclude_none=True).encode("utf-8")


def _der_to_raw_signature(der_signature: bytes) -> bytes:
    """Convert DER-encoded ECDSA signature to raw r||s format."""
    r, s = decode_dss_signature(der_signature)
    byte_length = (ec.SECP256R1().key_size + 7) // 8
    r_bytes = r.to_bytes(byte_length, byteorder="big")
    s_bytes = s.to_bytes(byte_length, byteorder="big")
    return r_bytes + s_bytes


def _raw_to_der_signature(raw_signature: bytes) -> bytes:
    """Convert raw r||s signature to DER-encoded format."""
    byte_length = (ec.SECP256R1().key_size + 7) // 8
    if len(raw_signature) != 2 * byte_length:
        raise EnvelopeError(
            f"Raw signature must be {2 * byte_length} bytes",
            code="INVALID_SIGNATURE_FORMAT",
        )
    r_bytes = raw_signature[:byte_length]
    s_bytes = raw_signature[byte_length:]
    r = int.from_bytes(r_bytes, byteorder="big")
    s = int.from_bytes(s_bytes, byteorder="big")
    return encode_dss_signature(r, s)


# =============================================================================
# Key loading
# =============================================================================

def load_private_key_from_file(path: str, password: Optional[str] = None):
    """Load ECDSA private key from PEM file."""
    if not _CRYPTO_AVAILABLE:
        return None
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        pem_data = f.read()
    password_bytes = password.encode() if password else None
    return serialization.load_pem_private_key(data=pem_data, password=password_bytes)


def load_public_key_from_der_b64(der_b64: str):
    """Load ECDSA public key from DER-encoded base64 string."""
    if not _CRYPTO_AVAILABLE:
        return None
    der_bytes = b64decode(der_b64)
    return serialization.load_der_public_key(der_bytes)


def public_key_to_der_b64(public_key) -> str:
    """Export public key as DER-encoded base64 string."""
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64encode(der_bytes).decode()


def public_key_der_sha256_hex(public_key) -> str:
    """Hash DER-encoded public key bytes with SHA256 (full hex digest)."""
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der_bytes).hexdigest()


def public_key_legacy_sha256_suffix(public_key) -> str:
    """Legacy Octo hash suffix: sha256(base64(der_pubkey))[:16]."""
    der_b64 = public_key_to_der_b64(public_key)
    return hashlib.sha256(der_b64.encode()).hexdigest()[:16]


def node_rid_suffix(node_rid: str) -> str:
    """Return RID suffix after '+', or empty string if malformed."""
    if "+" not in node_rid:
        return ""
    return node_rid.rsplit("+", 1)[-1]


def node_rid_matches_public_key(
    node_rid: str,
    public_key,
    allow_legacy16: bool = True,
    allow_der64: bool = True,
) -> bool:
    """Check whether a node RID suffix matches an expected public-key hash.

    Supported suffixes:
    - 16-char legacy: sha256(base64(der_pubkey))[:16]
    - 64-char canonical: sha256(der_pubkey)
    """
    suffix = node_rid_suffix(node_rid)
    if not suffix:
        return False

    if len(suffix) == 16:
        if not allow_legacy16:
            return False
        return suffix == public_key_legacy_sha256_suffix(public_key)

    if len(suffix) == 64:
        if not allow_der64:
            return False
        return suffix == public_key_der_sha256_hex(public_key)

    return False


# =============================================================================
# Sign / Verify
# =============================================================================

def sign_envelope(
    payload: Dict[str, Any],
    source_node: str,
    target_node: str,
    private_key,
) -> Dict[str, Any]:
    """Sign an envelope payload and return the signed envelope dict."""
    if not _CRYPTO_AVAILABLE:
        raise EnvelopeError("cryptography package required for signing", code="CRYPTO_UNAVAILABLE")
    message = _unsigned_envelope_bytes(payload, source_node, target_node)
    der_signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    raw_signature = _der_to_raw_signature(der_signature)
    return {
        "payload": payload,
        "source_node": source_node,
        "target_node": target_node,
        "signature": b64encode(raw_signature).decode(),
    }


def verify_envelope(
    envelope: Dict[str, Any],
    public_key,
    expected_source_node: Optional[str] = None,
    expected_target_node: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Verify a signed envelope using a single public key.

    Returns (payload, source_node) on success.
    Raises EnvelopeError on failure.
    """
    if not _CRYPTO_AVAILABLE:
        raise EnvelopeError(
            "cryptography package required for verification",
            code="CRYPTO_UNAVAILABLE",
        )

    source_node = envelope.get("source_node")
    target_node = envelope.get("target_node")
    signature = envelope.get("signature")

    if not source_node or not target_node or not signature:
        raise EnvelopeError("Envelope missing required fields", code="MISSING_ENVELOPE_FIELDS")
    if expected_source_node and source_node != expected_source_node:
        raise EnvelopeError(
            f"Envelope source_node mismatch: expected {expected_source_node}, got {source_node}",
            code="SOURCE_NODE_MISMATCH",
        )
    if expected_target_node and target_node != expected_target_node:
        raise EnvelopeError(
            f"Envelope target_node mismatch: expected {expected_target_node}, got {target_node}",
            code="TARGET_NODE_MISMATCH",
        )

    message = _unsigned_envelope_bytes(envelope["payload"], source_node, target_node)
    raw_signature = b64decode(signature)
    der_signature = _raw_to_der_signature(raw_signature)

    try:
        public_key.verify(der_signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise EnvelopeError("Invalid envelope signature", code="INVALID_SIGNATURE") from exc

    return envelope["payload"], source_node


def is_signed_envelope(body: Dict[str, Any]) -> bool:
    """Check if a request body is a SignedEnvelope."""
    return (
        isinstance(body, dict)
        and "signature" in body
        and "payload" in body
        and "source_node" in body
        and "target_node" in body
    )
