# KOI Tool Contract v1.0

Canonical specification for the 15 KOI tools exposed by any agent framework (OpenClaw plugin, MCP server, etc.). Both implementations MUST satisfy this contract.

## Return Format

All tools return:

```typescript
{
  content: [{ type: "text", text: string }],
  isError?: true  // present only on error
}
```

For API-backed tools, `text` is `JSON.stringify(apiResponse, null, 2)`.
For vault tools, `text` is the raw content or a status message.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KOI_API_ENDPOINT` | No | KOI API base URL (default: `http://127.0.0.1:8351`) |
| `VAULT_PATH` | Yes | Absolute path to the agent's vault directory |

## API-Backed Tools (12)

These tools are thin HTTP wrappers calling the KOI API.

### `resolve_entity`

Resolve an entity name to its canonical form in the knowledge graph.

- **Endpoint:** `POST /entity/resolve`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `label` | string | Yes | Entity name or label to resolve |
  | `type_hint` | string | No | Type hint: Person, Organization, Project, Concept, Location, Meeting |
- **Returns:** Ranked candidates with URI, type, confidence scores

### `get_entity_neighborhood`

Get the neighborhood of an entity — relationships, affiliated organizations, projects, connected people.

- **Endpoint:** `GET /relationships/{uri}`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `entity_uri` | string | Yes | Entity URI or name (resolved via `resolveToUri` if not a URI) |
- **Resolution:** If input doesn't start with `orn:`, resolves via `POST /entity/resolve` first
- **Returns:** Typed relationships and connected entities

### `get_entity_documents`

Find all documents that mention a specific entity.

- **Endpoint:** `GET /entity/{uri}/mentioned-in`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `entity_uri` | string | Yes | Entity URI or name |
- **Resolution:** Same as `get_entity_neighborhood`
- **Returns:** Document references mentioning the entity

### `koi_search`

Search the knowledge graph using semantic similarity.

- **Endpoint:** `GET /entity-search?query=...&limit=...&type_filter=...`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `query` | string | Yes | Search query |
  | `type_filter` | string | No | Filter by entity type |
  | `limit` | number | No | Max results (default: 10) |
- **Returns:** Entities and documents matching the query

### `knowledge_search`

Semantic search over indexed documents (RAG).

- **Endpoint:** `POST /search`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `query` | string | Yes | Natural language query or keywords |
  | `source` | string | No | Filter by source: 'github', 'vault', 'email' |
  | `limit` | number | No | Max results (default: 10) |
  | `include_chunks` | boolean | No | Include chunk-level results (default: true) |
- **Returns:** Document-level and chunk-level search results

### `preview_url`

Fetch and preview a URL for evaluation. Does NOT ingest.

- **Endpoint:** `POST /web/preview`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `url` | string | Yes | URL to preview |
  | `submitted_by` | string | No | Username who shared the URL |
  | `submitted_via` | string | No | Channel: telegram, discord, or api (default: api) |
- **Returns:** Title, content summary, detected entities, safety check

### `process_url`

Extract entities/relationships from a previewed URL using server-side LLM. Call AFTER `preview_url`.

- **Endpoint:** `POST /web/process`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `url` | string | Yes | URL to process (must be previewed first) |
  | `hint_entities` | string[] | No | Entity names to help the LLM match |
- **Returns:** Structured extraction with entities, relationships, descriptions

### `ingest_url`

Ingest a previously previewed URL into the knowledge graph. Call AFTER `preview_url`.

- **Endpoint:** `POST /web/ingest`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `url` | string | Yes | URL to ingest |
  | `entities` | array | No | Entities to resolve and link: `[{name, type, context?}]` |
  | `relationships` | array | No | Relationships: `[{subject, predicate, object}]` |
- **Entity schema:** `{ name: string, type: string, context?: string }` (type from BKC ontology)
- **Relationship schema:** `{ subject: string, predicate: string, object: string }`
- **Returns:** Ingestion result with resolved entities

### `github_scan`

Trigger a GitHub repository scan or check sensor status.

- **Endpoint:** `POST /github/scan` (action=scan) or `GET /github/status` (action=status)
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `action` | string | No | 'scan' or 'status' (default: status) |
  | `repo_name` | string | No | Specific repo to scan (e.g., 'DarrenZal/Octo') |
- **Returns:** Scan progress or sensor status

### `monitor_url`

Manage web source monitoring for periodic change detection.

- **Endpoint:** `POST /web/monitor/{add,remove}` or `GET /web/monitor/status`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `action` | string | No | 'add', 'remove', or 'status' (default: status) |
  | `url` | string | No | URL to add/remove |
  | `title` | string | No | Title for the source (used when adding) |
- **Returns:** Monitor action result or current status

### `code_query`

Run Cypher queries against the code knowledge graph.

- **Endpoint:** `POST /code/query`
- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `cypher` | string | Yes | Cypher query (graph contains Functions, Classes, Modules, Files, Imports, Interfaces) |
- **Returns:** Query result rows

### `federation_status`

Get KOI-net federation status.

- **Endpoint:** `GET /koi-net/health`
- **Parameters:** None
- **Returns:** Node identity, connected peers, event queue size, protocol policy

## Local Vault Tools (3)

These tools operate directly on the local filesystem. They require `VAULT_PATH` to be set.

### Security Requirements

All vault tools MUST:
1. Normalize the path using `path.resolve(VAULT_PATH, userInput)`
2. Verify the resolved path starts with `VAULT_PATH + separator`
3. Reject paths that escape the vault root (e.g., containing `../`)

### `vault_read_note`

Read a markdown note from the vault.

- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `path` | string | Yes | Relative path within vault (e.g., 'People/Bill Baue.md') |
- **Returns:** File content as text, or error
- **Errors:** File not found, path traversal rejected

### `vault_write_note`

Create or update a note in the vault.

- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `path` | string | Yes | Relative path (e.g., 'People/New Person.md') |
  | `content` | string | Yes | Full markdown content including YAML frontmatter |
- **Returns:** `Written: {path}` on success
- **Side effects:** Creates parent directories if needed
- **Errors:** Path traversal rejected

### `vault_list_notes`

List markdown notes in a vault folder.

- **Parameters:**
  | Name | Type | Required | Description |
  |------|------|----------|-------------|
  | `folder` | string | Yes | Folder name (e.g., 'People', 'Organizations') |
- **Returns:** Newline-separated list of `.md` filenames
- **Errors:** Folder not found, path traversal rejected

## NanoClaw Integration

### .mcp.json configuration

```json
{
  "mcpServers": {
    "koi": {
      "command": "node",
      "args": ["/path/to/personal-koi-mcp/dist/index.js"],
      "env": {
        "KOI_API_ENDPOINT": "http://host.docker.internal:8351",
        "VAULT_PATH": "/root/vault"
      }
    }
  }
}
```

**Linux note:** `host.docker.internal` requires `--add-host=host.docker.internal:host-gateway`
in `docker run`, or add to docker-compose:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Pilot tools (start with 3)

1. `resolve_entity` — verify entity resolution works
2. `koi_search` — verify semantic search
3. `knowledge_search` — verify RAG search

Expand to full 15 once these 3 are confirmed working.

## PicoClaw (Exploratory)

PicoClaw is a candidate runtime for ultra-light edge/sensor nodes in the BKC
network. This is exploratory only: no official integration or support path is
defined yet.

Current stance:
- Keep Octo on OpenClaw as coordinator
- Use NanoClaw/MCP for near-term portability
- Evaluate PicoClaw as a future pilot for low-resource sensor leaf nodes that
  publish into KOI-net

## Changelog

- **v1.1.1** (2026-02-18): Verification & closeout
  - Contract tests: 76/76 passed (schema, security, vault smoke, response shape, error shape, API smoke)
  - Manual verification: 8/8 checks passed (build, env vars, output format, path traversal, endpoints, defaults)
  - Commits: `05ee778` (Octo plugin fixes, tagged `koi-gv-remote-stable`), `bf7c0d3` (14 BKC entity types in personal-koi-mcp), `206524b` (tsx dev dep fix)
- **v1.1** (2026-02-18): Parity fixes — lazy VAULT_PATH, contract-aligned entity/vault tools in MCP, submitted_via default → "api", NanoClaw integration guide
- **v1.0** (2026-02-18): Initial contract extracted from OpenClaw plugin `index.ts`
