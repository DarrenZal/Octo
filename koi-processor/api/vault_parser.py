#!/usr/bin/env python3
"""
Vault YAML Parser for Relationship Extraction

Parses Obsidian vault YAML frontmatter to extract relationships between entities.
Maps vault field names (affiliation, memberOf, founder, etc.) to canonical predicates.

Key Features:
- Case-insensitive field mapping
- Robust wikilink parsing (multiple formats)
- Batch entity resolution (avoids N+1 queries)
- Replace-all sync strategy (atomic via transaction)
- Pending relationships for unresolved targets
- Symmetric predicate handling (knows → both directions)
"""

import re
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import asyncpg

logger = logging.getLogger(__name__)

# =============================================================================
# Predicate Mapping
# =============================================================================

# Case-insensitive field mapping: vault YAML field → (predicate, direction, default_type_hint)
# Direction: 'outgoing' = subject is current entity, 'incoming' = object is current entity
FIELD_TO_PREDICATE: Dict[str, Tuple[str, str, Optional[str]]] = {
    # Person → Organization
    'affiliation': ('affiliated_with', 'outgoing', 'Organization'),
    'memberof': ('affiliated_with', 'outgoing', 'Organization'),
    'organization': ('affiliated_with', 'outgoing', 'Organization'),
    'organizations': ('affiliated_with', 'outgoing', 'Organization'),

    # Person → Organization/Project (founding)
    'founder': ('founded', 'outgoing', None),
    'founderof': ('founded', 'outgoing', None),

    # Organization/Project → Person (has founder - inverse)
    'founders': ('has_founder', 'incoming', 'Person'),

    # Person → Person
    'knows': ('knows', 'outgoing', 'Person'),
    'friendswith': ('knows', 'outgoing', 'Person'),
    'collaborateswith': ('collaborates_with', 'outgoing', 'Person'),
    'collaborators': ('collaborates_with', 'outgoing', 'Person'),

    # Project → Organization
    # Note: 'organizations' in Project context goes to involves_organization
    # But we already have it mapped to affiliated_with for Person
    # The type context will determine which applies

    # Project → Person
    'people': ('involves_person', 'outgoing', 'Person'),
    'participants': ('involves_person', 'outgoing', 'Person'),
    'members': ('involves_person', 'outgoing', 'Person'),

    # Organization → Project
    'projects': ('has_project', 'outgoing', 'Project'),

    # Meeting → Person (attendees)
    'attendees': ('attended', 'incoming', 'Person'),  # Person attended Meeting

    # Location relationships
    'location': ('located_in', 'outgoing', 'Location'),
    'headquarters': ('located_in', 'outgoing', 'Location'),

    # Project → Organization (parent org)
    'parentorg': ('involves_organization', 'outgoing', 'Organization'),

    # Project → Person (creator - same as founder semantically)
    'creator': ('has_founder', 'incoming', 'Person'),
    'lead': ('involves_person', 'outgoing', 'Person'),

    # Phase A: Knowledge Commoning
    'aggregatesinto': ('aggregates_into', 'outgoing', 'Pattern'),
    'aggregates_into': ('aggregates_into', 'outgoing', 'Pattern'),
    'patterns': ('aggregates_into', 'outgoing', 'Pattern'),
    'suggests': ('suggests', 'outgoing', 'Practice'),
    'suggestedby': ('suggests', 'incoming', 'Pattern'),
    'bioregion': ('practiced_in', 'outgoing', 'Bioregion'),
    'practicedin': ('practiced_in', 'outgoing', 'Bioregion'),
    'practiced_in': ('practiced_in', 'outgoing', 'Bioregion'),
    'documentedby': ('documents', 'incoming', 'CaseStudy'),
    'documented_by': ('documents', 'incoming', 'CaseStudy'),
    'documents': ('documents', 'outgoing', None),
    'practices': ('aggregates_into', 'incoming', 'Practice'),

    # Phase B: Discourse Graph
    'supports': ('supports', 'outgoing', None),
    'opposes': ('opposes', 'outgoing', None),
    'informs': ('informs', 'outgoing', None),
    'generates': ('generates', 'outgoing', None),
    'implementedby': ('implemented_by', 'outgoing', 'Playbook'),
    'implemented_by': ('implemented_by', 'outgoing', 'Playbook'),
    'implements': ('implemented_by', 'incoming', 'Protocol'),
    'synthesizes': ('synthesizes', 'outgoing', 'Evidence'),
    'protocol': ('implemented_by', 'incoming', 'Protocol'),
    'about': ('about', 'outgoing', None),

    # Phase C: SKOS + Hyphal
    'broader': ('broader', 'outgoing', 'Concept'),
    'narrower': ('narrower', 'outgoing', 'Concept'),
    'relatedto': ('related_to', 'outgoing', None),
    'related_to': ('related_to', 'outgoing', None),
    'forkedfrom': ('forked_from', 'outgoing', None),
    'forked_from': ('forked_from', 'outgoing', None),
    'buildson': ('builds_on', 'outgoing', None),
    'builds_on': ('builds_on', 'outgoing', None),
    'inspiredby': ('inspired_by', 'outgoing', None),
    'inspired_by': ('inspired_by', 'outgoing', None),
}

# Symmetric predicates: when A knows B, also create B knows A
SYMMETRIC_PREDICATES = {'knows', 'collaborates_with'}

# Reverse mapping: predicate → preferred YAML field name for vault note generation
# Picks the most natural/readable field name for each predicate
PREDICATE_TO_FIELD: Dict[str, str] = {
    'affiliated_with': 'affiliation',
    'founded': 'founder',
    'has_founder': 'founders',
    'knows': 'knows',
    'collaborates_with': 'collaborators',
    'involves_person': 'people',
    'has_project': 'projects',
    'attended': 'attendees',
    'located_in': 'location',
    'involves_organization': 'parentOrg',
    'aggregates_into': 'patterns',
    'suggests': 'suggests',
    'practiced_in': 'bioregion',
    'documents': 'documents',
    'supports': 'supports',
    'opposes': 'opposes',
    'informs': 'informs',
    'generates': 'generates',
    'implemented_by': 'implementedBy',
    'synthesizes': 'synthesizes',
    'about': 'about',
    'broader': 'broader',
    'narrower': 'narrower',
    'related_to': 'relatedTo',
    'forked_from': 'forkedFrom',
    'builds_on': 'buildsOn',
    'inspired_by': 'inspiredBy',
}


# =============================================================================
# Wikilink Parsing
# =============================================================================

def parse_wikilink(value: str) -> Tuple[str, Optional[str]]:
    """
    Parse various wikilink formats, return (name, type_hint).

    Handles:
    - [[Organizations/Regen Network]] → ("Regen Network", "Organization")
    - [[People/Shawn Anderson|Shawn]] → ("Shawn Anderson", "Person")
    - [[Regen Network]] → ("Regen Network", None)
    - organizations/open-civics → ("open civics", "Organization")
    - "Regen Network" → ("Regen Network", None)

    Returns:
        Tuple of (entity_name, type_hint or None)
    """
    value = value.strip().strip('"').strip("'")

    if not value:
        return ('', None)

    # Handle [[path/name|alias]] format - extract path, ignore alias
    match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', value)
    if match:
        path = match.group(1)
    else:
        # Handle bare path: organizations/open-civics
        path = value

    # Extract type hint from path prefix
    type_hint = None
    if '/' in path:
        folder, name = path.rsplit('/', 1)
        folder_lower = folder.lower()

        # Map folder names to entity types
        folder_type_map = {
            'people': 'Person',
            'person': 'Person',
            'organizations': 'Organization',
            'organization': 'Organization',
            'orgs': 'Organization',
            'projects': 'Project',
            'project': 'Project',
            'locations': 'Location',
            'location': 'Location',
            'places': 'Location',
            'concepts': 'Concept',
            'concept': 'Concept',
            'practices': 'Practice',
            'practice': 'Practice',
            'patterns': 'Pattern',
            'pattern': 'Pattern',
            'casestudies': 'CaseStudy',
            'casestudy': 'CaseStudy',
            'bioregions': 'Bioregion',
            'bioregion': 'Bioregion',
            'protocols': 'Protocol',
            'protocol': 'Protocol',
            'playbooks': 'Playbook',
            'playbook': 'Playbook',
            'questions': 'Question',
            'question': 'Question',
            'claims': 'Claim',
            'claim': 'Claim',
            'evidence': 'Evidence',
        }
        type_hint = folder_type_map.get(folder_lower)
    else:
        name = path

    # Normalize: convert kebab-case to spaces, preserve original case
    # Entity resolution handles case-insensitivity
    name = name.replace('-', ' ') if '-' in name else name

    return name.strip(), type_hint


def parse_yaml_values(value: Any) -> List[str]:
    """
    Parse YAML field value into list of strings.

    Handles:
    - List: ["a", "b"]
    - CSV string: "a, b, c"
    - Quoted list string: "[[a]], [[b]]"
    - Single value: "a"

    Returns:
        List of string values
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [str(v).strip() for v in value if v]

    if isinstance(value, str):
        # Check if it's a comma-separated string with wikilinks
        if '[[' in value and ']]' in value:
            # Split on ]], but keep the brackets
            parts = re.split(r'\]\]\s*,\s*', value)
            result = []
            for p in parts:
                if p:
                    # Add closing brackets if they were stripped
                    if not p.endswith(']]'):
                        p = p + ']]'
                    result.append(p)
            return result
        # Simple CSV
        return [v.strip() for v in value.split(',') if v.strip()]

    return [str(value)] if value else []


# =============================================================================
# Entity Resolution (Batch)
# =============================================================================

async def batch_resolve_entities(
    conn: asyncpg.Connection,
    targets: List[Tuple[str, Optional[str]]]  # [(name, type_hint), ...]
) -> Dict[Tuple[str, Optional[str]], str]:
    """
    Resolve multiple entity names in one query.

    Args:
        conn: Database connection
        targets: List of (name, type_hint) tuples to resolve

    Returns:
        Dict mapping (name.lower(), type_hint) → fuseki_uri

    Uses (normalized_text, entity_type) when type_hint is provided, otherwise name-only.
    This avoids collisions when entities share a name across types.
    """
    if not targets:
        return {}

    # Separate targets with and without type hints
    typed_targets = [(n.lower(), t) for n, t in targets if t]
    untyped_names = list(set(n.lower() for n, t in targets if not t))

    result: Dict[Tuple[str, Optional[str]], str] = {}

    # Resolve typed targets (more precise)
    if typed_targets:
        # Build VALUES clause for typed lookup
        values_clause = ', '.join(
            f"('{n.replace(chr(39), chr(39)+chr(39))}', '{t}')"  # Escape single quotes
            for n, t in typed_targets
        )
        rows = await conn.fetch(f"""
            SELECT e.normalized_text, e.entity_type, e.fuseki_uri
            FROM entity_registry e
            JOIN (VALUES {values_clause}) AS t(name, type)
            ON e.normalized_text = t.name AND e.entity_type = t.type
        """)
        for row in rows:
            result[(row['normalized_text'], row['entity_type'])] = row['fuseki_uri']

    # Resolve untyped targets (fall back to name-only, first match wins)
    if untyped_names:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (normalized_text) normalized_text, fuseki_uri
            FROM entity_registry
            WHERE normalized_text = ANY($1)
            ORDER BY normalized_text, occurrence_count DESC NULLS LAST
        """, untyped_names)
        for row in rows:
            result[(row['normalized_text'], None)] = row['fuseki_uri']

    return result


# =============================================================================
# Relationship Insertion
# =============================================================================

async def insert_relationship_with_symmetric(
    conn: asyncpg.Connection,
    subject_uri: str,
    predicate: str,
    object_uri: str,
    vault_path: str,
    field_key: str,
    raw_value: str
) -> None:
    """
    Insert relationship, and if symmetric, also insert the inverse.

    Args:
        conn: Database connection
        subject_uri: Subject entity URI
        predicate: Canonical predicate name
        object_uri: Object entity URI
        vault_path: Source vault file path
        field_key: Original YAML field name
        raw_value: Original raw value from YAML
    """
    # Insert primary relationship
    await conn.execute("""
        INSERT INTO entity_relationships
        (subject_uri, predicate, object_uri, source, source_rid, source_field, raw_value)
        VALUES ($1, $2, $3, 'vault', $4, $5, $6)
        ON CONFLICT (subject_uri, predicate, object_uri) DO UPDATE
        SET updated_at = NOW(), source_field = $5, raw_value = $6
    """, subject_uri, predicate, object_uri, vault_path, field_key, raw_value)

    # Insert symmetric relationship if applicable
    if predicate in SYMMETRIC_PREDICATES and subject_uri != object_uri:
        await conn.execute("""
            INSERT INTO entity_relationships
            (subject_uri, predicate, object_uri, source, source_rid, source_field, raw_value)
            VALUES ($1, $2, $3, 'vault', $4, $5, $6)
            ON CONFLICT (subject_uri, predicate, object_uri) DO NOTHING
        """, object_uri, predicate, subject_uri, vault_path, f"{field_key}_symmetric", raw_value)


# =============================================================================
# Main Sync Function
# =============================================================================

async def sync_vault_relationships(
    conn: asyncpg.Connection,
    vault_path: str,
    entity_uri: str,
    frontmatter: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract relationships from vault YAML and store in database.

    Uses replace-all strategy: delete existing, then re-insert.
    Wrapped in transaction for atomicity (caller should use conn.transaction()).

    Args:
        conn: Database connection (should be in a transaction)
        vault_path: Path to vault file (e.g., "People/Shawn Anderson.md")
        entity_uri: Canonical URI of the entity being synced
        frontmatter: Parsed YAML frontmatter dict

    Returns:
        Dict with sync statistics
    """
    stats = {
        'resolved': 0,
        'pending': 0,
        'skipped': 0,
        'deleted_old': 0
    }

    # Step 1: Delete existing relationships from this file
    deleted_rels = await conn.execute("""
        DELETE FROM entity_relationships WHERE source_rid = $1
    """, vault_path)
    deleted_pending = await conn.execute("""
        DELETE FROM pending_relationships WHERE source_rid = $1
    """, vault_path)

    # Parse deletion counts
    try:
        stats['deleted_old'] = int(deleted_rels.split()[-1]) + int(deleted_pending.split()[-1])
    except (ValueError, IndexError):
        pass

    # Step 2: Collect all target names first (for batch resolution)
    targets_to_process: List[Tuple[str, Optional[str], str, str, str, str]] = []
    # Structure: (target_name, type_hint, field_key, predicate, direction, raw_value)

    for field_key, field_value in frontmatter.items():
        field_lower = field_key.lower()
        if field_lower not in FIELD_TO_PREDICATE:
            continue

        predicate, direction, default_type_hint = FIELD_TO_PREDICATE[field_lower]
        values = parse_yaml_values(field_value)

        for raw_value in values:
            target_name, type_hint = parse_wikilink(raw_value)
            if not target_name:
                continue
            type_hint = type_hint or default_type_hint
            targets_to_process.append((target_name, type_hint, field_key, predicate, direction, raw_value))

    if not targets_to_process:
        return stats

    # Step 3: Batch resolve all targets in one query
    target_tuples = list(set((t[0], t[1]) for t in targets_to_process))
    resolved_uris = await batch_resolve_entities(conn, target_tuples)

    # Step 4: Insert relationships using resolved URIs
    for target_name, type_hint, field_key, predicate, direction, raw_value in targets_to_process:
        # Try typed match first, then fall back to untyped
        target_uri = resolved_uris.get((target_name.lower(), type_hint))
        if not target_uri and type_hint:
            target_uri = resolved_uris.get((target_name.lower(), None))

        # Determine subject/object based on direction
        if direction == 'outgoing':
            subject_uri, object_uri = entity_uri, target_uri
        else:  # incoming
            subject_uri, object_uri = target_uri, entity_uri

        if target_uri:
            # Target exists - insert resolved relationship
            try:
                await insert_relationship_with_symmetric(
                    conn, subject_uri, predicate, object_uri, vault_path, field_key, raw_value
                )
                stats['resolved'] += 1
            except Exception as e:
                logger.warning(f"Failed to insert relationship: {e}")
                stats['skipped'] += 1
        else:
            # Target missing - store as pending
            try:
                if direction == 'outgoing':
                    await conn.execute("""
                        INSERT INTO pending_relationships
                        (subject_uri, predicate, raw_unknown_label, unknown_side, target_type_hint, source, source_rid, source_field)
                        VALUES ($1, $2, $3, 'object', $4, 'vault', $5, $6)
                        ON CONFLICT DO NOTHING
                    """, entity_uri, predicate, target_name, type_hint, vault_path, field_key)
                else:  # incoming: current entity is object, unknown target is subject
                    await conn.execute("""
                        INSERT INTO pending_relationships
                        (object_uri, predicate, raw_unknown_label, unknown_side, target_type_hint, source, source_rid, source_field)
                        VALUES ($1, $2, $3, 'subject', $4, 'vault', $5, $6)
                        ON CONFLICT DO NOTHING
                    """, entity_uri, predicate, target_name, type_hint, vault_path, field_key)
                stats['pending'] += 1
            except Exception as e:
                logger.warning(f"Failed to insert pending relationship: {e}")
                stats['skipped'] += 1

    logger.info(f"Synced relationships from {vault_path}: "
                f"resolved={stats['resolved']}, pending={stats['pending']}, skipped={stats['skipped']}")

    return stats


# =============================================================================
# Pending Resolution
# =============================================================================

async def resolve_pending_relationships(
    conn: asyncpg.Connection,
    new_entity_uri: str,
    entity_name: str,
    entity_type: str
) -> int:
    """
    Promote pending relationships when their target gets registered.

    Uses fuzzy matching (not just exact) since pending labels may have slight variations.
    E.g., "Regen Network" might match pending "Regen Network Inc."

    Applies "top-1 + margin" rule: only promote if best match >= 0.85 AND
    (no second match OR best - second >= 0.05). This prevents ambiguous promotions.

    Args:
        conn: Database connection
        new_entity_uri: URI of the newly registered entity
        entity_name: Name of the new entity
        entity_type: Type of the new entity

    Returns:
        Number of pending relationships promoted
    """
    # Find pending relationships that might match this new entity
    # Use similarity() for fuzzy matching (requires pg_trgm extension)
    pending = await conn.fetch("""
        SELECT id, subject_uri, object_uri, predicate, raw_unknown_label, unknown_side,
               target_type_hint, source_rid, source_field,
               similarity(LOWER(raw_unknown_label), LOWER($1)) as sim
        FROM pending_relationships
        WHERE similarity(LOWER(raw_unknown_label), LOWER($1)) >= 0.8
        AND (target_type_hint IS NULL OR target_type_hint = $2)
        ORDER BY sim DESC
    """, entity_name, entity_type)

    if not pending:
        return 0

    # Apply top-1 + margin rule
    best_sim = pending[0]['sim']
    if best_sim < 0.85:
        logger.info(f"Pending promotion skipped: best sim {best_sim:.2f} < 0.85 for {entity_name}")
        return 0

    # Check margin if there are multiple matches
    if len(pending) > 1:
        second_sim = pending[1]['sim']
        margin = best_sim - second_sim
        if margin < 0.05:
            logger.warning(f"Pending promotion skipped: ambiguous match for {entity_name} "
                          f"(best={best_sim:.2f}, second={second_sim:.2f}, margin={margin:.2f})")
            return 0

    # Only promote the top match
    row = pending[0]

    # Determine subject/object based on which side was unknown
    if row['unknown_side'] == 'object':
        subject_uri = row['subject_uri']
        object_uri = new_entity_uri
    else:  # unknown_side == 'subject'
        subject_uri = new_entity_uri
        object_uri = row['object_uri']

    try:
        # Insert resolved relationship (with symmetric handling)
        await insert_relationship_with_symmetric(
            conn, subject_uri, row['predicate'], object_uri,
            row['source_rid'], row['source_field'], row['raw_unknown_label']
        )

        # Delete from pending
        await conn.execute("DELETE FROM pending_relationships WHERE id = $1", row['id'])

        logger.info(f"Promoted pending relationship for {entity_name} "
                   f"(sim: {row['sim']:.2f}, predicate: {row['predicate']})")
        return 1

    except Exception as e:
        logger.warning(f"Failed to promote pending relationship: {e}")
        return 0


# =============================================================================
# Utility Functions
# =============================================================================

async def get_entity_relationships(
    conn: asyncpg.Connection,
    entity_uri: str,
    predicate: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all relationships for an entity (both directions).

    Args:
        conn: Database connection
        entity_uri: Entity URI to lookup
        predicate: Optional predicate filter

    Returns:
        List of relationship dicts
    """
    if predicate:
        rows = await conn.fetch("""
            SELECT subject_uri, predicate, object_uri, confidence, source, source_rid
            FROM entity_relationships
            WHERE (subject_uri = $1 OR object_uri = $1)
            AND predicate = $2
            ORDER BY confidence DESC
        """, entity_uri, predicate)
    else:
        rows = await conn.fetch("""
            SELECT subject_uri, predicate, object_uri, confidence, source, source_rid
            FROM entity_relationships
            WHERE subject_uri = $1 OR object_uri = $1
            ORDER BY predicate, confidence DESC
        """, entity_uri)

    return [dict(r) for r in rows]


async def check_relationship_exists(
    conn: asyncpg.Connection,
    subject_uri: str,
    predicate: str,
    object_uri: str
) -> bool:
    """Check if a specific relationship exists."""
    return await conn.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM entity_relationships
            WHERE subject_uri = $1 AND predicate = $2 AND object_uri = $3
        )
    """, subject_uri, predicate, object_uri)
