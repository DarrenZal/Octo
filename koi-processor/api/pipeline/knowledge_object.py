"""KnowledgeObject — the data carrier flowing through the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


@dataclass
class KnowledgeObject:
    rid: str
    event_type: Optional[str] = None
    normalized_event_type: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None
    contents: Optional[Dict[str, Any]] = None
    source_node: Optional[str] = None
    event_id: Optional[str] = None
    # Populated by handlers
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None
    local_uri: Optional[str] = None
    cross_ref_confidence: Optional[float] = None
    cross_ref_relationship: Optional[str] = None
    network_targets: Set[str] = field(default_factory=set)
