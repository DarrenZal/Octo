#!/usr/bin/env python3
"""
Personal KOI Ingest API

FastAPI server for ingesting pre-extracted entities from Claude Code.
Runs on port 8351 as part of the personal KOI-net.

This endpoint accepts entities already extracted by Claude (no LLM cost)
and performs:
1. Entity deduplication against the personal knowledge base
2. Canonical URI assignment
3. Storage in PostgreSQL with pgvector embeddings
4. Returns resolved entities with URIs for vault linking

Entity Resolution Tiers:
- Tier 1: Exact match (normalized text, B-Tree index)
- Tier 1.x: Fuzzy string match (Jaro-Winkler similarity)
- Tier 2: Semantic match (BGE embeddings + pgvector HNSW)
- Tier 3: Create new entity with deterministic URI
"""

import os
import re
import asyncio
import asyncpg
import hashlib
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
import uuid
from metaphone import doublemetaphone

# Import vault relationship parser
from api.vault_parser import (
    sync_vault_relationships,
    resolve_pending_relationships,
    get_entity_relationships,
    check_relationship_exists,
    SYMMETRIC_PREDICATES,
    PREDICATE_TO_FIELD,
)

# Import web fetcher
from api.web_fetcher import (
    fetch_and_preview,
    check_rate_limit,
    URLValidationError,
    generate_web_rid,
)

# Import schema loader
from api.entity_schema import (
    get_entity_schemas,
    get_schema_for_type,
    get_schema_version,
    reload_entity_schemas,
    get_first_significant_token,
    get_phonetic_enabled_types,
    type_to_folder,
    EntityTypeConfig,
)

# Import LLM extraction layer
from api.llm_enricher import (
    extract_from_content,
    describe_entities_batch,
    is_enrichment_available,
    ExtractionResult,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Personal KOI Ingest API",
    version="1.0.0",
    description="Ingests pre-extracted entities from Claude Code into personal knowledge base"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
DB_URL = os.getenv('POSTGRES_URL', 'postgresql://darrenzal:@localhost:5432/personal_koi')
KOI_MODE = os.getenv('KOI_MODE', 'personal')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-ada-002')
ENABLE_SEMANTIC_MATCHING = os.getenv('ENABLE_SEMANTIC_MATCHING', 'true').lower() == 'true'
KOI_NET_ENABLED = os.getenv('KOI_NET_ENABLED', 'false').lower() == 'true'
GITHUB_SENSOR_ENABLED = os.getenv('GITHUB_SENSOR_ENABLED', 'false').lower() == 'true'
WEB_SENSOR_ENABLED = os.getenv('WEB_SENSOR_ENABLED', 'false').lower() == 'true'
QUARTZ_BASE_URL = os.getenv('QUARTZ_BASE_URL', '').rstrip('/')

# DEPRECATED: These are now loaded from vault schemas via entity_schema.py
# Kept as fallback comments for reference
# SEMANTIC_THRESHOLDS = loaded from schema.semantic_threshold
# SIMILARITY_THRESHOLDS = loaded from schema.similarity_threshold

def make_quartz_url(entity_name: str, entity_type: str) -> Optional[str]:
    """Build a Quartz site URL for an entity page."""
    if not QUARTZ_BASE_URL:
        return None
    folder = type_to_folder(entity_type)
    slug = re.sub(r'[/\\]', '-', entity_name).replace(' ', '-')
    return f"{QUARTZ_BASE_URL}/{folder}/{slug}"

# Global connection pool
db_pool: Optional[asyncpg.Pool] = None
openai_available: bool = False
openai_client: Optional[Any] = None
github_sensor = None  # GitHubSensor instance (lazy import)
web_sensor = None  # WebSensor instance (lazy import)


# =============================================================================
# Pydantic Models
# =============================================================================

class ExtractedEntity(BaseModel):
    """Entity extracted by Claude Code"""
    name: str
    type: str  # Person, Organization, Location, Project, Concept
    mentions: List[str] = []
    confidence: float = 0.9
    context: Optional[str] = None
    # Per-entity context for resolution (merged with global context)
    associated_people: Optional[List[str]] = None
    associated_organizations: Optional[List[str]] = None


class ExtractedRelationship(BaseModel):
    """Relationship between entities"""
    subject: str
    predicate: str
    object: str
    confidence: float = 0.9


class ResolutionContext(BaseModel):
    """Context for entity resolution disambiguation"""
    associated_people: Optional[List[str]] = None
    project: Optional[str] = None           # Meeting project name for relationship matching
    organizations: Optional[List[str]] = None  # Mentioned organizations for relationship matching
    topics: Optional[List[str]] = None      # Topics for future use
    associated_orgs: Optional[List[str]] = None  # Deprecated: use organizations instead
    source_text: Optional[str] = None  # Reserved for future use


class IngestRequest(BaseModel):
    """Request to ingest extracted entities"""
    document_rid: str  # e.g., "vault:notes/salish-sea-herring"
    content: Optional[str] = None
    entities: List[ExtractedEntity]
    relationships: List[ExtractedRelationship] = []
    source: str = "obsidian-vault"
    context: Optional[ResolutionContext] = None  # For contextual entity resolution
    create_vault_notes: bool = False  # When true, create entity vault notes for new entities


class CanonicalEntity(BaseModel):
    """Resolved canonical entity"""
    name: str
    uri: str
    type: str
    is_new: bool
    merged_with: Optional[str] = None  # If deduplicated
    confidence: float = 1.0


class IngestResponse(BaseModel):
    """Response from ingest endpoint"""
    success: bool
    canonical_entities: List[CanonicalEntity]
    receipt_rid: str
    stats: Dict[str, int]


class RegisterEntityRequest(BaseModel):
    """Request to register a vault entity"""
    vault_rid: str  # e.g., "orn:obsidian.entity:Notes/Person/clare-attwell"
    vault_path: str  # e.g., "People/Clare Attwell.md"
    entity_type: str  # Person, Organization, etc.
    name: str
    properties: Dict[str, Any] = {}
    frontmatter: Optional[Dict[str, Any]] = None  # YAML frontmatter for relationship extraction
    content_hash: str


class RegisterEntityResponse(BaseModel):
    """Response from register-entity endpoint"""
    success: bool
    canonical_uri: str
    is_new: bool
    vault_rid: str
    merged_with: Optional[str] = None


class VaultEntityMapping(BaseModel):
    """Mapping between vault RID and canonical entity"""
    vault_rid: str
    vault_path: str
    canonical_uri: str
    entity_type: str
    name: str
    sync_status: str  # linked, local_only, pending_sync, conflict
    content_hash: str
    last_synced: str


class ResolveRequest(BaseModel):
    """Request to resolve an entity with optional context"""
    label: str
    type_hint: Optional[str] = None
    limit: int = 5
    context: Optional[ResolutionContext] = None


# =============================================================================
# OpenAI Embedding Service (same as production entity_resolver.py)
# =============================================================================

async def generate_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding using OpenAI API (same as production)"""
    if not openai_available or not ENABLE_SEMANTIC_MATCHING or not openai_client:
        return None

    try:
        # Normalize text before embedding (same as entity_resolver.py)
        normalized = normalize_entity_text(text)

        # Use asyncio.to_thread for sync OpenAI call
        response = await asyncio.to_thread(
            openai_client.embeddings.create,
            model=EMBEDDING_MODEL,
            input=normalized
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning(f"Error generating OpenAI embedding: {e}")
        return None


def check_openai_availability() -> bool:
    """Check if OpenAI API key is configured"""
    return bool(OPENAI_API_KEY)


# =============================================================================
# Entity Resolution
# =============================================================================

def normalize_entity_text(text: str) -> str:
    """Normalize entity text for comparison"""
    return (
        text.lower()
        .strip()
        .replace('_', ' ')
        .replace('-', ' ')
        .replace('  ', ' ')
        .lstrip('@')
    )


def normalize_alias(alias: Any) -> str:
    """
    Strip [[...]], lowercase, trim for alias matching.

    Handles wikilinks like [[People/Name|Display]] → name
    """
    alias = str(alias)  # Guard against non-string values
    alias = re.sub(r'\[\[([^\]|]+)(\|[^\]]+)?\]\]', r'\1', alias)  # Strip wikilinks
    # Extract just the name part if it's a path
    if '/' in alias:
        alias = alias.rsplit('/', 1)[-1]
    alias = alias.lower().strip()
    return alias


def get_phonetic_code(text: str) -> Optional[str]:
    """
    Get Double Metaphone code for first token of text.

    Uses first token only to handle cases like "Mihal" vs "Mehul Sangham"
    where full-name comparison would fail but first-token matches.
    """
    if not text:
        return None
    first_token = text.split()[0]
    codes = doublemetaphone(first_token)
    return codes[0] if codes[0] else codes[1]  # Primary or secondary


def phonetic_codes_match(code1: Optional[str], code2: Optional[str]) -> bool:
    """Check if two phonetic codes match (both must be non-empty)."""
    return bool(code1 and code2 and code1 == code2)


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calculate Jaro-Winkler similarity between two strings"""
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

    # Find matches
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

    # Count transpositions
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
        matches / len1 +
        matches / len2 +
        (matches - transpositions / 2) / matches
    ) / 3

    # Winkler adjustment (common prefix)
    prefix_len = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * 0.1 * (1 - jaro)


# DEPRECATED: Similarity thresholds now loaded from schema
# See entity_schema.py get_schema_for_type() for schema-driven thresholds

# Token overlap constants (not type-specific, just thresholds)
MIN_TOKEN_OVERLAP_RATIO = 0.5  # At least 50% of shorter entity's tokens must match
MIN_TOKEN_OVERLAP_COUNT = 2    # At least 2 tokens must match (for 2+ token entities)


def compute_token_overlap(text1: str, text2: str) -> Tuple[float, int]:
    """
    Compute token (word) overlap between two texts.

    Returns: (overlap_ratio, overlap_count)
    - overlap_ratio: proportion of shorter text's tokens found in longer text
    - overlap_count: number of matching tokens
    """
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())

    # Find intersection
    overlap = tokens1 & tokens2
    overlap_count = len(overlap)

    # Compute ratio based on shorter text
    shorter_len = min(len(tokens1), len(tokens2))
    if shorter_len == 0:
        return 0.0, 0

    overlap_ratio = overlap_count / shorter_len
    return overlap_ratio, overlap_count


def passes_token_overlap_check(text1: str, text2: str, entity_type: str) -> bool:
    """
    Check if two texts pass the token overlap requirement.

    For types with require_token_overlap=True in schema:
    - At least MIN_TOKEN_OVERLAP_RATIO of shorter text's tokens match
    - At least MIN_TOKEN_OVERLAP_COUNT tokens match (for multi-word entities)

    Types with require_token_overlap=False bypass this check.
    """
    # Get schema-driven config
    schema = get_schema_for_type(entity_type)
    if not schema.require_token_overlap:
        return True  # Schema says bypass this check

    overlap_ratio, overlap_count = compute_token_overlap(text1, text2)

    # For single-word entities, just use Jaro-Winkler
    tokens1 = text1.lower().split()
    tokens2 = text2.lower().split()
    if len(tokens1) == 1 or len(tokens2) == 1:
        return True

    # For multi-word entities, require token overlap
    if overlap_ratio < MIN_TOKEN_OVERLAP_RATIO:
        return False

    if overlap_count < MIN_TOKEN_OVERLAP_COUNT:
        return False

    return True


# =============================================================================
# Relationship-Aware Context Relevance
# =============================================================================

class RelevanceSignal(Enum):
    """Signal from relationship-based context relevance check."""
    POSITIVE = "positive"      # Has relevant relationship
    NEGATIVE = "negative"      # Candidate HAS relationships, but NONE are relevant
    UNKNOWN = "unknown"        # Candidate has no relationships (data incomplete)


@dataclass
class RelevanceResult:
    """Result of context relevance check."""
    signal: RelevanceSignal
    score: float
    details: str


# Predicates that connect people to projects (not affiliated_with which is person→org)
PROJECT_RELEVANCE_PREDICATES = ('involves_person', 'founded', 'has_founder', 'attended')


async def resolve_entity_to_uri(
    conn: asyncpg.Connection,
    entity_name: str,
    entity_type: Optional[str] = None
) -> Optional[str]:
    """
    Resolve an entity name to its canonical URI.

    Args:
        conn: Database connection
        entity_name: Entity name to resolve
        entity_type: Optional type filter

    Returns:
        Canonical URI or None if not found
    """
    normalized = normalize_entity_text(entity_name)
    if entity_type:
        return await conn.fetchval("""
            SELECT fuseki_uri FROM entity_registry
            WHERE normalized_text = $1 AND entity_type = $2
            LIMIT 1
        """, normalized, entity_type)
    else:
        return await conn.fetchval("""
            SELECT fuseki_uri FROM entity_registry
            WHERE normalized_text = $1
            LIMIT 1
        """, normalized)


async def check_context_relevance(
    conn: asyncpg.Connection,
    candidate_uri: str,
    context: ResolutionContext
) -> RelevanceResult:
    """
    Check if candidate has relationships relevant to the resolution context.

    Returns:
    - POSITIVE: Candidate is connected to project/orgs (boost score)
    - NEGATIVE: Candidate has relationships, but none are relevant (penalize)
    - UNKNOWN: Candidate has no relationships (no penalty - data incomplete)
    """
    # First, check if candidate has ANY relationships
    has_any_relationships = await conn.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM entity_relationships
            WHERE subject_uri = $1 OR object_uri = $1
        )
    """, candidate_uri)

    if not has_any_relationships:
        # No relationships = data incomplete, don't penalize
        return RelevanceResult(RelevanceSignal.UNKNOWN, 0.0, "no relationships in DB")

    # Check connection to meeting's project
    if context.project:
        project_uri = await resolve_entity_to_uri(conn, context.project, 'Project')
        if project_uri:
            connected = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM entity_relationships
                    WHERE ((subject_uri = $1 AND object_uri = $2)
                           OR (subject_uri = $2 AND object_uri = $1))
                    AND predicate = ANY($3)
                )
            """, candidate_uri, project_uri, list(PROJECT_RELEVANCE_PREDICATES))
            if connected:
                return RelevanceResult(RelevanceSignal.POSITIVE, 0.3, f"connected to project")

    # Check connection to mentioned organizations
    # Based on actual data format (verified from DB):
    #   - affiliated_with: Person (subj) → Org (obj)
    #   - has_founder: Person (subj) → Org (obj) - from org's founders: field (parser uses 'incoming' direction)
    #   - founded: Person (subj) → Org (obj) - from person's founder: field
    #   - involves_person: Org/Project (subj) → Person (obj)
    orgs = context.organizations or context.associated_orgs or []
    if orgs:
        for org_name in orgs:
            org_uri = await resolve_entity_to_uri(conn, org_name, 'Organization')
            if org_uri:
                connected = await conn.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM entity_relationships
                        WHERE (
                            -- person→org predicates (person is subject)
                            (subject_uri = $1 AND predicate IN ('affiliated_with', 'founded', 'has_founder') AND object_uri = $2)
                            -- org→person predicates (person is object)
                            OR (subject_uri = $2 AND predicate = 'involves_person' AND object_uri = $1)
                        )
                    )
                """, candidate_uri, org_uri)
                if connected:
                    return RelevanceResult(RelevanceSignal.POSITIVE, 0.2, f"affiliated with {org_name}")

    # Try 2-hop path for person → org → project chains
    # Path: Person -[has_founder]→ Org -[has_project]→ Project
    # Or: Project -[involves_person]→ Person (direct link to project)
    if context.project:
        project_uri = await resolve_entity_to_uri(conn, context.project, 'Project')
        if project_uri:
            # Check direct involves_person link first
            direct_project = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM entity_relationships
                    WHERE subject_uri = $2 AND predicate = 'involves_person' AND object_uri = $1
                )
            """, candidate_uri, project_uri)

            if direct_project:
                return RelevanceResult(
                    signal=RelevanceSignal.POSITIVE,
                    score=0.25,
                    details=f"member of project {context.project}"
                )

            # 2-hop: Person -[affiliation/founded/has_founder]→ Org -[has_project]→ Project
            # All person→org predicates: person is subject, org is object
            two_hop = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM entity_relationships er1
                    JOIN entity_relationships er2 ON er1.object_uri = er2.subject_uri
                    WHERE er1.subject_uri = $1
                      AND er1.predicate IN ('affiliated_with', 'founded', 'has_founder')
                      AND er2.predicate = 'has_project'
                      AND er2.object_uri = $2
                )
            """, candidate_uri, project_uri)

            if two_hop:
                return RelevanceResult(
                    signal=RelevanceSignal.POSITIVE,
                    score=0.1,
                    details=f"2-hop path via org to {context.project}"
                )

    # Candidate HAS relationships but NONE match context = negative signal
    return RelevanceResult(RelevanceSignal.NEGATIVE, -0.15, "has relationships, none relevant")


async def check_fallback_relevance(
    conn: asyncpg.Connection,
    candidate_uri: str,
    context: ResolutionContext
) -> float:
    """
    Fallback: Use document_entity_links when relationships are sparse.

    If candidate appears in same documents as context entities, that's a weak positive signal.
    """
    if not context.associated_people:
        return 0.0

    # Check if candidate co-occurs with associated people in documents
    people_uris = []
    for person in context.associated_people:
        uri = await resolve_entity_to_uri(conn, person, 'Person')
        if uri:
            people_uris.append(uri)

    if not people_uris:
        return 0.0

    # Count shared documents
    shared_docs = await conn.fetchval("""
        SELECT COUNT(DISTINCT d1.document_rid)
        FROM document_entity_links d1
        JOIN document_entity_links d2 ON d1.document_rid = d2.document_rid
        WHERE d1.entity_uri = $1
        AND d2.entity_uri = ANY($2)
    """, candidate_uri, people_uris)

    if shared_docs and shared_docs > 0:
        return min(shared_docs * 0.05, 0.15)  # Cap at 0.15

    return 0.0


async def resolve_entity(
    conn: asyncpg.Connection,
    entity: ExtractedEntity,
    context: Optional[ResolutionContext] = None
) -> Tuple[CanonicalEntity, bool]:
    """
    Resolve an entity against the knowledge base.

    Resolution Tiers:
    - Tier 1: Exact match (normalized text)
    - Tier 1.5: Contextual co-occurrence match (all entity types with phonetic boost for Person)
    - Tier 2a: Fuzzy match (Jaro-Winkler with token overlap check)
    - Tier 2b: Semantic match (OpenAI embeddings + pgvector)
    - Tier 3: Create new entity

    Args:
        conn: Database connection
        entity: The entity to resolve
        context: Optional disambiguation context (associated_people)

    Returns: (CanonicalEntity, is_new)
    """
    normalized = normalize_entity_text(entity.name)

    # Get schema-driven config for this entity type
    schema = get_schema_for_type(entity.type)
    threshold = schema.similarity_threshold

    # Tier 1: Exact match (normalized text)
    if entity.type:
        exact_match = await conn.fetchrow("""
            SELECT id, fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
            WHERE normalized_text = $1
            AND entity_type = $2
            LIMIT 1
        """, normalized, entity.type)
    else:
        exact_match = await conn.fetchrow("""
            SELECT id, fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
            WHERE normalized_text = $1
            LIMIT 1
        """, normalized)

    if exact_match:
        return CanonicalEntity(
            name=exact_match['entity_text'],
            uri=exact_match['fuseki_uri'],
            type=exact_match['entity_type'] or entity.type,
            is_new=False,
            merged_with=entity.name if exact_match['entity_text'] != entity.name else None,
            confidence=1.0
        ), False

    # Tier 1.1: Alias match (check if input matches any registered alias)
    # Uses normalized name to search against TEXT[] aliases column
    normalized_name = normalize_alias(entity.name)

    if entity.type:
        alias_match = await conn.fetchrow("""
            SELECT fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
            WHERE entity_type = $1
            AND $2 = ANY(aliases)
            LIMIT 1
        """, entity.type, normalized_name)
    else:
        # Type-agnostic alias lookup (when type_hint not provided)
        # Risk: may return wrong entity if alias is reused across types
        logger.warning(f"Type-agnostic alias lookup for '{entity.name}' - consider providing type_hint")
        alias_match = await conn.fetchrow("""
            SELECT fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
            WHERE $1 = ANY(aliases)
            LIMIT 1
        """, normalized_name)

    if alias_match:
        # Alias match = Tier-1 exact (short-circuit, don't enter contextual pool)
        logger.info(f"Tier 1.1 alias match: '{entity.name}' → '{alias_match['entity_text']}'")
        return CanonicalEntity(
            name=alias_match["entity_text"],
            uri=alias_match["fuseki_uri"],
            type=alias_match["entity_type"] or entity.type,
            is_new=False,
            merged_with=entity.name if alias_match["entity_text"] != entity.name else None,
            confidence=1.0,
        ), False

    # Tier 1.5: Contextual co-occurrence match (ALL entity types, with phonetic boost)
    # Requirements:
    # - min_context_people from schema (default: Person=1, others=2)
    # - Two-tier threshold:
    #   - With phonetic match: combined_score ≥0.6 (phonetic is strong evidence)
    #   - Without phonetic match: combined_score ≥0.75 (stricter to avoid false positives)
    if context and context.associated_people:
        min_people = schema.min_context_people

        if len(context.associated_people) >= min_people:
            logger.info(f"Tier 1.5: Trying contextual match for '{entity.name}' ({entity.type}) "
                       f"with {len(context.associated_people)} associated people")

            contextual_candidates = await get_contextual_entity_candidates(
                conn,
                entity.name,
                entity.type,
                context.associated_people,
                context  # Pass full context for relationship checking
            )

            if contextual_candidates:
                best = contextual_candidates[0]
                has_phonetic = best.get('phonetic_match', False)

                # Two-tier threshold: phonetic matches get lower bar (strong evidence)
                # Non-phonetic matches need higher score to avoid false positives
                threshold_phonetic = 0.6      # "Quoxala" -> "Kwaxala" (same sound)
                threshold_no_phonetic = 0.75  # Stricter: avoid "Miranda" -> "Mehul Sangham"

                effective_threshold = threshold_phonetic if has_phonetic else threshold_no_phonetic

                if best["combined_score"] >= effective_threshold:
                    logger.info(f"Tier 1.5 contextual match: '{entity.name}' -> '{best['name']}' "
                               f"(combined_score: {best['combined_score']:.3f}, "
                               f"phonetic: {has_phonetic}, threshold: {effective_threshold})")
                    return CanonicalEntity(
                        name=best["name"],
                        uri=best["uri"],
                        type=best.get("entity_type") or entity.type,
                        is_new=False,
                        merged_with=entity.name if best["name"] != entity.name else None,
                        confidence=best["combined_score"]  # Always 0-1 scale
                    ), False
                else:
                    logger.info(f"Tier 1.5 contextual match REJECTED: '{entity.name}' -> '{best['name']}' "
                               f"(score: {best['combined_score']:.3f} < threshold: {effective_threshold}, "
                               f"phonetic: {has_phonetic})")

    # Tier 2a: Fuzzy match (Jaro-Winkler with token overlap check)
    if entity.type:
        candidates = await conn.fetch("""
            SELECT id, fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
            WHERE entity_type = $1
        """, entity.type)
    else:
        candidates = await conn.fetch("""
            SELECT id, fuseki_uri, entity_text, entity_type, normalized_text
            FROM entity_registry
        """)

    best_match = None
    best_score = 0.0

    for candidate in candidates:
        score = jaro_winkler_similarity(normalized, candidate['normalized_text'])
        if score >= threshold and score > best_score:
            # Additional check: token overlap for Organization/Project/Concept
            overlap_ratio, overlap_count = compute_token_overlap(normalized, candidate['normalized_text'])
            logger.info(f"Fuzzy candidate: {entity.name} vs {candidate['entity_text']} | JW={score:.3f} | overlap={overlap_count} ({overlap_ratio:.2f})")
            if not passes_token_overlap_check(normalized, candidate['normalized_text'], entity.type):
                logger.info(f"Fuzzy match REJECTED due to low token overlap: {entity.name} vs {candidate['entity_text']}")
                continue
            best_score = score
            best_match = candidate

    if best_match:
        return CanonicalEntity(
            name=best_match['entity_text'],
            uri=best_match['fuseki_uri'],
            type=best_match['entity_type'] or entity.type,
            is_new=False,
            merged_with=entity.name if best_match['entity_text'] != entity.name else None,
            confidence=best_score
        ), False

    # Tier 2b: Semantic match (OpenAI embeddings + pgvector)
    if openai_available and ENABLE_SEMANTIC_MATCHING:
        embedding = await generate_embedding(entity.name)
        if embedding:
            semantic_threshold = schema.semantic_threshold

            # Query for semantic matches using pgvector cosine similarity
            if entity.type:
                semantic_match = await conn.fetchrow("""
                    SELECT id, fuseki_uri, entity_text, entity_type,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM entity_registry
                    WHERE embedding IS NOT NULL
                      AND entity_type = $2
                      AND 1 - (embedding <=> $1::vector) > $3
                    ORDER BY similarity DESC
                    LIMIT 1
                """, str(embedding), entity.type, semantic_threshold)
            else:
                semantic_match = await conn.fetchrow("""
                    SELECT id, fuseki_uri, entity_text, entity_type,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM entity_registry
                    WHERE embedding IS NOT NULL
                      AND 1 - (embedding <=> $1::vector) > $2
                    ORDER BY similarity DESC
                    LIMIT 1
                """, str(embedding), semantic_threshold)

            if semantic_match:
                logger.info(f"Tier 2b semantic match: '{entity.name}' -> '{semantic_match['entity_text']}' "
                           f"(similarity: {semantic_match['similarity']:.3f})")
                return CanonicalEntity(
                    name=semantic_match['entity_text'],
                    uri=semantic_match['fuseki_uri'],
                    type=semantic_match['entity_type'] or entity.type,
                    is_new=False,
                    merged_with=entity.name if semantic_match['entity_text'] != entity.name else None,
                    confidence=float(semantic_match['similarity'])
                ), False

    # Tier 3: Create new entity
    new_uri = generate_entity_uri(entity.name, entity.type)

    return CanonicalEntity(
        name=entity.name,
        uri=new_uri,
        type=entity.type,
        is_new=True,
        confidence=entity.confidence
    ), True


def generate_entity_uri(name: str, entity_type: str) -> str:
    """Generate a deterministic URI for a new entity"""
    normalized = normalize_entity_text(name)
    # Create a stable hash-based ID
    hash_input = f"{entity_type}:{normalized}"
    hash_id = hashlib.sha256(hash_input.encode()).hexdigest()[:12]

    type_prefix = entity_type.lower()
    safe_name = normalized.replace(' ', '-').replace("'", '')[:50]

    return f"orn:personal-koi.entity:{type_prefix}-{safe_name}-{hash_id}"


async def store_new_entity(
    conn: asyncpg.Connection,
    entity: ExtractedEntity,
    canonical: CanonicalEntity,
    document_rid: str
) -> None:
    """Store a new entity in the registry with embedding and phonetic code"""
    normalized = normalize_entity_text(entity.name)

    import json as json_module
    metadata = json_module.dumps({
        'mentions': entity.mentions,
        'context': entity.context,
        'confidence': entity.confidence
    })

    # Generate embedding for new entity (enables future Tier 2 matching)
    embedding = None
    if openai_available and ENABLE_SEMANTIC_MATCHING:
        embedding = await generate_embedding(entity.name)
        if embedding:
            logger.info(f"Generated embedding for new entity: {entity.name}")

    # Compute phonetic code for types with phonetic_matching enabled (schema-driven)
    phonetic_code = None
    schema = get_schema_for_type(entity.type)
    if schema.phonetic_matching:
        # Use first significant token (skip stopwords)
        first_token = get_first_significant_token(normalized, schema.phonetic_stopwords)
        phonetic_code = get_phonetic_code(first_token)
        if phonetic_code:
            logger.info(f"Generated phonetic code for new {entity.type}: {entity.name} -> {phonetic_code}")

    # Use context as description (when populated by LLM extraction layer)
    description = entity.context if entity.context else None

    if embedding:
        await conn.execute("""
            INSERT INTO entity_registry (
                fuseki_uri, entity_text, entity_type, normalized_text,
                source, first_seen_rid, metadata, embedding, phonetic_code, description
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::vector, $9, $10)
            ON CONFLICT (fuseki_uri) DO NOTHING
        """,
            canonical.uri,
            entity.name,
            entity.type,
            normalized,
            'personal-vault',
            document_rid,
            metadata,
            str(embedding),
            phonetic_code,
            description
        )
    else:
        await conn.execute("""
            INSERT INTO entity_registry (
                fuseki_uri, entity_text, entity_type, normalized_text,
                source, first_seen_rid, metadata, phonetic_code, description
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
            ON CONFLICT (fuseki_uri) DO NOTHING
        """,
            canonical.uri,
            entity.name,
            entity.type,
            normalized,
            'personal-vault',
            document_rid,
            metadata,
            phonetic_code,
            description
        )


# =============================================================================
# API Endpoints
# =============================================================================

@app.on_event("startup")
async def startup():
    """Initialize database connection pool and OpenAI client"""
    global db_pool, openai_available, openai_client
    try:
        db_pool = await asyncpg.create_pool(
            DB_URL,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info(f"Connected to database (mode: {KOI_MODE})")

        # Ensure schema exists
        async with db_pool.acquire() as conn:
            await ensure_schema(conn)

        # Mount KOI-net protocol router if enabled
        if KOI_NET_ENABLED:
            try:
                from api.koi_net_router import koi_net_router, setup_koi_net
                app.include_router(koi_net_router, prefix="/koi-net")
                await setup_koi_net(db_pool)
                logger.info("KOI-net protocol endpoints mounted at /koi-net/")
            except Exception as e:
                logger.error(f"Failed to initialize KOI-net: {e}")

        # Initialize OpenAI client if API key is available
        openai_available = check_openai_availability()
        if openai_available:
            try:
                from openai import OpenAI
                openai_client = OpenAI(api_key=OPENAI_API_KEY)
                logger.info(f"OpenAI client initialized (model: {EMBEDDING_MODEL})")
                logger.info("Tier 2 semantic matching: ENABLED")
            except ImportError:
                logger.warning("OpenAI package not installed. Run: pip install openai")
                openai_available = False
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
                openai_available = False
        else:
            logger.warning("OPENAI_API_KEY not set")
            logger.info("Tier 2 semantic matching: DISABLED (falling back to fuzzy matching)")

        # Initialize GitHub sensor if enabled
        if GITHUB_SENSOR_ENABLED:
            try:
                global github_sensor
                from api.github_sensor import GitHubSensor
                # Get event queue if KOI-net is available
                event_queue = None
                if KOI_NET_ENABLED:
                    try:
                        from api.koi_net_router import _event_queue
                        event_queue = _event_queue
                    except Exception:
                        pass
                github_sensor = GitHubSensor(db_pool, event_queue=event_queue)
                github_sensor._embed_fn = generate_embedding
                await github_sensor.start()
                logger.info("GitHub sensor: ENABLED")
            except Exception as e:
                logger.error(f"Failed to initialize GitHub sensor: {e}")

        # Initialize Web sensor if enabled
        if WEB_SENSOR_ENABLED:
            try:
                global web_sensor
                from api.web_sensor import WebSensor
                web_sensor = WebSensor(db_pool, event_queue=event_queue)
                await web_sensor.start()
                logger.info("Web sensor: ENABLED")
            except Exception as e:
                logger.error(f"Failed to initialize Web sensor: {e}")

    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise


@app.on_event("shutdown")
async def shutdown():
    """Stop background tasks and close database connection pool"""
    global db_pool, github_sensor, web_sensor
    if github_sensor:
        try:
            await github_sensor.stop()
        except Exception as e:
            logger.warning(f"GitHub sensor shutdown error: {e}")
    if web_sensor:
        try:
            await web_sensor.stop()
        except Exception as e:
            logger.warning(f"Web sensor shutdown error: {e}")
    if KOI_NET_ENABLED:
        try:
            from api.koi_net_router import shutdown_koi_net
            await shutdown_koi_net()
        except Exception as e:
            logger.warning(f"KOI-net shutdown error: {e}")
    if db_pool:
        await db_pool.close()


async def ensure_schema(conn: asyncpg.Connection):
    """Ensure the entity_registry table exists"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_registry (
            id SERIAL PRIMARY KEY,
            fuseki_uri TEXT UNIQUE NOT NULL,
            entity_text TEXT NOT NULL,
            entity_type TEXT,
            normalized_text TEXT NOT NULL,
            ledger_id TEXT,
            metadata_iri TEXT,
            admin_address TEXT,
            aliases TEXT[],
            jurisdiction TEXT,
            class_id TEXT,
            source TEXT DEFAULT 'personal-vault',
            first_seen_rid TEXT,
            phonetic_code TEXT,
            vault_rid TEXT,
            koi_rid TEXT,
            metadata JSONB,
            embedding vector(1536),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Create index on normalized_text for fast lookups
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_registry_normalized
        ON entity_registry(normalized_text)
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_entity_registry_type
        ON entity_registry(entity_type)
    """)

    # Create document_entity_links table
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS document_entity_links (
            id SERIAL PRIMARY KEY,
            document_rid TEXT NOT NULL,
            entity_uri TEXT NOT NULL,
            mention_count INT DEFAULT 1,
            context TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(document_rid, entity_uri)
        )
    """)

    # Create entity_rid_mappings table for vault entity registration
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_rid_mappings (
            id SERIAL PRIMARY KEY,
            vault_rid TEXT UNIQUE NOT NULL,
            vault_path TEXT NOT NULL,
            canonical_uri TEXT NOT NULL,
            entity_type TEXT,
            name TEXT,
            content_hash TEXT,
            sync_status TEXT DEFAULT 'linked',
            last_synced TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT valid_sync_status CHECK (
                sync_status IN ('linked', 'local_only', 'pending_sync', 'conflict')
            )
        )
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rid_mappings_canonical
        ON entity_rid_mappings(canonical_uri)
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rid_mappings_vault_path
        ON entity_rid_mappings(vault_path)
    """)

    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rid_mappings_sync_status
        ON entity_rid_mappings(sync_status)
    """)

    # Add vault_rid column to entity_registry if not exists
    try:
        await conn.execute("""
            ALTER TABLE entity_registry
            ADD COLUMN IF NOT EXISTS vault_rid TEXT
        """)
    except Exception:
        pass  # Column may already exist

    # ==========================================================================
    # Entity Relationships Tables (for relationship-aware entity resolution)
    # ==========================================================================

    # Enable pg_trgm extension for fuzzy matching in pending resolution
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Predicate allow-list (must be created first - FK target)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS allowed_predicates (
            predicate TEXT PRIMARY KEY,
            description TEXT,
            subject_types TEXT[],
            object_types TEXT[]
        )
    """)

    # Seed with canonical predicates (idempotent)
    await conn.execute("""
        INSERT INTO allowed_predicates (predicate, description, subject_types, object_types) VALUES
            ('affiliated_with', 'Person belongs to organization', ARRAY['Person'], ARRAY['Organization']),
            ('founded', 'Person founded org/project', ARRAY['Person'], ARRAY['Organization', 'Project']),
            ('has_founder', 'Org/project was founded by', ARRAY['Organization', 'Project'], ARRAY['Person']),
            ('knows', 'Person knows person (symmetric)', ARRAY['Person'], ARRAY['Person']),
            ('collaborates_with', 'Person collaborates with person (symmetric)', ARRAY['Person'], ARRAY['Person']),
            ('involves_person', 'Project involves person', ARRAY['Project', 'Meeting'], ARRAY['Person']),
            ('involves_organization', 'Project involves organization', ARRAY['Project'], ARRAY['Organization']),
            ('has_project', 'Organization has project', ARRAY['Organization'], ARRAY['Project']),
            ('attended', 'Person attended meeting', ARRAY['Person'], ARRAY['Meeting']),
            ('located_in', 'Entity is located in place', NULL, ARRAY['Location'])
        ON CONFLICT (predicate) DO NOTHING
    """)

    # Entity relationships table (resolved relationships)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_relationships (
            id SERIAL PRIMARY KEY,
            subject_uri TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_uri TEXT NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            source TEXT DEFAULT 'vault',
            source_rid TEXT,
            source_field TEXT,
            raw_value TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(subject_uri, predicate, object_uri),
            CHECK (subject_uri != object_uri),
            CHECK (predicate ~ '^[a-z][a-z0-9_]*$')
        )
    """)

    # Add FK constraints if they don't exist (ignore errors if already exist)
    try:
        await conn.execute("""
            ALTER TABLE entity_relationships
            ADD CONSTRAINT fk_rel_predicate FOREIGN KEY (predicate)
                REFERENCES allowed_predicates(predicate)
        """)
    except Exception:
        pass

    try:
        await conn.execute("""
            ALTER TABLE entity_relationships
            ADD CONSTRAINT fk_rel_subject FOREIGN KEY (subject_uri)
                REFERENCES entity_registry(fuseki_uri) ON DELETE CASCADE
        """)
    except Exception:
        pass

    try:
        await conn.execute("""
            ALTER TABLE entity_relationships
            ADD CONSTRAINT fk_rel_object FOREIGN KEY (object_uri)
                REFERENCES entity_registry(fuseki_uri) ON DELETE CASCADE
        """)
    except Exception:
        pass

    # Pending relationships table (unresolved targets)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_relationships (
            id SERIAL PRIMARY KEY,
            subject_uri TEXT,
            object_uri TEXT,
            predicate TEXT NOT NULL,
            raw_unknown_label TEXT NOT NULL,
            unknown_side TEXT NOT NULL CHECK (unknown_side IN ('subject', 'object')),
            target_type_hint TEXT,
            source TEXT DEFAULT 'vault',
            source_rid TEXT,
            source_field TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            CHECK ((subject_uri IS NOT NULL AND object_uri IS NULL) OR
                   (subject_uri IS NULL AND object_uri IS NOT NULL)),
            CHECK (
                (unknown_side = 'subject' AND subject_uri IS NULL AND object_uri IS NOT NULL) OR
                (unknown_side = 'object' AND object_uri IS NULL AND subject_uri IS NOT NULL)
            )
        )
    """)

    # Add unique index for pending edges (expression index)
    try:
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique_edge
            ON pending_relationships (
                COALESCE(subject_uri, ''),
                COALESCE(object_uri, ''),
                predicate,
                raw_unknown_label,
                unknown_side
            )
        """)
    except Exception:
        pass

    # Add FK constraints for pending
    try:
        await conn.execute("""
            ALTER TABLE pending_relationships
            ADD CONSTRAINT fk_pending_predicate FOREIGN KEY (predicate)
                REFERENCES allowed_predicates(predicate)
        """)
    except Exception:
        pass

    try:
        await conn.execute("""
            ALTER TABLE pending_relationships
            ADD CONSTRAINT fk_pending_subject FOREIGN KEY (subject_uri)
                REFERENCES entity_registry(fuseki_uri) ON DELETE CASCADE
        """)
    except Exception:
        pass

    try:
        await conn.execute("""
            ALTER TABLE pending_relationships
            ADD CONSTRAINT fk_pending_object FOREIGN KEY (object_uri)
                REFERENCES entity_registry(fuseki_uri) ON DELETE CASCADE
        """)
    except Exception:
        pass

    # Indexes for entity_relationships
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_subject ON entity_relationships(subject_uri)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_object ON entity_relationships(object_uri)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_subject_predicate ON entity_relationships(subject_uri, predicate)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_object_predicate ON entity_relationships(object_uri, predicate)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_source_rid ON entity_relationships(source_rid)")

    # Indexes for pending_relationships
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_unknown_label ON pending_relationships(raw_unknown_label)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_source_rid ON pending_relationships(source_rid)")

    # GIN trigram index for fuzzy matching
    try:
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_unknown_label_trgm
            ON pending_relationships USING GIN (raw_unknown_label gin_trgm_ops)
        """)
    except Exception:
        pass  # May fail if pg_trgm extension not available

    # ==========================================================================
    # Web Submissions Table (URL ingestion pipeline)
    # ==========================================================================
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS web_submissions (
            id SERIAL PRIMARY KEY,
            url TEXT NOT NULL,
            rid TEXT NOT NULL,
            domain TEXT NOT NULL,
            submitted_by TEXT,
            submitted_via TEXT DEFAULT 'telegram',
            submission_message TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            relevance_score FLOAT,
            relevance_reasoning TEXT,
            bioregional_tags TEXT[],
            title TEXT,
            description TEXT,
            content_hash TEXT,
            word_count INT,
            matching_entities JSONB DEFAULT '[]'::jsonb,
            ingested_entities JSONB DEFAULT '[]'::jsonb,
            vault_note_path TEXT,
            fetched_at TIMESTAMPTZ,
            evaluated_at TIMESTAMPTZ,
            ingested_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT valid_web_status CHECK (
                status IN ('pending', 'previewed', 'evaluated', 'ingested', 'rejected', 'error')
            )
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_web_submissions_created_at ON web_submissions(created_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_web_submissions_user_created ON web_submissions(submitted_by, created_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_web_submissions_url ON web_submissions(url)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_web_submissions_status ON web_submissions(status)")

    # ==========================================================================
    # GitHub Sensor Tables (Phase 5.7)
    # ==========================================================================
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS github_repos (
            id SERIAL PRIMARY KEY,
            repo_url TEXT NOT NULL UNIQUE,
            repo_name TEXT NOT NULL,
            branch TEXT DEFAULT 'main',
            clone_path TEXT,
            last_commit_sha TEXT,
            last_scan_at TIMESTAMPTZ,
            file_count INT DEFAULT 0,
            code_entity_count INT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'active',
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS github_file_state (
            id SERIAL PRIMARY KEY,
            repo_id INT REFERENCES github_repos(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            rid TEXT NOT NULL,
            vault_note_path TEXT,
            line_count INT,
            byte_size INT,
            file_type TEXT,
            last_commit_sha TEXT,
            last_commit_author TEXT,
            last_commit_date TIMESTAMPTZ,
            last_commit_message TEXT,
            entity_count INT DEFAULT 0,
            code_entity_count INT DEFAULT 0,
            scanned_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(repo_id, file_path)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS koi_code_artifacts (
            id SERIAL PRIMARY KEY,
            code_uri TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL,
            repo_key TEXT NOT NULL,
            file_path TEXT NOT NULL,
            symbol TEXT,
            language TEXT,
            signature TEXT,
            docstring TEXT,
            line_start INT,
            line_end INT,
            commit_sha TEXT,
            extraction_run_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_code_artifacts_repo ON koi_code_artifacts(repo_key)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_code_artifacts_kind ON koi_code_artifacts(kind)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_code_artifacts_file ON koi_code_artifacts(file_path)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_code_artifacts_symbol ON koi_code_artifacts(symbol)")

    # =========================================================================
    # KOI Memories + Chunks (RAG storage for documents)
    # =========================================================================

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS koi_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rid VARCHAR(500) NOT NULL,
            version INTEGER DEFAULT 1,
            event_type VARCHAR(20) NOT NULL DEFAULT 'NEW',
            source_sensor VARCHAR(200) NOT NULL,
            content JSONB NOT NULL,
            metadata JSONB DEFAULT '{}',
            superseded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(rid, version)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_koi_memories_rid ON koi_memories(rid)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_koi_memories_source ON koi_memories(source_sensor)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_koi_memories_created ON koi_memories(created_at DESC)")

    # Unique constraint on rid for FK references
    try:
        await conn.execute("ALTER TABLE koi_memories ADD CONSTRAINT koi_memories_rid_key UNIQUE (rid)")
    except Exception:
        pass  # Already exists

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS koi_embeddings (
            id SERIAL PRIMARY KEY,
            memory_id UUID NOT NULL REFERENCES koi_memories(id) ON DELETE CASCADE,
            dim_1536 vector(1536),
            dim_1024 vector(1024),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(memory_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS koi_memory_chunks (
            id SERIAL PRIMARY KEY,
            chunk_rid VARCHAR UNIQUE NOT NULL,
            document_rid VARCHAR NOT NULL REFERENCES koi_memories(rid) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            total_chunks INTEGER NOT NULL,
            content JSONB NOT NULL,
            embedding vector(1536),
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON koi_memory_chunks(document_rid)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_created ON koi_memory_chunks(created_at DESC)")

    logger.info("Schema verified/created (including relationship + GitHub + RAG tables)")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

        # Get loaded entity types from schema
        schemas = get_entity_schemas()
        entity_types = list(schemas.keys())

        return {
            "status": "healthy",
            "mode": KOI_MODE,
            "database": "connected",
            "openai_available": openai_available,
            "embedding_model": EMBEDDING_MODEL if openai_available else None,
            "semantic_matching": openai_available and ENABLE_SEMANTIC_MATCHING,
            "entity_types": entity_types,
            "schema_version": get_schema_version(),
            "github_sensor": GITHUB_SENSOR_ENABLED and github_sensor is not None,
            "web_sensor": WEB_SENSOR_ENABLED and web_sensor is not None,
            "llm_enrichment": is_enrichment_available(),
            "resolution_tiers": {
                "tier1_exact": True,
                "tier1x_fuzzy": True,
                "tier15_contextual": True,
                "tier2_semantic": openai_available and ENABLE_SEMANTIC_MATCHING,
                "tier3_create": True
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/entity-types")
async def get_entity_types_endpoint():
    """
    Return entity type configs for MCP and external tools.

    This is the source of truth for entity type configuration.
    MCP and other clients should call this endpoint instead of
    maintaining their own hardcoded type mappings.

    Returns:
        version: Schema version hash for cache invalidation
        types: List of entity type configurations
    """
    schemas = get_entity_schemas()
    return {
        "version": get_schema_version(),
        "types": [
            {
                "type_key": s.type_key,
                "label": s.label,
                "folder": s.folder,
                "phonetic_matching": s.phonetic_matching,
                "min_context_people": s.min_context_people,
                "similarity_threshold": s.similarity_threshold,
                "semantic_threshold": s.semantic_threshold,
                "require_token_overlap": s.require_token_overlap,
            }
            for s in schemas.values()
        ]
    }


@app.post("/reload-schemas")
async def reload_schemas_endpoint(vault_path: Optional[str] = None):
    """
    Hot reload entity schemas from vault without restart.

    This endpoint reloads schemas from the vault Ontology/ folder.
    Use after adding or modifying schema files.

    Args:
        vault_path: Optional override for vault path (default: ~/Documents/Notes)

    Returns:
        version: New schema version hash
        types: Updated list of entity type keys
        phonetic_enabled: Types with phonetic matching enabled
    """
    schemas = reload_entity_schemas(vault_path)
    return {
        "success": True,
        "version": get_schema_version(),
        "types": list(schemas.keys()),
        "phonetic_enabled": get_phonetic_enabled_types(),
        "count": len(schemas)
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest_extraction(request: IngestRequest):
    """
    Ingest pre-extracted entities from Claude Code.

    This endpoint:
    1. Deduplicates entities against the personal KB
    2. Assigns canonical URIs to new entities
    3. Stores entities and document links
    4. Returns resolved entities for vault linking
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    canonical_entities: List[CanonicalEntity] = []
    new_count = 0
    resolved_count = 0

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            for entity in request.entities:
                try:
                    logger.info(f"Processing entity: {entity.name} ({entity.type})")

                    # Build context for this entity, merging global + per-entity (with deduplication)
                    global_people = request.context.associated_people if request.context else []
                    entity_people = entity.associated_people or []
                    global_orgs = request.context.organizations if request.context else []
                    entity_orgs = entity.associated_organizations or []

                    context_for_entity = ResolutionContext(
                        associated_people=list(set((global_people or []) + entity_people)),
                        organizations=list(set((global_orgs or []) + entity_orgs)),
                        project=request.context.project if request.context else None,
                        topics=request.context.topics if request.context else []
                    ) if (global_people or entity_people or global_orgs or entity_orgs or
                          (request.context and request.context.project)) else request.context

                    canonical, is_new = await resolve_entity(conn, entity, context_for_entity)
                    logger.info(f"Resolved: {canonical.name} -> {canonical.uri} (new={is_new})")
                    canonical_entities.append(canonical)

                    if is_new:
                        new_count += 1
                        await store_new_entity(conn, entity, canonical, request.document_rid)
                        logger.info(f"Stored new entity: {canonical.uri}")
                    else:
                        resolved_count += 1
                        logger.info(f"Resolved to existing: {canonical.uri}")

                    # Link entity to document
                    await conn.execute("""
                        INSERT INTO document_entity_links (document_rid, entity_uri, context)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (document_rid, entity_uri)
                        DO UPDATE SET mention_count = document_entity_links.mention_count + 1
                    """, request.document_rid, canonical.uri, entity.context)
                    logger.info(f"Linked entity to document")

                except Exception as e:
                    import traceback
                    logger.error(f"Error processing entity {entity.name}: {e}")
                    logger.error(traceback.format_exc())
                    # Continue with other entities

    # Create vault notes for new entities if requested
    if request.create_vault_notes:
        async with db_pool.acquire() as conn:
            for entity, canonical in zip(request.entities, canonical_entities):
                if canonical.is_new:
                    await _generate_entity_vault_note(
                        conn, canonical.name, canonical.type, canonical.uri,
                        description=entity.context,
                    )

    # Generate receipt RID
    receipt_rid = f"orn:personal-koi.receipt:{uuid.uuid4().hex[:16]}"

    return IngestResponse(
        success=True,
        canonical_entities=canonical_entities,
        receipt_rid=receipt_rid,
        stats={
            "entities_processed": len(request.entities),
            "new_entities": new_count,
            "resolved_entities": resolved_count,
            "relationships_processed": len(request.relationships)
        }
    )


@app.get("/entities")
async def list_entities(
    entity_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """List entities in the knowledge base"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        if entity_type:
            entities = await conn.fetch("""
                SELECT fuseki_uri, entity_text, entity_type, source, created_at
                FROM entity_registry
                WHERE entity_type = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, entity_type, limit, offset)
        else:
            entities = await conn.fetch("""
                SELECT fuseki_uri, entity_text, entity_type, source, created_at
                FROM entity_registry
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """, limit, offset)

        return {
            "entities": [dict(e) for e in entities],
            "count": len(entities),
            "limit": limit,
            "offset": offset
        }


@app.get("/entity/resolve")
async def resolve_entity_get(
    label: str,
    type_hint: Optional[str] = None,
    limit: int = 5
):
    """
    Resolve an entity label to canonical entity (GET - backward compatible).

    Query Parameters:
        label: Entity name to resolve
        type_hint: Optional entity type filter
        limit: Maximum candidates (default 5)

    Returns candidates with URIs and confidence scores.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    entity = ExtractedEntity(name=label, type=type_hint or "")
    async with db_pool.acquire() as conn:
        canonical, is_new = await resolve_entity(conn, entity, context=None)

    if canonical is None:
        return {"candidates": [], "is_new": False}

    return {
        "candidates": [{
            "name": canonical.name,
            "uri": canonical.uri,
            "type": canonical.type,
            "confidence": canonical.confidence,
            "merged_with": canonical.merged_with
        }],
        "is_new": is_new
    }


@app.post("/entity/resolve")
async def resolve_entity_post(request: ResolveRequest):
    """
    Resolve an entity label to canonical entity with optional context (POST).

    Request Body:
        label: Entity name to resolve
        type_hint: Optional entity type filter
        limit: Maximum candidates (default 5)
        context: Optional disambiguation context
            - associated_people: List of people co-occurring with this entity

    The context parameter enables Tier 1.5 contextual matching, which uses
    co-occurrence in documents to disambiguate entities. For example:
    - "Biocene Labs" with associated_people=["Shawn Anderson", "Darren Zal"]
      may resolve to "Symbiocene Labs" if those people appear together in
      documents mentioning Symbiocene Labs.

    Returns candidates with URIs and confidence scores (same format as GET).
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    entity = ExtractedEntity(name=request.label, type=request.type_hint or "")
    async with db_pool.acquire() as conn:
        canonical, is_new = await resolve_entity(conn, entity, request.context)

    if canonical is None:
        return {"candidates": [], "is_new": False}

    return {
        "candidates": [{
            "name": canonical.name,
            "uri": canonical.uri,
            "type": canonical.type,
            "confidence": canonical.confidence,
            "merged_with": canonical.merged_with
        }],
        "is_new": is_new
    }


# =============================================================================
# Entity MentionedIn Endpoints (for bidirectional linking)
# IMPORTANT: These must be defined BEFORE the generic /entity/{uri:path} route
# =============================================================================

class MentionedInDocument(BaseModel):
    """A document that mentions an entity"""
    vault_path: str  # NO .md extension
    document_rid: str
    mention_count: int
    doc_date: Optional[str] = None
    first_seen: str
    source_url: Optional[str] = None
    quartz_url: Optional[str] = None


class MentionedInResponse(BaseModel):
    """Response from mentioned-in endpoint"""
    entity_uri: str
    total_count: int
    truncated: bool
    documents: List[MentionedInDocument]


class BatchMentionedInRequest(BaseModel):
    """Request for batch mentioned-in query"""
    uris: List[str]
    limit_per_entity: int = 500


class BatchMentionedInResponse(BaseModel):
    """Response from batch mentioned-in query"""
    results: Dict[str, MentionedInResponse]
    total_entities: int


def extract_date_from_vault_path(vault_path: str) -> Optional[str]:
    """
    Extract date from vault path if present.
    Looks for YYYY-MM-DD pattern at start of filename.
    """
    import re
    # Get filename from path
    filename = vault_path.split('/')[-1] if '/' in vault_path else vault_path
    # Remove .md extension if present
    if filename.endswith('.md'):
        filename = filename[:-3]
    # Look for date pattern at start
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', filename)
    return match.group(1) if match else None


@app.get("/entity/{entity_uri:path}/mentioned-in", response_model=MentionedInResponse)
async def get_entity_mentioned_in(
    entity_uri: str,
    limit: int = 500
):
    """
    Get documents that mention an entity.

    This endpoint queries document_entity_links to find all documents
    that mention the given entity. Used for populating mentionedIn
    frontmatter in entity notes.

    Args:
        entity_uri: Canonical entity URI (orn:personal-koi.entity:...)
        limit: Maximum documents to return (default 500, high to avoid silent truncation)

    Returns:
        MentionedInResponse with sorted document list (alphabetical by vault_path)
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Query document_entity_links, joining web_submissions for source URLs
        # document_rid uses "web:<rid>" format, web_submissions.rid is "<rid>"
        rows = await conn.fetch("""
            SELECT del.document_rid, del.mention_count, del.created_at,
                   ws.url AS source_url
            FROM document_entity_links del
            LEFT JOIN web_submissions ws
                ON ws.rid = REPLACE(del.document_rid, 'web:', '')
                AND del.document_rid LIKE 'web:%'
            WHERE del.entity_uri = $1
            ORDER BY del.document_rid ASC
            LIMIT $2
        """, entity_uri, limit + 1)  # Fetch limit+1 to detect truncation

        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]

        documents = []
        for row in rows:
            # Convert document_rid to vault_path
            # document_rid format: "orn:obsidian.entity:Notes/..." or "vault:notes/..."
            doc_rid = row['document_rid']

            # Extract vault path from RID
            # Handles various formats: orn:obsidian.entity:Notes/, vault:notes/, vault:
            if doc_rid.startswith('orn:obsidian.entity:Notes/'):
                vault_path = doc_rid.replace('orn:obsidian.entity:Notes/', '')
            elif doc_rid.startswith('vault:notes/'):
                vault_path = doc_rid.replace('vault:notes/', '')
            elif doc_rid.startswith('vault:'):
                vault_path = doc_rid.replace('vault:', '')
            else:
                vault_path = doc_rid

            # Remove .md extension for Obsidian wikilink format
            if vault_path.endswith('.md'):
                vault_path = vault_path[:-3]

            # Extract date from filename if present
            doc_date = extract_date_from_vault_path(vault_path)

            # Build Quartz URL for source documents
            quartz_url = None
            if QUARTZ_BASE_URL and vault_path:
                slug = vault_path.replace(' ', '-').replace('/', '/')
                quartz_url = f"{QUARTZ_BASE_URL}/{slug}"

            documents.append(MentionedInDocument(
                vault_path=vault_path,
                document_rid=doc_rid,
                mention_count=row['mention_count'] or 1,
                doc_date=doc_date,
                first_seen=row['created_at'].isoformat() if row['created_at'] else None,
                source_url=row['source_url'],
                quartz_url=quartz_url,
            ))

        return MentionedInResponse(
            entity_uri=entity_uri,
            total_count=len(documents),
            truncated=truncated,
            documents=documents
        )


@app.post("/entities/mentioned-in", response_model=BatchMentionedInResponse)
async def get_entities_mentioned_in_batch(request: BatchMentionedInRequest):
    """
    Batch query for documents mentioning multiple entities.

    This endpoint allows efficient querying of multiple entities at once,
    avoiding N+1 API calls when propagating mentionedIn to many entity notes.

    Args:
        uris: List of entity URIs to query
        limit_per_entity: Maximum documents per entity (default 500)

    Returns:
        BatchMentionedInResponse with results keyed by entity URI
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if not request.uris:
        return BatchMentionedInResponse(results={}, total_entities=0)

    results = {}

    async with db_pool.acquire() as conn:
        for entity_uri in request.uris:
            rows = await conn.fetch("""
                SELECT del.document_rid, del.mention_count, del.created_at,
                       ws.url AS source_url
                FROM document_entity_links del
                LEFT JOIN web_submissions ws
                    ON ws.rid = REPLACE(del.document_rid, 'web:', '')
                    AND del.document_rid LIKE 'web:%'
                WHERE del.entity_uri = $1
                ORDER BY del.document_rid ASC
                LIMIT $2
            """, entity_uri, request.limit_per_entity + 1)

            truncated = len(rows) > request.limit_per_entity
            if truncated:
                rows = rows[:request.limit_per_entity]

            documents = []
            for row in rows:
                doc_rid = row['document_rid']

                if doc_rid.startswith('orn:obsidian.entity:Notes/'):
                    vault_path = doc_rid.replace('orn:obsidian.entity:Notes/', '')
                elif doc_rid.startswith('vault:notes/'):
                    vault_path = doc_rid.replace('vault:notes/', '')
                elif doc_rid.startswith('vault:'):
                    vault_path = doc_rid.replace('vault:', '')
                else:
                    vault_path = doc_rid

                if vault_path.endswith('.md'):
                    vault_path = vault_path[:-3]

                doc_date = extract_date_from_vault_path(vault_path)

                quartz_url = None
                if QUARTZ_BASE_URL and vault_path:
                    slug = vault_path.replace(' ', '-').replace('/', '/')
                    quartz_url = f"{QUARTZ_BASE_URL}/{slug}"

                documents.append(MentionedInDocument(
                    vault_path=vault_path,
                    document_rid=doc_rid,
                    mention_count=row['mention_count'] or 1,
                    doc_date=doc_date,
                    first_seen=row['created_at'].isoformat() if row['created_at'] else None,
                    source_url=row['source_url'],
                    quartz_url=quartz_url,
                ))

            results[entity_uri] = MentionedInResponse(
                entity_uri=entity_uri,
                total_count=len(documents),
                truncated=truncated,
                documents=documents
            )

    return BatchMentionedInResponse(
        results=results,
        total_entities=len(results)
    )


# =============================================================================
# Entity CRUD Endpoints
# =============================================================================

@app.get("/entity/{entity_uri:path}")
async def get_entity(entity_uri: str):
    """Get a specific entity by URI"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        entity = await conn.fetchrow("""
            SELECT fuseki_uri, entity_text, entity_type, normalized_text,
                   source, first_seen_rid, metadata, created_at
            FROM entity_registry
            WHERE fuseki_uri = $1
        """, entity_uri)

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Get linked documents
        docs = await conn.fetch("""
            SELECT document_rid, mention_count, context, created_at
            FROM document_entity_links
            WHERE entity_uri = $1
            ORDER BY created_at DESC
        """, entity_uri)

        return {
            "entity": dict(entity),
            "documents": [dict(d) for d in docs]
        }


@app.get("/stats")
async def get_stats():
    """Get knowledge base statistics"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM entity_registry")

        by_type = await conn.fetch("""
            SELECT entity_type, COUNT(*) as count
            FROM entity_registry
            GROUP BY entity_type
            ORDER BY count DESC
        """)

        recent = await conn.fetch("""
            SELECT entity_text, entity_type, created_at
            FROM entity_registry
            ORDER BY created_at DESC
            LIMIT 10
        """)

        return {
            "total_entities": total,
            "by_type": {r['entity_type']: r['count'] for r in by_type},
            "recent_entities": [dict(r) for r in recent],
            "mode": KOI_MODE
        }


@app.post("/register-entity", response_model=RegisterEntityResponse)
async def register_vault_entity(request: RegisterEntityRequest):
    """
    Register a vault entity note with the backend.

    This endpoint:
    1. Checks if entity already exists (by name + type)
    2. Creates new or links to existing canonical entity
    3. Stores the vault RID → canonical URI mapping
    4. Returns canonical URI for frontmatter update
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Create an ExtractedEntity from the request for resolution
            entity = ExtractedEntity(
                name=request.name,
                type=request.entity_type,
                mentions=[request.name],
                confidence=1.0,
                context=None
            )

            # Resolve against existing entities
            canonical, is_new = await resolve_entity(conn, entity)

            if is_new:
                # Store new entity
                await store_new_entity(conn, entity, canonical, request.vault_rid)
                logger.info(f"Registered new entity: {canonical.uri}")
            else:
                logger.info(f"Linked to existing entity: {canonical.uri}")

            # Store or update RID mapping
            await conn.execute("""
                INSERT INTO entity_rid_mappings (
                    vault_rid, vault_path, canonical_uri, entity_type,
                    name, content_hash, sync_status, last_synced
                ) VALUES ($1, $2, $3, $4, $5, $6, 'linked', NOW())
                ON CONFLICT (vault_rid) DO UPDATE SET
                    vault_path = EXCLUDED.vault_path,
                    canonical_uri = EXCLUDED.canonical_uri,
                    entity_type = EXCLUDED.entity_type,
                    name = EXCLUDED.name,
                    content_hash = EXCLUDED.content_hash,
                    sync_status = 'linked',
                    last_synced = NOW()
            """,
                request.vault_rid,
                request.vault_path,
                canonical.uri,
                request.entity_type,
                request.name,
                request.content_hash
            )

            # Update entity_registry with vault_rid if not set
            await conn.execute("""
                UPDATE entity_registry
                SET vault_rid = $1
                WHERE fuseki_uri = $2 AND vault_rid IS NULL
            """, request.vault_rid, canonical.uri)

            # Sync relationships from frontmatter if provided
            # Accept frontmatter OR properties (for older MCP clients)
            rel_stats = None
            frontmatter_data = request.frontmatter or request.properties
            if frontmatter_data:
                try:
                    rel_stats = await sync_vault_relationships(
                        conn,
                        request.vault_path,
                        canonical.uri,
                        frontmatter_data
                    )
                    logger.info(f"Synced relationships: {rel_stats}")
                except Exception as e:
                    logger.warning(f"Failed to sync relationships: {e}")

                # Update aliases in entity_registry if provided in frontmatter
                raw_aliases = frontmatter_data.get('aliases', [])
                if raw_aliases:
                    if isinstance(raw_aliases, str):
                        raw_aliases = [raw_aliases]
                    normalized_aliases = [normalize_alias(a) for a in raw_aliases if a]

                    if normalized_aliases:
                        try:
                            # Merge with existing aliases using DISTINCT to prevent duplicates
                            await conn.execute("""
                                UPDATE entity_registry
                                SET aliases = (
                                    SELECT ARRAY(
                                        SELECT DISTINCT unnest(
                                            array_cat(COALESCE(aliases, '{}'), $1::TEXT[])
                                        )
                                    )
                                )
                                WHERE fuseki_uri = $2
                            """, normalized_aliases, canonical.uri)
                            logger.info(f"Updated aliases for {canonical.uri}: {normalized_aliases}")
                        except Exception as e:
                            logger.warning(f"Failed to update aliases: {e}")

            # Resolve any pending relationships that match this new entity
            pending_promoted = 0
            if is_new:
                try:
                    pending_promoted = await resolve_pending_relationships(
                        conn,
                        canonical.uri,
                        request.name,
                        request.entity_type
                    )
                    if pending_promoted > 0:
                        logger.info(f"Promoted {pending_promoted} pending relationship(s)")
                except Exception as e:
                    logger.warning(f"Failed to resolve pending relationships: {e}")

            # Emit KOI-net event if enabled
            if KOI_NET_ENABLED:
                try:
                    from api.koi_net_router import _event_queue
                    if _event_queue:
                        # Generate koi_rid if not yet set
                        koi_rid = await conn.fetchval(
                            "SELECT koi_rid FROM entity_registry WHERE fuseki_uri = $1",
                            canonical.uri,
                        )
                        if not koi_rid:
                            import hashlib, re
                            slug = re.sub(r"[^\w\s-]", "", request.name.lower().strip())
                            slug = re.sub(r"[\s_]+", "-", slug).strip("-") or "unnamed"
                            uri_hash = hashlib.sha256(canonical.uri.encode()).hexdigest()[:16]
                            type_lower = request.entity_type.lower()
                            koi_rid = f"orn:koi-net.{type_lower}:{slug}+{uri_hash}"
                            await conn.execute(
                                "UPDATE entity_registry SET koi_rid = $1 WHERE fuseki_uri = $2",
                                koi_rid, canonical.uri,
                            )
                        event_type = "NEW" if is_new else "UPDATE"
                        await _event_queue.add(
                            rid=koi_rid,
                            event_type=event_type,
                            contents={
                                "name": request.name,
                                "@type": f"bkc:{request.entity_type}",
                                "entity_type": request.entity_type,
                                "source": "vault",
                            },
                        )
                        logger.info(f"KOI-net event emitted: {event_type} {koi_rid}")
                except Exception as e:
                    logger.warning(f"Failed to emit KOI-net event: {e}")

            return RegisterEntityResponse(
                success=True,
                canonical_uri=canonical.uri,
                is_new=is_new,
                vault_rid=request.vault_rid,
                merged_with=canonical.merged_with
            )


@app.get("/vault-entities")
async def list_vault_entities(
    entity_type: Optional[str] = None,
    sync_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
):
    """List all vault entities registered with the backend"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Build query with optional filters
        conditions = []
        params = []
        param_idx = 1

        if entity_type:
            conditions.append(f"entity_type = ${param_idx}")
            params.append(entity_type)
            param_idx += 1

        if sync_status:
            conditions.append(f"sync_status = ${param_idx}")
            params.append(sync_status)
            param_idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Add limit and offset
        params.extend([limit, offset])

        query = f"""
            SELECT vault_rid, vault_path, canonical_uri, entity_type,
                   name, sync_status, content_hash, last_synced
            FROM entity_rid_mappings
            {where_clause}
            ORDER BY last_synced DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        entities = await conn.fetch(query, *params)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM entity_rid_mappings {where_clause}"
        if params[:-2]:  # Exclude limit/offset for count
            total = await conn.fetchval(count_query, *params[:-2])
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM entity_rid_mappings")

        return {
            "entities": [
                {
                    "vault_rid": e['vault_rid'],
                    "vault_path": e['vault_path'],
                    "canonical_uri": e['canonical_uri'],
                    "entity_type": e['entity_type'],
                    "name": e['name'],
                    "sync_status": e['sync_status'],
                    "content_hash": e['content_hash'],
                    "last_synced": e['last_synced'].isoformat() if e['last_synced'] else None
                }
                for e in entities
            ],
            "count": total,
            "limit": limit,
            "offset": offset
        }


@app.get("/vault-entity/{vault_rid:path}")
async def get_vault_entity(vault_rid: str):
    """Get a specific vault entity by its RID"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        mapping = await conn.fetchrow("""
            SELECT vault_rid, vault_path, canonical_uri, entity_type,
                   name, sync_status, content_hash, last_synced, created_at
            FROM entity_rid_mappings
            WHERE vault_rid = $1
        """, vault_rid)

        if not mapping:
            raise HTTPException(status_code=404, detail="Vault entity not found")

        # Get the canonical entity details
        entity = await conn.fetchrow("""
            SELECT fuseki_uri, entity_text, entity_type, normalized_text,
                   source, first_seen_rid, metadata, created_at
            FROM entity_registry
            WHERE fuseki_uri = $1
        """, mapping['canonical_uri'])

        return {
            "mapping": {
                "vault_rid": mapping['vault_rid'],
                "vault_path": mapping['vault_path'],
                "canonical_uri": mapping['canonical_uri'],
                "entity_type": mapping['entity_type'],
                "name": mapping['name'],
                "sync_status": mapping['sync_status'],
                "content_hash": mapping['content_hash'],
                "last_synced": mapping['last_synced'].isoformat() if mapping['last_synced'] else None,
                "created_at": mapping['created_at'].isoformat() if mapping['created_at'] else None
            },
            "entity": dict(entity) if entity else None
        }


@app.post("/resolve-to-vault")
async def resolve_canonical_to_vault(uris: List[str]):
    """
    Resolve canonical URIs to vault paths for wikilink generation.

    Given a list of canonical entity URIs, returns the corresponding vault paths
    that can be used to create wikilinks like [[People/Clare Attwell]].

    Example:
        POST /resolve-to-vault
        ["orn:personal-koi.entity:person-clare-attwell-abc123", ...]

        Returns:
        {
            "mappings": [
                {
                    "canonical_uri": "orn:personal-koi.entity:person-clare-attwell-abc123",
                    "vault_path": "People/Clare Attwell.md",
                    "name": "Clare Attwell",
                    "wikilink": "[[People/Clare Attwell]]"
                }
            ],
            "not_found": []
        }
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    mappings = []
    not_found = []

    async with db_pool.acquire() as conn:
        for uri in uris:
            row = await conn.fetchrow("""
                SELECT vault_rid, vault_path, canonical_uri, entity_type, name
                FROM entity_rid_mappings
                WHERE canonical_uri = $1
                LIMIT 1
            """, uri)

            if row:
                # Generate wikilink from vault path
                vault_path = row['vault_path']
                # Remove .md extension and use as wikilink
                wikilink_path = vault_path.replace('.md', '') if vault_path.endswith('.md') else vault_path

                mappings.append({
                    "canonical_uri": row['canonical_uri'],
                    "vault_path": row['vault_path'],
                    "name": row['name'],
                    "entity_type": row['entity_type'],
                    "wikilink": f"[[{wikilink_path}]]"
                })
            else:
                not_found.append(uri)

    return {
        "mappings": mappings,
        "not_found": not_found,
        "resolved": len(mappings),
        "total": len(uris)
    }


class ContextualCandidatesRequest(BaseModel):
    """Request for contextual entity candidates based on meeting context"""
    project: Optional[str] = None
    attendees: Optional[List[str]] = None
    topics: Optional[List[str]] = None
    document_rid: Optional[str] = None  # Current document being processed
    entity_types: List[str] = Field(default_factory=lambda: ["Person"])  # Entity types to return


async def get_contextual_candidates_internal(
    conn: asyncpg.Connection,
    project: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    attendee_uris: Optional[List[str]] = None,
    topics: Optional[List[str]] = None,
    document_rid: Optional[str] = None,
    entity_types: Optional[List[str]] = None
) -> dict:
    """
    Internal helper for finding contextual entity candidates.

    Returns: {"candidates": [...], "related_documents": [...], "context_types": [...]}
    """
    if entity_types is None:
        entity_types = ["Person"]

    candidates = {}  # uri -> candidate info
    related_docs = set()
    context_types = []

    # Strategy 1: Find meetings linked to the same project entity
    if project:
        project_normalized = project.lower().strip()
        project_docs = await conn.fetch("""
            SELECT DISTINCT del.document_rid
            FROM document_entity_links del
            JOIN entity_registry er ON del.entity_uri = er.fuseki_uri
            WHERE er.entity_type = 'Project'
              AND (LOWER(er.entity_text) LIKE $1
                   OR LOWER(er.normalized_text) LIKE $1)
        """, f"%{project_normalized}%")

        for row in project_docs:
            related_docs.add(row['document_rid'])
        if project_docs:
            context_types.append("project")

    # Strategy 2a: Find meetings by attendee URIs (most precise)
    if attendee_uris:
        uri_docs = await conn.fetch("""
            SELECT DISTINCT document_rid
            FROM document_entity_links
            WHERE entity_uri = ANY($1)
        """, attendee_uris)
        for row in uri_docs:
            related_docs.add(row['document_rid'])
        if uri_docs:
            context_types.append("attendee_uris")

    # Strategy 2b: Find meetings with common attendees (by name)
    if attendees:
        for attendee in attendees:
            attendee_normalized = attendee.lower().strip()
            attendee_docs = await conn.fetch("""
                SELECT DISTINCT del.document_rid
                FROM document_entity_links del
                JOIN entity_registry er ON del.entity_uri = er.fuseki_uri
                WHERE er.entity_type = 'Person'
                  AND (LOWER(er.entity_text) LIKE $1
                       OR LOWER(er.normalized_text) LIKE $1)
            """, f"%{attendee_normalized}%")

            for row in attendee_docs:
                related_docs.add(row['document_rid'])
        if attendees and related_docs:
            context_types.append("attendees")

    # Strategy 3: Find meetings with similar topics (linked Concept entities)
    if topics:
        for topic in topics:
            topic_normalized = topic.lower().strip()
            topic_docs = await conn.fetch("""
                SELECT DISTINCT del.document_rid
                FROM document_entity_links del
                JOIN entity_registry er ON del.entity_uri = er.fuseki_uri
                WHERE er.entity_type = 'Concept'
                  AND (LOWER(er.entity_text) LIKE $1
                       OR LOWER(er.normalized_text) LIKE $1)
            """, f"%{topic_normalized}%")

            for row in topic_docs:
                related_docs.add(row['document_rid'])
        if topics and related_docs:
            context_types.append("topics")

    # Exclude current document from related docs
    if document_rid and document_rid in related_docs:
        related_docs.discard(document_rid)

    # Get entities of requested types from related documents
    if related_docs:
        related_docs_list = list(related_docs)
        entities = await conn.fetch("""
            SELECT DISTINCT er.fuseki_uri, er.entity_text, er.entity_type,
                   er.normalized_text, er.phonetic_code, del.document_rid
            FROM entity_registry er
            JOIN document_entity_links del ON er.fuseki_uri = del.entity_uri
            WHERE er.entity_type = ANY($1)
              AND del.document_rid = ANY($2)
        """, entity_types, related_docs_list)

        for entity in entities:
            uri = entity['fuseki_uri']
            if uri not in candidates:
                candidates[uri] = {
                    "name": entity['entity_text'],
                    "uri": uri,
                    "normalized_name": entity['normalized_text'],
                    "entity_type": entity['entity_type'],
                    "phonetic_code": entity['phonetic_code'],
                    "source_documents": []
                }
            candidates[uri]["source_documents"].append(entity['document_rid'])

    # Also include entities from vault registry (registered but not yet linked)
    # Only for Person type to keep backward compatibility
    if "Person" in entity_types:
        vault_people = await conn.fetch("""
            SELECT DISTINCT er.fuseki_uri, er.entity_text, er.normalized_text,
                   er.phonetic_code, erm.vault_path
            FROM entity_registry er
            LEFT JOIN entity_rid_mappings erm ON er.fuseki_uri = erm.canonical_uri
            WHERE er.entity_type = 'Person'
              AND erm.vault_path IS NOT NULL
              AND er.fuseki_uri NOT IN (
                  SELECT entity_uri FROM document_entity_links
              )
            LIMIT 50
        """)

        for person in vault_people:
            uri = person['fuseki_uri']
            if uri not in candidates:
                candidates[uri] = {
                    "name": person['entity_text'],
                    "uri": uri,
                    "normalized_name": person['normalized_text'],
                    "entity_type": "Person",
                    "phonetic_code": person['phonetic_code'],
                    "source_documents": [],
                    "vault_path": person['vault_path']
                }

    return {
        "candidates": list(candidates.values()),
        "related_documents": list(related_docs),
        "context_types": context_types
    }


async def get_contextual_entity_candidates(
    conn: asyncpg.Connection,
    label: str,
    entity_type: str,
    associated_people: List[str],
    context: Optional[ResolutionContext] = None
) -> List[dict]:
    """
    Find entity candidates that co-occur with given people.

    Works for any entity type (Person, Organization, Project, Location, Concept).
    Uses unified scoring formula with phonetic boost for types with phonetic_matching=true.
    Now includes relationship-based relevance scoring when context includes project/organizations.

    Args:
        conn: Database connection
        label: The entity label to match against
        entity_type: Type of entity to search for
        associated_people: List of people names that should co-occur
        context: Optional resolution context with project/organizations for relationship checking

    Returns:
        List of scored candidate entities
    """
    target_normalized = normalize_entity_text(label)

    # Get schema-driven config for this entity type
    schema = get_schema_for_type(entity_type)

    # Exclude self from associated_people (prevents circular context)
    people = [
        p.strip() for p in associated_people
        if p.strip() and normalize_entity_text(p.strip()) != target_normalized
    ]
    people = list(set(people))  # Dedupe

    # Cap at 10 to avoid huge ANY() lists if extraction gets noisy
    if len(people) > 10:
        logger.warning(f"Contextual: truncating {len(people)} associated_people to 10")
        people = people[:10]

    # Schema-driven minimum people requirements
    min_people = schema.min_context_people

    if len(people) < min_people:
        logger.info(f"Contextual: need {min_people} associated people for {entity_type}, got {len(people)}")
        return []

    # Resolve people names to URIs
    # For 1-person case: require UNIQUE resolution (1 URI only)
    # For 2+ people: collect all URIs
    resolved_uris = []
    for person in people:
        rows = await conn.fetch("""
            SELECT fuseki_uri FROM entity_registry
            WHERE entity_type = 'Person' AND normalized_text = $1
        """, normalize_entity_text(person))

        if len(people) == 1:
            # Single associated person: require unique resolution
            if len(rows) != 1:
                logger.info(f"Contextual: '{person}' resolves to {len(rows)} URIs, "
                           f"need exactly 1 for single-person context (blocking)")
                return []  # Ambiguous or not found
            resolved_uris.append(rows[0]['fuseki_uri'])
        else:
            # Multiple associated people: collect all URIs
            for row in rows:
                resolved_uris.append(row['fuseki_uri'])

    if len(resolved_uris) < min_people:
        logger.info(f"Contextual: resolved {len(resolved_uris)} URIs, need {min_people}")
        return []

    # Call internal helper with URIs
    response = await get_contextual_candidates_internal(
        conn,
        attendee_uris=resolved_uris,
        entity_types=[entity_type]
    )

    # Compute query's phonetic code (for types with phonetic_matching enabled)
    query_phonetic = None
    if schema.phonetic_matching:
        first_token = get_first_significant_token(target_normalized, schema.phonetic_stopwords)
        query_phonetic = get_phonetic_code(first_token)

    # Score candidates
    scored = []
    for candidate in response.get("candidates", []):
        candidate_normalized = candidate.get("normalized_name", normalize_entity_text(candidate["name"]))
        name_sim = jaro_winkler_similarity(target_normalized, candidate_normalized)
        doc_count = len(candidate.get("source_documents", []))

        # Phonetic bonus for types with phonetic_matching enabled (schema-driven)
        phonetic_bonus = 0.0
        phonetic_match = False
        if schema.phonetic_matching and query_phonetic:
            candidate_phonetic = candidate.get("phonetic_code")
            # Guard: if phonetic_code missing, compute on the fly
            if candidate_phonetic is None:
                candidate_first_token = get_first_significant_token(candidate_normalized, schema.phonetic_stopwords)
                candidate_phonetic = get_phonetic_code(candidate_first_token)
            if phonetic_codes_match(query_phonetic, candidate_phonetic):
                phonetic_bonus = 1.0
                phonetic_match = True

        # Minimum fuzzy threshold (relaxed if phonetic match)
        min_fuzzy = 0.4 if phonetic_bonus > 0 else 0.5
        if name_sim >= min_fuzzy:
            scored.append({
                **candidate,
                "name_similarity": name_sim,
                "phonetic_match": phonetic_match,
                "doc_count": doc_count
            })

    # Combined scoring (unified formula)
    # Stable doc_score normalization: min(doc_count / 3, 1.0)
    for c in scored:
        doc_score = min(c["doc_count"] / 3.0, 1.0)
        phonetic_score = 0.2 if c.get("phonetic_match") else 0.0

        # Unified formula: 0.5 * fuzzy + 0.2 * phonetic + 0.3 * doc
        c["combined_score"] = 0.5 * c["name_similarity"] + phonetic_score + 0.3 * doc_score

    # Relationship-based context relevance scoring
    # Only check if context includes project or organizations
    if context and (context.project or context.organizations):
        for c in scored:
            candidate_uri = c.get("uri")
            if not candidate_uri:
                continue

            relevance = await check_context_relevance(conn, candidate_uri, context)

            if relevance.signal == RelevanceSignal.POSITIVE:
                c["combined_score"] += relevance.score  # Boost
                c["relevance_detail"] = relevance.details
                logger.debug(f"Relevance POSITIVE for {c['name']}: {relevance.details}")

            elif relevance.signal == RelevanceSignal.NEGATIVE:
                # CRITICAL: Phonetic match alone is NOT enough to bypass penalty
                # Paul→Polly is a phonetic match, but Polly has no Regen/Gaia relationships
                # Require phonetic + high name similarity (>0.9) OR phonetic + semantic match
                has_strong_phonetic = (
                    c.get('phonetic_match') and
                    c.get('name_similarity', 0) >= 0.9  # "Sean"→"Shawn" = 0.93
                )

                if not has_strong_phonetic:
                    c["combined_score"] += relevance.score  # Penalty (negative value)
                    c["relevance_detail"] = relevance.details
                    logger.debug(f"Relevance NEGATIVE for {c['name']}: {relevance.details}")

            elif relevance.signal == RelevanceSignal.UNKNOWN:
                # Fallback to document co-occurrence
                fallback = await check_fallback_relevance(conn, candidate_uri, context)
                if fallback > 0:
                    c["combined_score"] += fallback
                    c["relevance_detail"] = f"doc co-occurrence (+{fallback:.2f})"

    # Short-name guard with explicit bypass conditions
    has_context = len(resolved_uris) > 0  # Context is present if we got here
    for c in scored:
        if len(c["name"]) < 8:
            # Bypass guard if phonetic match (strong evidence despite short name)
            if c.get("phonetic_match"):
                continue  # Allow short names with phonetic match
            # Bypass guard if: low min_context (like Person) + context present + high fuzzy
            if schema.min_context_people == 1 and has_context and c["name_similarity"] >= 0.85:
                continue  # Allow short names with high fuzzy + context
            # Otherwise apply strict guard
            if c["name_similarity"] < 0.7 or c["doc_count"] < 2:
                c["combined_score"] = 0  # Disqualify short names with weak signals

    scored = [c for c in scored if c["combined_score"] > 0]
    scored.sort(key=lambda x: -x["combined_score"])

    logger.info(f"Contextual {entity_type} candidates for '{label}': {len(scored)} candidates found")
    for c in scored[:3]:  # Log top 3
        phonetic_str = f", phonetic={c.get('phonetic_match', False)}" if schema.phonetic_matching else ""
        logger.info(f"  - {c['name']}: name_sim={c['name_similarity']:.3f}, "
                   f"docs={c['doc_count']}, combined={c['combined_score']:.3f}{phonetic_str}")

    return scored[:10]


# Backward compatibility alias
async def get_contextual_org_candidates(
    conn: asyncpg.Connection,
    label: str,
    associated_people: List[str]
) -> List[dict]:
    """Backward compatible wrapper - use get_contextual_entity_candidates instead."""
    return await get_contextual_entity_candidates(conn, label, 'Organization', associated_people)


@app.post("/get-contextual-candidates")
async def get_contextual_candidates(request: ContextualCandidatesRequest):
    """
    Get contextual entity candidates based on related meetings.

    This endpoint finds entities from related meetings that share:
    - The same project
    - Common attendees
    - Similar topics

    Use case: When processing a meeting that mentions "Sean", this endpoint
    can return "Shawn Anderson" as a candidate if they attended other meetings
    for the same project.

    Example:
        POST /get-contextual-candidates
        {"project": "GLOTCHA", "attendees": ["Mehul Patel"], "entity_types": ["Person"]}

        Returns:
        {
            "candidates": [
                {"name": "Shawn Anderson", "uri": "orn:...", "source_documents": [...]}
            ],
            "related_documents": [...],
            "context_types": ["project"]
        }
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        result = await get_contextual_candidates_internal(
            conn,
            project=request.project,
            attendees=request.attendees,
            topics=request.topics,
            document_rid=request.document_rid,
            entity_types=request.entity_types
        )

    return {
        **result,
        "candidate_count": len(result["candidates"]),
        "related_document_count": len(result["related_documents"])
    }


# =============================================================================
# Relationship Endpoints
# =============================================================================

class SyncRelationshipsRequest(BaseModel):
    """Request to sync relationships from a vault file"""
    vault_path: str  # e.g., "People/Shawn Anderson.md"
    entity_uri: str  # Canonical URI of the entity
    frontmatter: Dict[str, Any]  # YAML frontmatter dict


@app.post("/sync-relationships")
async def sync_relationships_endpoint(request: SyncRelationshipsRequest):
    """
    Sync relationships from vault YAML frontmatter to the database.

    This endpoint:
    1. Deletes existing relationships from this file (replace-all strategy)
    2. Parses YAML fields (affiliation, founder, knows, etc.)
    3. Resolves targets to entity URIs
    4. Stores resolved relationships in entity_relationships
    5. Stores unresolved targets in pending_relationships

    Use Case: Backfill relationships for existing vault entities.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            stats = await sync_vault_relationships(
                conn,
                request.vault_path,
                request.entity_uri,
                request.frontmatter
            )

    return {
        "success": True,
        "vault_path": request.vault_path,
        "stats": stats
    }


@app.get("/relationships/{entity_uri:path}")
async def get_relationships_endpoint(
    entity_uri: str,
    predicate: Optional[str] = None
):
    """
    Get all relationships for an entity (both directions).

    Query Parameters:
        predicate: Optional filter by predicate (e.g., 'affiliated_with')

    Returns relationships where the entity is subject or object.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        relationships = await get_entity_relationships(conn, entity_uri, predicate)

        # Enrich with entity names
        enriched = []
        for rel in relationships:
            # Get subject name
            subject_row = await conn.fetchrow("""
                SELECT entity_text, entity_type FROM entity_registry
                WHERE fuseki_uri = $1
            """, rel['subject_uri'])

            # Get object name
            object_row = await conn.fetchrow("""
                SELECT entity_text, entity_type FROM entity_registry
                WHERE fuseki_uri = $1
            """, rel['object_uri'])

            enriched.append({
                **rel,
                "subject_name": subject_row['entity_text'] if subject_row else None,
                "subject_type": subject_row['entity_type'] if subject_row else None,
                "object_name": object_row['entity_text'] if object_row else None,
                "object_type": object_row['entity_type'] if object_row else None,
            })

    return {
        "entity_uri": entity_uri,
        "relationships": enriched,
        "count": len(enriched)
    }


@app.get("/relationship-stats")
async def get_relationship_stats():
    """Get relationship statistics"""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Total counts
        total_relationships = await conn.fetchval("SELECT COUNT(*) FROM entity_relationships")
        total_pending = await conn.fetchval("SELECT COUNT(*) FROM pending_relationships")

        # By predicate
        by_predicate = await conn.fetch("""
            SELECT predicate, COUNT(*) as count
            FROM entity_relationships
            GROUP BY predicate
            ORDER BY count DESC
        """)

        # Top pending (unresolved labels)
        top_pending = await conn.fetch("""
            SELECT raw_unknown_label, predicate, unknown_side, COUNT(*) as count
            FROM pending_relationships
            GROUP BY raw_unknown_label, predicate, unknown_side
            ORDER BY count DESC
            LIMIT 20
        """)

        return {
            "total_relationships": total_relationships,
            "total_pending": total_pending,
            "by_predicate": {r['predicate']: r['count'] for r in by_predicate},
            "top_pending": [dict(r) for r in top_pending]
        }


# =============================================================================
# Session Search Endpoints (for Claude Code session memory)
# =============================================================================

class SearchSessionsRequest(BaseModel):
    """Request to search Claude Code sessions"""
    query: str
    limit: int = 10
    session_id: Optional[str] = None  # Filter to specific session
    include_context: bool = True  # Include surrounding chunks


class SessionSearchResult(BaseModel):
    """A single session search result"""
    session_id: str
    session_rid: str
    chunk_index: int
    chunk_text: str
    similarity: Optional[float] = None
    summary: Optional[str] = None
    first_prompt: Optional[str] = None
    timestamp: Optional[str] = None


@app.post("/search-sessions")
async def search_sessions(request: SearchSessionsRequest):
    """
    Search Claude Code session transcripts.

    Performs semantic search over indexed session chunks.
    Returns matching chunks with session metadata.

    Example:
        POST /search-sessions
        {"query": "entity resolution", "limit": 10}
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    results = []

    async with db_pool.acquire() as conn:
        # Check if session_chunks table exists
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'session_chunks'
            )
        """)

        if not table_exists:
            return {
                "results": [],
                "count": 0,
                "message": "Session chunks table not found. Run the session sensor first."
            }

        # Check if we have embeddings
        has_embeddings = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM session_chunks WHERE embedding IS NOT NULL LIMIT 1
            )
        """)

        if has_embeddings and openai_available and ENABLE_SEMANTIC_MATCHING:
            # Semantic search with embeddings
            query_embedding = await generate_embedding(request.query)

            if query_embedding:
                if request.session_id:
                    # Search within specific session
                    rows = await conn.fetch("""
                        SELECT sc.session_id, sc.session_rid, sc.chunk_index,
                               sc.chunk_text, sc.timestamp,
                               1 - (sc.embedding <=> $1::vector) AS similarity,
                               sil.summary, sil.first_prompt
                        FROM session_chunks sc
                        LEFT JOIN session_ingestion_log sil ON sc.session_id = sil.session_id
                        WHERE sc.session_id = $2
                          AND sc.embedding IS NOT NULL
                        ORDER BY similarity DESC
                        LIMIT $3
                    """, str(query_embedding), request.session_id, request.limit)
                else:
                    # Search all sessions
                    rows = await conn.fetch("""
                        SELECT sc.session_id, sc.session_rid, sc.chunk_index,
                               sc.chunk_text, sc.timestamp,
                               1 - (sc.embedding <=> $1::vector) AS similarity,
                               sil.summary, sil.first_prompt
                        FROM session_chunks sc
                        LEFT JOIN session_ingestion_log sil ON sc.session_id = sil.session_id
                        WHERE sc.embedding IS NOT NULL
                        ORDER BY similarity DESC
                        LIMIT $2
                    """, str(query_embedding), request.limit)

                for row in rows:
                    results.append({
                        "session_id": row['session_id'],
                        "session_rid": row['session_rid'],
                        "chunk_index": row['chunk_index'],
                        "chunk_text": row['chunk_text'][:2000],  # Limit text size
                        "similarity": float(row['similarity']) if row['similarity'] else None,
                        "summary": row['summary'],
                        "first_prompt": row['first_prompt'][:200] if row['first_prompt'] else None,
                        "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
                    })
        else:
            # Fallback: text search (basic ILIKE)
            search_pattern = f"%{request.query}%"

            if request.session_id:
                rows = await conn.fetch("""
                    SELECT sc.session_id, sc.session_rid, sc.chunk_index,
                           sc.chunk_text, sc.timestamp,
                           sil.summary, sil.first_prompt
                    FROM session_chunks sc
                    LEFT JOIN session_ingestion_log sil ON sc.session_id = sil.session_id
                    WHERE sc.session_id = $1
                      AND sc.chunk_text ILIKE $2
                    ORDER BY sc.chunk_index
                    LIMIT $3
                """, request.session_id, search_pattern, request.limit)
            else:
                rows = await conn.fetch("""
                    SELECT sc.session_id, sc.session_rid, sc.chunk_index,
                           sc.chunk_text, sc.timestamp,
                           sil.summary, sil.first_prompt
                    FROM session_chunks sc
                    LEFT JOIN session_ingestion_log sil ON sc.session_id = sil.session_id
                    WHERE sc.chunk_text ILIKE $1
                    ORDER BY sil.last_ingested_at DESC, sc.chunk_index
                    LIMIT $2
                """, search_pattern, request.limit)

            for row in rows:
                results.append({
                    "session_id": row['session_id'],
                    "session_rid": row['session_rid'],
                    "chunk_index": row['chunk_index'],
                    "chunk_text": row['chunk_text'][:2000],
                    "similarity": None,  # No similarity for text search
                    "summary": row['summary'],
                    "first_prompt": row['first_prompt'][:200] if row['first_prompt'] else None,
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None
                })

    return {
        "results": results,
        "count": len(results),
        "query": request.query,
        "search_type": "semantic" if has_embeddings and openai_available else "text"
    }


@app.get("/session-stats")
async def get_session_stats():
    """Get statistics about indexed Claude Code sessions."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Check if tables exist
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'session_ingestion_log'
            )
        """)

        if not table_exists:
            return {
                "indexed": False,
                "message": "Session tables not found. Run the session sensor first."
            }

        total_sessions = await conn.fetchval(
            "SELECT COUNT(*) FROM session_ingestion_log"
        )
        total_chunks = await conn.fetchval(
            "SELECT COUNT(*) FROM session_chunks"
        )
        chunks_with_embeddings = await conn.fetchval(
            "SELECT COUNT(*) FROM session_chunks WHERE embedding IS NOT NULL"
        )

        recent_sessions = await conn.fetch("""
            SELECT session_id, summary, first_prompt, message_count, chunk_count, last_ingested_at
            FROM session_ingestion_log
            ORDER BY last_ingested_at DESC
            LIMIT 5
        """)

        return {
            "indexed": True,
            "total_sessions": total_sessions,
            "total_chunks": total_chunks,
            "chunks_with_embeddings": chunks_with_embeddings,
            "embedding_coverage": f"{(chunks_with_embeddings / total_chunks * 100):.1f}%" if total_chunks > 0 else "0%",
            "recent_sessions": [
                {
                    "session_id": r['session_id'],
                    "summary": r['summary'],
                    "first_prompt": r['first_prompt'][:100] if r['first_prompt'] else None,
                    "message_count": r['message_count'],
                    "chunk_count": r['chunk_count'],
                    "last_ingested_at": r['last_ingested_at'].isoformat() if r['last_ingested_at'] else None
                }
                for r in recent_sessions
            ]
        }


@app.get("/session-tools")
async def get_session_tools(
    tool: Optional[str] = None,
    mcp_server: Optional[str] = None,
    limit: int = 20
):
    """
    Query sessions by tool usage.

    Examples:
        GET /session-tools?tool=Bash
        GET /session-tools?mcp_server=personal-koi
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Check if table exists
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'session_tool_usage'
            )
        """)

        if not table_exists:
            return {
                "results": [],
                "message": "Session tool usage table not found. Re-run sensor to extract metadata."
            }

        if tool:
            # Find sessions using a specific tool
            rows = await conn.fetch("""
                SELECT stu.session_id, stu.tool_name, stu.call_count,
                       sil.summary, sil.first_prompt, sil.last_ingested_at
                FROM session_tool_usage stu
                JOIN session_ingestion_log sil ON stu.session_id = sil.session_id
                WHERE stu.tool_name ILIKE $1
                ORDER BY stu.call_count DESC, sil.last_ingested_at DESC
                LIMIT $2
            """, f"%{tool}%", limit)
        elif mcp_server:
            # Find sessions using a specific MCP server
            rows = await conn.fetch("""
                SELECT stu.session_id, stu.tool_name, stu.call_count, stu.mcp_server,
                       sil.summary, sil.first_prompt, sil.last_ingested_at
                FROM session_tool_usage stu
                JOIN session_ingestion_log sil ON stu.session_id = sil.session_id
                WHERE stu.mcp_server ILIKE $1
                ORDER BY sil.last_ingested_at DESC
                LIMIT $2
            """, f"%{mcp_server}%", limit)
        else:
            # Return overall tool usage stats
            rows = await conn.fetch("""
                SELECT tool_name, SUM(call_count) as total_calls,
                       COUNT(DISTINCT session_id) as session_count,
                       is_mcp, mcp_server
                FROM session_tool_usage
                GROUP BY tool_name, is_mcp, mcp_server
                ORDER BY total_calls DESC
                LIMIT $1
            """, limit)

            return {
                "tool_stats": [
                    {
                        "tool_name": r['tool_name'],
                        "total_calls": r['total_calls'],
                        "session_count": r['session_count'],
                        "is_mcp": r['is_mcp'],
                        "mcp_server": r['mcp_server']
                    }
                    for r in rows
                ]
            }

        return {
            "results": [
                {
                    "session_id": r['session_id'],
                    "tool_name": r['tool_name'],
                    "call_count": r['call_count'],
                    "mcp_server": r.get('mcp_server'),
                    "summary": r['summary'],
                    "first_prompt": r['first_prompt'][:100] if r['first_prompt'] else None,
                    "last_ingested_at": r['last_ingested_at'].isoformat() if r['last_ingested_at'] else None
                }
                for r in rows
            ],
            "count": len(rows),
            "filter": {"tool": tool, "mcp_server": mcp_server}
        }


@app.get("/session-files")
async def get_session_files(
    path_contains: Optional[str] = None,
    limit: int = 20
):
    """
    Query sessions by files accessed.

    Examples:
        GET /session-files?path_contains=koi-processor
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        if path_contains:
            # Find sessions that accessed files matching pattern
            rows = await conn.fetch("""
                SELECT session_id, summary, first_prompt, files_accessed, last_ingested_at
                FROM session_ingestion_log
                WHERE files_accessed IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM unnest(files_accessed) f WHERE f ILIKE $1
                  )
                ORDER BY last_ingested_at DESC
                LIMIT $2
            """, f"%{path_contains}%", limit)
        else:
            # Return sessions with most files accessed
            rows = await conn.fetch("""
                SELECT session_id, summary, first_prompt,
                       files_accessed, array_length(files_accessed, 1) as file_count,
                       last_ingested_at
                FROM session_ingestion_log
                WHERE files_accessed IS NOT NULL
                  AND array_length(files_accessed, 1) > 0
                ORDER BY array_length(files_accessed, 1) DESC
                LIMIT $1
            """, limit)

        return {
            "results": [
                {
                    "session_id": r['session_id'],
                    "summary": r['summary'],
                    "first_prompt": r['first_prompt'][:100] if r['first_prompt'] else None,
                    "files_accessed": r['files_accessed'][:20] if r['files_accessed'] else [],
                    "file_count": len(r['files_accessed']) if r['files_accessed'] else 0,
                    "last_ingested_at": r['last_ingested_at'].isoformat() if r['last_ingested_at'] else None
                }
                for r in rows
            ],
            "count": len(rows),
            "filter": {"path_contains": path_contains}
        }


# =============================================================================
# Knowledge Base Search (Emails, Vault, etc.)
# =============================================================================

BGE_SERVER_URL = os.getenv('BGE_SERVER_URL', 'http://localhost:8091/encode')


class SearchRequest(BaseModel):
    """Request for knowledge base search"""
    query: str
    limit: int = 10
    source: Optional[str] = None  # Filter by source: 'email', 'vault', etc.
    include_chunks: bool = False  # Also search chunk-level embeddings


class SearchResult(BaseModel):
    """Single search result"""
    rid: str
    title: Optional[str] = None
    content_preview: str
    similarity: float
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


async def get_bge_embedding(text: str) -> Optional[List[float]]:
    """Get embedding from local BGE server."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                BGE_SERVER_URL,
                json={"text": text}
            )
            if response.status_code == 200:
                return response.json().get("embedding")
            else:
                logger.warning(f"BGE server error: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"BGE embedding error: {e}")
        return None


@app.post("/search")
async def search_knowledge_base(request: SearchRequest):
    """
    Search the personal knowledge base (emails, vault notes, etc.).

    Performs semantic search using BGE embeddings over koi_memories.

    Args:
        query: Search query text
        limit: Max results (default 10)
        source: Filter by source ('email', 'vault', etc.)
        include_chunks: Also search chunk-level embeddings

    Example:
        POST /search
        {"query": "hackathon ethereum", "limit": 10, "source": "email"}
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    # Generate query embedding using OpenAI (or fall back to BGE)
    query_embedding = await generate_embedding(request.query)
    if not query_embedding:
        query_embedding = await get_bge_embedding(request.query)

    results = []
    chunk_results = []
    search_type = "text"  # fallback

    async with db_pool.acquire() as conn:
        if query_embedding:
            search_type = "semantic"
            embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

            # Build query with optional source filter
            if request.source == 'email':
                source_filter = "AND m.source_sensor = 'email-sensor'"
            elif request.source == 'vault':
                source_filter = "AND m.source_sensor = 'obsidian-sensor'"
            elif request.source == 'github':
                source_filter = "AND m.source_sensor = 'github-sensor'"
            elif request.source:
                source_filter = f"AND m.source_sensor = '{request.source}'"
            else:
                source_filter = ""

            # Search doc-level embeddings (prefer dim_1536 OpenAI, fall back to dim_1024 BGE)
            dim_col = "dim_1536" if len(query_embedding) > 1024 else "dim_1024"
            query = f"""
                SELECT
                    m.rid,
                    m.content->>'title' as title,
                    LEFT(m.content->>'text', 500) as content_preview,
                    1 - (e.{dim_col} <=> $1::vector) as similarity,
                    m.source_sensor,
                    m.metadata,
                    m.created_at
                FROM koi_memories m
                JOIN koi_embeddings e ON e.memory_id = m.id
                WHERE e.{dim_col} IS NOT NULL
                {source_filter}
                ORDER BY e.{dim_col} <=> $1::vector
                LIMIT $2
            """

            rows = await conn.fetch(query, embedding_str, request.limit)

            for row in rows:
                # Handle metadata - asyncpg returns JSONB as dict already
                metadata = row['metadata']
                if metadata is None:
                    metadata = {}
                elif isinstance(metadata, str):
                    import json as json_module
                    metadata = json_module.loads(metadata)

                result = {
                    "rid": row['rid'],
                    "title": row['title'],
                    "content_preview": row['content_preview'],
                    "similarity": float(row['similarity']) if row['similarity'] else 0,
                    "source": row['source_sensor'],
                    "metadata": metadata,
                }

                # Add email-specific metadata if available
                if row['source_sensor'] == 'email-sensor':
                    email_meta = await conn.fetchrow("""
                        SELECT subject, from_name, from_address, date_sent
                        FROM email_metadata
                        WHERE rid = $1
                    """, row['rid'])

                    if email_meta:
                        result['email'] = {
                            "subject": email_meta['subject'],
                            "from_name": email_meta['from_name'],
                            "from_address": email_meta['from_address'],
                            "date_sent": email_meta['date_sent'].isoformat() if email_meta['date_sent'] else None
                        }

                results.append(result)

            # Search chunk-level embeddings (separate results for granularity)
            if request.include_chunks:
                chunk_query = f"""
                    SELECT
                        c.chunk_rid,
                        c.document_rid,
                        m.content->>'title' as doc_title,
                        c.content->>'text' as chunk_text,
                        1 - (c.embedding <=> $1::vector) as similarity,
                        m.source_sensor,
                        c.metadata as chunk_metadata
                    FROM koi_memory_chunks c
                    JOIN koi_memories m ON m.rid = c.document_rid
                    WHERE c.embedding IS NOT NULL
                    {source_filter}
                    ORDER BY c.embedding <=> $1::vector
                    LIMIT $2
                """

                chunk_rows = await conn.fetch(
                    chunk_query,
                    embedding_str,
                    request.limit,
                )

                for row in chunk_rows:
                    chunk_meta = row['chunk_metadata'] if row['chunk_metadata'] else {}
                    chunk_results.append({
                        "chunk_rid": row['chunk_rid'],
                        "document_rid": row['document_rid'],
                        "doc_title": row['doc_title'],
                        "text": row['chunk_text'][:500] if row['chunk_text'] else "",
                        "similarity": float(row['similarity']) if row['similarity'] else 0,
                        "source": row['source_sensor'],
                        "metadata": chunk_meta,
                    })

        else:
            # Fallback: text search
            search_type = "text"
            search_pattern = f"%{request.query}%"

            if request.source == 'email':
                source_filter = "AND m.source_sensor = 'email-sensor'"
            elif request.source:
                source_filter = f"AND m.source_sensor = '{request.source}'"
            else:
                source_filter = ""

            query = f"""
                SELECT
                    m.rid,
                    m.content->>'title' as title,
                    LEFT(m.content->>'text', 500) as content_preview,
                    m.source_sensor,
                    m.metadata,
                    m.created_at
                FROM koi_memories m
                WHERE m.content->>'text' ILIKE $1
                {source_filter}
                ORDER BY m.created_at DESC
                LIMIT $2
            """

            rows = await conn.fetch(query, search_pattern, request.limit)

            for row in rows:
                text_metadata = row['metadata'] if row['metadata'] else {}
                results.append({
                    "rid": row['rid'],
                    "title": row['title'],
                    "content_preview": row['content_preview'],
                    "similarity": None,
                    "source": row['source_sensor'],
                    "metadata": text_metadata
                })

    response = {
        "results": results,
        "count": len(results),
        "query": request.query,
        "search_type": search_type,
        "source_filter": request.source
    }
    if chunk_results:
        response["chunk_results"] = chunk_results
    return response


@app.get("/search")
async def search_knowledge_base_get(
    q: str,
    limit: int = 10,
    source: Optional[str] = None
):
    """GET version of search for convenience."""
    request = SearchRequest(query=q, limit=limit, source=source)
    return await search_knowledge_base(request)


# =============================================================================
# /entity-search Endpoint (Entity-level semantic search using OpenAI embeddings)
# =============================================================================

@app.get("/entity-search")
async def entity_search(
    query: str,
    type_filter: Optional[str] = None,
    limit: int = 10
):
    """
    Search entities by semantic similarity using OpenAI embeddings.

    Unlike /search (which queries koi_memories via BGE), this endpoint
    searches entity_registry directly using the same OpenAI embeddings
    stored during entity registration.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    results = []
    search_method = "text"

    async with db_pool.acquire() as conn:
        query_embedding = await generate_embedding(query)
        if query_embedding:
            search_method = "semantic"
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

            if type_filter:
                rows = await conn.fetch(
                    "SELECT fuseki_uri, entity_text, entity_type, normalized_text, "
                    "aliases, metadata, 1 - (embedding <=> $1::vector) as similarity "
                    "FROM entity_registry "
                    "WHERE embedding IS NOT NULL AND entity_type = $3 "
                    "ORDER BY embedding <=> $1::vector LIMIT $2",
                    embedding_str, limit, type_filter
                )
            else:
                rows = await conn.fetch(
                    "SELECT fuseki_uri, entity_text, entity_type, normalized_text, "
                    "aliases, metadata, 1 - (embedding <=> $1::vector) as similarity "
                    "FROM entity_registry "
                    "WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> $1::vector LIMIT $2",
                    embedding_str, limit
                )

            for row in rows:
                if row["similarity"] < 0.3:
                    continue
                result = {
                    "uri": row["fuseki_uri"],
                    "name": row["entity_text"],
                    "type": row["entity_type"],
                    "similarity": round(float(row["similarity"]), 4),
                    "aliases": row["aliases"] or [],
                }
                qurl = make_quartz_url(row["entity_text"], row["entity_type"])
                if qurl:
                    result["quartz_url"] = qurl
                results.append(result)
        else:
            search_method = "text"
            normalized = query.lower().strip()

            if type_filter:
                rows = await conn.fetch(
                    "SELECT fuseki_uri, entity_text, entity_type, normalized_text, "
                    "aliases, similarity(normalized_text, $1) as sim "
                    "FROM entity_registry "
                    "WHERE similarity(normalized_text, $1) > 0.2 AND entity_type = $3 "
                    "ORDER BY similarity(normalized_text, $1) DESC LIMIT $2",
                    normalized, limit, type_filter
                )
            else:
                rows = await conn.fetch(
                    "SELECT fuseki_uri, entity_text, entity_type, normalized_text, "
                    "aliases, similarity(normalized_text, $1) as sim "
                    "FROM entity_registry "
                    "WHERE similarity(normalized_text, $1) > 0.2 "
                    "ORDER BY similarity(normalized_text, $1) DESC LIMIT $2",
                    normalized, limit
                )

            for row in rows:
                result = {
                    "uri": row["fuseki_uri"],
                    "name": row["entity_text"],
                    "type": row["entity_type"],
                    "similarity": round(float(row["sim"]), 4),
                    "aliases": row["aliases"] or [],
                }
                qurl = make_quartz_url(row["entity_text"], row["entity_type"])
                if qurl:
                    result["quartz_url"] = qurl
                results.append(result)

        for r in results[:5]:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_relationships "
                "WHERE subject_uri = $1 OR object_uri = $1",
                r["uri"]
            )
            r["relationship_count"] = count

    return {
        "query": query,
        "search_method": search_method,
        "type_filter": type_filter,
        "results": results,
        "count": len(results)
    }




# =============================================================================
# /query Endpoint (Compatible with regen-koi-mcp)
# =============================================================================

class QueryRequest(BaseModel):
    """Query request compatible with regen-koi-mcp format"""
    query: Optional[str] = None
    question: Optional[str] = None  # Alternative field name
    limit: int = 10
    intent: Optional[str] = None
    source: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    published_from: Optional[str] = None
    published_to: Optional[str] = None


@app.post("/query")
async def query_knowledge_base(request: QueryRequest):
    """
    Query endpoint compatible with regen-koi-mcp format.

    This wraps the /search endpoint to provide compatibility with the MCP client.
    Accepts both 'query' and 'question' parameters.

    Example:
        POST /query
        {"query": "hackathon", "limit": 10, "source": "email"}
    """
    # Use query or question parameter
    query_text = request.query or request.question or ""

    if not query_text or query_text == "warmup":
        # Return empty results for warmup or empty queries
        return {"results": [], "count": 0, "query": query_text}

    # Map source filter
    source = request.source
    if request.filters and request.filters.get('source'):
        source = request.filters['source']

    # Call the search endpoint
    search_request = SearchRequest(
        query=query_text,
        limit=request.limit,
        source=source,
        include_chunks=True  # Include chunks for better coverage
    )

    search_result = await search_knowledge_base(search_request)

    # Transform results to match expected format
    results = []
    for r in search_result.get("results", []):
        result = {
            "rid": r.get("rid"),
            "title": r.get("title") or r.get("email", {}).get("subject") or "Untitled",
            "content": r.get("content_preview", ""),
            "similarity": r.get("similarity", 0),
            "source": r.get("source"),
            "url": None,  # Emails don't have URLs
            "published_at": r.get("email", {}).get("date_sent") if r.get("email") else None,
            "metadata": r.get("metadata", {}),
        }

        # Add email-specific fields if present
        if r.get("email"):
            result["email"] = r["email"]

        results.append(result)

    return {
        "results": results,
        "count": len(results),
        "query": query_text,
        "search_type": search_result.get("search_type", "semantic")
    }


# =============================================================================
# Web URL Submission Pipeline (/web/*)
# =============================================================================

class WebPreviewRequest(BaseModel):
    """Request to preview a URL"""
    url: str
    submitted_by: Optional[str] = None
    submitted_via: str = "telegram"
    submission_message: Optional[str] = None


class WebEvaluateRequest(BaseModel):
    """Store Octo's relevance assessment for a previewed URL"""
    url: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    relevance_reasoning: str
    bioregional_tags: List[str] = []
    decision: str = "pending"  # ingest, reject, pending


class WebIngestRequest(BaseModel):
    """Ingest a previewed+evaluated URL into the knowledge graph"""
    url: str
    entities: List[ExtractedEntity] = []
    relationships: List[ExtractedRelationship] = []
    vault_folder: str = "Sources"


class WebProcessRequest(BaseModel):
    """Extract entities and relationships from a previewed URL using LLM"""
    url: str
    hint_entities: List[str] = []
    auto_ingest: bool = True  # Automatically ingest ALL extracted entities


class EntityEnrichRequest(BaseModel):
    """Backfill descriptions for existing entities"""
    entity_uri: Optional[str] = None
    entity_type: Optional[str] = None
    limit: int = 50


@app.post("/web/preview")
async def web_preview(request: WebPreviewRequest):
    """Fetch a URL, extract content, scan for known entities.

    Does NOT ingest — just returns a preview for the agent to evaluate.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    # Rate limit check
    rate_error = await check_rate_limit(db_pool, request.submitted_by)
    if rate_error:
        raise HTTPException(status_code=429, detail=rate_error)

    # Check if URL was already submitted
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, status, title, rid FROM web_submissions WHERE url = $1",
            request.url,
        )
        if existing and existing["status"] in ("ingested",):
            return {
                "already_ingested": True,
                "submission_id": existing["id"],
                "title": existing["title"],
                "rid": existing["rid"],
                "message": "This URL has already been ingested into the knowledge graph.",
            }

    # Validate and fetch
    try:
        preview = await fetch_and_preview(request.url, db_pool)
    except URLValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if preview.fetch_error:
        # Store the failed attempt
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO web_submissions (url, rid, domain, submitted_by, submitted_via,
                    submission_message, status, fetched_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'error', NOW())
                ON CONFLICT DO NOTHING
            """, request.url, preview.rid, preview.domain,
                request.submitted_by, request.submitted_via, request.submission_message)
        raise HTTPException(status_code=422, detail=preview.fetch_error)

    # Store the preview
    import json as json_module
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO web_submissions (
                url, rid, domain, submitted_by, submitted_via, submission_message,
                status, title, description, content_hash, word_count,
                matching_entities, content_text, fetched_at
            ) VALUES ($1, $2, $3, $4, $5, $6, 'previewed', $7, $8, $9, $10, $11::jsonb, $12, NOW())
            ON CONFLICT DO NOTHING
        """, request.url, preview.rid, preview.domain,
            request.submitted_by, request.submitted_via, request.submission_message,
            preview.title, preview.description, preview.content_hash, preview.word_count,
            json_module.dumps([e.to_dict() if hasattr(e, 'to_dict') else {
                "name": e.name, "uri": e.uri, "type": e.entity_type, "context": e.match_context
            } for e in preview.matching_entities]),
            preview.content_text)

    logger.info(f"Web preview: {request.url} -> {preview.title} ({preview.word_count} words, "
                f"{len(preview.matching_entities)} entities)")

    return preview.to_dict()


@app.post("/web/evaluate")
async def web_evaluate(request: WebEvaluateRequest):
    """Store the agent's relevance evaluation for a previewed URL.

    Called by Octo after previewing a URL and deciding whether to ingest.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE web_submissions
            SET relevance_score = $2,
                relevance_reasoning = $3,
                bioregional_tags = $4,
                status = CASE WHEN $5 = 'reject' THEN 'rejected' ELSE 'evaluated' END,
                evaluated_at = NOW()
            WHERE url = $1 AND status = 'previewed'
        """, request.url, request.relevance_score, request.relevance_reasoning,
            request.bioregional_tags, request.decision)

        if result == "UPDATE 0":
            raise HTTPException(
                status_code=404,
                detail="URL not found in previewed state. Preview the URL first."
            )

    status = "rejected" if request.decision == "reject" else "evaluated"
    logger.info(f"Web evaluate: {request.url} -> score={request.relevance_score}, "
                f"status={status}, tags={request.bioregional_tags}")

    return {
        "url": request.url,
        "status": status,
        "relevance_score": request.relevance_score,
        "relevance_reasoning": request.relevance_reasoning,
        "bioregional_tags": request.bioregional_tags,
    }


@app.post("/web/process")
async def web_process(request: WebProcessRequest):
    """Extract entities, relationships, and descriptions from stored content using LLM.

    This is the LLM extraction layer. Sits between /web/preview and /web/ingest.
    Reads full content_text from web_submissions, calls Gemini to extract
    structured data, returns entities + relationships ready for /web/ingest.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if not is_enrichment_available():
        raise HTTPException(
            status_code=503,
            detail="LLM enrichment not configured. Set LLM_ENRICHMENT_ENABLED=true and GEMINI_API_KEY."
        )

    async with db_pool.acquire() as conn:
        submission = await conn.fetchrow(
            "SELECT url, rid, title, description, content_text, status FROM web_submissions WHERE url = $1",
            request.url,
        )

    if not submission:
        raise HTTPException(status_code=404, detail="URL not found. Preview it first with /web/preview.")

    content_text = submission["content_text"]
    if not content_text:
        # Re-fetch content if not stored
        logger.info(f"No content_text for {request.url}, re-fetching...")
        try:
            preview = await fetch_and_preview(request.url)
            content_text = preview.content_text
            if content_text:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE web_submissions SET content_text = $1 WHERE url = $2",
                        content_text, request.url
                    )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"No stored content and re-fetch failed: {e}"
            )

    # Get existing entities for matching context
    existing_entities = []
    if request.hint_entities:
        existing_entities = [{"name": n} for n in request.hint_entities]
    else:
        # Fetch some known entities for context
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT entity_text AS name, entity_type AS type FROM entity_registry ORDER BY entity_text LIMIT 100"
            )
            existing_entities = [{"name": r["name"], "type": r["type"]} for r in rows]

    # Call LLM extraction
    result = await extract_from_content(
        source_content=content_text,
        source_title=submission["title"] or "",
        source_url=request.url,
        existing_entities=existing_entities,
    )

    logger.info(f"Web process: {request.url} -> {len(result.entities)} entities, "
                f"{len(result.relationships)} relationships (model: {result.model_used})")

    ingested_count = 0
    new_entities = 0
    new_relationships = 0
    vault_notes_created = 0

    # Auto-ingest: resolve, store, and create vault notes for ALL extracted entities
    if request.auto_ingest and result.entities:
        rid = submission["rid"]
        document_rid = f"web:{rid}"

        canonical_entities = []

        # Transaction 1: Resolve and store ALL entities (isolated from relationships)
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                for extracted in result.entities:
                    if not extracted.name.strip():
                        continue
                    try:
                        # Build ExtractedEntity-compatible object for resolve_entity
                        entity = ExtractedEntity(
                            name=extracted.name,
                            type=extracted.type,
                            context=extracted.description,
                        )
                        canonical, is_new = await resolve_entity(conn, entity, None)
                        canonical_entities.append((extracted, canonical, is_new))

                        if is_new:
                            await store_new_entity(conn, entity, canonical, document_rid)
                            new_entities += 1

                        # Always update description if we have one and entity lacks it
                        if extracted.description:
                            await conn.execute(
                                """UPDATE entity_registry SET description = $1
                                   WHERE fuseki_uri = $2 AND (description IS NULL OR description = '')""",
                                extracted.description, canonical.uri
                            )

                        # Link entity to document
                        await conn.execute("""
                            INSERT INTO document_entity_links (document_rid, entity_uri, context)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (document_rid, entity_uri)
                            DO UPDATE SET mention_count = document_entity_links.mention_count + 1
                        """, document_rid, canonical.uri, extracted.description)

                        ingested_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to ingest extracted entity {extracted.name}: {e}")

        # Build name→canonical map for relationship resolution
        name_to_canonical = {}
        for extracted, canonical, is_new in canonical_entities:
            name_to_canonical[extracted.name.lower().strip()] = canonical

        # Transaction 2: Store relationships individually (each in its own savepoint)
        async with db_pool.acquire() as conn:
            for rel in result.relationships:
                subj = name_to_canonical.get(rel.subject.lower().strip())
                obj = name_to_canonical.get(rel.object.lower().strip())
                if not subj or not obj:
                    continue
                # Skip self-referencing relationships
                if subj.uri == obj.uri:
                    logger.debug(f"Skipping self-referencing relationship: {rel.subject} -> {rel.predicate} -> {rel.object}")
                    continue
                try:
                    async with conn.transaction():
                        exists = await check_relationship_exists(
                            conn, subj.uri, rel.predicate, obj.uri
                        )
                        if not exists:
                            await conn.execute("""
                                INSERT INTO entity_relationships
                                    (subject_uri, predicate, object_uri, confidence, source, source_rid)
                                VALUES ($1, $2, $3, $4, 'web', $5)
                                ON CONFLICT (subject_uri, predicate, object_uri) DO NOTHING
                            """, subj.uri, rel.predicate, obj.uri, rel.confidence, document_rid)
                            new_relationships += 1
                except Exception as e:
                    logger.warning(f"Failed to store relationship {rel.subject} -> {rel.predicate} -> {rel.object}: {e}")

        # Generate vault notes for ALL entities (new = create, existing = update)
        async with db_pool.acquire() as conn:
            for extracted, canonical, is_new in canonical_entities:
                try:
                    await _generate_entity_vault_note(
                        conn, canonical.name, canonical.type, canonical.uri,
                        description=extracted.description,
                        overwrite=is_new,  # Overwrite if new (may have stale stub)
                    )
                    if is_new:
                        vault_notes_created += 1
                except Exception as e:
                    logger.warning(f"Failed to create vault note for {canonical.name}: {e}")

        # Update submission status
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE web_submissions SET status = 'ingested', ingested_at = NOW() WHERE url = $1 AND status != 'monitoring'",
                request.url
            )

        logger.info(f"Auto-ingest: {ingested_count} entities ({new_entities} new), "
                    f"{new_relationships} relationships, {vault_notes_created} vault notes")

    # Format response
    return {
        "url": request.url,
        "title": submission["title"],
        "summary": result.summary,
        "topics": result.topics,
        "model_used": result.model_used,
        "entities": [
            {
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "fields": e.fields,
                "confidence": e.confidence,
                "context": e.description,
            }
            for e in result.entities
        ],
        "relationships": [
            {
                "subject": r.subject,
                "predicate": r.predicate,
                "object": r.object,
                "confidence": r.confidence,
            }
            for r in result.relationships
        ],
        "ingestion": {
            "auto_ingested": request.auto_ingest,
            "entities_resolved": ingested_count,
            "new_entities": new_entities,
            "new_relationships": new_relationships,
            "vault_notes_created": vault_notes_created,
        } if request.auto_ingest else None,
    }


@app.post("/web/ingest")
async def web_ingest(request: WebIngestRequest):
    """Ingest a previewed+evaluated URL into the knowledge graph.

    1. Resolve entities via existing 3-tier resolution
    2. Create entity relationships
    3. Generate vault note in Sources/ folder
    4. Link document to entities via document_entity_links
    5. Emit KOI-net event if federation enabled
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        # Get the submission record
        submission = await conn.fetchrow(
            "SELECT * FROM web_submissions WHERE url = $1",
            request.url,
        )
        if not submission:
            raise HTTPException(status_code=404, detail="URL not found. Preview it first.")
        if submission["status"] == "ingested":
            return {
                "already_ingested": True,
                "rid": submission["rid"],
                "vault_note_path": submission["vault_note_path"],
                "message": "This URL has already been ingested.",
            }
        if submission["status"] not in ("previewed", "evaluated"):
            raise HTTPException(
                status_code=400,
                detail=f"URL is in '{submission['status']}' state, not ready for ingestion."
            )

    rid = submission["rid"]
    document_rid = f"web:{rid}"

    # Resolve entities
    canonical_entities = []
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            for entity in request.entities:
                try:
                    canonical, is_new = await resolve_entity(conn, entity, None)
                    canonical_entities.append(canonical)

                    if is_new:
                        await store_new_entity(conn, entity, canonical, document_rid)

                    # Link entity to this web document
                    await conn.execute("""
                        INSERT INTO document_entity_links (document_rid, entity_uri, context)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (document_rid, entity_uri)
                        DO UPDATE SET mention_count = document_entity_links.mention_count + 1
                    """, document_rid, canonical.uri, entity.context)

                except Exception as e:
                    logger.warning(f"Failed to resolve entity {entity.name}: {e}")

            # Store relationships
            for rel in request.relationships:
                try:
                    # Find URIs for subject and object
                    subj_uri = None
                    obj_uri = None
                    for ce in canonical_entities:
                        if ce.name.lower() == rel.subject.lower():
                            subj_uri = ce.uri
                        if ce.name.lower() == rel.object.lower():
                            obj_uri = ce.uri

                    if subj_uri and obj_uri:
                        exists = await check_relationship_exists(
                            conn, subj_uri, rel.predicate, obj_uri
                        )
                        if not exists:
                            await conn.execute("""
                                INSERT INTO entity_relationships
                                    (subject_uri, predicate, object_uri, confidence, source, source_rid)
                                VALUES ($1, $2, $3, $4, 'web', $5)
                                ON CONFLICT (subject_uri, predicate, object_uri) DO NOTHING
                            """, subj_uri, rel.predicate, obj_uri, rel.confidence, document_rid)
                except Exception as e:
                    logger.warning(f"Failed to store relationship: {e}")

    # Generate vault note
    vault_path = _generate_source_vault_note(
        submission, canonical_entities, request.vault_folder
    )

    # Create vault notes for newly discovered entities
    source_note_name = vault_path.replace(".md", "")  # e.g. "Sources/SalishSeaio"

    # Build a map of entity name → canonical for relationship lookup
    name_to_canonical = {}
    for ce in canonical_entities:
        name_to_canonical[ce.name.lower()] = ce

    async with db_pool.acquire() as conn:
        for entity, canonical in zip(request.entities, canonical_entities):
            if canonical.is_new:
                await _generate_entity_vault_note(
                    conn, canonical.name, canonical.type, canonical.uri,
                    description=entity.context,
                )

    # Update submission record
    import json as json_module
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE web_submissions
            SET status = 'ingested',
                ingested_at = NOW(),
                vault_note_path = $2,
                ingested_entities = $3::jsonb
            WHERE url = $1
        """, request.url, vault_path,
            json_module.dumps([{"name": ce.name, "uri": ce.uri, "type": ce.type,
                                "is_new": ce.is_new} for ce in canonical_entities]))

    # Emit KOI-net event
    if KOI_NET_ENABLED:
        try:
            from api.koi_net_router import _event_queue
            if _event_queue:
                await _event_queue.add(
                    rid=rid,
                    event_type="NEW",
                    contents={
                        "url": request.url,
                        "@type": "bkc:WebSource",
                        "title": submission["title"],
                        "domain": submission["domain"],
                        "source": "web",
                    },
                )
                logger.info(f"KOI-net event emitted: NEW {rid}")
        except Exception as e:
            logger.warning(f"Failed to emit KOI-net event: {e}")

    logger.info(f"Web ingest: {request.url} -> {len(canonical_entities)} entities, "
                f"vault={vault_path}")

    return {
        "success": True,
        "url": request.url,
        "rid": rid,
        "document_rid": document_rid,
        "vault_note_path": vault_path,
        "entities_resolved": len(canonical_entities),
        "entities": [
            {"name": ce.name, "uri": ce.uri, "type": ce.type, "is_new": ce.is_new}
            for ce in canonical_entities
        ],
    }


def _generate_source_vault_note(
    submission, canonical_entities, vault_folder: str = "Sources"
) -> str:
    """Generate a vault note for an ingested web source.

    Returns the relative vault path (e.g., 'Sources/salishsea_io.md').
    """
    import os as os_module

    vault_base = os.getenv("VAULT_PATH", "/root/.openclaw/workspace/vault")
    domain = submission["domain"]
    title = submission["title"] or domain

    # Create safe filename from title
    safe_name = re.sub(r"[^\w\s-]", "", title)[:60].strip()
    safe_name = re.sub(r"\s+", " ", safe_name).strip()
    if not safe_name:
        safe_name = domain.replace(".", "_")

    rel_path = f"{vault_folder}/{safe_name}.md"
    full_path = os_module.path.join(vault_base, rel_path)

    # Ensure directory exists
    os_module.makedirs(os_module.path.dirname(full_path), exist_ok=True)

    # Build frontmatter
    entity_links = []
    for ce in canonical_entities:
        folder = type_to_folder(ce.type)
        entity_links.append(f"[[{folder}/{ce.name}]]")

    tags = list(submission["bioregional_tags"] or [])

    lines = [
        "---",
        f'"@type": WebSource',
        f"name: \"{title}\"",
        f"url: \"{submission['url']}\"",
        f"domain: \"{domain}\"",
        f"rid: \"{submission['rid']}\"",
    ]
    if submission.get("relevance_score") is not None:
        lines.append(f"relevanceScore: {submission['relevance_score']}")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    if submission.get("submitted_by"):
        lines.append(f"submittedBy: \"{submission['submitted_by']}\"")
    lines.append(f"ingestedAt: \"{datetime.now(timezone.utc).isoformat()}\"")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**URL:** {submission['url']}")
    lines.append(f"**Domain:** {domain}")
    if submission.get("description"):
        lines.append(f"**Description:** {submission['description']}")
    lines.append(f"**Word Count:** {submission.get('word_count', 0)}")
    lines.append("")

    if submission.get("relevance_reasoning"):
        lines.append("## Relevance Assessment")
        lines.append("")
        lines.append(submission["relevance_reasoning"])
        lines.append("")

    if entity_links:
        lines.append("## Connected Entities")
        lines.append("")
        for link in entity_links:
            lines.append(f"- {link}")
        lines.append("")

    content = "\n".join(lines)

    with open(full_path, "w") as f:
        f.write(content)

    logger.info(f"Generated vault note: {rel_path}")
    return rel_path


async def _generate_entity_vault_note(
    conn,
    entity_name: str,
    entity_type: str,
    entity_uri: str,
    description: str = None,
    overwrite: bool = False,
) -> Optional[str]:
    """Generate a vault note for an entity using full DB state.

    Pulls ALL relationships (outgoing + incoming) and ALL mentionedIn links
    from the database to produce a complete, rich vault note.

    Generates notes with:
    - YAML frontmatter: @type, name, description, relationship fields, uri, mentionedIn
    - Wikilinks in frontmatter arrays (for vault_parser.py)
    - ## Relationships body section with wikilinks (for Quartz graph view)
    - Description as body paragraph
    """
    folder = type_to_folder(entity_type)
    safe_name = entity_name.replace("/", "-").replace("\\", "-")
    rel_path = f"{folder}/{safe_name}.md"

    vault_base = os.getenv("VAULT_PATH", "/root/.openclaw/workspace/vault")
    full_path = os.path.join(vault_base, rel_path)

    if os.path.exists(full_path) and not overwrite:
        return rel_path

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # --- Fetch ALL relationships from DB ---
    # Outgoing: this entity is the subject
    outgoing = await conn.fetch(
        """SELECT er2.predicate, t.entity_text as target_text, t.entity_type as target_type
           FROM entity_relationships er2
           JOIN entity_registry t ON t.fuseki_uri = er2.object_uri
           WHERE er2.subject_uri = $1""",
        entity_uri
    )
    # Incoming: this entity is the object
    incoming = await conn.fetch(
        """SELECT er2.predicate, s.entity_text as source_text, s.entity_type as source_type
           FROM entity_relationships er2
           JOIN entity_registry s ON s.fuseki_uri = er2.subject_uri
           WHERE er2.object_uri = $1""",
        entity_uri
    )

    # --- Fetch ALL mentionedIn from DB ---
    doc_links = await conn.fetch(
        """SELECT del.document_rid, ws.title, ws.vault_note_path
           FROM document_entity_links del
           LEFT JOIN web_submissions ws ON ws.rid = REPLACE(del.document_rid, 'web:', '')
           WHERE del.entity_uri = $1""",
        entity_uri
    )

    # --- Map @type ---
    SCHEMA_PREFIX_TYPES = {"Person": "schema:Person", "Organization": "schema:Organization", "Location": "schema:Place"}
    BKC_PREFIX_TYPES = {"Practice", "Pattern", "CaseStudy", "Bioregion", "Protocol", "Playbook", "Question", "Claim", "Evidence"}
    if entity_type in SCHEMA_PREFIX_TYPES:
        at_type = f'"{SCHEMA_PREFIX_TYPES[entity_type]}"'
    elif entity_type in BKC_PREFIX_TYPES:
        at_type = f'"bkc:{entity_type}"'
    else:
        at_type = entity_type

    # --- Build frontmatter ---
    lines = [
        "---",
        f'"@type": {at_type}',
        f'name: "{entity_name}"',
    ]

    if description:
        safe_desc = description.replace('"', '\\"')
        lines.append(f'description: "{safe_desc}"')

    # Group relationships by YAML field name (deduped)
    rel_fields: Dict[str, list] = {}  # field_name -> [wikilinks]
    body_rels = []  # (predicate_display, wikilink)

    for rel in outgoing:
        field_name = PREDICATE_TO_FIELD.get(rel["predicate"], rel["predicate"])
        target_folder = type_to_folder(rel["target_type"])
        wikilink = f'[[{target_folder}/{rel["target_text"]}]]'
        pred_display = rel["predicate"].replace("_", " ")

        rel_fields.setdefault(field_name, [])
        if wikilink not in rel_fields[field_name]:
            rel_fields[field_name].append(wikilink)
        body_rels.append((pred_display, wikilink))

    for rel in incoming:
        field_name = PREDICATE_TO_FIELD.get(rel["predicate"], rel["predicate"])
        source_folder = type_to_folder(rel["source_type"])
        wikilink = f'[[{source_folder}/{rel["source_text"]}]]'
        pred_display = rel["predicate"].replace("_", " ")

        rel_fields.setdefault(field_name, [])
        if wikilink not in rel_fields[field_name]:
            rel_fields[field_name].append(wikilink)
        body_rels.append((f"{pred_display} (from)", wikilink))

    # Write relationship fields to frontmatter
    for field_name, wikilinks in sorted(rel_fields.items()):
        lines.append(f"{field_name}:")
        for wl in sorted(set(wikilinks)):
            lines.append(f'  - "{wl}"')

    lines.append(f'uri: "{entity_uri}"')

    # mentionedIn (sorted, deduped)
    mentioned = []
    for doc in doc_links:
        doc_rid = doc["document_rid"]
        # Web sources: use vault_note_path from web_submissions (matches actual filename)
        if doc_rid.startswith("web:") and doc["vault_note_path"]:
            vpath = doc["vault_note_path"]
            if vpath.endswith(".md"):
                vpath = vpath[:-3]
            mentioned.append(f"[[{vpath}]]")
        elif doc_rid.startswith("vault:"):
            # Vault documents: strip prefix and .md extension
            vpath = doc_rid.replace("vault:", "")
            if vpath.endswith(".md"):
                vpath = vpath[:-3]
            mentioned.append(f"[[{vpath}]]")
        elif doc_rid.startswith("github:"):
            # GitHub documents: not in vault, skip for now
            continue
        else:
            mentioned.append(f"[[{doc_rid}]]")
    if mentioned:
        lines.append("mentionedIn:")
        for m in sorted(set(mentioned)):
            lines.append(f'  - "{m}"')

    lines.append("---")
    lines.append("")
    lines.append(f"# {entity_name}")
    lines.append("")

    # Body: description
    if description:
        lines.append(description)
        lines.append("")

    # Body: relationships section (for Quartz graph rendering)
    if body_rels:
        lines.append("## Relationships")
        lines.append("")
        seen = set()
        for pred_display, wikilink in body_rels:
            key = f"{pred_display}:{wikilink}"
            if key not in seen:
                seen.add(key)
                lines.append(f"- {pred_display}: {wikilink}")
        lines.append("")

    # Body: mentioned in section (visible on Quartz pages)
    if mentioned:
        lines.append("## Mentioned In")
        lines.append("")
        for m in sorted(set(mentioned)):
            lines.append(f"- {m}")
        lines.append("")

    with open(full_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"{'Regenerated' if overwrite else 'Created'} vault note: {rel_path}")
    return rel_path


# =============================================================================
# Entity Enrichment Endpoint (LLM backfill)
# =============================================================================

@app.post("/entity/enrich")
async def entity_enrich(request: EntityEnrichRequest):
    """Backfill descriptions for existing entities using LLM extraction.

    Finds entities without descriptions, looks up their source content,
    and uses LLM to extract descriptions. Groups by source URL for efficiency.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if not is_enrichment_available():
        raise HTTPException(
            status_code=503,
            detail="LLM enrichment not configured. Set LLM_ENRICHMENT_ENABLED=true and GEMINI_API_KEY."
        )

    async with db_pool.acquire() as conn:
        # Find entities without descriptions
        query = """
            SELECT er.fuseki_uri, er.entity_text, er.entity_type,
                   del.document_rid, ws.url, ws.title, ws.content_text
            FROM entity_registry er
            LEFT JOIN document_entity_links del ON del.entity_uri = er.fuseki_uri
            LEFT JOIN web_submissions ws ON ws.rid = REPLACE(del.document_rid, 'web:', '')
            WHERE er.description IS NULL
        """
        params = []
        param_idx = 1

        if request.entity_uri:
            query += f" AND er.fuseki_uri = ${param_idx}"
            params.append(request.entity_uri)
            param_idx += 1
        if request.entity_type:
            query += f" AND er.entity_type = ${param_idx}"
            params.append(request.entity_type)
            param_idx += 1

        query += f" ORDER BY er.entity_type, er.entity_text LIMIT ${param_idx}"
        params.append(request.limit)

        rows = await conn.fetch(query, *params)

    if not rows:
        return {"enriched": 0, "message": "No entities need enrichment"}

    # Group by source URL for batched LLM calls
    by_source: Dict[str, List[Any]] = {}
    for row in rows:
        url = row["url"] or "no_source"
        if url not in by_source:
            by_source[url] = []
        by_source[url].append(row)

    enriched_count = 0
    errors = []

    for source_url, entities in by_source.items():
        content_text = entities[0]["content_text"] if entities[0]["content_text"] else None
        title = entities[0]["title"] or ""

        if not content_text and source_url != "no_source":
            # Re-fetch the URL to get content
            logger.info(f"No content_text for {source_url}, re-fetching...")
            try:
                preview = await fetch_and_preview(source_url)
                content_text = preview.content_text
                title = title or preview.title or ""
                # Store the content for future use
                if content_text:
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE web_submissions SET content_text = $1 WHERE url = $2",
                            content_text, source_url
                        )
                        logger.info(f"Stored {len(content_text)} chars of content_text for {source_url}")
            except Exception as e:
                logger.warning(f"Failed to re-fetch {source_url}: {e}")

        if not content_text:
            logger.info(f"No content available for source {source_url}, skipping {len(entities)} entities")
            continue

        # Extract from this source
        try:
            result = await extract_from_content(
                source_content=content_text,
                source_title=title,
                source_url=source_url if source_url != "no_source" else "",
            )
        except Exception as e:
            errors.append(f"Extraction failed for {source_url}: {e}")
            continue

        # Match extracted descriptions back to entities (exact + fuzzy)
        extracted_by_name = {e.name.lower().strip(): e for e in result.entities}

        async with db_pool.acquire() as conn:
            for row in entities:
                entity_name = row["entity_text"]
                # Exact match first
                extracted = extracted_by_name.get(entity_name.lower().strip())
                # Fuzzy match if no exact match
                if not extracted:
                    from rapidfuzz import fuzz
                    best_score, best_match = 0, None
                    for ext_name, ext_entity in extracted_by_name.items():
                        score = fuzz.ratio(entity_name.lower(), ext_name)
                        if score > best_score:
                            best_score = score
                            best_match = ext_entity
                    if best_score >= 80:
                        extracted = best_match
                        logger.info(f"Fuzzy matched '{entity_name}' → '{best_match.name}' (score={best_score})")

                if extracted and extracted.description:
                    await conn.execute(
                        "UPDATE entity_registry SET description = $1 WHERE fuseki_uri = $2",
                        extracted.description, row["fuseki_uri"]
                    )
                    enriched_count += 1
                    logger.info(f"Enriched: {entity_name} ({row['entity_type']})")

    return {
        "enriched": enriched_count,
        "total_checked": len(rows),
        "sources_processed": len(by_source),
        "errors": errors if errors else None,
    }


class EntityDescribeRequest(BaseModel):
    """Request for batch entity description generation."""
    entity_type: Optional[str] = None  # Filter by type
    limit: int = 30  # Batch size (Gemini handles ~30 well per call)
    regenerate_notes: bool = True  # Also regenerate vault notes


@app.post("/entity/describe")
async def entity_describe(request: EntityDescribeRequest):
    """Generate descriptions for entities using LLM, based on name + type + relationships.

    Unlike /entity/enrich which requires web source content, this endpoint uses
    Gemini's training knowledge plus entity relationships to write descriptions.
    Works for vault-seeded entities that have no web source.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if not is_enrichment_available():
        raise HTTPException(
            status_code=503,
            detail="LLM enrichment not configured. Set LLM_ENRICHMENT_ENABLED=true and GEMINI_API_KEY."
        )

    async with db_pool.acquire() as conn:
        # Find entities without descriptions
        query = """
            SELECT er.fuseki_uri, er.entity_text, er.entity_type
            FROM entity_registry er
            WHERE er.description IS NULL
        """
        params = []
        param_idx = 1

        if request.entity_type:
            query += f" AND er.entity_type = ${param_idx}"
            params.append(request.entity_type)
            param_idx += 1

        query += f" ORDER BY er.entity_type, er.entity_text LIMIT ${param_idx}"
        params.append(request.limit)

        rows = await conn.fetch(query, *params)

    if not rows:
        return {"described": 0, "message": "No entities need descriptions"}

    # Get relationships for each entity
    entity_batch = []
    entity_map = {}  # name → fuseki_uri
    for row in rows:
        rels = []
        if db_pool:
            async with db_pool.acquire() as conn:
                rel_rows = await conn.fetch(
                    """SELECT er2.predicate, er.entity_text as target_text
                       FROM entity_relationships er2
                       JOIN entity_registry er ON er.fuseki_uri = er2.object_uri
                       WHERE er2.subject_uri = $1 LIMIT 10""",
                    row["fuseki_uri"]
                )
                rels = [f"{r['predicate']}: {r['target_text']}" for r in rel_rows]

        entity_batch.append({
            "name": row["entity_text"],
            "type": row["entity_type"],
            "relationships": rels,
        })
        entity_map[row["entity_text"].lower().strip()] = row["fuseki_uri"]

    # Call LLM for batch descriptions
    descriptions = await describe_entities_batch(entity_batch)

    # Store descriptions
    described_count = 0
    async with db_pool.acquire() as conn:
        for name, desc in descriptions.items():
            if not desc or not desc.strip():
                continue
            uri = entity_map.get(name.lower().strip())
            if not uri:
                # Try fuzzy match
                from rapidfuzz import fuzz
                best_score, best_uri = 0, None
                for db_name, db_uri in entity_map.items():
                    score = fuzz.ratio(name.lower(), db_name)
                    if score > best_score:
                        best_score = score
                        best_uri = db_uri
                if best_score >= 80:
                    uri = best_uri

            if uri:
                await conn.execute(
                    "UPDATE entity_registry SET description = $1 WHERE fuseki_uri = $2",
                    desc.strip(), uri
                )
                described_count += 1
                logger.info(f"Described: {name}")

    # Regenerate vault notes if requested
    regenerated = 0
    if request.regenerate_notes and described_count > 0:
        async with db_pool.acquire() as conn:
            for name, desc in descriptions.items():
                uri = entity_map.get(name.lower().strip())
                if not uri:
                    continue
                row = await conn.fetchrow(
                    "SELECT entity_text, entity_type, description FROM entity_registry WHERE fuseki_uri = $1",
                    uri
                )
                if row:
                    try:
                        await _generate_entity_vault_note(conn, row["entity_text"], row["entity_type"], uri, description=row["description"], overwrite=True)
                        regenerated += 1
                    except Exception as e:
                        logger.warning(f"Failed to regenerate note for {name}: {e}")

    return {
        "described": described_count,
        "total_checked": len(rows),
        "notes_regenerated": regenerated,
    }


@app.post("/vault/regenerate")
async def vault_regenerate_all(entity_type: Optional[str] = None, limit: int = 500):
    """Regenerate ALL vault notes from current DB state.

    Pulls complete relationships, descriptions, and mentionedIn from the database
    and overwrites existing vault notes. Useful after bulk ingestion or schema changes.
    """
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    query = "SELECT fuseki_uri, entity_text, entity_type, description FROM entity_registry"
    params = []
    if entity_type:
        query += " WHERE entity_type = $1"
        params.append(entity_type)
    query += f" ORDER BY entity_text LIMIT {limit}"

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    regenerated = 0
    errors = 0
    async with db_pool.acquire() as conn:
        for row in rows:
            try:
                await _generate_entity_vault_note(
                    conn, row["entity_text"], row["entity_type"], row["fuseki_uri"],
                    description=row["description"],
                    overwrite=True,
                )
                regenerated += 1
            except Exception as e:
                logger.warning(f"Failed to regenerate {row['entity_text']}: {e}")
                errors += 1

    return {
        "regenerated": regenerated,
        "errors": errors,
        "total": len(rows),
        "entity_type_filter": entity_type,
    }


# =============================================================================
# GitHub Sensor Endpoints (Phase 5.7)
# =============================================================================

@app.get("/github/status")
async def github_status():
    """Get GitHub sensor status and code entity counts."""
    if not github_sensor:
        return {"enabled": False, "message": "GitHub sensor not enabled"}
    return await github_sensor.get_status()


@app.post("/github/scan")
async def github_trigger_scan(repo_name: Optional[str] = None):
    """Manually trigger a GitHub scan."""
    if not github_sensor:
        raise HTTPException(status_code=503, detail="GitHub sensor not enabled")
    return await github_sensor.trigger_scan(repo_name)


class AddRepoRequest(BaseModel):
    repo_url: str
    repo_name: Optional[str] = None
    branch: str = "main"


@app.post("/github/repos")
async def github_add_repo(request: AddRepoRequest):
    """Add a repository to monitor."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    # Derive repo_name from URL if not provided
    repo_name = request.repo_name
    if not repo_name:
        # Extract "owner/repo" from URL
        match = re.search(r'github\.com[/:]([^/]+/[^/.]+)', request.repo_url)
        if match:
            repo_name = match.group(1)
        else:
            repo_name = request.repo_url.split("/")[-1].replace(".git", "")

    async with db_pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO github_repos (repo_url, repo_name, branch)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (repo_url) DO UPDATE SET
                     branch=EXCLUDED.branch, status='active', updated_at=NOW()
                   RETURNING id, repo_name, status""",
                request.repo_url, repo_name, request.branch,
            )
            return {
                "status": "added",
                "repo_id": row["id"],
                "repo_name": row["repo_name"],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/github/files")
async def github_list_files(repo_name: Optional[str] = None, limit: int = 100):
    """List tracked files from GitHub sensor."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        if repo_name:
            rows = await conn.fetch(
                """SELECT fs.file_path, fs.content_hash, fs.line_count, fs.byte_size,
                          fs.file_type, fs.code_entity_count, fs.scanned_at,
                          r.repo_name
                   FROM github_file_state fs
                   JOIN github_repos r ON r.id = fs.repo_id
                   WHERE r.repo_name = $1
                   ORDER BY fs.file_path
                   LIMIT $2""",
                repo_name, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT fs.file_path, fs.content_hash, fs.line_count, fs.byte_size,
                          fs.file_type, fs.code_entity_count, fs.scanned_at,
                          r.repo_name
                   FROM github_file_state fs
                   JOIN github_repos r ON r.id = fs.repo_id
                   ORDER BY r.repo_name, fs.file_path
                   LIMIT $1""",
                limit,
            )

    return {
        "files": [dict(r) for r in rows],
        "count": len(rows),
    }


class CodeQueryRequest(BaseModel):
    cypher: str = "MATCH (n) RETURN labels(n), count(n)"


@app.post("/code/query")
async def code_graph_query(request: CodeQueryRequest):
    """Run a Cypher query against the code knowledge graph."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        from api.code_graph import query_code_graph
        async with db_pool.acquire() as conn:
            results = await query_code_graph(conn, request.cypher)
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Web Sensor Endpoints
# =============================================================================

class WebMonitorRequest(BaseModel):
    url: str
    title: str = ""


@app.get("/web/monitor/status")
async def web_monitor_status():
    """Get web sensor monitoring status."""
    if not web_sensor:
        return {"enabled": False, "message": "Web sensor not enabled. Set WEB_SENSOR_ENABLED=true."}
    return await web_sensor.get_status()


@app.post("/web/monitor/add")
async def web_monitor_add(request: WebMonitorRequest):
    """Add a URL to the monitoring list."""
    if not web_sensor:
        raise HTTPException(status_code=503, detail="Web sensor not enabled")
    return await web_sensor.add_url(request.url, request.title)


@app.post("/web/monitor/remove")
async def web_monitor_remove(request: WebMonitorRequest):
    """Remove a URL from monitoring."""
    if not web_sensor:
        raise HTTPException(status_code=503, detail="Web sensor not enabled")
    return await web_sensor.remove_url(request.url)


@app.post("/web/monitor/scan")
async def web_monitor_trigger_scan():
    """Manually trigger a scan of all monitored URLs."""
    if not web_sensor:
        raise HTTPException(status_code=503, detail="Web sensor not enabled")
    asyncio.create_task(web_sensor._check_all_sources())
    return {"status": "scan_triggered"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('KOI_API_PORT', '8351'))
    uvicorn.run(app, host="0.0.0.0", port=port)
