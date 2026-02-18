"""Pure entity resolution primitives.

No module-level state. No external API calls.
Embedding generation is injected as an optional async callable.

Copied from personal_ingest_api.py for use in the KOI-net pipeline
without pulling in the full app module and its side effects.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from api.entity_schema import get_schema_for_type

logger = logging.getLogger(__name__)

# Token overlap constants (matches personal_ingest_api.py)
MIN_TOKEN_OVERLAP_RATIO = 0.5
MIN_TOKEN_OVERLAP_COUNT = 2


def normalize_entity_text(text: str) -> str:
    """Normalize entity text for comparison."""
    return (
        text.lower()
        .strip()
        .replace("_", " ")
        .replace("-", " ")
        .replace("  ", " ")
        .lstrip("@")
    )


def normalize_alias(alias: Any) -> str:
    """Strip [[...]], lowercase, trim for alias matching.

    Handles wikilinks like [[People/Name|Display]] -> name
    """
    alias = str(alias)
    alias = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", alias)
    if "/" in alias:
        alias = alias.rsplit("/", 1)[-1]
    alias = alias.lower().strip()
    return alias


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calculate Jaro-Winkler similarity between two strings."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (
        matches / len1
        + matches / len2
        + (matches - transpositions / 2) / matches
    ) / 3

    prefix_len = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * 0.1 * (1 - jaro)


def compute_token_overlap(text1: str, text2: str) -> Tuple[float, int]:
    """Compute token (word) overlap between two texts.

    Returns: (overlap_ratio, overlap_count)
    """
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())
    overlap = tokens1 & tokens2
    overlap_count = len(overlap)
    shorter_len = min(len(tokens1), len(tokens2))
    if shorter_len == 0:
        return 0.0, 0
    return overlap_count / shorter_len, overlap_count


def passes_token_overlap_check(text1: str, text2: str, entity_type: str) -> bool:
    """Check if two texts pass the token overlap requirement."""
    schema = get_schema_for_type(entity_type)
    if not schema.require_token_overlap:
        return True

    overlap_ratio, overlap_count = compute_token_overlap(text1, text2)
    tokens1 = text1.lower().split()
    tokens2 = text2.lower().split()
    if len(tokens1) == 1 or len(tokens2) == 1:
        return True
    if overlap_ratio < MIN_TOKEN_OVERLAP_RATIO:
        return False
    if overlap_count < MIN_TOKEN_OVERLAP_COUNT:
        return False
    return True


async def resolve_entity_multi_tier(
    conn,
    entity_name: str,
    entity_type: str,
    mode: str = "exact_alias",
    embed_fn: Optional[Callable[[str], Awaitable[Optional[List[float]]]]] = None,
) -> Tuple[Optional[str], float, str]:
    """Multi-tier entity resolution against entity_registry.

    Tiers enabled by mode:
    - "exact": Tier 1 only
    - "exact_alias": Tiers 1 + 1.1
    - "fuzzy": Tiers 1 + 1.1 + 2a
    - "semantic": Tiers 1 + 1.1 + 2a + 2b (requires embed_fn)

    Does NOT include Tier 1.5 (contextual) or Tier 3 (create new entity).
    Returns: (local_uri or None, confidence, relationship)
    """
    normalized = normalize_entity_text(entity_name)

    # --- Tier 1: Exact match on normalized_text ---
    row = await conn.fetchrow(
        """
        SELECT fuseki_uri FROM entity_registry
        WHERE normalized_text = $1 AND entity_type = $2
        """,
        normalized,
        entity_type,
    )
    if row:
        return row["fuseki_uri"], 1.0, "same_as"

    if mode == "exact":
        return None, 0.0, "unresolved"

    # --- Tier 1.1: Alias match ---
    alias_norm = normalize_alias(entity_name)
    rows = await conn.fetch(
        """
        SELECT fuseki_uri, aliases FROM entity_registry
        WHERE entity_type = $1 AND aliases IS NOT NULL
        """,
        entity_type,
    )
    for r in rows:
        aliases = r["aliases"]
        if isinstance(aliases, str):
            import json as _json

            try:
                aliases = _json.loads(aliases)
            except (ValueError, TypeError):
                aliases = [aliases]
        if not isinstance(aliases, list):
            continue
        for a in aliases:
            if normalize_alias(a) == alias_norm:
                return r["fuseki_uri"], 1.0, "same_as"

    if mode == "exact_alias":
        return None, 0.0, "unresolved"

    # --- Tier 2a: Fuzzy (Jaro-Winkler) ---
    schema = get_schema_for_type(entity_type)
    threshold = schema.similarity_threshold

    candidates = await conn.fetch(
        """
        SELECT fuseki_uri, normalized_text FROM entity_registry
        WHERE entity_type = $1
        """,
        entity_type,
    )
    best_uri = None
    best_score = 0.0

    for c in candidates:
        score = jaro_winkler_similarity(normalized, c["normalized_text"])
        if score >= threshold and score > best_score:
            if passes_token_overlap_check(normalized, c["normalized_text"], entity_type):
                best_score = score
                best_uri = c["fuseki_uri"]

    if best_uri:
        return best_uri, best_score, "related_to"

    if mode == "fuzzy":
        return None, 0.0, "unresolved"

    # --- Tier 2b: Semantic (embedding similarity) ---
    if not embed_fn:
        return None, 0.0, "unresolved"

    query_embedding = await embed_fn(normalized)
    if not query_embedding:
        return None, 0.0, "unresolved"

    semantic_threshold = schema.semantic_threshold

    # pgvector cosine distance: 1 - distance = similarity
    sem_row = await conn.fetchrow(
        """
        SELECT fuseki_uri, 1 - (embedding <=> $1::vector) AS similarity
        FROM entity_registry
        WHERE entity_type = $2 AND embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT 1
        """,
        str(query_embedding),
        entity_type,
    )
    if sem_row and sem_row["similarity"] >= semantic_threshold:
        return sem_row["fuseki_uri"], float(sem_row["similarity"]), "related_to"

    return None, 0.0, "unresolved"
