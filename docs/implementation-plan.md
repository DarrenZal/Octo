# Holonic Bioregional Knowledge Commons — Implementation Plan

*Concrete engineering plan for building a holonic network: Greater Victoria + Cowichan Valley → Salish Sea (Octo) → Cascadia, with Front Range as a separate bioregional peer.*

**Strategy document:** [holonic-bioregional-knowledge-commons.md](./holonic-bioregional-knowledge-commons.md)
**Ontological architecture:** [ontological-architecture.md](./ontological-architecture.md)

---

## Architecture

### Three-Level Holon

```
[Greater Victoria]   [Cowichan Valley]
        ↘                 ↙
   [Octo / Salish Sea Coordinator]     ← holon boundary
              ↓
      [Cascadia Coordinator]           ← sees "Salish Sea" as one node

                                       [Front Range]
                                           ↑ separate bioregional network
                                           (peer of Cascadia, not under it)
```

### Infrastructure (Single VPS)

All agents run on the existing VPS (`45.132.245.30`, 4 vCPU / 8GB RAM / 247GB disk), sharing the PostgreSQL container with separate databases:

| Agent | Database | KOI API Port | Vault Path | Status |
|-------|----------|-------------|------------|--------|
| **Octo** (Salish Sea) | `octo_koi` | 8351 | `~/.openclaw/workspace/vault/` | Existing |
| **Greater Victoria** | `gv_koi` | 8352 | `/root/gv-agent/vault/` | Phase 2 |
| **Cowichan Valley** | `cv_koi` | 8354 | `/root/cv-agent/vault/` | Phase 4.5 |
| **Cascadia** | `cascadia_koi` | 8353 | `/root/cascadia-agent/vault/` | Phase 5 |
| **Front Range** | `fr_koi` | 8355 | `/root/fr-agent/vault/` | Phase 5.5 |

### Shared PostgreSQL Container

The existing `regen-koi-postgres` container (PostgreSQL 15 + pgvector 0.5.1 + Apache AGE 1.5.0 + pg_trgm + fuzzystrmatch) supports multiple databases. Each database gets its own `regen_graph`, entity registry, and relationship tables.

---

## Phase 0.5: BKC CoIP Vault Audit

**Goal:** Understand the BKC CoIP's actual data format and ontological conventions before building the sensor.

> **Ontological architecture:** See [ontological-architecture.md](./ontological-architecture.md) for the full framework on handling diverse schemas, the three-layer ingestion model, and ontological pluriversality.

The BKC CoIP Seed phase produced 59 case studies and 57 organization profiles in Obsidian with specific YAML frontmatter conventions. The markdown sensor needs to handle *their* schema, not just ours. This is a discovery task that de-risks Phase 1.

### Tasks

**Schema Discovery:**
- [ ] Obtain access to the BKC CoIP Obsidian vault (coordinate with Andrea Farias / Vincent Arena)
- [ ] Document their YAML frontmatter schema — fields, types, cardinality, example values for both organizations and case studies
- [ ] Profile the schema using the agent's ontology skillset: detect structure, generate field inventory, note controlled vocabularies
- [ ] Create a `source_schemas` entry for `bkc-coip-organizations-v1` and `bkc-coip-casestudies-v1`

**Ontology Mapping:**
- [ ] Map their entity types to BKC ontology types (their `type: organization` → our `Organization`, etc.)
- [ ] Map their relationship fields to BKC predicates (their `network-affiliation` → our `affiliated_with`, etc.)
- [ ] Identify unmapped fields (`category`, `bioregional_context`, `status`, etc.) — document why they don't map and whether they suggest ontology extensions
- [ ] Create `ontology_mappings` entries for each field with mapping type (equivalent / narrower / broader / unmapped / proposed_extension)
- [ ] Flag proposed extensions for community review (e.g., `organizational_role`, geographic coordinates)

**Integration Assessment:**
- [ ] Assess OMNI-Mapping's three-layer structure (interface / data management / input) for compatibility
- [ ] Document the BKC CoIP's data commoning intentions: permission models, sovereignty requirements
- [ ] Verify consent: does the BKC CoIP team consent to ingestion into Octo's KOI backend?

**Output:**
- Schema mapping document: `koi-processor/sensors/bkc_schema_mapping.md`
- `source_schemas` table entries for BKC CoIP schemas
- `ontology_mappings` table entries for each field mapping
- List of proposed ontology extensions for community review

---

## Phase 1: BKC CoIP Interoperability

**Goal:** Enable Octo to ingest from and contribute to the BKC Practices & Patterns Project, regardless of their tooling. Preserve source structure per the [ontological architecture](./ontological-architecture.md).

**Why first:** The BKC CoIP is the most immediate community Octo serves. This delivers value before any federation infrastructure.

**Depends on:** Phase 0.5 schema mapping.

### 1.1 Markdown Sensor Node

**What:** A Python service that watches a directory or Git repository for markdown files with BKC-compatible frontmatter, parses them into entities, and ingests them into Octo's KOI backend via the existing API.

**New file:** `koi-processor/sensors/markdown_sensor.py`

```python
# Core logic:
# 1. Watch directory or poll Git repo for new/changed .md files
# 2. Parse YAML frontmatter (extract @type, name, relationships)
# 3. Look up source_schema and ontology_mappings for this file type
# 4. For each entity found:
#    - POST /entity/resolve to check if entity exists
#    - POST /register-entity with:
#      - BKC-mapped fields (via ontology_mappings)
#      - source_metadata: full original YAML frontmatter (preserved as-is)
#      - source_schema_id: reference to the source schema
#      - contributed_by / source_community: attribution
#    - POST /sync-relationships to create relationships
# 5. Track processed files (hash-based dedup)
```

**Dependencies on existing API:**
- `POST /entity/resolve` — already exists
- `POST /register-entity` — already exists
- `POST /sync-relationships` — already exists
- No new API endpoints needed for ingestion

**Configuration:** `koi-processor/config/sensors.yaml`
```yaml
markdown_sensor:
  source_type: git  # or 'directory'
  source_path: /root/bkc-coip-data/  # cloned repo or shared directory
  poll_interval: 300  # seconds
  api_url: http://127.0.0.1:8351
  file_patterns:
    - "Practices/*.md"
    - "Patterns/*.md"
    - "CaseStudies/*.md"
```

**State tracking:** `koi-processor/sensors/sensor_state.json`
```json
{
  "processed_files": {
    "Practices/herring-monitoring.md": {
      "sha256": "abc123...",
      "last_processed": "2026-02-10T12:00:00Z",
      "entities_created": ["orn:entity:practice/herring-monitoring+..."]
    }
  }
}
```

**Tasks:**
- [ ] Create `koi-processor/sensors/` directory
- [ ] Write `markdown_sensor.py` — frontmatter parser, entity extraction, API integration
- [ ] Write `sensor_state.py` — file hash tracking, dedup
- [ ] Write `schema_mapper.py` — loads `source_schemas` + `ontology_mappings` from DB, applies mappings during ingestion
- [ ] Add sensor config to `koi-processor/config/sensors.yaml`
- [ ] Add systemd service file for the sensor (`/etc/systemd/system/bkc-sensor.service`)
- [ ] Test with sample BKC markdown files

**Test criteria:**
- Sensor detects new markdown file → creates entities in Octo's registry
- Sensor detects updated file → updates entities (not duplicates)
- Sensor handles missing/malformed frontmatter gracefully
- Entities have correct types and relationships per BKC ontology
- `source_metadata` populated with full original YAML frontmatter
- `source_schema_id` correctly linked to BKC CoIP schema entry
- Unmapped fields (category, bioregional_context, etc.) preserved in `source_metadata`
- `access_level` set correctly (default: `public`)

### 1.1b Schema & Mapping Infrastructure

**New migration:** `koi-processor/migrations/039b_ontology_mappings.sql`

> **Note:** This migration supports the three-layer ingestion model from the [ontological architecture](./ontological-architecture.md). Source metadata is preserved alongside BKC mappings.

```sql
-- Source schemas: records known external data schemas
CREATE TABLE IF NOT EXISTS source_schemas (
    id SERIAL PRIMARY KEY,
    schema_name TEXT UNIQUE NOT NULL,
    description TEXT,
    source_community TEXT,
    source_type TEXT,                           -- obsidian_yaml, csv, json_ld, rdf
    field_definitions JSONB NOT NULL DEFAULT '{}',
    mapping_status TEXT DEFAULT 'unmapped',     -- unmapped, partial, complete
    consent_status TEXT DEFAULT 'pending',      -- pending, verbal, written, formal, declined
    consent_details JSONB DEFAULT '{}',
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);

-- Ontology mappings: explicit source → BKC correspondences
CREATE TABLE IF NOT EXISTS ontology_mappings (
    id SERIAL PRIMARY KEY,
    source_schema_id INTEGER REFERENCES source_schemas(id),
    source_field TEXT NOT NULL,
    source_value_pattern TEXT,
    bkc_entity_type TEXT,
    bkc_predicate TEXT,
    bkc_property TEXT,
    mapping_type TEXT NOT NULL DEFAULT 'unmapped'
        CHECK (mapping_type IN ('equivalent', 'narrower', 'broader', 'related', 'unmapped', 'proposed_extension')),
    mapping_direction TEXT DEFAULT 'outgoing',
    confidence FLOAT DEFAULT 1.0,
    notes TEXT,
    reviewed_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ontology_mappings_schema
    ON ontology_mappings(source_schema_id);

-- Entity registry additions for source preservation
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_schema_id
    INTEGER REFERENCES source_schemas(id);
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_metadata
    JSONB DEFAULT '{}';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS access_level
    TEXT DEFAULT 'public';
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS contributed_by TEXT;
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS source_community TEXT;
```

**Tasks:**
- [ ] Create migration `039b_ontology_mappings.sql`
- [ ] Run on `octo_koi`: apply via `docker exec`
- [ ] Verify tables exist and entity_registry has new columns
- [ ] Populate initial `source_schemas` entry for BKC CoIP (from Phase 0.5 output)
- [ ] Populate initial `ontology_mappings` entries (from Phase 0.5 output)

**Test criteria:**
- `source_schemas` and `ontology_mappings` tables exist
- Entity registration works with `source_metadata` and `source_schema_id` populated
- Existing entities unaffected (new columns have defaults)
- `access_level` defaults to `public` for existing entities

### 1.2 Practice Export

**What:** An API endpoint that exports Octo's documented practices as BKC-compatible markdown files, suitable for contribution back to the project.

**New endpoint in `personal_ingest_api.py`:**
```python
GET /export/practices?format=markdown&bioregion=salish-sea
```

Returns a ZIP or tar of markdown files with YAML frontmatter:
```yaml
---
"@type": Practice
name: Herring Monitoring
practiced_in:
  - "[[Bioregions/Salish Sea]]"
aggregates_into:
  - "[[Patterns/Commons Resource Monitoring]]"
documented_by:
  - "[[CaseStudies/Victoria Herring Count]]"
---

# Herring Monitoring

Community-led monitoring of Pacific herring spawning...
```

**Tasks:**
- [ ] Add `GET /export/practices` endpoint to `personal_ingest_api.py`
- [ ] Add `GET /export/entities` generic endpoint (type-filtered)
- [ ] Generate markdown with YAML frontmatter matching vault_parser's expected format
- [ ] Include relationship fields using wikilink syntax
- [ ] Test round-trip: export → re-import via sensor → no duplicates

### 1.3 Murmurations Profile (Exploration)

**What:** Publish a Murmurations-compatible JSON profile describing Octo's public knowledge base, making it discoverable by other bioregional knowledge systems.

**Tasks:**
- [ ] Research Murmurations profile schema
- [ ] Create static profile at `/root/octo-quartz/public/murmurations.json`
- [ ] Serve via nginx alongside the Quartz site
- [ ] Register with Murmurations index (if available)

**Deferred — explore after 1.1 and 1.2 are working.**

---

## Phase 2: Multi-Instance Infrastructure

**Goal:** Set up the database and configuration infrastructure for running multiple KOI agents on one VPS.

### 2.1 Additional Databases

**New script:** `docker/create-additional-dbs.sh`

> **Note:** Database creation requires separate `psql` invocations per database. The `\c` and `\gexec` psql meta-commands don't work reliably through piped `docker exec` input. Use a shell script instead.

```bash
#!/bin/bash
# Create additional databases for multi-agent KOI deployment
# Usage: ./create-additional-dbs.sh [db_name ...]
# Examples:
#   ./create-additional-dbs.sh gv_koi cascadia_koi    # Phase 2
#   ./create-additional-dbs.sh cv_koi                  # Phase 4.5
#   ./create-additional-dbs.sh                         # No args = default set

CONTAINER="regen-koi-postgres"
PSQL="docker exec -i $CONTAINER psql -U postgres"

create_koi_db() {
  local DB_NAME=$1
  echo "Creating database $DB_NAME..."
  $PSQL -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    $PSQL -c "CREATE DATABASE $DB_NAME"

  # Extensions must be created per-database
  $PSQL -d "$DB_NAME" <<EOF
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF

  # AGE requires LOAD per session
  $PSQL -d "$DB_NAME" -c "LOAD 'age'; SET search_path = ag_catalog, \"\$user\", public; SELECT create_graph('regen_graph');"

  # Bootstrap schema and predicates
  echo "Bootstrapping schema for $DB_NAME..."
  cat /root/koi-processor/migrations/038_bkc_predicates.sql | $PSQL -d "$DB_NAME"

  echo "$DB_NAME ready."
}

# Accept DB names as arguments, or default set
DBS="${@:-gv_koi cascadia_koi}"
for DB in $DBS; do
  create_koi_db "$DB"
done
```

**Important:** The KOI API's `ensure_schema()` creates tables (`entity_registry`, `entity_relationships`, `allowed_predicates`, etc.) at startup. But the 27 BKC predicates in `038_bkc_predicates.sql` must be loaded separately — the script above handles this. Without it, new agents will have empty predicate tables and relationship creation will fail.

**Tasks:**
- [ ] Create `docker/create-additional-dbs.sh`
- [ ] Run on server: `scp docker/create-additional-dbs.sh root@45.132.245.30:~/koi-stack/ && ssh root@45.132.245.30 "bash ~/koi-stack/create-additional-dbs.sh"`
- [ ] Verify databases exist: `docker exec regen-koi-postgres psql -U postgres -c "\l" | grep koi`
- [ ] Verify extensions loaded: `docker exec regen-koi-postgres psql -U postgres -d gv_koi -c "\dx"`
- [ ] Verify predicates populated: `docker exec regen-koi-postgres psql -U postgres -d gv_koi -c "SELECT count(*) FROM allowed_predicates;"`

### 2.2 Greater Victoria Agent Configuration

**New directory structure on server:**
```
/root/gv-agent/
├── config/
│   └── gv.env              # DB_NAME=gv_koi, KOI_API_PORT=8352
├── vault/
│   ├── Practices/
│   ├── Patterns/
│   ├── CaseStudies/
│   ├── Bioregions/
│   ├── People/
│   ├── Organizations/
│   └── Projects/
└── workspace/
    ├── IDENTITY.md          # Greater Victoria agent identity
    └── SOUL.md              # GV-specific grounding
```

**Config file:** `gv-agent/config/gv.env`
```env
POSTGRES_URL=postgresql://postgres:PASSWORD@localhost:5432/gv_koi
KOI_API_PORT=8352
OPENAI_API_KEY=<shared key>
EMBEDDING_MODEL=text-embedding-ada-002
ENABLE_SEMANTIC_MATCHING=true
VAULT_PATH=/root/gv-agent/vault
KOI_MODE=bioregional
KOI_NODE_NAME=greater-victoria
```

**Systemd service:** `/etc/systemd/system/gv-koi-api.service`
```ini
[Unit]
Description=Greater Victoria KOI API
After=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/koi-processor
EnvironmentFile=/root/gv-agent/config/gv.env
ExecStart=/root/koi-processor/venv/bin/uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port 8352
Restart=always

[Install]
WantedBy=multi-user.target
```

**Tasks:**
- [ ] Create directory structure on server
- [ ] Write `gv.env` config file
- [ ] Write GV workspace files (IDENTITY.md, SOUL.md — minimal)
- [ ] Create and enable systemd service
- [ ] Verify: `curl http://127.0.0.1:8352/health` returns healthy
- [ ] Seed GV vault with 2-3 practice notes (e.g., Gorge Creek Herring, Goldstream Salmon, Beacon Hill Camas)
- [ ] Register seed entities via API

**Test criteria:**
- GV KOI API runs independently on port 8352
- Entity resolution works against gv_koi database
- Vault notes readable and writable
- No interference with Octo's instance on port 8351

### 2.3 Backup & Monitoring

**Backup:** Add new databases to the existing daily backup cron job.

```bash
# Add to /root/backups/backup.sh (or equivalent cron):
for DB in octo_koi gv_koi cascadia_koi; do
  docker exec regen-koi-postgres pg_dump -U postgres $DB | gzip > /root/backups/${DB}_$(date +%Y%m%d).sql.gz
done
```

**Monitoring:** Baseline resource monitoring before adding more instances.

```bash
# Add to cron (every 15 minutes):
echo "$(date) | $(free -m | awk '/Mem:/{print "RAM: "$3"/"$2"MB"}') | $(docker exec regen-koi-postgres psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity") active PG conns" >> /var/log/koi-resources.log
```

**Tasks:**
- [ ] Update backup script to include `gv_koi` and `cascadia_koi`
- [ ] Add resource monitoring cron job
- [ ] Verify backups run successfully for new databases

### 2.4 Multi-Instance Management Script

**New file:** `scripts/manage-agents.sh`

> **Config-driven:** Reads agent definitions from `scripts/agents.conf` so new agents (Phase 4.5, Phase 5) don't require script changes — just add a line to the config file.

```bash
#!/bin/bash
# Start/stop/status for all KOI agents
# Agent definitions read from agents.conf (one per line: name:service:port)

SCRIPT_DIR="$(dirname "$0")"
AGENTS_CONF="${SCRIPT_DIR}/agents.conf"

# Default agents if no config file exists
if [ ! -f "$AGENTS_CONF" ]; then
  cat > "$AGENTS_CONF" <<EOF
octo:koi-api:8351
greater-victoria:gv-koi-api:8352
# cowichan-valley:cv-koi-api:8354  # Uncomment for Phase 4.5
# cascadia:cascadia-koi-api:8353  # Uncomment for Phase 5
# front-range:fr-koi-api:8355    # Separate bioregional network
EOF
fi

case "$1" in
  start|stop)
    while IFS=: read -r name service port; do
      [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
      echo "$1: $name ($service)"
      systemctl "$1" "$service"
    done < "$AGENTS_CONF"
    ;;
  status)
    while IFS=: read -r name service port; do
      [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
      echo "=== $name ==="
      systemctl is-active --quiet "$service" && \
        curl -s "http://127.0.0.1:${port}/health" | python3 -m json.tool || \
        echo "NOT RUNNING"
    done < "$AGENTS_CONF"
    echo "=== Resources ==="
    free -m | awk '/Mem:/{print "RAM: "$3"/"$2"MB"}'
    docker exec regen-koi-postgres psql -U postgres -t -c "SELECT datname, numbackends FROM pg_stat_database WHERE datname LIKE '%_koi'"
    ;;
esac
```

---

## Phase 3: KOI-net Protocol Layer

**Goal:** Add KOI-net protocol support to the KOI API, enabling inter-agent communication.

**Reference implementations:**
- RegenAI coordinator: `~/projects/regenai/koi-sensors/koi_protocol/coordinator/koi_coordinator.py`
- BlockScience [koi-net](https://github.com/BlockScience/koi-net): `~/projects/RegenAI/koi-research/sources/blockscience/koi-net/`
- Interop test: `~/projects/regenai/koi-sensors/scripts/koi_net_interop_test.py`

**Key dependency:** [`rid-lib`](https://github.com/BlockScience/rid-lib) (v3.2.8+) from BlockScience. Provides RID, RIDType, Manifest, Bundle, and `sha256_hash()` using JCS (JSON Canonicalization Scheme). Reimplementing JCS hashing is error-prone and breaks interop. Add as a Python dependency.

### 3.1 Feature Flag

All KOI-net protocol endpoints live in a separate FastAPI router, conditionally mounted based on an environment variable:

```python
# In personal_ingest_api.py startup:
if os.getenv("KOI_NET_ENABLED", "false").lower() == "true":
    from api.koi_net_router import koi_net_router
    app.include_router(koi_net_router, prefix="/koi-net")
```

This allows the GV agent to run without protocol endpoints while Octo is under active development. Enable per-agent via env file: `KOI_NET_ENABLED=true`.

### 3.2 Protocol Models

**New file:** `koi-processor/api/koi_protocol.py`

Pydantic models matching the BlockScience wire format, using `rid-lib` types where possible:

```python
# Event types
class EventType(StrEnum):
    NEW = "NEW"
    UPDATE = "UPDATE"
    FORGET = "FORGET"

# Wire models (strict P1a/P1b format)
# Use rid-lib's sha256_hash() for JCS-canonical hashing
class WireManifest(BaseModel):
    rid: str
    timestamp: str  # ISO 8601 UTC with Z suffix
    sha256_hash: str  # JCS-canonical hash via rid-lib

class WireEvent(BaseModel):
    rid: str
    event_type: EventType
    manifest: WireManifest | None = None
    contents: dict | None = None

# Node capability declaration (from BlockScience NodeProfile)
class NodeProvides(BaseModel):
    event: list[str] = []   # RID types this node broadcasts events for
    state: list[str] = []   # RID types this node serves state queries for

class NodeProfile(BaseModel):
    node_rid: str
    node_name: str
    node_type: str          # "FULL" or "PARTIAL"
    base_url: str | None    # None for PARTIAL nodes
    provides: NodeProvides
    public_key: str | None  # DER-encoded, base64
    # Deferred to post-Phase 5: ontology_uri, ontology_version
    # (see ontological-architecture.md Section 9 for full design)

# Request models
class PollEventsRequest(BaseModel):
    type: Literal["poll_events"]
    limit: int = 50

class FetchRidsRequest(BaseModel):
    type: Literal["fetch_rids"]
    rid_types: list[str] | None = None  # Filter by RID type (Practice, Pattern, etc.)

class FetchManifestsRequest(BaseModel):
    type: Literal["fetch_manifests"]
    rids: list[str]

class FetchBundlesRequest(BaseModel):
    type: Literal["fetch_bundles"]
    rids: list[str]

class EventsPayloadRequest(BaseModel):
    type: Literal["events_payload"]
    events: list[WireEvent]

class HandshakeRequest(BaseModel):
    type: Literal["handshake"]
    profile: NodeProfile

# Response models
class EventsPayloadResponse(BaseModel):
    type: Literal["events_payload"] = "events_payload"
    events: list[WireEvent]

class RidsPayloadResponse(BaseModel):
    type: Literal["rids_payload"] = "rids_payload"
    rids: list[str]

class ManifestsPayloadResponse(BaseModel):
    type: Literal["manifests_payload"] = "manifests_payload"
    manifests: list[WireManifest]

class BundlesPayloadResponse(BaseModel):
    type: Literal["bundles_payload"] = "bundles_payload"
    bundles: list[dict]
    not_found: list[str] = []   # RIDs that don't exist
    deferred: list[str] = []    # RIDs not yet available

class HandshakeResponse(BaseModel):
    type: Literal["handshake_response"] = "handshake_response"
    profile: NodeProfile
    accepted: bool

# Signed envelope (Generic[T] pattern from BlockScience)
class SignedEnvelope(BaseModel):
    model_config = ConfigDict(exclude_none=True)
    payload: dict
    source_node: str
    target_node: str
    signature: str
```

### 3.3 Event Queue (Database-Backed)

**New file:** `koi-processor/api/event_queue.py`

> **Design decision:** Use the `koi_net_events` database table (migration 039) as the event queue, NOT JSON file persistence. We already have PostgreSQL — adding a second persistence mechanism creates unnecessary failure modes. The RegenAI coordinator used JSON files because it didn't have a local DB. Octo does.

```python
# Database-backed event queue
#
# Key operations:
# - add(event): INSERT into koi_net_events
# - poll(node_rid, limit): SELECT events not yet in delivered_to for this node
# - confirm(event_ids, node_rid): UPDATE confirmed_by array
# - cleanup(): DELETE WHERE expires_at < NOW() AND all peers confirmed
#   (or TTL-based: DELETE WHERE expires_at < NOW())
#
# The confirmed_by column tracks delivery acknowledgment per peer.
# Events expire after configurable TTL (default 24h for localhost,
# 72h for remote peers) but are only deleted once all configured
# peers have confirmed receipt (or TTL expires).
```

**Event confirmation flow:**

The poller confirms **after successfully processing** the event — not on receipt, not after storing a cross-reference, but after the entire handler pipeline completes:

```python
# Poller confirmation sequence:
# 1. POST /koi-net/events/poll → receive events
# 2. For each event:
#    a. Resolve entity against local registry
#    b. Create cross-reference (or merge/skip)
#    c. Store in local cache
#    d. If all steps succeed: add event_id to confirm_batch
#    e. If any step fails: log error, skip this event (will re-deliver next poll)
# 3. POST /koi-net/events/confirm with confirm_batch
# 4. If confirm call fails (network blip): no harm — events re-deliver next poll
```

**Idempotent processing:** Because confirmation can fail, the poller must handle duplicate delivery:
- Entity resolution is naturally idempotent (resolve → "already exists" → skip)
- Cross-reference creation uses `ON CONFLICT (local_uri, remote_rid) DO NOTHING`
- The `delivered_to` array on poll prevents re-delivery within the same poll cycle, but a failed confirm means the event appears again on the next poll — this is correct behavior

**TTL configuration:** Event TTL is configurable per edge via `koi_net_edges.metadata`:
```python
# Default: 24 hours (localhost peers, fast polling)
# Remote peers: 72 hours (allows for maintenance windows)
# Configurable via edge metadata: {"event_ttl_hours": 72}
```

### 3.4 Signed Envelope Support

**New file:** `koi-processor/api/koi_envelope.py`

**Port directly** from RegenAI's `shared/koi_envelope.py` — do not reimplement:
- ECDSA P-256 key generation and loading
- Raw `r||s` signature encoding (not DER — the `_der_to_raw_signature()` converter is critical)
- `model_dump_json(exclude_none=True)` for canonical serialization
- Sign/verify envelope functions
- Public key registry

**Key storage:** `/root/koi-state/{agent_name}_private_key.pem`
**Public keys:** Stored in `koi_net_nodes` table (not a separate JSON file)

**New dependency:** `cryptography>=42.0` (add to `requirements.txt`)

**Acceptance test:** Port `koi_net_interop_test.py` from RegenAI. If it passes against the new implementation, we're compatible.

### 3.5 Protocol Endpoints

**New file:** `koi-processor/api/koi_net_router.py` (separate FastAPI router)

```python
# KOI-net protocol endpoints (under /koi-net/ prefix)
POST /koi-net/handshake           # Exchange NodeProfile, establish edges
POST /koi-net/events/broadcast    # Receive events from peers
POST /koi-net/events/poll         # Serve queued events to polling nodes
POST /koi-net/events/confirm      # Acknowledge receipt of events
POST /koi-net/manifests/fetch     # Serve manifests by RID
POST /koi-net/bundles/fetch       # Serve bundles by RID (with not_found/deferred)
POST /koi-net/rids/fetch          # List available RIDs (with rid_types filter)
GET  /koi-net/health              # Node identity, connected peers, capabilities
```

**Handshake endpoint** (`POST /koi-net/handshake`):
1. Receive peer's `NodeProfile` (base_url, node_type, capabilities, public_key)
2. Store/update in `koi_net_nodes` table
3. Respond with own `NodeProfile`
4. Auto-propose edges based on matching `provides.event` ↔ subscribed `rid_types`
5. Initially: auto-approve edges for localhost peers (same VPS)

Each endpoint:
1. Detects if request is a `SignedEnvelope`
2. Verifies signature if present (lookup public key from `koi_net_nodes`)
3. Processes request
4. Signs response if request was signed

### 3.6 Node Identity

**New file:** `koi-processor/api/node_identity.py`

```python
# Generates or loads node identity:
# - Private key (ECDSA P-256)
# - Public key (DER-encoded, base64)
# - Node RID: orn:koi-net.node:{name}+{sha256(public_key_der)[:16]}
# - NodeProfile with capability declaration:
#     provides.event = [Practice, Pattern, CaseStudy, Bioregion]
#     provides.state = [Practice, Pattern, CaseStudy, Bioregion, Organization, Person]
#
# On first startup: generate keypair, save private key, derive node RID
# On subsequent startups: load from file
```

### 3.7 Database Migration

**New migration:** `koi-processor/migrations/039_koi_net_events.sql`

```sql
-- Event tracking for KOI-net protocol (database-backed queue)
CREATE TABLE IF NOT EXISTS koi_net_events (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT gen_random_uuid(),
    event_type VARCHAR(10) NOT NULL,  -- NEW, UPDATE, FORGET
    rid TEXT NOT NULL,
    manifest JSONB,
    contents JSONB,
    source_node TEXT,
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    delivered_to TEXT[] DEFAULT '{}',
    confirmed_by TEXT[] DEFAULT '{}',
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours'  -- default; overridden per-edge via metadata.event_ttl_hours
);

CREATE INDEX IF NOT EXISTS idx_koi_events_rid ON koi_net_events(rid);
CREATE INDEX IF NOT EXISTS idx_koi_events_type ON koi_net_events(event_type);
CREATE INDEX IF NOT EXISTS idx_koi_events_expires ON koi_net_events(expires_at);
CREATE INDEX IF NOT EXISTS idx_koi_events_queued ON koi_net_events(queued_at);

-- Edge profiles for node-to-node relationships
CREATE TABLE IF NOT EXISTS koi_net_edges (
    id SERIAL PRIMARY KEY,
    edge_rid TEXT UNIQUE NOT NULL,
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    edge_type VARCHAR(10) NOT NULL,  -- WEBHOOK, POLL
    status VARCHAR(10) NOT NULL,     -- PROPOSED, APPROVED
    rid_types TEXT[] DEFAULT '{}',   -- Which RID types flow on this edge
    metadata JSONB DEFAULT '{}',    -- Per-edge config (e.g., {"event_ttl_hours": 72})
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Node registry (known peers)
CREATE TABLE IF NOT EXISTS koi_net_nodes (
    id SERIAL PRIMARY KEY,
    node_rid TEXT UNIQUE NOT NULL,
    node_name TEXT,
    node_type VARCHAR(10),    -- FULL, PARTIAL
    base_url TEXT,
    public_key TEXT,          -- DER-encoded, base64
    provides_event TEXT[] DEFAULT '{}',   -- RID types this node broadcasts
    provides_state TEXT[] DEFAULT '{}',   -- RID types this node serves
    last_seen TIMESTAMPTZ,
    status VARCHAR(10) DEFAULT 'active',
    metadata JSONB DEFAULT '{}'
);
```

### Tasks

- [ ] Add `rid-lib>=3.2.8` to `requirements.txt` and verify it installs in Python 3.12 venv
- [ ] Create `koi-processor/api/koi_protocol.py` — Pydantic wire models with NodeProfile, rid_types filter, not_found/deferred
- [ ] Create `koi-processor/api/event_queue.py` — database-backed event queue with confirmation tracking
- [ ] Create `koi-processor/api/koi_envelope.py` — port from RegenAI's `shared/koi_envelope.py` (ECDSA P-256, raw r||s signatures)
- [ ] Create `koi-processor/api/node_identity.py` — keypair generation, node RID, NodeProfile
- [ ] Create `koi-processor/api/koi_net_router.py` — separate FastAPI router with feature flag
- [ ] Implement all 8 endpoints (handshake, broadcast, poll, confirm, manifests, bundles, rids, health)
- [ ] Create migration `039_koi_net_events.sql`
- [ ] Run migration on all databases (octo_koi, gv_koi)
- [ ] Add `cryptography>=42.0`, `httpx>=0.27`, `rid-lib>=3.2.8` to `requirements.txt`
- [ ] Set `KOI_NET_ENABLED=true` in Octo's env, `KOI_NET_ENABLED=false` in GV's env initially
- [ ] Generate node identities for Octo and GV agents
- [ ] Run interop test (ported from RegenAI) against Octo's endpoints

**Test criteria:**
- Node identity generated and persisted across restarts
- Signed envelope round-trip: sign → serialize → deserialize → verify (using raw r||s, not DER)
- Events can be broadcast to one node and polled from another
- Event confirmation endpoint updates `confirmed_by` array
- RIDs fetchable with `rid_types` filter (e.g., only Practice RIDs)
- Bundle fetch returns `not_found` for deleted/unknown RIDs
- Handshake exchanges NodeProfile and stores in `koi_net_nodes`
- Interop test passes against the implementation
- Feature flag: endpoints return 404 when `KOI_NET_ENABLED=false`

---

## Phase 4: Federation (Greater Victoria ↔ Octo)

**Goal:** Prove two-node federation works — GV documents a practice, Octo receives it.

### 4.0 RID Mapping for Existing Entities

Existing entities use `fuseki_uri` format (e.g., `orn:entity:practice/herring-monitoring+abc123`). KOI-net protocol expects RIDs matching `rid-lib` format. Before federation can work, we need a mapping strategy.

**Approach:** Add `koi_rid` column via SQL migration, then backfill in Python using `rid-lib`'s own hash function to ensure RID format exactly matches runtime generation.

> **Why Python, not SQL:** The original plan used SQL's `sha256()` + `entity_slug`, but: (1) `sha256()` requires the `pgcrypto` extension (not currently installed), (2) `entity_slug` doesn't exist as a column — entities have `fuseki_uri`, `canonical_name`, `normalized_text`, `entity_type`, but no pre-computed slug, and (3) computing RIDs in Python using `rid-lib` guarantees format compatibility with what the runtime generates.

**SQL migration:** `koi-processor/migrations/040_entity_koi_rids.sql`
```sql
-- Add KOI RID column (backfill happens via Python script)
ALTER TABLE entity_registry ADD COLUMN IF NOT EXISTS koi_rid TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_koi_rid ON entity_registry(koi_rid) WHERE koi_rid IS NOT NULL;
```

**Python backfill script:** `koi-processor/scripts/backfill_koi_rids.py`
```python
# One-time migration script — run after 040_entity_koi_rids.sql
#
# 1. Connect to database (asyncpg)
# 2. SELECT fuseki_uri, entity_type, normalized_text FROM entity_registry WHERE koi_rid IS NULL
# 3. For each entity:
#    - Derive slug from normalized_text (lowercase, replace spaces with hyphens)
#    - Generate KOI RID using rid-lib: sha256_hash() of fuseki_uri for the hash suffix
#    - Format: orn:koi-net.{type}:{slug}+{hash[:16]}
# 4. UPDATE entity_registry SET koi_rid = ? WHERE fuseki_uri = ?
# 5. Report: "{n} entities backfilled with KOI RIDs"
#
# Usage: python3 koi-processor/scripts/backfill_koi_rids.py --db-url postgresql://postgres:PASSWORD@localhost:5432/octo_koi
```

New entities created after Phase 4 get both `fuseki_uri` (for backward compatibility) and `koi_rid` (for federation) at registration time. The `/register-entity` endpoint generates `koi_rid` using the same `rid-lib` logic as the backfill script.

### 4.0b Concurrent Entity Creation Safety

Add `ON CONFLICT` handling to entity creation to prevent race conditions when two agents simultaneously resolve the same entity:

```python
# In register-entity endpoint:
# INSERT INTO entity_registry ... ON CONFLICT (fuseki_uri) DO UPDATE SET updated_at = NOW()
# This prevents unhandled exceptions during concurrent cross-agent resolution
```

### 4.1 Edge Negotiation

Configure edges between GV (partial node) and Octo (full node):

```python
# GV → Octo edge:
#   source: orn:koi-net.node:greater-victoria+abc123
#   target: orn:koi-net.node:octo-salish-sea+def456
#   edge_type: POLL  (GV polls Octo)
#   rid_types: [Practice, Pattern, CaseStudy, Bioregion]
#   status: APPROVED

# Octo → GV edge:
#   source: orn:koi-net.node:octo-salish-sea+def456
#   target: orn:koi-net.node:greater-victoria+abc123
#   edge_type: POLL  (GV polls Octo)
#   rid_types: [Practice, Pattern]  # GV only gets practices and patterns
#   status: APPROVED
```

For the initial implementation, edges can be configured manually via database inserts rather than the full negotiation protocol.

### 4.2 Entity-to-Event Bridge

**What:** When an entity is registered or updated in Octo's vault, emit a KOI-net event.

**Modify:** `personal_ingest_api.py` — `POST /register-entity` endpoint

```python
# After successful entity registration:
# 1. Create WireManifest (rid, timestamp, sha256 of content)
# 2. Create WireEvent (NEW or UPDATE based on is_new)
# 3. Queue event in event_queue
# 4. Event becomes available to polling peers
```

Similarly for `POST /sync-relationships` — emit UPDATE events when relationships change.

### 4.3 Polling Client

**New file:** `koi-processor/api/koi_poller.py`

```python
# Background task that polls a peer node for events
# Runs as part of the KOI API startup
#
# 1. Read configured edges from koi_net_edges table
# 2. For each POLL edge where we are the target:
#    - POST /koi-net/events/poll to source node
#    - Receive events
#    - For each event: resolve entity against local registry
#    - Cache or link as appropriate
# 3. Sleep poll_interval seconds, repeat
```

### 4.4 Cross-Agent Entity Resolution

When GV receives a Practice from Octo (or vice versa), it needs to resolve the entity:

```python
# Entity arrives: "Herring Monitoring" (Practice) from Octo
# GV's resolver runs:
#   Tier 1: Exact match against gv_koi → no hit
#   Tier 2: Semantic match → similarity 0.92 with local "Gorge Creek Herring Count"
#   Decision: Create cross-reference (related_to) rather than merge
#   Store: koi_net_cross_refs table links GV entity to Octo entity via RID
```

**New migration:** `koi-processor/migrations/041_cross_references.sql`

```sql
CREATE TABLE IF NOT EXISTS koi_net_cross_refs (
    id SERIAL PRIMARY KEY,
    local_uri TEXT NOT NULL,
    remote_rid TEXT NOT NULL,
    remote_node TEXT NOT NULL,
    relationship VARCHAR(20) DEFAULT 'related_to',
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cross_refs_local ON koi_net_cross_refs(local_uri);
CREATE INDEX IF NOT EXISTS idx_cross_refs_remote ON koi_net_cross_refs(remote_rid);
```

### 4.5 End-to-End Test

**Test scenario:**
1. Create a new Practice note in GV vault: `vault/Practices/gorge-creek-herring.md`
2. Register entity via GV API: `POST http://127.0.0.1:8352/register-entity`
3. GV emits NEW event to its event queue
4. Octo's poller picks up the event from GV
5. Octo resolves entity against its own registry
6. Octo creates cross-reference to GV's entity
7. Verify: `GET http://127.0.0.1:8351/entity/{uri}` shows cross-reference

**Test script:** `scripts/test-federation.sh`

### Tasks

- [ ] Create migration `040_entity_koi_rids.sql` — add `koi_rid` column and unique index
- [ ] Create `koi-processor/scripts/backfill_koi_rids.py` — one-time Python backfill using rid-lib's hash function
- [ ] Run migration, then backfill script on `octo_koi`
- [ ] Add `ON CONFLICT` handling to entity creation path in `/register-entity`
- [ ] Insert manual edge configurations for GV ↔ Octo (via handshake or DB insert)
- [ ] Enable `KOI_NET_ENABLED=true` on both Octo and GV
- [ ] Modify `/register-entity` to emit KOI-net events (using `koi_rid` as the event RID)
- [ ] Modify `/sync-relationships` to emit KOI-net events
- [ ] Create `koi_poller.py` — background polling client
- [ ] Integrate poller into FastAPI startup (asyncio background task)
- [ ] Create migration `041_cross_references.sql`
- [ ] Write end-to-end federation test script
- [ ] Test: GV Practice → event → Octo receives → cross-reference created

**Test criteria:**
- All existing entities have `koi_rid` values after migration + backfill script
- New entities get both `fuseki_uri` and `koi_rid` at creation
- Entity creation handles concurrent inserts without exceptions
- Event emitted when entity registered in either agent
- Polling client successfully retrieves events from peer
- Entity resolved against local registry (not blindly imported)
- Cross-references created with confidence scores
- No duplicate entities created

---

## Resource Checkpoint (Gate: Phase 4 → Phase 4.5)

Before adding a third agent, review resource monitoring logs from Phase 2.3:

```bash
# Check sustained RAM usage over the past 7 days
grep "RAM:" /var/log/koi-resources.log | tail -168  # 7 days × 24 checks/day

# Check PostgreSQL connection count
docker exec regen-koi-postgres psql -U postgres -t -c \
  "SELECT datname, numbackends FROM pg_stat_database WHERE datname LIKE '%_koi'"
```

**Gate criteria:**
- Sustained RAM < 6GB → proceed to Phase 4.5
- Sustained RAM 6-7GB → increase VPS RAM to 16GB before proceeding
- Sustained RAM > 7GB → investigate memory pressure (likely pgvector HNSW indexes), optimize before adding agents
- PostgreSQL connections < 30 (of 100 max) → proceed
- PostgreSQL connections > 50 → review pool sizes, consider reducing `max_size` per agent from 10 to 5

This checkpoint is a gate, not a note. Do not proceed to Phase 4.5 without passing these criteria.

---

## Phase 4.5: Second Leaf Node (Cowichan Valley)

**Goal:** Add a second leaf node under Octo to prove horizontal federation and genuine aggregation at the coordinator level.

**Why needed:** With one leaf node (GV), Cascadia just sees Octo — not a network. Two leaves prove that Octo genuinely aggregates knowledge from multiple sub-bioregions before forwarding to Cascadia. This is the minimum viable test of the holon pattern.

**Depends on:** Resource Checkpoint passing.

**Bioregion:** Cowichan Valley — distinct watershed and ecological identity, separate from Greater Victoria, with strong community monitoring traditions.

### Setup

Follow the same pattern as Phase 2 (GV agent):
- Database: `cv_koi`
- Port: 8354
- Config: `/root/cv-agent/config/cv.env`
- Systemd: `cv-koi-api.service`
- Vault: Seed with 2-3 local practices distinct from GV's

### Federation

- Configure edges: CV ↔ Octo (same pattern as GV ↔ Octo)
- Enable `KOI_NET_ENABLED=true`
- Test: CV documents a practice → Octo receives from both GV and CV
- Verify: Octo's event queue contains events from both leaf nodes

### Tasks

- [ ] Create agent directory and config (same pattern as Phase 2.2)
- [ ] Create database: `./create-additional-dbs.sh cv_koi`
- [ ] Seed vault with 2-3 unique practices
- [ ] Configure edges to Octo
- [ ] Test horizontal federation: both GV and CV events arrive at Octo
- [ ] Verify entity cross-references work across three agents

**Test criteria:**
- Octo receives events from both GV and CV independently
- Cross-agent entity resolution works between all three agents
- No event duplication or cross-contamination between leaf nodes

---

## Phase 5: Cascadia Coordinator

**Goal:** Add a third agent that sees the Salish Sea (Octo + GV) as a single node — proving the holon pattern.

### 5.1 Cascadia Database & API

Follow the same pattern as Phase 2:
- Database: `cascadia_koi` (already created in Phase 2 migration)
- Port: 8353
- Config: `/root/cascadia-agent/config/cascadia.env`
- Systemd: `cascadia-koi-api.service`

Cascadia's workspace files encode the broader bioregional context:
```
/root/cascadia-agent/
├── config/cascadia.env
├── vault/
│   ├── Bioregions/
│   │   └── Cascadia.md
│   │   └── Salish Sea.md  # Cross-reference to Octo
│   ├── Patterns/          # Aggregated patterns
│   └── Practices/         # Cross-bioregional practices
└── workspace/
    └── IDENTITY.md         # "I am Cascadia..."
```

### 5.2 Holon Boundary: Octo as Proxy

**What:** Octo acts as the Salish Sea network's external interface. When Cascadia polls Octo, it sees aggregated knowledge from both Octo and GV — not the internal structure.

**Implementation:** Octo's network handler filters outbound events:
- Practices and Patterns from GV are re-broadcast to Cascadia
- GV's node identity is not exposed — events appear to come from Octo
- Internal governance, meeting notes, etc. are never shared
- Entities with `access_level` of `restricted` or `sacred` are **never** included in outbound events (enforced in network handler, per [ontological architecture](./ontological-architecture.md))

**Modify:** Event queue logic to support "upstream forwarding." This is the core of the holon boundary — Octo is a **knowledge-transforming relay**, not a passthrough proxy.

```python
# When Octo receives a Practice event from GV:
#
# 1. Process locally (cross-reference, resolve entity)
# 2. Create a NEW outbound event for Cascadia:
#
#    RID:       PRESERVED — the RID is the stable reference to the knowledge,
#               not the messenger. Cascadia needs the same RID to track updates.
#
#    Manifest:  REWRITTEN — new timestamp (Octo's relay time), new sha256_hash
#               (content may have changed during processing). The manifest is
#               Octo's attestation of this knowledge, not GV's.
#
#    Contents:  TRANSFORMED — Octo resolves internal references before forwarding:
#               - GV-local wikilinks (e.g., [[People/Jane Smith]]) are stripped
#                 or replaced with entity URIs
#               - Relationships referencing GV-only entities are either resolved
#                 to Octo-level entities or omitted
#               - access_level filtering applied (restricted/sacred never forwarded)
#               - source attribution added: {"relayed_by": "octo", "origin": "greater-victoria"}
#
#    source_node: REWRITTEN to Octo's node RID (holon boundary)
#
#    Signature:  RE-SIGNED with Octo's key (Cascadia trusts Octo, not GV)
#
# 3. Queue the transformed event for Cascadia's poll
```

This means Cascadia sees a Practice that appears to originate from the Salish Sea (Octo), with Octo's attestation (manifest + signature), and clean content (no internal GV references). The original GV provenance is preserved in the content's `origin` field for auditability, but the protocol-level identity is Octo's.

### 5.3 Aggregation Logic

Cascadia's bundle handler implements pattern detection:
```python
# When Cascadia receives Practices from Octo:
# 1. Resolve against Cascadia's entity registry
# 2. Compute semantic similarity with all cached Practices
# 3. If cluster of 3+ similar Practices found:
#    - Propose a Pattern entity
#    - Link via aggregates_into
#    - Queue Pattern as NEW event for downstream
```

This is the initial version — full pattern mining is Phase 6.

### Tasks

- [ ] Set up Cascadia database, API, systemd service (same pattern as Phase 2)
- [ ] Write Cascadia workspace files
- [ ] Configure edges: Octo → Cascadia (POLL, Practices + Patterns only)
- [ ] Implement upstream forwarding in Octo's event logic
- [ ] Implement basic aggregation handler for Cascadia
- [ ] Test: GV documents practice → Octo receives → Cascadia receives (3-hop)
- [ ] Verify: Cascadia sees "Salish Sea" as source, not "Greater Victoria"

**Test criteria:**
- Cascadia receives events from Octo only (not directly from GV)
- Events appear to originate from Octo (holon boundary maintained)
- Cascadia can resolve entities against its own registry
- Three-hop event propagation works within acceptable latency

---

## Phase 5.5: Front Range (Peer Network)

**Goal:** Establish the Front Range as a separate bioregional network that peers with Cascadia — proving inter-network federation beyond the Salish Sea holon.

**Why needed:** Front Range is NOT a leaf under Cascadia. It's a distinct bioregional network with its own coordinator and leaf nodes. Federation between Cascadia and Front Range happens at the coordinator level, demonstrating that the holon pattern scales horizontally across bioregions.

**Depends on:** Phase 5 (Cascadia Coordinator) working.

### Setup

- Database: `fr_koi`
- Port: 8355
- Config: `/root/fr-agent/config/fr.env`
- Systemd: `fr-koi-api.service`
- Node name: `front-range-coordinator`

### Federation

- Peer edges: Cascadia ↔ Front Range (bidirectional POLL, coordinator-to-coordinator)
- NOT hierarchical — neither is "above" the other
- Each network maintains its own holon boundary
- Shared ontology ensures cross-network entity resolution

### Tasks

- [ ] Create Front Range agent directory and config
- [ ] Create database: `./create-additional-dbs.sh fr_koi`
- [ ] Write workspace files (IDENTITY.md with Front Range context)
- [ ] Seed vault with Front Range-specific practices
- [ ] Configure peer edges: Cascadia ↔ Front Range
- [ ] Test: Practice registered in Front Range appears as cross-reference in Cascadia
- [ ] Verify: Practices do NOT flow from Front Range → Octo (holon boundary)

---

## Phase 5.6: Error Handling & Failure Modes

**Goal:** Before opening the network to external nodes, design and implement error handling for cross-node failure scenarios.

> **Why a separate phase:** Phases 2-5 test on localhost where network failures don't happen. Before any real federation (second VPS, external bioregional agents), we need to handle the failure modes that only appear over real networks.

### Failure Modes to Handle

| Failure | Detection | Response |
|---------|-----------|----------|
| **Peer node down** during poll | `httpx.ConnectError` or timeout | Exponential backoff: 30s → 60s → 120s → 300s → 600s (max). Log warning. Resume normal interval after successful poll. |
| **Signed envelope verification fails** | `InvalidSignature` exception | **Reject event.** Log at WARNING with peer node RID, event RID, and failure reason. Do NOT alert on single failures (could be key rotation). Alert if 3+ consecutive failures from same peer (possible key compromise or misconfiguration). |
| **Event references unknown RID** | `not_found` in bundle fetch response | Cache the RID as "pending." Re-request on next poll cycle. After 3 failed attempts: mark as "stale" and stop retrying. Log at INFO. |
| **Poll returns events from revoked edge** | Edge status = REVOKED in `koi_net_edges` | Silently discard events. Do not confirm. Log at DEBUG. |
| **Confirm endpoint unreachable** | `httpx.ConnectError` on confirm call | No harm — events will re-deliver on next poll. Idempotent processing handles duplicates. Log at DEBUG. |
| **Database full / connection pool exhausted** | `asyncpg.TooManyConnectionsError` | Return 503 on all KOI-net endpoints. Poller pauses. Resume when connections available. |
| **Malformed event payload** | Pydantic validation error | Reject individual event, continue processing remaining events in batch. Log at WARNING with payload hash (not full content — could be large). |

### Tasks

- [ ] Implement exponential backoff in `koi_poller.py`
- [ ] Add signature verification failure logging and alerting threshold
- [ ] Add "pending RID" tracking with retry limit
- [ ] Add 503 response on pool exhaustion for KOI-net endpoints
- [ ] Add per-event error handling in batch processing (don't fail entire batch on one bad event)
- [ ] Write integration test: simulate peer down → backoff → recovery
- [ ] Document failure modes in operational runbook

---

## Phase 5.7: GitHub Sensor (Self-Knowledge)

**Goal:** Give Octo knowledge of its own architecture by ingesting its GitHub repository through a KOI sensor. This enables Octo to answer questions about its own codebase, implementation plan, and ontology.

**Why:** Currently Octo has 70 entities about bioregional knowledge but zero self-knowledge. It can explain herring monitoring but not how its own event queue works. A GitHub sensor that indexes `DarrenZal/Octo` into the KOI API creates a self-referential knowledge loop — the agent understands the system it runs on.

**Reference implementation:** `~/projects/RegenAI/koi-sensors/sensors/github/github_sensor.py` — an existing GitHub sensor that indexes Regen Network repos into the RegenAI KOI coordinator. Adapt this to target Octo's KOI API.

### Setup

**New file:** `koi-processor/sensors/github_sensor.py` (adapted from RegenAI)
**Config:** `koi-processor/config/github_sensor.yaml`

```yaml
sensor:
  name: octo-github-sensor
  type: github
  coordinator_url: "http://127.0.0.1:8351"  # Octo KOI API

repositories:
  - name: Octo
    url: https://github.com/DarrenZal/Octo
    branch: main
    paths:
      - "docs/"
      - "koi-processor/api/"
      - "koi-processor/migrations/"
      - "workspace/"
      - "ontology/"
      - "README.md"
      - "CLAUDE.md"
    priority: high
    check_interval: 3600  # 1 hour

  - name: koi-net
    url: https://github.com/BlockScience/koi-net
    branch: main
    paths: ["src/", "docs/", "README.md"]
    priority: medium
    check_interval: 86400  # Daily

  - name: personal-koi-mcp
    url: https://github.com/DarrenZal/personal-koi-mcp
    branch: main
    paths: ["src/", "README.md"]
    priority: medium
    check_interval: 86400
```

### What Gets Indexed

The sensor creates entities of type `Concept` (for architectural components) and documents (for markdown files), with relationships:
- Implementation plan sections → `about` → entity types they describe
- API files → `implements` → protocol concepts
- Ontology files → `documents` → the BKC ontology itself

### Integration

- Source tag: `source: "github-sensor"` (distinct from `personal-vault`)
- Entity types: primarily `Concept` and `Project` (not Practice/Pattern — those come from bioregional knowledge)
- Cross-references: entities from GitHub docs that mention bioregional concepts (e.g., "Herring Monitoring" in README.md) create links to existing vault entities

### Tasks

- [ ] Adapt `github_sensor.py` from RegenAI to work with Octo's KOI API (different endpoint format)
- [ ] Create `github_sensor.yaml` config pointing at Octo + BlockScience repos
- [ ] Add systemd service for the sensor
- [ ] Test: sensor indexes Octo README → entity created with source `github-sensor`
- [ ] Verify: cross-references between GitHub-sourced entities and vault entities resolve correctly
- [ ] Optional: add sensor for each leaf node's repo (CV, FR) so each agent knows its own code

---

## Phase 6: Cross-Scale Pattern Mining

> **Status: Design TBD.** This phase requires a separate design spike before implementation. The outline below captures intent and open questions, but is not yet a buildable spec. Plan a dedicated design session after Phase 5 proves the holon pattern works.

**Goal:** Automatically surface trans-bioregional patterns from the aggregates_into / suggests cycle.

### 6.1 Practice Clustering

At the Cascadia coordinator level:
1. Maintain embeddings for all cached Practice entities
2. Periodically compute pairwise semantic similarity
3. Cluster similar practices (threshold: TBD, starting point 0.75)
4. For clusters with 3+ practices from 2+ sub-bioregions: propose a Pattern

### 6.2 Pattern Creation

```python
# Proposed Pattern:
# - name: derived from cluster centroid (or LLM-generated summary)
# - @type: Pattern
# - aggregates_into relationships to all source Practices
# - practiced_in: union of all source Bioregions
# - confidence: average pairwise similarity
```

### 6.3 Pattern Broadcasting

Cascadia broadcasts the Pattern as a NEW event to all connected agents. Each agent:
1. Receives the Pattern
2. Links local Practices via `aggregates_into`
3. Can use `suggests` to identify gaps (practices this bioregion could adopt)

### Design Questions (Must Resolve Before Implementation)

These questions need answers during the design spike:

1. **Embedding model:** Same `text-embedding-ada-002` used for entity resolution, or a different model optimized for document-level similarity? ada-002 works well for short entity names but may not capture practice-level semantics from longer descriptions.

2. **Trigger mechanism:** When does clustering run? Options:
   - Cron job (e.g., daily) — simplest, but pattern discovery is delayed
   - On new practice arrival — responsive, but expensive if practices arrive in bursts
   - On-demand via API call — manual but controlled
   - Threshold-based: re-cluster when N new practices have arrived since last run

3. **Pattern proposal review:** How are proposed patterns reviewed?
   - Auto-created with `status: proposed` → human reviews and approves/rejects
   - Flagged for Darren (or designated reviewer) via notification
   - Auto-approved above confidence threshold (risky — may create noise)
   - Presented to the BKC CoIP community for validation

4. **`suggests` relationship generation:** How does a Pattern suggest new practices?
   - LLM reasoning: "Given this pattern and this bioregion, what practices might apply?" (expensive, creative)
   - Nearest-neighbor: find practices in other bioregions semantically close to the pattern but not yet linked (mechanical, fast)
   - Manual: human creates suggests links after reviewing patterns (safe, slow)
   - Hybrid: nearest-neighbor proposes, human approves

5. **Similarity threshold:** 0.75 is a starting point. Need empirical validation with real practice data. Too high = no patterns found. Too low = noisy patterns. Should this be configurable per entity type?

6. **Pattern deduplication:** When the same cluster is detected on consecutive runs, how do we avoid creating duplicate patterns? Match by constituent practices? By embedding similarity to existing patterns?

7. **Mapping completeness threshold:** What minimum mapping coverage is needed for meaningful pattern mining? An entity only enters the commons layer through an explicit mapping — if a source schema has < 30% mapped fields, its entities contribute little to pattern discovery. Should pattern mining require a minimum mapping ratio per source? See [ontological architecture](./ontological-architecture.md) Section 5.

### Tasks (After Design Spike)

- [ ] **Design spike:** Answer the 6 design questions above, write design doc
- [ ] Implement practice embedding caching at coordinator level
- [ ] Implement clustering algorithm (cosine similarity + threshold)
- [ ] Implement Pattern entity creation from clusters
- [ ] Implement pattern review workflow (per design spike decision)
- [ ] Implement Pattern broadcasting
- [ ] Implement `suggests` relationship generation (per design spike decision)
- [ ] Test with synthetic data: 6+ practices from 2 sub-bioregions
- [ ] Validate: Pattern emerges → agents receive it → suggests relationships created

---

## Dependencies & Requirements

### Python Packages (add to `requirements.txt`)

```
rid-lib>=3.2.8        # BlockScience RID library (RID types, JCS hashing, manifests)
cryptography>=42.0    # ECDSA P-256 for signed envelopes
httpx>=0.27           # Async HTTP client for polling/federation
pyyaml>=6.0           # Sensor config parsing
watchdog>=4.0         # File system monitoring (markdown sensor)
```

> **Note:** [`rid-lib`](https://github.com/BlockScience/rid-lib) uses JCS (JSON Canonicalization Scheme) for deterministic hashing of knowledge objects. This is not the same as `hashlib.sha256(json.dumps(...))`. Using the canonical library prevents interop failures with other KOI-net nodes.

### Existing Dependencies (already in use)
- `fastapi`, `uvicorn` — API framework
- `asyncpg` — PostgreSQL async driver
- `pydantic>=2.0` — Data models
- `openai` — Embeddings

### Infrastructure
- No additional VPS needed (all agents on existing server)
- No additional Docker containers (shared PostgreSQL)
- Disk usage: ~500MB per additional agent (vault + database)
- Memory: ~100-200MB per additional KOI API instance
- **Resource concern:** 4 agents sharing 8GB RAM with pgvector HNSW indexes on 1536-dim vectors will stress `shared_buffers`. Monitor PostgreSQL memory usage via `pg_stat_activity` before adding Phase 4.5 agent. If RAM exceeds 6GB sustained, consider either reducing embedding dimensions, increasing VPS RAM, or splitting to a second server.
- **OpenAI API:** All agents share one API key. Tag embedding requests with agent name for cost tracking. Watch rate limits during concurrent entity resolution across 3+ agents.

---

## Milestones & Verification

| Milestone | Phase | Verification |
|-----------|-------|-------------|
| BKC vault schema mapped | 0.5 | Schema mapping document written |
| Source schemas & ontology mappings populated | 0.5 | `source_schemas` and `ontology_mappings` tables have BKC CoIP entries |
| Ontology gaps identified | 0.5 | Unmapped fields documented with extension proposals where warranted |
| Schema infrastructure migration applied | 1.1b | `source_schemas`, `ontology_mappings` tables exist; entity_registry has new columns |
| BKC sensor ingests markdown | 1.1 | Entity created from external markdown file |
| Source metadata preserved on ingestion | 1.1 | Entity's `source_metadata` contains full original YAML |
| Practice export works | 1.2 | Round-trip: export → re-import → no duplicates |
| GV agent runs independently | 2 | Health check passes, entities resolvable, predicates populated |
| Backups cover all databases | 2.3 | Daily backup includes gv_koi, cascadia_koi |
| rid-lib installed and working | 3.1 | JCS hash matches BlockScience reference output |
| Signed envelope round-trip | 3.4 | Sign → verify across two nodes (raw r\|\|s format) |
| Handshake exchanges profiles | 3.5 | NodeProfile stored in koi_net_nodes table |
| Event broadcast/poll/confirm works | 3.5 | Event emitted, polled, confirmed across two nodes |
| Interop test passes | 3 | Ported koi_net_interop_test.py succeeds |
| NodeProfile ontology fields added | Post-5 | `ontology_uri`, `ontology_version` on NodeProfile; `ontology_mapping` on edges (see [ontological architecture](./ontological-architecture.md) Section 9) |
| Existing entities have KOI RIDs | 4.0 | Python backfill script completes, all entity_registry rows have koi_rid values |
| GV → Octo federation | 4 | GV practice appears as cross-reference in Octo |
| Resource checkpoint passes | Gate | Sustained RAM < 6GB, PG connections < 30 |
| Second leaf node operational | 4.5 | Both GV and CV events arrive at Octo |
| Horizontal aggregation proven | 4.5 | Octo holds cross-references from 2 leaf nodes |
| 3-hop event propagation | 5 | GV → Octo → Cascadia with holon boundary |
| Upstream forwarding transforms content | 5.2 | Cascadia sees Octo as source, GV references resolved, access_level enforced |
| Cascadia sees aggregated network | 5 | Cascadia receives events from both sub-bioregions via Octo |
| Front Range peers with Cascadia | 5.5 | Practices federate between independent bioregional networks |
| Error handling for network failures | 5.6 | Exponential backoff, signature failure logging, stale RID handling |
| GitHub sensor indexes Octo repo | 5.7 | Entities with `source: github-sensor` exist, cross-ref to vault entities |
| Pattern mining design spike complete | 6 | Design doc answers all 6 open questions |
| Pattern emerges from practices | 6 | Cascadia creates Pattern from clustered practices |

---

## Open Questions (Resolved)

Resolved based on review feedback, with reasoning:

1. **OpenClaw for GV agent? → No, API-only.** GV's purpose is to prove federation — it's a knowledge backend, not a community-facing chatbot. Adding OpenClaw adds complexity (Telegram auth, Discord setup, workspace files) without testing anything new. If a Greater Victoria community emerges that wants its own chatbot, that's a future decision.

2. **Shared vs. separate embedding keys? → Shared key, tag requests for cost tracking.** Tag each embedding request with the agent name via custom metadata. Cost visibility without managing multiple API keys. Separate keys only matter if billing different organizations.

3. **Edge negotiation automation? → After Phase 5, before external deployment.** Manual edges work for 3-4 nodes on one VPS. Automate via handshake before anyone outside our control connects. This is effectively a Phase 5.6 task.

4. **Second leaf node? → Phase 4.5 (Cowichan Valley).** Added to plan. Two leaf nodes under one coordinator is the minimum viable test of the holon pattern — with one leaf, Cascadia just sees Octo, not a network.

5. **Coordinator separation? → Keep merged, separate when resource-constrained.** The dual-role is simpler to deploy and debug. The code is structured so separation is a config change (different env file, different port, different endpoints enabled), not an architectural rewrite. Separate when adding a second leaf causes resource pressure or if entity count exceeds ~500.

## Remaining Open Questions

1. **rid-lib compatibility:** Does rid-lib v3.2.8 install cleanly in the Python 3.12 venv on the VPS? Validate before committing to Phase 3.

2. **BKC CoIP data access:** How do we get access to the BKC CoIP Obsidian vault? Through Andrea Farias, Vincent Arena (OMNI-Mapping), or the r3.0 team? This blocks Phase 0.5.

3. **localhost vs real federation:** All Phase 2-5 testing happens on localhost. The first real federation test (TLS, network latency, firewalls) happens when deploying to a second server. At what point does this become necessary to validate? Probably before inviting external bioregional agents to connect.

4. **Ontology extension governance:** Who reviews proposed ontology extensions? The BKC CoIP has a "Philosophy, Epistemology & Indigenous Knowledge" working group — are they the right body? How formal does the review process need to be for early stages vs. when external communities are contributing? See [ontological architecture](./ontological-architecture.md) Section 10.

5. **BKC CoIP consent model:** The BKC CoIP proposal mentions "granular permission systems" for data commoning. What's their timeline for implementing this? Does ingesting their published data into Octo require explicit consent, or is published data implicitly available? This affects Phase 0.5 scope.
