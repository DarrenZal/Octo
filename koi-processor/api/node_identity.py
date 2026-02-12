"""
KOI-net Node Identity

Generates or loads ECDSA P-256 keypair for node identity.
Derives node RID and builds NodeProfile with capability declarations.

Key storage: /root/koi-state/{agent_name}_private_key.pem
"""

from __future__ import annotations

import hashlib
import os
import logging
from base64 import b64encode
from pathlib import Path

from api.koi_protocol import NodeProfile, NodeProvides

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


# BKC entity types this node handles
DEFAULT_EVENT_TYPES = ["Practice", "Pattern", "CaseStudy", "Bioregion"]
DEFAULT_STATE_TYPES = [
    "Practice", "Pattern", "CaseStudy", "Bioregion",
    "Organization", "Person",
]

# Key storage directory
KEY_STATE_DIR = os.getenv("KOI_STATE_DIR", "/root/koi-state")


def _key_path(node_name: str) -> Path:
    return Path(KEY_STATE_DIR) / f"{node_name}_private_key.pem"


def generate_keypair():
    """Generate a new ECDSA P-256 keypair."""
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package required for key generation")
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key


def save_private_key(private_key, path: Path):
    """Save private key to PEM file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    os.chmod(path, 0o600)
    logger.info(f"Saved private key to {path}")


def load_private_key(path: Path):
    """Load private key from PEM file."""
    if not _CRYPTO_AVAILABLE:
        return None
    if not path.exists():
        return None
    return serialization.load_pem_private_key(
        data=path.read_bytes(),
        password=None,
    )


def node_rid_suffix(node_rid: str) -> str:
    """Return RID hash suffix after '+'."""
    if "+" not in node_rid:
        return ""
    return node_rid.rsplit("+", 1)[-1]


def derive_node_rid_hash(public_key, hash_mode: str = "legacy16") -> str:
    """Derive a node RID hash suffix from the public key.

    Supported modes:
    - legacy16: sha256(base64(der_pubkey))[:16]
    - der64: sha256(der_pubkey) full 64 hex
    """
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if hash_mode == "legacy16":
        der_b64 = b64encode(der_bytes).decode()
        return hashlib.sha256(der_b64.encode()).hexdigest()[:16]
    if hash_mode == "der64":
        return hashlib.sha256(der_bytes).hexdigest()
    raise ValueError(f"Unsupported hash_mode: {hash_mode}")


def derive_node_rid(node_name: str, public_key, hash_mode: str = "legacy16") -> str:
    """Derive node RID from name and public key."""
    return f"orn:koi-net.node:{node_name}+{derive_node_rid_hash(public_key, hash_mode)}"


def node_rid_matches_public_key(
    node_rid: str,
    public_key,
    allow_legacy16: bool = True,
    allow_der64: bool = True,
) -> bool:
    """Check whether RID suffix matches supported hash semantics for a key."""
    suffix = node_rid_suffix(node_rid)
    if not suffix:
        return False
    if len(suffix) == 16:
        return allow_legacy16 and suffix == derive_node_rid_hash(public_key, "legacy16")
    if len(suffix) == 64:
        return allow_der64 and suffix == derive_node_rid_hash(public_key, "der64")
    return False


def get_public_key_der_b64(private_key) -> str:
    """Get the DER-encoded base64 public key from a private key."""
    public_key = private_key.public_key()
    der_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64encode(der_bytes).decode()


def load_or_create_identity(
    node_name: str,
    base_url: str | None = None,
    node_type: str = "FULL",
) -> tuple:
    """Load existing identity or create new one.

    Returns (private_key, node_profile).
    """
    key_file = _key_path(node_name)

    private_key = load_private_key(key_file)
    if private_key is None:
        logger.info(f"No existing key found at {key_file}, generating new keypair")
        private_key = generate_keypair()
        save_private_key(private_key, key_file)
    else:
        logger.info(f"Loaded existing key from {key_file}")

    public_key = private_key.public_key()
    node_rid = derive_node_rid(node_name, public_key)
    public_key_b64 = get_public_key_der_b64(private_key)

    profile = NodeProfile(
        node_rid=node_rid,
        node_name=node_name,
        node_type=node_type,
        base_url=base_url,
        provides=NodeProvides(
            event=DEFAULT_EVENT_TYPES,
            state=DEFAULT_STATE_TYPES,
        ),
        public_key=public_key_b64,
    )

    logger.info(f"Node identity: {node_rid}")
    return private_key, profile
