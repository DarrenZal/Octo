"""OctoHandlerContext — shared state passed to all handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional

if TYPE_CHECKING:
    import asyncpg
    from api.event_queue import EventQueue
    from api.koi_protocol import NodeProfile


@dataclass
class OctoHandlerContext:
    pool: asyncpg.Pool
    node_rid: str
    node_profile: NodeProfile
    event_queue: EventQueue
    embed_fn: Optional[Callable[[str], Awaitable[Optional[List[float]]]]] = None
