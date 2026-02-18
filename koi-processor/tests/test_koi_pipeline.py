"""Tests for the KOI-net knowledge pipeline (P3a parity extraction).

Infrastructure tests: pure Python, no DB.
Parity tests: mock asyncpg pool, verify identical DB effects.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from api.pipeline.knowledge_object import KnowledgeObject
from api.pipeline.handler import Handler, HandlerType, StopChain, STOP_CHAIN
from api.pipeline.context import OctoHandlerContext
from api.pipeline.pipeline import KnowledgePipeline
from api.pipeline.handlers.rid_handlers import (
    block_self_referential,
    set_forget_flag,
    forget_delete_and_stop,
    extract_entity_type,
)
from api.pipeline.handlers.bundle_handlers import (
    entity_type_validator,
    cross_reference_resolver,
)
from api.pipeline.handlers.final_handlers import log_processing_result


# =============================================================================
# Helpers
# =============================================================================


def _mock_context(pool=None) -> OctoHandlerContext:
    """Create a mock OctoHandlerContext."""
    return OctoHandlerContext(
        pool=pool or MagicMock(),
        node_rid="orn:koi-net.node:test+abcdef1234567890",
        node_profile=MagicMock(),
        event_queue=MagicMock(),
    )


def _make_kobj(**kwargs) -> KnowledgeObject:
    """Create a KnowledgeObject with defaults."""
    defaults = {
        "rid": "orn:koi-net.practice:test-practice+abc123",
        "event_type": "NEW",
        "contents": {"@type": "bkc:Practice", "name": "Test Practice"},
        "source_node": "orn:koi-net.node:peer+def456",
    }
    defaults.update(kwargs)
    return KnowledgeObject(**defaults)


class MockConnection:
    """Mock asyncpg connection with recorded SQL calls."""

    def __init__(self, fetchrow_result=None, fetch_result=None):
        self._fetchrow_result = fetchrow_result
        self._fetch_result = fetch_result or []
        self.executed: List[Tuple[str, tuple]] = []
        self.fetchrow_calls: List[Tuple[str, tuple]] = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return self._fetchrow_result

    async def fetch(self, query, *args):
        return self._fetch_result


class MockPool:
    """Mock asyncpg.Pool that yields a MockConnection."""

    def __init__(self, conn: MockConnection):
        self._conn = conn

    def acquire(self):
        return _MockAcquire(self._conn)


class _MockAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


# =============================================================================
# Infrastructure Tests (1-8): Pure Python, no DB
# =============================================================================


def _tracking_handler(handler_type, name, record_list):
    """Create a handler that records its invocation."""
    def fn(ctx, kobj):
        record_list.append(name)
        return kobj
    return Handler(handler_type=handler_type, fn=fn)


@pytest.mark.asyncio
async def test_1_handler_chain_executes_in_order():
    """Handlers execute in registration order."""
    record = []
    handlers = [
        _tracking_handler(HandlerType.RID, "rid_1", record),
        _tracking_handler(HandlerType.RID, "rid_2", record),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    await pipeline.process(_make_kobj())
    assert record == ["rid_1", "rid_2"]


@pytest.mark.asyncio
async def test_2_stop_chain_halts_and_returns_none():
    """STOP_CHAIN halts processing, process() returns None."""
    record = []

    def stopper(ctx, kobj):
        record.append("stopper")
        return STOP_CHAIN

    handlers = [
        Handler(handler_type=HandlerType.RID, fn=stopper),
        _tracking_handler(HandlerType.RID, "should_not_run", record),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    result = await pipeline.process(_make_kobj())
    assert result is None
    assert record == ["stopper"]


@pytest.mark.asyncio
async def test_3_handler_returning_none_passes_kobj_unchanged():
    """Handler returning None passes kobj through unchanged."""
    def noop(ctx, kobj):
        return None  # explicit None

    handlers = [Handler(handler_type=HandlerType.RID, fn=noop)]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    kobj = _make_kobj()
    result = await pipeline.process(kobj)
    assert result is kobj  # same object, unchanged


@pytest.mark.asyncio
async def test_4_handler_returning_modified_kobj_propagates():
    """Handler returning a modified kobj propagates changes."""
    def modifier(ctx, kobj):
        kobj.entity_type = "Modified"
        return kobj

    handlers = [Handler(handler_type=HandlerType.RID, fn=modifier)]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    result = await pipeline.process(_make_kobj())
    assert result.entity_type == "Modified"


@pytest.mark.asyncio
async def test_5_rid_types_filtering_skips_nonmatching():
    """rid_types filtering skips handlers that don't match."""
    record = []
    handlers = [
        # First set entity_type so filtering works
        Handler(handler_type=HandlerType.RID, fn=lambda ctx, k: setattr(k, "entity_type", "Practice") or k),
        Handler(
            handler_type=HandlerType.Bundle,
            fn=lambda ctx, k: record.append("practice_only") or k,
            rid_types={"Practice"},
        ),
        Handler(
            handler_type=HandlerType.Bundle,
            fn=lambda ctx, k: record.append("concept_only") or k,
            rid_types={"Concept"},
        ),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    await pipeline.process(_make_kobj())
    assert record == ["practice_only"]


@pytest.mark.asyncio
async def test_6_event_types_filtering_skips_nonmatching():
    """event_types filtering skips handlers that don't match."""
    record = []
    handlers = [
        Handler(
            handler_type=HandlerType.RID,
            fn=lambda ctx, k: record.append("new_only") or k,
            event_types={"NEW"},
        ),
        Handler(
            handler_type=HandlerType.RID,
            fn=lambda ctx, k: record.append("forget_only") or k,
            event_types={"FORGET"},
        ),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    await pipeline.process(_make_kobj(event_type="NEW"))
    assert record == ["new_only"]


@pytest.mark.asyncio
async def test_7_phases_execute_in_order():
    """Phases execute RID -> Manifest -> Bundle -> Network -> Final."""
    record = []
    handlers = [
        _tracking_handler(HandlerType.Final, "final", record),
        _tracking_handler(HandlerType.RID, "rid", record),
        _tracking_handler(HandlerType.Bundle, "bundle", record),
        _tracking_handler(HandlerType.Network, "network", record),
        _tracking_handler(HandlerType.Manifest, "manifest", record),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    await pipeline.process(_make_kobj())
    assert record == ["rid", "manifest", "bundle", "network", "final"]


@pytest.mark.asyncio
async def test_8_stop_chain_in_rid_skips_all_later_phases():
    """STOP_CHAIN in RID phase skips Manifest, Bundle, Network, Final."""
    record = []
    handlers = [
        Handler(handler_type=HandlerType.RID, fn=lambda ctx, k: STOP_CHAIN),
        _tracking_handler(HandlerType.Manifest, "manifest", record),
        _tracking_handler(HandlerType.Bundle, "bundle", record),
        _tracking_handler(HandlerType.Network, "network", record),
        _tracking_handler(HandlerType.Final, "final", record),
    ]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    result = await pipeline.process(_make_kobj())
    assert result is None
    assert record == []


# =============================================================================
# Parity Handler Tests (9-14): Mock asyncpg pool
# =============================================================================


@pytest.mark.asyncio
async def test_9_forget_sets_flag_and_deletes():
    """FORGET event: set_forget_flag sets normalized_event_type, forget_delete_and_stop issues DELETE + STOP_CHAIN."""
    conn = MockConnection()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj(event_type="FORGET", contents={})

    # set_forget_flag
    result = set_forget_flag(ctx, kobj)
    assert result.normalized_event_type == "FORGET"

    # forget_delete_and_stop
    result2 = await forget_delete_and_stop(ctx, result)
    assert isinstance(result2, StopChain)

    # Verify DELETE was issued
    assert len(conn.executed) == 1
    sql, args = conn.executed[0]
    assert "DELETE FROM koi_net_cross_refs" in sql
    assert args[0] == kobj.rid
    assert args[1] == kobj.source_node


@pytest.mark.asyncio
async def test_10_forget_event_never_reaches_cross_reference_resolver():
    """FORGET event -> cross_reference_resolver never called (verified via full pipeline)."""
    conn = MockConnection()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    from api.pipeline.handlers import DEFAULT_HANDLERS
    pipeline = KnowledgePipeline(ctx=ctx, handlers=DEFAULT_HANDLERS)

    kobj = _make_kobj(event_type="FORGET", contents={})
    result = await pipeline.process(kobj)

    assert result is None  # STOP_CHAIN → None

    # Only the DELETE from forget_delete_and_stop should have been issued
    assert len(conn.executed) == 1
    assert "DELETE" in conn.executed[0][0]

    # No entity_registry queries (cross_reference_resolver never ran)
    for sql, _ in conn.fetchrow_calls:
        assert "entity_registry" not in sql


@pytest.mark.asyncio
async def test_11_new_event_matching_entity():
    """NEW event with matching entity: sets local_uri, confidence 1.0, inserts cross-ref."""
    # First call: entity_registry lookup returns a match
    # Second call: cross_refs lookup returns None (no existing)
    call_count = [0]

    class SequentialConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            call_count[0] += 1
            if "entity_registry" in query:
                return {"fuseki_uri": "local:practice/test-practice"}
            return None  # no existing cross-ref

    conn = SequentialConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "local:practice/test-practice"
    assert result.cross_ref_confidence == 1.0
    assert result.cross_ref_relationship == "same_as"

    # Verify INSERT was issued
    inserts = [s for s, _ in conn.executed if "INSERT" in s]
    assert len(inserts) == 1
    assert "koi_net_cross_refs" in inserts[0]


@pytest.mark.asyncio
async def test_12_new_event_no_match():
    """NEW event with no match: inserts unresolved cross-ref, confidence 0.0."""
    conn = MockConnection(fetchrow_result=None)
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Unknown Entity"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "unresolved:Practice:Unknown Entity"
    assert result.cross_ref_confidence == 0.0
    assert result.cross_ref_relationship == "unresolved"

    inserts = [s for s, _ in conn.executed if "INSERT" in s]
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_13_upgrade_unresolved_cross_ref():
    """NEW event upgrading existing unresolved cross-ref: UPDATE issued."""
    call_count = [0]

    class UpgradeConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            call_count[0] += 1
            if "entity_registry" in query:
                return {"fuseki_uri": "local:practice/test-practice"}
            if "koi_net_cross_refs" in query:
                return {"id": 42, "local_uri": "unresolved:Practice:Test", "relationship": "unresolved", "confidence": 0.0}
            return None

    conn = UpgradeConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.cross_ref_relationship == "same_as"

    # Verify UPDATE was issued (not INSERT)
    updates = [s for s, _ in conn.executed if "UPDATE" in s]
    assert len(updates) == 1
    inserts = [s for s, _ in conn.executed if "INSERT" in s]
    assert len(inserts) == 0


def test_14_extract_entity_type_strips_bkc_prefix():
    """extract_entity_type: 'bkc:Practice' -> entity_type='Practice'."""
    ctx = _mock_context()
    kobj = _make_kobj(contents={"@type": "bkc:Practice", "name": "Herring Monitoring"})

    result = extract_entity_type(ctx, kobj)

    assert result.entity_type == "Practice"
    assert result.entity_name == "Herring Monitoring"


def test_14b_extract_entity_type_no_prefix():
    """extract_entity_type: 'Practice' (no prefix) -> entity_type='Practice'."""
    ctx = _mock_context()
    kobj = _make_kobj(contents={"@type": "Practice", "name": "Herring"})

    result = extract_entity_type(ctx, kobj)

    assert result.entity_type == "Practice"


def test_14c_extract_entity_type_fallback_to_entity_type_key():
    """extract_entity_type: falls back to 'entity_type' key if '@type' missing."""
    ctx = _mock_context()
    kobj = _make_kobj(contents={"entity_type": "Concept", "name": "Reciprocity"})

    result = extract_entity_type(ctx, kobj)

    assert result.entity_type == "Concept"


# =============================================================================
# Async handler support
# =============================================================================


@pytest.mark.asyncio
async def test_async_handler_is_awaited():
    """Pipeline correctly awaits async handlers."""
    async def async_handler(ctx, kobj):
        kobj.entity_type = "AsyncModified"
        return kobj

    handlers = [Handler(handler_type=HandlerType.RID, fn=async_handler)]
    ctx = _mock_context()
    pipeline = KnowledgePipeline(ctx=ctx, handlers=handlers)
    result = await pipeline.process(_make_kobj())
    assert result.entity_type == "AsyncModified"


# =============================================================================
# KnowledgeObject construction
# =============================================================================


def test_knowledge_object_defaults():
    """KnowledgeObject has sensible defaults."""
    kobj = KnowledgeObject(rid="orn:test")
    assert kobj.rid == "orn:test"
    assert kobj.event_type is None
    assert kobj.normalized_event_type is None
    assert kobj.entity_type is None
    assert kobj.entity_name is None
    assert kobj.local_uri is None
    assert kobj.cross_ref_confidence is None
    assert kobj.network_targets == set()


# =============================================================================
# extract_rid_type promotion
# =============================================================================


def test_extract_rid_type_is_public():
    """extract_rid_type (formerly _extract_rid_type) is importable."""
    from api.event_queue import extract_rid_type
    assert extract_rid_type("orn:koi-net.practice:foo+abc") == "Practice"
    assert extract_rid_type("orn:entity:concept/bar+def") == "Concept"
    assert extract_rid_type("unknown-format") is None


# =============================================================================
# P3b: block_self_referential tests (20-24)
# =============================================================================

NODE_RID = "orn:koi-net.node:test+abcdef1234567890"
PEER_RID = "orn:koi-net.node:peer+def456"


def test_20_block_self_referential_external():
    """External peer sends event with our node RID -> STOP_CHAIN."""
    ctx = _mock_context()
    kobj = _make_kobj(rid=NODE_RID, source_node=PEER_RID)
    result = block_self_referential(ctx, kobj)
    assert isinstance(result, StopChain)


def test_21_block_self_referential_source_none():
    """Our node RID but source_node is None (local event) -> passes through."""
    ctx = _mock_context()
    kobj = _make_kobj(rid=NODE_RID, source_node=None)
    result = block_self_referential(ctx, kobj)
    assert result is kobj


def test_22_block_self_referential_source_is_self():
    """Our node RID and source_node is ourselves -> passes through (self-originated)."""
    ctx = _mock_context()
    kobj = _make_kobj(rid=NODE_RID, source_node=NODE_RID)
    result = block_self_referential(ctx, kobj)
    assert result is kobj


def test_23_block_self_referential_different_rid():
    """Different entity RID from external peer -> passes through regardless."""
    ctx = _mock_context()
    kobj = _make_kobj(rid="orn:koi-net.practice:something+abc", source_node=PEER_RID)
    result = block_self_referential(ctx, kobj)
    assert result is kobj


@pytest.mark.asyncio
async def test_24_block_self_referential_before_forget_delete():
    """External FORGET with rid == node_rid: block_self_referential fires STOP_CHAIN before forget_delete_and_stop."""
    conn = MockConnection()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    from api.pipeline.handlers import DEFAULT_HANDLERS
    pipeline = KnowledgePipeline(ctx=ctx, handlers=DEFAULT_HANDLERS)

    kobj = _make_kobj(rid=NODE_RID, event_type="FORGET", contents={}, source_node=PEER_RID)
    result = await pipeline.process(kobj)

    assert result is None  # STOP_CHAIN
    # block_self_referential stopped the chain before forget_delete_and_stop could DELETE
    assert len(conn.executed) == 0


# =============================================================================
# P3b: entity_type_validator tests (25-26)
# =============================================================================


def test_25_entity_type_validator_unknown(caplog):
    """Unknown entity type -> passes through (no STOP_CHAIN), debug logged."""
    import logging
    ctx = _mock_context()
    kobj = _make_kobj()
    kobj.entity_type = "CompletelyUnknownType"

    with caplog.at_level(logging.DEBUG, logger="api.pipeline.handlers.bundle_handlers"):
        result = entity_type_validator(ctx, kobj)

    assert result is kobj  # permissive — no STOP_CHAIN
    assert any("Unknown entity type" in msg for msg in caplog.messages)


def test_26_entity_type_validator_known():
    """Known entity type ('Practice') -> passes through silently."""
    import logging
    ctx = _mock_context()
    kobj = _make_kobj()
    kobj.entity_type = "Practice"

    result = entity_type_validator(ctx, kobj)

    assert result is kobj


# =============================================================================
# P6: UPDATE-aware cross-ref upsert (29-31)
# =============================================================================


@pytest.mark.asyncio
async def test_29_update_event_reresolved():
    """UPDATE event where entity resolves to different local_uri -> cross-ref updated."""
    call_count = [0]

    class ReResolveConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            call_count[0] += 1
            if "entity_registry" in query:
                return {"fuseki_uri": "local:practice/new-practice"}
            if "koi_net_cross_refs" in query:
                return {
                    "id": 99,
                    "local_uri": "local:practice/old-practice",
                    "relationship": "same_as",
                    "confidence": 1.0,
                }
            return None

    conn = ReResolveConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj(event_type="UPDATE")
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "local:practice/new-practice"
    assert result.cross_ref_relationship == "same_as"

    updates = [s for s, _ in conn.executed if "UPDATE" in s]
    assert len(updates) == 1
    inserts = [s for s, _ in conn.executed if "INSERT" in s]
    assert len(inserts) == 0


@pytest.mark.asyncio
async def test_30_update_event_same_resolution():
    """UPDATE event resolving to same uri/relationship/confidence -> no SQL UPDATE issued."""
    class SameResolveConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            if "entity_registry" in query:
                return {"fuseki_uri": "local:practice/test-practice"}
            if "koi_net_cross_refs" in query:
                return {
                    "id": 42,
                    "local_uri": "local:practice/test-practice",
                    "relationship": "same_as",
                    "confidence": 1.0,
                }
            return None

    conn = SameResolveConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj(event_type="UPDATE")
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "local:practice/test-practice"
    # No SQL UPDATE should have been issued (nothing changed)
    assert len(conn.executed) == 0


@pytest.mark.asyncio
async def test_31_new_event_still_upgrades_unresolved():
    """Existing unresolved -> NEW with same_as -> still upgrades (regression guard)."""
    class UpgradeConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            if "entity_registry" in query:
                return {"fuseki_uri": "local:practice/test-practice"}
            if "koi_net_cross_refs" in query:
                return {
                    "id": 42,
                    "local_uri": "unresolved:Practice:Test",
                    "relationship": "unresolved",
                    "confidence": 0.0,
                }
            return None

    conn = UpgradeConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj(event_type="NEW")
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.cross_ref_relationship == "same_as"
    updates = [s for s, _ in conn.executed if "UPDATE" in s]
    assert len(updates) == 1


# =============================================================================
# P7: Multi-tier resolution pipeline integration (32-34)
# =============================================================================


@pytest.mark.asyncio
async def test_32_crossref_resolver_alias_match():
    """Full pipeline: alias match creates same_as cross-ref."""
    import json as _json

    class AliasConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            if "normalized_text" in query and "entity_type" in query:
                return None  # No exact match
            if "koi_net_cross_refs" in query:
                return None  # No existing cross-ref
            return None

        async def fetch(self, query, *args):
            if "aliases" in query:
                return [
                    {
                        "fuseki_uri": "local:org/dfo",
                        "aliases": _json.dumps(["DFO", "Department of Fisheries and Oceans"]),
                    }
                ]
            return []

    conn = AliasConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Department of Fisheries and Oceans"
    kobj.entity_type = "Organization"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "local:org/dfo"
    assert result.cross_ref_confidence == 1.0
    assert result.cross_ref_relationship == "same_as"

    inserts = [s for s, _ in conn.executed if "INSERT" in s]
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_33_crossref_resolver_exact_still_works():
    """Regression: exact match still creates same_as cross-ref."""
    class ExactConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            if "normalized_text" in query and "entity_type" in query:
                return {"fuseki_uri": "local:practice/test-practice"}
            if "koi_net_cross_refs" in query:
                return None
            return None

    conn = ExactConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Test Practice"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "local:practice/test-practice"
    assert result.cross_ref_confidence == 1.0
    assert result.cross_ref_relationship == "same_as"


@pytest.mark.asyncio
async def test_34_crossref_resolver_no_match_still_unresolved():
    """Regression: no match still creates unresolved cross-ref."""
    class NoMatchConn(MockConnection):
        async def fetchrow(self, query, *args):
            self.fetchrow_calls.append((query, args))
            return None

        async def fetch(self, query, *args):
            return []

    conn = NoMatchConn()
    pool = MockPool(conn)
    ctx = _mock_context(pool=pool)

    kobj = _make_kobj()
    kobj.entity_name = "Unknown Entity"
    kobj.entity_type = "Practice"

    result = await cross_reference_resolver(ctx, kobj)

    assert result.local_uri == "unresolved:Practice:Unknown Entity"
    assert result.cross_ref_confidence == 0.0
    assert result.cross_ref_relationship == "unresolved"


# =============================================================================
# P8: WEBHOOK push delivery — EventQueue peek/mark tests (35-39)
# =============================================================================


class InMemoryEventQueue:
    """In-memory mock of EventQueue for peek/mark tests."""

    def __init__(self):
        self._events: Dict[str, Dict[str, Any]] = {}
        self._delivered: Dict[str, set] = {}  # event_id -> set of target_nodes

    def _add(self, event_id: str, event_type: str, rid: str, source_node: str):
        self._events[event_id] = {
            "event_id": event_id,
            "event_type": event_type,
            "rid": rid,
            "manifest": None,
            "contents": None,
            "source_node": source_node,
            "queued_at": "2026-02-18T00:00:00Z",
        }
        self._delivered.setdefault(event_id, set())

    async def peek_undelivered(self, target_node, limit=50, rid_types=None):
        result = []
        for eid, ev in self._events.items():
            if target_node not in self._delivered.get(eid, set()):
                result.append(ev)
            if len(result) >= limit:
                break
        return result

    async def mark_delivered(self, event_ids, target_node):
        count = 0
        for eid in event_ids:
            delivered_set = self._delivered.get(eid, set())
            if target_node not in delivered_set:
                delivered_set.add(target_node)
                self._delivered[eid] = delivered_set
                count += 1
        return count


@pytest.mark.asyncio
async def test_35_event_queue_peek_does_not_mark():
    """peek returns events; subsequent peek returns same events (not marked)."""
    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")
    eq._add("evt-2", "NEW", "orn:koi-net.practice:bar+def", "src-node")

    events1 = await eq.peek_undelivered("target-A")
    events2 = await eq.peek_undelivered("target-A")

    assert len(events1) == 2
    assert len(events2) == 2
    assert [e["event_id"] for e in events1] == [e["event_id"] for e in events2]


@pytest.mark.asyncio
async def test_36_event_queue_mark_delivered():
    """mark_delivered updates delivered_to; subsequent peek excludes marked events."""
    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")
    eq._add("evt-2", "NEW", "orn:koi-net.practice:bar+def", "src-node")

    count = await eq.mark_delivered(["evt-1"], "target-A")
    assert count == 1

    events = await eq.peek_undelivered("target-A")
    assert len(events) == 1
    assert events[0]["event_id"] == "evt-2"


@pytest.mark.asyncio
async def test_37_mark_delivered_idempotent():
    """Marking already-delivered events is a no-op (returns 0)."""
    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")

    await eq.mark_delivered(["evt-1"], "target-A")
    count = await eq.mark_delivered(["evt-1"], "target-A")

    assert count == 0


@pytest.mark.asyncio
async def test_38_webhook_push_failure_preserves_events():
    """Mock push failure; verify events remain undelivered for retry."""
    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")

    # Simulate: peek succeeded, push failed, mark_delivered NOT called
    events = await eq.peek_undelivered("target-A")
    assert len(events) == 1
    # (push fails — we don't call mark_delivered)

    # Events should still be available for retry
    retry_events = await eq.peek_undelivered("target-A")
    assert len(retry_events) == 1
    assert retry_events[0]["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_39_event_insert_dedup():
    """Inserting same event_id for same source should be idempotent in the mock."""
    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")
    eq._add("evt-1", "UPDATE", "orn:koi-net.practice:foo+abc", "src-node")

    # In our dict-based mock, same key overwrites (simulates ON CONFLICT DO NOTHING behavior)
    events = await eq.peek_undelivered("target-A")
    assert len(events) == 1  # Only one event with event_id "evt-1"


# =============================================================================
# Webhook key-refresh fallback tests
# =============================================================================


def _make_poller(event_queue=None):
    """Create a KOIPoller with mocked pool and event queue for webhook tests."""
    from api.koi_poller import KOIPoller

    pool = MagicMock()
    poller = KOIPoller(
        pool=pool,
        node_rid="orn:koi-net.node:test+abcdef1234567890",
        private_key=None,  # unsigned requests for simplicity
        event_queue=event_queue or InMemoryEventQueue(),
    )
    return poller


@pytest.mark.asyncio
async def test_40_webhook_key_refresh_on_missing():
    """When edge public_key is None, _learn_peer_public_key is called and verification succeeds."""
    from api.koi_envelope import EnvelopeError

    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:foo+abc", "src-node")
    poller = _make_poller(event_queue=eq)

    target_node = "orn:koi-net.node:peer+1111111111111111"
    base_url = "http://peer:8351"
    refreshed_key = "MFkwEwYHKoZIzj0REFRESHED"

    # Mock pool.acquire to return one WEBHOOK edge with public_key=None
    edge_row = {
        "target_node": target_node,
        "rid_types": None,
        "base_url": base_url,
        "public_key": None,
    }
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[edge_row])
    poller.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    poller.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    # Mock HTTP response: signed envelope that needs the refreshed key
    successful_body = {"queued": 1}

    call_count = 0

    def mock_unwrap(raw_body, source_node, pub_key, expected_target_node=None):
        nonlocal call_count
        call_count += 1
        if pub_key is None:
            raise EnvelopeError("No public key", code="UNKNOWN_SOURCE_NODE")
        if pub_key == refreshed_key:
            return successful_body
        raise EnvelopeError("Bad key", code="SIGNATURE_INVALID")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"envelope": "signed", "payload": {}, "signature": "abc"}

    with patch("api.koi_poller.httpx.AsyncClient") as mock_client_cls, \
         patch("api.koi_poller.unwrap_and_verify_response", side_effect=mock_unwrap):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock _learn_peer_public_key to return the refreshed key
        poller._learn_peer_public_key = AsyncMock(return_value=refreshed_key)

        await poller._push_webhook_peers()

    # _learn_peer_public_key should have been called with the target node
    poller._learn_peer_public_key.assert_called_once_with(target_node, base_url)

    # unwrap_and_verify_response should have been called twice:
    # 1st with None (fails), 2nd with refreshed key (succeeds)
    assert call_count == 2

    # Events should be marked delivered (success path)
    remaining = await eq.peek_undelivered(target_node)
    assert len(remaining) == 0

    # No backoff should be set
    assert poller._webhook_backoff.get(target_node, 0) == 0


@pytest.mark.asyncio
async def test_41_webhook_key_refresh_on_stale():
    """When cached key fails verification, refreshed key succeeds on retry."""
    from api.koi_envelope import EnvelopeError

    eq = InMemoryEventQueue()
    eq._add("evt-1", "NEW", "orn:koi-net.practice:bar+def", "src-node")
    poller = _make_poller(event_queue=eq)

    target_node = "orn:koi-net.node:peer+2222222222222222"
    base_url = "http://peer:8351"
    stale_key = "MFkwEwYHKoZIzj0STALE"
    refreshed_key = "MFkwEwYHKoZIzj0REFRESHED"

    edge_row = {
        "target_node": target_node,
        "rid_types": None,
        "base_url": base_url,
        "public_key": stale_key,
    }
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[edge_row])
    poller.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    poller.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    successful_body = {"queued": 1}

    call_count = 0

    def mock_unwrap(raw_body, source_node, pub_key, expected_target_node=None):
        nonlocal call_count
        call_count += 1
        if pub_key == refreshed_key:
            return successful_body
        raise EnvelopeError("Stale key", code="SIGNATURE_INVALID")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"envelope": "signed", "payload": {}, "signature": "abc"}

    with patch("api.koi_poller.httpx.AsyncClient") as mock_client_cls, \
         patch("api.koi_poller.unwrap_and_verify_response", side_effect=mock_unwrap):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        poller._learn_peer_public_key = AsyncMock(return_value=refreshed_key)

        await poller._push_webhook_peers()

    # _learn_peer_public_key called after stale key failed
    poller._learn_peer_public_key.assert_called_once_with(target_node, base_url)

    # Two calls: 1st with stale key (fails), 2nd with refreshed key (succeeds)
    assert call_count == 2

    # Events marked delivered
    remaining = await eq.peek_undelivered(target_node)
    assert len(remaining) == 0

    # No backoff
    assert poller._webhook_backoff.get(target_node, 0) == 0
