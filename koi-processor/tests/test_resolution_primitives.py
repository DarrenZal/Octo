"""Tests for api/resolution_primitives.py — pure functions and multi-tier resolution."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from api.resolution_primitives import (
    compute_token_overlap,
    jaro_winkler_similarity,
    normalize_alias,
    normalize_entity_text,
    passes_token_overlap_check,
    resolve_entity_multi_tier,
)


# =============================================================================
# Pure function tests
# =============================================================================


def test_normalize_entity_text():
    assert normalize_entity_text("  Herring_Monitoring ") == "herring monitoring"
    assert normalize_entity_text("@TypePrefix") == "typeprefix"
    assert normalize_entity_text("Some-Thing") == "some thing"
    assert normalize_entity_text("  double  space  ") == "double space"


def test_normalize_alias_wikilink():
    assert normalize_alias("[[People/John Smith|John]]") == "john smith"
    assert normalize_alias("[[Organizations/DFO]]") == "dfo"
    assert normalize_alias("plain text") == "plain text"


def test_jaro_winkler_identical():
    assert jaro_winkler_similarity("hello", "hello") == 1.0


def test_jaro_winkler_similar():
    score = jaro_winkler_similarity("herring monitoring", "herring monitring")
    assert score > 0.9


def test_jaro_winkler_different():
    score = jaro_winkler_similarity("apple", "zebra")
    assert score < 0.5


def test_jaro_winkler_empty():
    assert jaro_winkler_similarity("", "hello") == 0.0
    assert jaro_winkler_similarity("hello", "") == 0.0


def test_compute_token_overlap():
    ratio, count = compute_token_overlap("herring monitoring program", "herring monitoring")
    assert count == 2
    assert ratio == 1.0  # 2/2 of shorter text


# =============================================================================
# Mock connection for resolution tests
# =============================================================================


class MockConn:
    """Minimal mock asyncpg connection for resolution tests."""

    def __init__(
        self,
        exact_result=None,
        alias_rows=None,
        fuzzy_rows=None,
        semantic_row=None,
    ):
        self._exact_result = exact_result
        self._alias_rows = alias_rows or []
        self._fuzzy_rows = fuzzy_rows or []
        self._semantic_row = semantic_row

    async def fetchrow(self, query, *args):
        if "normalized_text" in query and "entity_type" in query and "embedding" not in query:
            return self._exact_result
        if "embedding" in query:
            return self._semantic_row
        return None

    async def fetch(self, query, *args):
        if "aliases" in query:
            return self._alias_rows
        if "normalized_text" in query:
            return self._fuzzy_rows
        return []


# =============================================================================
# Multi-tier resolution tests
# =============================================================================


@pytest.mark.asyncio
async def test_resolve_exact_match():
    conn = MockConn(exact_result={"fuseki_uri": "local:practice/herring"})
    uri, conf, rel = await resolve_entity_multi_tier(conn, "Herring Monitoring", "Practice")
    assert uri == "local:practice/herring"
    assert conf == 1.0
    assert rel == "same_as"


@pytest.mark.asyncio
async def test_resolve_alias_match():
    conn = MockConn(
        exact_result=None,
        alias_rows=[
            {"fuseki_uri": "local:org/dfo", "aliases": json.dumps(["DFO", "Fisheries and Oceans"])}
        ],
    )
    uri, conf, rel = await resolve_entity_multi_tier(
        conn, "Fisheries and Oceans", "Organization", mode="exact_alias"
    )
    assert uri == "local:org/dfo"
    assert conf == 1.0
    assert rel == "same_as"


@pytest.mark.asyncio
async def test_resolve_fuzzy_match():
    # Use single-word entity names to bypass token overlap check
    conn = MockConn(
        exact_result=None,
        alias_rows=[],
        fuzzy_rows=[
            {"fuseki_uri": "local:concept/herring", "normalized_text": "herrings"}
        ],
    )
    uri, conf, rel = await resolve_entity_multi_tier(
        conn, "herring", "Concept", mode="fuzzy"
    )
    assert uri == "local:concept/herring"
    assert conf > 0.85
    assert rel == "related_to"


@pytest.mark.asyncio
async def test_resolve_mode_exact_skips_fuzzy():
    conn = MockConn(
        exact_result=None,
        alias_rows=[],
        fuzzy_rows=[
            {"fuseki_uri": "local:practice/herring-mon", "normalized_text": "herring monitring"}
        ],
    )
    uri, conf, rel = await resolve_entity_multi_tier(
        conn, "herring monitoring", "Practice", mode="exact"
    )
    assert uri is None
    assert conf == 0.0
    assert rel == "unresolved"


@pytest.mark.asyncio
async def test_resolve_no_match():
    conn = MockConn(exact_result=None, alias_rows=[], fuzzy_rows=[])
    uri, conf, rel = await resolve_entity_multi_tier(
        conn, "Completely Unknown Entity", "Practice", mode="fuzzy"
    )
    assert uri is None
    assert conf == 0.0
    assert rel == "unresolved"
