# TOOLS.md — Your Tool Environment

You have a powerful set of tools for interacting with your knowledge graph, code, and vault. **Use them proactively** — don't rely only on your workspace context when you can search for specific, grounded information.

## CRITICAL: Search Your Own Knowledge First

**Before answering ANY factual question, ALWAYS search your knowledge graph and vault first.** Do NOT use web fetch or make up answers from workspace context alone.

**Required order for every question:**
1. `knowledge_search` — search your indexed documents (RAG)
2. `koi_search` — search your entity registry
3. `vault_read_note` — read specific vault notes if you know the path
4. Only AFTER exhausting your own knowledge, consider web search or telling the user you don't know

This applies to questions about people, organizations, projects, URLs, concepts — anything. Your vault contains Sources/ notes for ingested web pages, entity notes for people and organizations, and indexed documents from the Octo repository. Search them.

## Knowledge Search Tools

### `knowledge_search` — RAG over indexed documents
**When to use:** For ANY question about your codebase, architecture, documentation, implementation details, or knowledge base content. This searches over your entire indexed repository using semantic similarity.

**Examples of when to use it:**
- "How does entity resolution work?" → search for implementation details
- "What is the ontological architecture?" → search docs/
- "How do you use holonic design?" → search for architecture docs and design patterns
- "What KOI-net endpoints exist?" → search for code and docs
- Any knowledge question that could be answered by your codebase or docs

**How it works:** Searches 58 indexed documents from the DarrenZal/Octo repository with OpenAI embeddings. Returns semantically similar documents ranked by relevance. Supports source filtering (`github`, `vault`, `email`) and chunk-level search (`include_chunks: true`) for more granular results.

### `koi_search` — Entity search
**When to use:** To find specific entities (people, organizations, projects, concepts, practices, etc.) in your knowledge graph.

**Examples:** "Who is Andrea Farias?", "What organizations are involved in BKC?", "Find projects related to bioregional mapping"

### `code_query` — Cypher graph queries
**When to use:** To query structural relationships in your code — what calls what, what contains what, class hierarchies, import chains.

**Examples:**
- "What functions call resolve_entity?" → `MATCH (caller:Function)-[:CALLS]->(callee:Function) WHERE callee.name = "resolve_entity" RETURN caller.name, caller.file_path`
- "What classes exist in the API?" → `MATCH (c:Class) RETURN c.name, c.file_path`
- "What does github_sensor.py contain?" → `MATCH (f:File {file_path: "koi-processor/api/github_sensor.py"})-[:CONTAINS]->(e) RETURN e.name, e.entity_type`

The code graph contains: Function, Class, Module, File, Import nodes with CALLS, CONTAINS, BELONGS_TO, IMPORTS edges.

## Vault Tools

### `vault_read_note` — Read entity notes
Read structured notes from: People/, Organizations/, Projects/, Concepts/, Bioregions/, Practices/, Patterns/, Sources/

### `vault_write_note` — Write/update entity notes
Create or update entity notes in the vault.

## Other Tools

### `resolve_entity` — Entity resolution
Resolve a name to a canonical entity with deduplication (exact match → fuzzy → semantic → create new).

### `get_entity_relationships` — Relationship queries
Get typed relationships for an entity (who is affiliated with whom, what involves what).

### `get_entity_documents` — Document mentions
Find which documents mention a given entity.

### `github_scan` — Trigger repository scan
Manually trigger a re-scan of monitored GitHub repositories, or check sensor status.

## Tool Selection Guide

| Question Type | Primary Tool | Fallback |
|---|---|---|
| Knowledge/architecture/design questions | `knowledge_search` | workspace context |
| "How does X work?" (implementation) | `knowledge_search` + `code_query` | — |
| "Who/what is X?" (entity lookup) | `koi_search` | `knowledge_search` |
| "What calls/contains X?" (code structure) | `code_query` | `knowledge_search` |
| "Show me the note for X" | `vault_read_note` | — |
| "What documents mention X?" | `get_entity_documents` | `knowledge_search` |

**Key principle:** When answering substantive questions, always try `knowledge_search` first to ground your response in your actual indexed content rather than relying solely on workspace context. Your workspace files give you identity and values; your indexed documents give you specific knowledge.

## Response Formatting — Citations & Links

When answering questions, format your responses with entity links and source citations:

1. **Link entity names to Quartz pages:** `koi_search` results include a `quartz_url` field. Use markdown links: `[Entity Name](quartz_url)`. For example, `[Herring Conservation and Restoration Society](http://45.132.245.30/Organizations/Herring-Conservation-and-Restoration-Society)`.

2. **Add a "Sources:" section at the end** when your answer draws on ingested web content or vault documents. Use `get_entity_documents` to find source URLs for entities you cite. List original URLs so users can verify information:
   ```
   Sources:
   - [Salish Sea Hub](https://www.salishseahub.ca/)
   - [Cascade Institute](https://cascadeinstitute.org/)
   ```

3. **Pattern:** Inline entity links throughout the response body + source list at the bottom. This gives readers navigable knowledge graph connections AND provenance for the information.
