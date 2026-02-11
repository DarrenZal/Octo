#!/usr/bin/env python3
"""
Regenerate entity vault notes with rich content.

Queries the DB for all entities and their relationships, then regenerates
vault notes that are stubs (< 5 non-empty lines in body). Preserves
existing rich notes.

Usage:
    cd ~/koi-processor
    venv/bin/python scripts/regenerate_vault_notes.py \
        --db-url postgresql://postgres:PASSWORD@localhost:5432/octo_koi

    # Dry run (default) - shows what would change:
    venv/bin/python scripts/regenerate_vault_notes.py --db-url ...

    # Actually write files:
    venv/bin/python scripts/regenerate_vault_notes.py --db-url ... --apply

    # Enrich entities missing descriptions via LLM before regenerating:
    venv/bin/python scripts/regenerate_vault_notes.py --db-url ... --apply --enrich
"""

import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import asyncpg

# Add parent to path so we can import from api/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.vault_parser import PREDICATE_TO_FIELD
from api.entity_schema import type_to_folder


# Same type mappings as in personal_ingest_api.py
SCHEMA_PREFIX_TYPES = {
    "Person": '"schema:Person"',
    "Organization": '"schema:Organization"',
    "Location": '"schema:Place"',
}
BKC_PREFIX_TYPES = {
    "Practice", "Pattern", "CaseStudy", "Bioregion", "Protocol",
    "Playbook", "Question", "Claim", "Evidence",
}


def format_at_type(entity_type: str) -> str:
    if entity_type in SCHEMA_PREFIX_TYPES:
        return SCHEMA_PREFIX_TYPES[entity_type]
    elif entity_type in BKC_PREFIX_TYPES:
        return f'"bkc:{entity_type}"'
    return entity_type


def is_stub_note(filepath: str) -> bool:
    """Check if a vault note is a stub (body has < 5 non-empty lines)."""
    if not os.path.exists(filepath):
        return True  # Missing = definitely regenerate

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Split on frontmatter
    parts = content.split("---")
    if len(parts) < 3:
        return True  # No proper frontmatter

    body = "---".join(parts[2:]).strip()
    non_empty_lines = [line for line in body.split("\n") if line.strip()]

    return len(non_empty_lines) < 5


def generate_note_content(
    entity: dict,
    relationships: List[dict],
    mentioned_in: List[str],
) -> str:
    """Generate rich vault note content for an entity."""
    name = entity["label"]
    entity_type = entity["entity_type"]
    uri = entity["uri"]
    description = entity.get("description")

    at_type = format_at_type(entity_type)

    lines = [
        "---",
        f'"@type": {at_type}',
        f'name: "{name}"',
    ]

    if description:
        safe_desc = description.replace('"', '\\"')
        lines.append(f'description: "{safe_desc}"')

    # Group relationships by predicate field for frontmatter
    rel_fields: Dict[str, List[str]] = defaultdict(list)
    body_relationships: List[Tuple[str, str, str, str]] = []

    for rel in relationships:
        predicate = rel["predicate"]
        is_subject = rel["is_subject"]
        target_name = rel["target_name"]
        target_type = rel["target_type"]

        field_name = PREDICATE_TO_FIELD.get(predicate, predicate)
        target_folder = type_to_folder(target_type) if target_type else None
        wikilink = f"[[{target_folder}/{target_name}]]" if target_folder else f"[[{target_name}]]"

        rel_fields[field_name].append(wikilink)

        label = predicate.replace("_", " ")
        direction = "" if is_subject else " (inverse)"
        body_relationships.append((f"{label}{direction}", target_name, target_type, target_folder))

    # Write relationship fields in frontmatter
    for field_name, wikilinks in sorted(rel_fields.items()):
        lines.append(f"{field_name}:")
        for wl in sorted(set(wikilinks)):
            lines.append(f'  - "{wl}"')

    lines.append(f'uri: "{uri}"')

    if mentioned_in:
        lines.append("mentionedIn:")
        for doc in sorted(mentioned_in):
            lines.append(f'  - "[[{doc}]]"')

    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")

    # Description paragraph in body
    if description:
        lines.append(description)
        lines.append("")

    # Relationships section with wikilinks (makes Quartz graph work)
    if body_relationships:
        lines.append("## Relationships")
        lines.append("")
        for label, target_name, target_type, target_folder in body_relationships:
            if target_folder:
                lines.append(f"- {label}: [[{target_folder}/{target_name}]]")
            else:
                lines.append(f"- {label}: [[{target_name}]]")
        lines.append("")

    return "\n".join(lines)


async def enrich_entities(conn: asyncpg.Connection, limit: int = 50) -> int:
    """Enrich entities missing descriptions via LLM extraction.

    Groups entities by source URL to batch LLM calls efficiently.
    Returns number of entities enriched.
    """
    from api.llm_enricher import extract_from_content, is_enrichment_available

    if not is_enrichment_available():
        print("  LLM enrichment not available (check LLM_ENRICHMENT_ENABLED and VERTEX_PROJECT_ID)")
        return 0

    # Find entities without descriptions that have web source content
    rows = await conn.fetch("""
        SELECT er.fuseki_uri, er.entity_text, er.entity_type,
               del.document_rid, ws.url, ws.title, ws.content_text
        FROM entity_registry er
        LEFT JOIN document_entity_links del ON del.entity_uri = er.fuseki_uri
        LEFT JOIN web_submissions ws ON ws.rid = REPLACE(del.document_rid, 'web:', '')
        WHERE er.description IS NULL
        AND ws.content_text IS NOT NULL
        ORDER BY er.entity_type, er.entity_text
        LIMIT $1
    """, limit)

    if not rows:
        print("  No entities need enrichment (all have descriptions or no source content)")
        return 0

    # Group by source URL
    by_source: Dict[str, list] = {}
    for row in rows:
        url = row["url"] or "no_source"
        if url not in by_source:
            by_source[url] = []
        by_source[url].append(row)

    enriched = 0
    for source_url, entities in by_source.items():
        content_text = entities[0]["content_text"]
        title = entities[0]["title"] or ""

        print(f"  Extracting from: {title or source_url} ({len(entities)} entities)...")

        try:
            result = await extract_from_content(
                source_content=content_text,
                source_title=title,
                source_url=source_url if source_url != "no_source" else "",
            )
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        # Match extracted descriptions back to entities
        extracted_by_name = {e.name.lower(): e for e in result.entities}

        for row in entities:
            entity_name = row["entity_text"]
            extracted = extracted_by_name.get(entity_name.lower())

            if extracted and extracted.description:
                await conn.execute(
                    "UPDATE entity_registry SET description = $1 WHERE fuseki_uri = $2",
                    extracted.description, row["fuseki_uri"]
                )
                enriched += 1
                print(f"    Enriched: {entity_name}")

    return enriched


async def main():
    parser = argparse.ArgumentParser(description="Regenerate stub entity vault notes")
    parser.add_argument("--db-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--vault-path", default="/root/.openclaw/workspace/vault",
                        help="Path to vault directory")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write files (default is dry run)")
    parser.add_argument("--enrich", action="store_true",
                        help="Use LLM to backfill missing entity descriptions before regenerating")
    parser.add_argument("--enrich-limit", type=int, default=50,
                        help="Max entities to enrich per run (default 50)")
    args = parser.parse_args()

    conn = await asyncpg.connect(args.db_url)

    try:
        # Enrich entities via LLM if requested
        if args.enrich:
            print("Enriching entities via LLM...")
            enriched = await enrich_entities(conn, args.enrich_limit)
            print(f"  Enriched {enriched} entities\n")

        # Get all entities (including description)
        entities = await conn.fetch("""
            SELECT fuseki_uri AS uri, entity_text AS label, entity_type, description
            FROM entity_registry
            ORDER BY entity_type, entity_text
        """)
        print(f"Found {len(entities)} entities in database")

        # Get all relationships
        all_rels = await conn.fetch("""
            SELECT
                er.subject_uri, er.predicate, er.object_uri,
                s.entity_text AS subject_label, s.entity_type AS subject_type,
                o.entity_text AS object_label, o.entity_type AS object_type
            FROM entity_relationships er
            JOIN entity_registry s ON s.fuseki_uri = er.subject_uri
            JOIN entity_registry o ON o.fuseki_uri = er.object_uri
        """)
        print(f"Found {len(all_rels)} relationships")

        # Build relationship lookup by entity URI
        rels_by_entity: Dict[str, List[dict]] = defaultdict(list)
        for rel in all_rels:
            # For subject entity: outgoing relationship
            rels_by_entity[rel["subject_uri"]].append({
                "predicate": rel["predicate"],
                "is_subject": True,
                "target_name": rel["object_label"],
                "target_type": rel["object_type"],
            })
            # For object entity: incoming relationship
            rels_by_entity[rel["object_uri"]].append({
                "predicate": rel["predicate"],
                "is_subject": False,
                "target_name": rel["subject_label"],
                "target_type": rel["subject_type"],
            })

        # Get document-entity links for mentionedIn
        doc_links = await conn.fetch("""
            SELECT entity_uri, document_rid
            FROM document_entity_links
        """)
        mentions_by_entity: Dict[str, List[str]] = defaultdict(list)
        for link in doc_links:
            rid = link["document_rid"]
            # Convert document_rid to vault-style reference
            # "web:ws_xxx" -> use the vault_note_path from web_submissions
            # "vault:notes/xxx" -> use as-is
            if rid.startswith("vault:"):
                doc_name = rid[len("vault:"):]
            elif rid.startswith("web:"):
                # Look up the vault note path
                sub = await conn.fetchrow(
                    "SELECT vault_note_path FROM web_submissions WHERE rid = $1",
                    rid.replace("web:", ""),
                )
                if sub and sub["vault_note_path"]:
                    doc_name = sub["vault_note_path"].replace(".md", "")
                else:
                    doc_name = rid
            else:
                doc_name = rid
            mentions_by_entity[link["entity_uri"]].append(doc_name)

        # Process each entity
        regenerated = 0
        skipped_rich = 0
        skipped_missing_type = 0

        for entity in entities:
            uri = entity["uri"]
            label = entity["label"]
            entity_type = entity["entity_type"]

            if not entity_type:
                skipped_missing_type += 1
                continue

            folder = type_to_folder(entity_type)
            safe_name = label.replace("/", "-").replace("\\", "-")
            rel_path = f"{folder}/{safe_name}.md"
            full_path = os.path.join(args.vault_path, rel_path)

            if not is_stub_note(full_path):
                skipped_rich += 1
                continue

            rels = rels_by_entity.get(uri, [])
            mentioned_in = mentions_by_entity.get(uri, [])

            content = generate_note_content(
                {
                    "label": label,
                    "entity_type": entity_type,
                    "uri": uri,
                    "description": entity.get("description"),
                },
                rels,
                mentioned_in,
            )

            if args.apply:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                has_desc = " +desc" if entity.get("description") else ""
                print(f"  REGENERATED: {rel_path} ({len(rels)} rels, {len(mentioned_in)} mentions{has_desc})")
            else:
                has_desc = " +desc" if entity.get("description") else ""
                print(f"  WOULD REGENERATE: {rel_path} ({len(rels)} rels, {len(mentioned_in)} mentions{has_desc})")

            regenerated += 1

        print(f"\nSummary:")
        print(f"  Total entities: {len(entities)}")
        print(f"  Regenerated: {regenerated}")
        print(f"  Skipped (rich): {skipped_rich}")
        print(f"  Skipped (no type): {skipped_missing_type}")
        if not args.apply and regenerated > 0:
            print(f"\n  Run with --apply to write files")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
