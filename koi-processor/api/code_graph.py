"""
Apache AGE Graph Operations for Code Entities

Manages the code knowledge graph in PostgreSQL's regen_graph:
- Loading code entities (Function, Class, Module, File, Import, Interface)
- Loading edges (CALLS, CONTAINS, BELONGS_TO, IMPORTS)
- Mark/sweep cleanup of stale entities
- Cypher query execution for agent use

Adapted from RegenAI's load_to_staging.py and sync_stubs_to_age.py.
"""

import logging
from typing import Dict, List, Optional, Tuple

from api.tree_sitter_extractor import CodeEntity, CodeEdge

logger = logging.getLogger(__name__)

GRAPH_NAME = "regen_graph"
BATCH_SIZE = 100


def escape_cypher(text: str) -> str:
    """Escape special characters for Cypher queries"""
    if not text:
        return ""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


async def setup_age(conn) -> None:
    """Load AGE extension and set search path"""
    await conn.execute("LOAD 'age';")
    await conn.execute("SET search_path = ag_catalog, '$user', public;")


async def ensure_graph(conn, graph_name: str = GRAPH_NAME) -> None:
    """Create graph and edge labels if they don't exist"""
    result = await conn.fetchval(
        "SELECT COUNT(*) FROM ag_catalog.ag_graph WHERE name = $1",
        graph_name,
    )
    if result == 0:
        await conn.execute(f"SELECT create_graph('{graph_name}');")
        logger.info(f"Created graph '{graph_name}'")
    else:
        logger.info(f"Graph '{graph_name}' already exists")

    # Ensure edge labels exist by creating+deleting dummy edges via Cypher
    # AGE only creates edge label tables when first used in Cypher
    edge_labels = ["CALLS", "CONTAINS", "BELONGS_TO", "IMPORTS"]
    for label in edge_labels:
        try:
            # Check if the edge label table exists
            exists = await conn.fetchval(
                "SELECT COUNT(*) FROM ag_catalog.ag_label WHERE name = $1 AND graph = "
                "(SELECT graphid FROM ag_catalog.ag_graph WHERE name = $2)",
                label, graph_name,
            )
            if exists == 0:
                # Create edge label by creating a dummy relationship then deleting it
                await conn.execute(f"""
                    SELECT * FROM cypher('{graph_name}', $$
                        CREATE (a:_Dummy)-[r:{label}]->(b:_Dummy)
                        DELETE r, a, b
                    $$) as (result agtype);
                """)
                logger.info(f"Created edge label '{label}' in {graph_name}")
        except Exception as e:
            logger.warning(f"Edge label '{label}' setup: {e}")


async def load_code_entities(
    conn,
    entities: List[CodeEntity],
    run_id: str,
    graph_name: str = GRAPH_NAME,
) -> Tuple[int, int]:
    """Batch-create nodes in AGE graph. Returns (success, failed) counts."""
    success = 0
    failed = 0

    for batch_start in range(0, len(entities), BATCH_SIZE):
        batch = entities[batch_start:batch_start + BATCH_SIZE]

        try:
            create_statements = []
            for entity in batch:
                label = entity.entity_type
                props = {
                    "entity_id": entity.entity_id,
                    "name": escape_cypher(entity.name),
                    "entity_type": entity.entity_type,
                    "file_path": escape_cypher(entity.file_path),
                    "line_start": entity.line_start,
                    "line_end": entity.line_end,
                    "language": entity.language,
                    "repo": entity.repo,
                    "signature": escape_cypher(entity.signature[:500] if entity.signature else ""),
                    "params": escape_cypher(entity.params[:200] if entity.params else ""),
                    "return_type": escape_cypher(entity.return_type[:100] if entity.return_type else ""),
                    "docstring": escape_cypher(entity.docstring[:500] if entity.docstring else ""),
                    "receiver_type": escape_cypher(entity.receiver_type or ""),
                    "extraction_method": entity.extraction_method,
                    "extraction_run_id": run_id,
                    "module_name": escape_cypher(entity.module_name or ""),
                    "module_path": escape_cypher(entity.module_path or ""),
                }

                stmt = f"""CREATE (:{label} {{
                    entity_id: '{props['entity_id']}',
                    name: '{props['name']}',
                    entity_type: '{props['entity_type']}',
                    file_path: '{props['file_path']}',
                    line_start: {props['line_start']},
                    line_end: {props['line_end']},
                    language: '{props['language']}',
                    repo: '{props['repo']}',
                    signature: '{props['signature']}',
                    params: '{props['params']}',
                    return_type: '{props['return_type']}',
                    docstring: '{props['docstring']}',
                    receiver_type: '{props['receiver_type']}',
                    extraction_method: '{props['extraction_method']}',
                    extraction_run_id: '{props['extraction_run_id']}',
                    module_name: '{props['module_name']}',
                    module_path: '{props['module_path']}'
                }})"""
                create_statements.append(stmt)

            batch_query = f"""
            SELECT * FROM cypher('{graph_name}', $$
                {' '.join(create_statements)}
            $$) as (result agtype);
            """
            await conn.execute(batch_query)
            success += len(batch)

        except Exception as e:
            logger.error(f"Batch entity insert failed at {batch_start}: {e}")
            # Fall back to individual inserts
            for entity in batch:
                try:
                    await _load_entity_single(conn, entity, run_id, graph_name)
                    success += 1
                except Exception:
                    failed += 1

    return success, failed


async def _load_entity_single(
    conn,
    entity: CodeEntity,
    run_id: str,
    graph_name: str,
) -> None:
    """Load a single entity (fallback for failed batches)"""
    label = entity.entity_type
    props = {
        "entity_id": entity.entity_id,
        "name": escape_cypher(entity.name),
        "entity_type": entity.entity_type,
        "file_path": escape_cypher(entity.file_path),
        "line_start": entity.line_start,
        "language": entity.language,
        "repo": entity.repo,
        "extraction_run_id": run_id,
        "module_name": escape_cypher(entity.module_name or ""),
        "module_path": escape_cypher(entity.module_path or ""),
    }

    query = f"""
    SELECT * FROM cypher('{graph_name}', $$
        CREATE (:{label} {{
            entity_id: '{props['entity_id']}',
            name: '{props['name']}',
            repo: '{props['repo']}',
            file_path: '{props['file_path']}',
            line_start: {props['line_start']},
            language: '{props['language']}',
            module_name: '{props['module_name']}',
            module_path: '{props['module_path']}',
            extraction_run_id: '{props['extraction_run_id']}'
        }})
    $$) as (result agtype);
    """
    await conn.execute(query)


async def _load_entity_id_map(
    conn,
    graph_name: str = GRAPH_NAME,
) -> Tuple[Dict[str, int], Dict[str, List[int]]]:
    """Pre-load entity mappings for fast edge creation.

    Returns:
        (id_map: entity_id -> graph_id,
         name_map: name -> list of graph_ids)
    """
    query = f"""
    SELECT * FROM cypher('{graph_name}', $$
        MATCH (n)
        RETURN n.entity_id as entity_id, n.name as name, id(n) as graph_id
    $$) as (entity_id agtype, name agtype, graph_id agtype);
    """
    rows = await conn.fetch(query)

    id_map: Dict[str, int] = {}
    name_map: Dict[str, List[int]] = {}

    for row in rows:
        entity_id = str(row['entity_id']).strip('"')
        name = str(row['name']).strip('"')
        graph_id = int(str(row['graph_id']))

        id_map[entity_id] = graph_id
        if name not in name_map:
            name_map[name] = []
        name_map[name].append(graph_id)

    logger.info(f"Loaded {len(id_map)} entity IDs, {len(name_map)} unique names")
    return id_map, name_map


async def load_code_edges(
    conn,
    edges: List[CodeEdge],
    run_id: str,
    graph_name: str = GRAPH_NAME,
) -> Tuple[int, int]:
    """Load edges using pre-loaded ID map + direct SQL inserts. Returns (success, failed)."""
    success = 0
    failed = 0
    skipped = 0

    id_map, name_map = await _load_entity_id_map(conn, graph_name)

    # Group by type for batch inserts
    edges_by_type: Dict[str, List[CodeEdge]] = {}
    for edge in edges:
        edges_by_type.setdefault(edge.edge_type, []).append(edge)

    for edge_type, type_edges in edges_by_type.items():
        logger.info(f"Loading {len(type_edges)} {edge_type} edges...")

        edge_batch_size = 500
        for batch_start in range(0, len(type_edges), edge_batch_size):
            batch = type_edges[batch_start:batch_start + edge_batch_size]

            valid_edges = []
            for edge in batch:
                source_gid = id_map.get(edge.from_entity_id)
                if source_gid is None:
                    skipped += 1
                    continue

                # Try entity_id first, then name lookup
                target_gid = id_map.get(edge.to_entity_id)
                if target_gid is None:
                    target_gids = name_map.get(edge.to_entity_id, [])
                    if target_gids:
                        target_gid = target_gids[0]
                    # For dotted names like "module.function", try the last part
                    elif "." in edge.to_entity_id:
                        bare_name = edge.to_entity_id.split(".")[-1]
                        target_gids = name_map.get(bare_name, [])
                        if target_gids:
                            target_gid = target_gids[0]

                if target_gid is None:
                    skipped += 1
                    continue

                valid_edges.append({
                    "start_id": source_gid,
                    "end_id": target_gid,
                    "edge_id": edge.edge_id,
                    "line_number": edge.line_number,
                })

            if valid_edges:
                try:
                    values = []
                    for e in valid_edges:
                        edge_id_escaped = str(e["edge_id"]).replace("'", "''")
                        props = f'{{"edge_id": "{edge_id_escaped}", "line_number": {e["line_number"]}, "extraction_run_id": "{run_id}"}}'
                        values.append(
                            f"(graphid_in('{e['start_id']}'), graphid_in('{e['end_id']}'), '{props}'::agtype)"
                        )

                    insert_sql = f"""
                        INSERT INTO {graph_name}."{edge_type}" (start_id, end_id, properties)
                        VALUES {', '.join(values)}
                        ON CONFLICT DO NOTHING
                    """
                    await conn.execute(insert_sql)
                    success += len(valid_edges)
                except Exception as e:
                    logger.warning(f"Batch edge insert failed for {edge_type}: {e}")
                    failed += len(valid_edges)

    logger.info(f"Edges loaded: {success} success, {failed} failed, {skipped} skipped")
    return success, failed


async def sweep_old_entities(
    conn,
    repo: str,
    run_id: str,
    graph_name: str = GRAPH_NAME,
) -> int:
    """Remove graph entities from previous runs for a repo (mark/sweep)."""
    try:
        query = f"""
        SELECT * FROM cypher('{graph_name}', $$
            MATCH (n {{repo: '{escape_cypher(repo)}'}})
            WHERE n.extraction_run_id <> '{escape_cypher(run_id)}'
            DETACH DELETE n
        $$) as (result agtype);
        """
        await conn.execute(query)

        # Count remaining
        count_query = f"""
        SELECT * FROM cypher('{graph_name}', $$
            MATCH (n {{repo: '{escape_cypher(repo)}'}})
            RETURN count(n) as cnt
        $$) as (cnt agtype);
        """
        row = await conn.fetchrow(count_query)
        remaining = int(str(row['cnt'])) if row else 0
        logger.info(f"Swept old entities for {repo}, {remaining} remain from run {run_id}")
        return remaining

    except Exception as e:
        logger.error(f"Error sweeping old entities: {e}")
        return -1


async def query_code_graph(
    conn,
    cypher: str,
    graph_name: str = GRAPH_NAME,
) -> List[Dict]:
    """Execute a Cypher query against the code graph. Returns list of result rows.

    AGE requires column aliases matching the RETURN clause count. To support
    arbitrary queries, we use a raw SQL approach that captures results via
    the ag_catalog functions and returns results as agtype text.
    """
    await setup_age(conn)
    await ensure_graph(conn, graph_name)

    # Count RETURN columns to build the right alias list
    # Parse the RETURN clause to figure out how many columns we need
    import re
    return_match = re.search(r'\bRETURN\b(.+?)(?:\bORDER\b|\bLIMIT\b|\bSKIP\b|$)', cypher, re.IGNORECASE | re.DOTALL)

    if return_match:
        return_clause = return_match.group(1).strip()
        # Count commas not inside parentheses to determine column count
        depth = 0
        col_count = 1
        for ch in return_clause:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ',' and depth == 0:
                col_count += 1
    else:
        col_count = 1

    # Build column aliases: c1 agtype, c2 agtype, ...
    aliases = ", ".join(f"c{i+1} agtype" for i in range(col_count))

    query = f"""
    SELECT * FROM cypher('{graph_name}', $$
        {cypher}
    $$) as ({aliases});
    """

    try:
        rows = await conn.fetch(query)
        results = []
        for row in rows:
            row_dict = {}
            for i in range(col_count):
                col_name = f"c{i+1}"
                val = row.get(col_name)
                row_dict[col_name] = str(val) if val is not None else None
            results.append(row_dict)
        return results
    except Exception as e:
        logger.error(f"Cypher query error: {e}")
        raise
