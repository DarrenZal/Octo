"""RID-phase handlers — extracted 1:1 from koi_poller.py:368-384."""

from __future__ import annotations

import logging

from api.pipeline.context import OctoHandlerContext
from api.pipeline.handler import STOP_CHAIN, StopChain
from api.pipeline.knowledge_object import KnowledgeObject

logger = logging.getLogger(__name__)


def block_self_referential(ctx: OctoHandlerContext, kobj: KnowledgeObject):
    """Drop events where the RID is our own node RID from an external source.

    Matches BlockScience's basic_rid_handler (default_handlers.py:20-27):
    "Don't let anyone else tell me who I am!"
    """
    if kobj.rid == ctx.node_rid and kobj.source_node and kobj.source_node != ctx.node_rid:
        logger.info(f"Blocked self-referential event {kobj.rid} from {kobj.source_node}")
        return STOP_CHAIN
    return kobj


def set_forget_flag(ctx: OctoHandlerContext, kobj: KnowledgeObject) -> KnowledgeObject:
    """If event_type is FORGET, set normalized_event_type.

    Source: koi_poller.py:368
    """
    if kobj.event_type == "FORGET":
        kobj.normalized_event_type = "FORGET"
    return kobj


async def forget_delete_and_stop(ctx: OctoHandlerContext, kobj: KnowledgeObject):
    """Delete cross-refs for FORGET events and stop the chain.

    Source: koi_poller.py:370-377
    """
    if kobj.normalized_event_type != "FORGET":
        return kobj

    async with ctx.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM koi_net_cross_refs WHERE remote_rid = $1 AND remote_node = $2",
            kobj.rid,
            kobj.source_node,
        )
    logger.info(f"Removed cross-ref for forgotten RID {kobj.rid}")
    return STOP_CHAIN


def extract_entity_type(ctx: OctoHandlerContext, kobj: KnowledgeObject) -> KnowledgeObject:
    """Extract entity_type and entity_name from contents.

    Source: koi_poller.py:380-384
    """
    contents = kobj.contents or {}
    kobj.entity_name = contents.get("name", "")
    entity_type = contents.get("@type", contents.get("entity_type", ""))
    if entity_type.startswith("bkc:"):
        entity_type = entity_type[4:]
    kobj.entity_type = entity_type
    return kobj
