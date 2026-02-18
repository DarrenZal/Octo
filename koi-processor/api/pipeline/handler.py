"""Handler types and registration for the knowledge pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, List, Optional, Set, Union

from api.pipeline.knowledge_object import KnowledgeObject


class HandlerType(StrEnum):
    RID = "rid"
    Manifest = "manifest"
    Bundle = "bundle"
    Network = "network"
    Final = "final"


class StopChain:
    """Sentinel returned by a handler to halt the current phase and all subsequent phases."""


STOP_CHAIN = StopChain()


@dataclass
class Handler:
    handler_type: HandlerType
    fn: Callable
    rid_types: Optional[Set[str]] = None
    event_types: Optional[Set[str]] = None

    def __call__(self, ctx: Any, kobj: KnowledgeObject) -> Union[KnowledgeObject, StopChain, None]:
        return self.fn(ctx, kobj)
