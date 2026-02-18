"""KOI-net Knowledge Pipeline — 5-phase handler chain for event processing."""

from api.pipeline.context import OctoHandlerContext
from api.pipeline.handler import STOP_CHAIN, Handler, HandlerType, StopChain
from api.pipeline.knowledge_object import KnowledgeObject
from api.pipeline.pipeline import KnowledgePipeline

# Lazy import to avoid pulling in handler deps at package level
def _default_handlers():
    from api.pipeline.handlers import DEFAULT_HANDLERS
    return DEFAULT_HANDLERS

__all__ = [
    "KnowledgePipeline",
    "KnowledgeObject",
    "OctoHandlerContext",
    "Handler",
    "HandlerType",
    "StopChain",
    "STOP_CHAIN",
    "_default_handlers",
]
