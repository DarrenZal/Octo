#!/usr/bin/env python3
"""
Backfill KOI RIDs for existing entities.

One-time migration script — run after 040_entity_koi_rids.sql.
Generates KOI-net compatible RIDs for all entities missing koi_rid.

Usage:
    python3 scripts/backfill_koi_rids.py \
        --db-url postgresql://postgres:PASSWORD@localhost:5432/octo_koi
"""

import argparse
import asyncio
import hashlib
import re
import sys

import asyncpg


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def generate_koi_rid(entity_type: str, normalized_text: str, fuseki_uri: str) -> str:
    """Generate a KOI RID for an entity.

    Format: orn:koi-net.{type}:{slug}+{hash[:16]}
    Hash is derived from fuseki_uri for stability.
    """
    slug = slugify(normalized_text)
    if not slug:
        slug = "unnamed"
    uri_hash = hashlib.sha256(fuseki_uri.encode()).hexdigest()[:16]
    type_lower = entity_type.lower() if entity_type else "entity"
    return f"orn:koi-net.{type_lower}:{slug}+{uri_hash}"


async def backfill(db_url: str, dry_run: bool = False):
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(
            """
            SELECT fuseki_uri, entity_type, normalized_text
            FROM entity_registry
            WHERE koi_rid IS NULL
            """
        )

        if not rows:
            print("No entities need backfilling.")
            return

        print(f"Found {len(rows)} entities without koi_rid")

        updated = 0
        for row in rows:
            koi_rid = generate_koi_rid(
                row["entity_type"],
                row["normalized_text"],
                row["fuseki_uri"],
            )

            if dry_run:
                print(f"  {row['normalized_text']} -> {koi_rid}")
            else:
                await conn.execute(
                    "UPDATE entity_registry SET koi_rid = $1 WHERE fuseki_uri = $2",
                    koi_rid,
                    row["fuseki_uri"],
                )
                updated += 1

        if dry_run:
            print(f"\nDry run: would update {len(rows)} entities")
        else:
            print(f"\nBackfilled {updated} entities with KOI RIDs")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill KOI RIDs")
    parser.add_argument("--db-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    asyncio.run(backfill(args.db_url, args.dry_run))
