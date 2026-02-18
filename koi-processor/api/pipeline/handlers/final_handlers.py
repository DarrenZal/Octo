"""Final-phase handlers — extracted 1:1 from koi_poller.py:447-449."""

from __future__ import annotations

import logging

from api.pipeline.context import OctoHandlerContext
from api.pipeline.knowledge_object import KnowledgeObject

logger = logging.getLogger(__name__)


def log_processing_result(ctx: OctoHandlerContext, kobj: KnowledgeObject) -> KnowledgeObject:
    """Log the cross-reference outcome.

    Source: koi_poller.py:447-449
    """
    logger.info(
        f"Cross-ref: {kobj.rid} -> {kobj.local_uri} "
        f"({kobj.cross_ref_relationship}, conf={kobj.cross_ref_confidence})"
    )
    return kobj
