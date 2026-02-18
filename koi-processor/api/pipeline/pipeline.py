"""KnowledgePipeline — async 5-phase handler chain."""

from __future__ import annotations

import inspect
import logging
from typing import List, Optional

from api.pipeline.context import OctoHandlerContext
from api.pipeline.handler import Handler, HandlerType, StopChain, STOP_CHAIN
from api.pipeline.knowledge_object import KnowledgeObject

logger = logging.getLogger(__name__)

PHASES = [
    HandlerType.RID,
    HandlerType.Manifest,
    HandlerType.Bundle,
    HandlerType.Network,
    HandlerType.Final,
]


class KnowledgePipeline:
    """Async pipeline that processes KnowledgeObjects through 5 phases."""

    def __init__(self, ctx: OctoHandlerContext, handlers: List[Handler]):
        self.ctx = ctx
        self.handlers = handlers

    async def process(self, kobj: KnowledgeObject) -> Optional[KnowledgeObject]:
        for phase in PHASES:
            result = await self._call_handler_chain(phase, kobj)
            if isinstance(result, StopChain):
                return None
            kobj = result
        return kobj

    async def _call_handler_chain(self, handler_type: HandlerType, kobj: KnowledgeObject) -> KnowledgeObject | StopChain:
        for handler in self.handlers:
            if handler.handler_type != handler_type:
                continue
            if handler.rid_types and kobj.entity_type not in handler.rid_types:
                continue
            if handler.event_types and kobj.event_type not in handler.event_types:
                continue
            result = handler(self.ctx, kobj)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, StopChain):
                return STOP_CHAIN
            if isinstance(result, KnowledgeObject):
                kobj = result
        return kobj
