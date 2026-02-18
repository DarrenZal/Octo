"""Bundle-phase handlers — extracted 1:1 from koi_poller.py:389-445."""

from __future__ import annotations

import logging
import os

from api.pipeline.context import OctoHandlerContext
from api.pipeline.knowledge_object import KnowledgeObject
from api.entity_schema import get_schema_for_type, UNKNOWN_TYPE_SCHEMA
from api.resolution_primitives import resolve_entity_multi_tier

logger = logging.getLogger(__name__)

_CONFIDENCE_EPSILON = 0.001  # Avoid float flap on re-resolution


def _confidence_changed(old_conf, new_conf):
    """Null-safe epsilon comparison for confidence values."""
    return abs((old_conf or 0.0) - (new_conf or 0.0)) > _CONFIDENCE_EPSILON


def entity_type_validator(ctx: OctoHandlerContext, kobj: KnowledgeObject) -> KnowledgeObject:
    """Log debug message for unknown entity types. Permissive (no STOP_CHAIN).

    Note: get_schema_for_type() already logs a WARNING for unknown types.
    This handler adds RID context at DEBUG level for pipeline tracing.
    """
    if kobj.entity_type:
        schema = get_schema_for_type(kobj.entity_type)
        if schema is UNKNOWN_TYPE_SCHEMA:
            logger.debug(f"Unknown entity type '{kobj.entity_type}' in federated event {kobj.rid}")
    return kobj


async def cross_reference_resolver(ctx: OctoHandlerContext, kobj: KnowledgeObject) -> KnowledgeObject:
    """Resolve entity against local registry and upsert cross-reference.

    Uses multi-tier resolution via resolve_entity_multi_tier().
    Mode controlled by KOI_CROSSREF_MODE env var (default: exact_alias).

    Supports UPDATE-aware upsert: when an UPDATE event arrives and the
    resolved target, relationship, or confidence has changed, the existing
    cross-ref is updated in place.
    """
    entity_name = kobj.entity_name or ""
    entity_type = kobj.entity_type or ""

    if not entity_name:
        logger.debug(f"Event {kobj.rid} has no name in contents, storing cross-ref only")

    # Multi-tier resolution
    local_uri = None
    confidence = 0.0
    relationship = "unresolved"

    if entity_name:
        mode = os.environ.get("KOI_CROSSREF_MODE", "exact_alias")
        embed_fn = None
        if mode == "semantic":
            embed_fn = ctx.embed_fn
            if embed_fn is None:
                mode = "fuzzy"  # Graceful fallback if not registered

        async with ctx.pool.acquire() as conn:
            local_uri, confidence, relationship = await resolve_entity_multi_tier(
                conn, entity_name, entity_type, mode=mode, embed_fn=embed_fn,
            )

    if not local_uri:
        local_uri = f"unresolved:{entity_type}:{entity_name}"
        relationship = "unresolved"
        confidence = 0.0

    # Create or update cross-reference
    async with ctx.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, local_uri, relationship, confidence FROM koi_net_cross_refs WHERE remote_rid = $1 AND remote_node = $2",
            kobj.rid, kobj.source_node,
        )

        if existing:
            needs_update = False
            if existing["relationship"] == "unresolved" and relationship != "unresolved":
                needs_update = True  # upgrade from unresolved
            elif kobj.event_type == "UPDATE" and (
                existing["local_uri"] != local_uri
                or existing["relationship"] != relationship
                or _confidence_changed(existing["confidence"], confidence)
            ):
                needs_update = True  # UPDATE event changed resolved target, relationship, or confidence

            if needs_update:
                await conn.execute(
                    "UPDATE koi_net_cross_refs SET local_uri = $1, relationship = $2, confidence = $3 WHERE id = $4",
                    local_uri, relationship, confidence, existing["id"],
                )
                logger.info(
                    f"Updated cross-ref {kobj.rid}: "
                    f"{existing['relationship']}({existing['confidence']}) -> {relationship}({confidence})"
                )
        else:
            await conn.execute(
                """
                INSERT INTO koi_net_cross_refs
                    (local_uri, remote_rid, remote_node, relationship, confidence)
                VALUES ($1, $2, $3, $4, $5)
                """,
                local_uri,
                kobj.rid,
                kobj.source_node,
                relationship,
                confidence,
            )

    kobj.local_uri = local_uri
    kobj.cross_ref_confidence = confidence
    kobj.cross_ref_relationship = relationship
    return kobj
