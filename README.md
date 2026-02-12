# Octo 🐙

**A bioregional knowledge commoning agent for the Salish Sea**

Octo is an AI agent built on [OpenClaw](https://github.com/DarrenZal/openclaw) (our fork of [openclaw/openclaw](https://github.com/openclaw/openclaw)) that serves as an organ of perception for the Salish Sea bioregion. It combines a knowledge graph backend with a formal ontology for bioregional knowledge commoning — enabling it to reason about practices, patterns, discourse, and the relationships between them.

Octo is also a **KOI-net federation coordinator** — it aggregates knowledge from leaf-node agents (Greater Victoria, Cowichan Valley, etc.) into a unified Salish Sea knowledge commons using the [KOI-net protocol](https://github.com/BlockScience/koi-net) for authenticated, event-driven federation.

## What Octo Does

- **Knowledge Commoning**: Tracks bioregional practices, identifies trans-bioregional patterns, and documents case studies using a formal ontology grounded in the work of David Bollier & Silke Helfrich
- **Discourse Graph**: Manages questions, claims, and evidence with typed relationships (supports, opposes, informs) — enabling progressive formalization of bioregional knowledge
- **Entity Resolution**: Multi-tier entity resolution (exact → fuzzy → semantic → create) with OpenAI embeddings and pgvector
- **Web Content Curation**: Users share URLs via Telegram/Discord, Octo previews (with Playwright for JS-rendered sites), evaluates bioregional relevance, and ingests into the knowledge graph with entity linking
- **Vault Integration**: Bidirectional linking between an Obsidian-style vault and a PostgreSQL knowledge graph
- **KOI-net Federation**: Authenticated event-driven protocol for cross-bioregional knowledge sharing with ECDSA-signed envelopes, background polling, and cross-reference resolution

## Website

The [Salish Sea Knowledge Garden](https://github.com/DarrenZal/salish-sea-garden) is Octo's public-facing knowledge site — a browsable, searchable view of the knowledge graph with an interactive D3.js visualization and a chatbot for asking Octo questions directly.

- Canonical URL: `https://45.132.245.30.sslip.io`
- Legacy/raw-IP URL: `http://45.132.245.30`

## Architecture

### Holonic Network

```
[Greater Victoria]   [Cowichan Valley]      ← leaf nodes (bioregional agents)
        ↘                 ↙
   [Octo / Salish Sea Coordinator]         ← federation coordinator
              ↓
      [Cascadia Coordinator]               ← future meta-coordinator

                                            [Front Range]
                                                ↑ separate bioregional network
                                                (peer of Cascadia, not under it)
```

Each node runs the same KOI API codebase with its own database, vault, and identity. Nodes exchange events via the KOI-net protocol — when a practice is registered in Greater Victoria, it appears as a cross-reference in Octo within seconds.

### Single Node

```
┌──────────────────────────────────────────────────┐
│                  OpenClaw Runtime                  │
│  (Telegram / Discord / CLI)                       │
├──────────────────────────────────────────────────┤
│  Workspace: IDENTITY.md, SOUL.md, KNOWLEDGE.md   │
├──────────────────────────────────────────────────┤
│  bioregional-koi plugin                           │
│  ├─ Entity resolution (resolve, register, search) │
│  ├─ Web content curation (preview_url, ingest_url)│
│  ├─ Vault read/write                              │
│  └─ Relationship sync                             │
├──────────────────────────────────────────────────┤
│  KOI Processor API (uvicorn)                      │
│  ├─ entity_schema.py  (15 entity types)           │
│  ├─ vault_parser.py   (27 predicates, aliases)    │
│  ├─ web_fetcher.py    (URL fetch + Playwright)    │
│  ├─ personal_ingest_api.py                        │
│  └─ KOI-net protocol (feature flag)               │
│     ├─ koi_net_router.py   (8 protocol endpoints) │
│     ├─ koi_envelope.py     (ECDSA P-256 signing)  │
│     ├─ koi_poller.py       (background poller)     │
│     ├─ event_queue.py      (DB-backed queue)       │
│     └─ node_identity.py    (keypair + RID)         │
├──────────────────────────────────────────────────┤
│  PostgreSQL + pgvector + Apache AGE               │
│  (Docker, localhost:5432)                         │
└──────────────────────────────────────────────────┘
```

### Live Agents

| Agent | Port | Node RID | Entities | KOI-net |
|-------|------|----------|----------|---------|
| **Octo** (Salish Sea) | 8351 | `orn:koi-net.node:octo-salish-sea+50a3c...` | 57 | Enabled (coordinator) |
| **Greater Victoria** | 8352 | `orn:koi-net.node:greater-victoria+81ec4...` | 4 | Enabled (leaf node) |

## BKC Ontology

The formal ontology (`ontology/bkc-ontology.jsonld`) defines 9 entity types and 17 predicates for bioregional knowledge commoning:

### Entity Types

| Phase | Type | Description |
|-------|------|-------------|
| **Knowledge Commoning** | Practice | Bioregional-specific activity or approach |
| | Pattern | Trans-bioregional generalization from practices |
| | CaseStudy | Documented real-world example |
| | Bioregion | Named ecological/cultural region |
| **Discourse Graph** | Protocol | General coordination pattern |
| | Playbook | Local implementation of a protocol |
| | Question | Inquiry or hypothesis |
| | Claim | Assertion or conclusion |
| | Evidence | Data, observations, or results |

Plus 6 base types inherited from the KOI system: Person, Organization, Project, Location, Concept, Meeting.

### Key Predicates

**Knowledge Commoning**: `aggregates_into` (Practice → Pattern), `suggests` (Pattern → Practice), `documents` (CaseStudy → Practice), `practiced_in` (Practice → Bioregion)

**Discourse Graph**: `supports`, `opposes`, `informs`, `generates`, `implemented_by`, `synthesizes`, `about`

**SKOS + Hyphal**: `broader`, `narrower`, `related_to`, `forked_from`, `builds_on`, `inspired_by`

See [ontology/bkc-ontology.jsonld](ontology/bkc-ontology.jsonld) for the formal OWL/RDFS definitions.

## Repository Structure

```
├── workspace/              # Octo's OpenClaw workspace (agent identity & config)
│   ├── IDENTITY.md         # Who Octo is
│   ├── SOUL.md             # Philosophy and values
│   ├── KNOWLEDGE.md        # BKC domain expertise
│   ├── USER.md             # About the human operator
│   ├── AGENTS.md           # Agent routing and session rules
│   ├── TOOLS.md            # Environment-specific tool config
│   └── HEARTBEAT.md        # Periodic check tasks
├── gv-agent/               # Greater Victoria leaf node
│   ├── config/gv.env       # GV-specific env (DB, port, node name)
│   ├── workspace/          # GV agent identity (IDENTITY.md, SOUL.md)
│   └── vault/              # GV seed entities (Practices/, Bioregions/)
├── plugins/
│   └── bioregional-koi/    # OpenClaw plugin connecting to KOI API
│       ├── openclaw.plugin.json
│       └── index.ts
├── koi-processor/          # Python backend (shared by all agents)
│   ├── api/
│   │   ├── personal_ingest_api.py   # Main API (FastAPI/uvicorn)
│   │   ├── entity_schema.py         # 15 entity types, resolution config
│   │   ├── vault_parser.py          # YAML→predicate mapping
│   │   ├── web_fetcher.py           # URL fetch, Playwright, content extraction
│   │   ├── koi_net_router.py        # KOI-net protocol endpoints
│   │   ├── koi_envelope.py          # ECDSA P-256 signed envelopes
│   │   ├── koi_poller.py            # Background federation poller
│   │   ├── koi_protocol.py          # Wire format models (Pydantic)
│   │   ├── event_queue.py           # DB-backed event queue
│   │   └── node_identity.py         # Keypair + node RID generation
│   ├── config/
│   │   └── personal.env.example
│   ├── migrations/
│   │   ├── 038_bkc_predicates.sql
│   │   ├── 039_koi_net_events.sql   # Event queue, edges, nodes tables
│   │   ├── 039b_ontology_mappings.sql # Source schemas + mappings
│   │   ├── 040_entity_koi_rids.sql  # KOI RID column on entity_registry
│   │   ├── 041_cross_references.sql # Cross-references for federation
│   │   └── 042_web_submissions.sql  # URL submission tracking
│   ├── scripts/
│   │   └── backfill_koi_rids.py     # One-time RID backfill
│   ├── tests/
│   │   └── test_koi_interop.py      # KOI-net protocol interop tests
│   └── requirements.txt
├── docker/                 # PostgreSQL stack with pgvector + Apache AGE
│   ├── docker-compose.yml
│   ├── Dockerfile.postgres-age
│   ├── init-extensions.sql
│   └── create-additional-dbs.sh     # Create DBs for new agents
├── scripts/                # Multi-agent management
│   ├── manage-agents.sh    # Start/stop/status for all agents
│   ├── agents.conf         # Agent registry (name:service:port)
│   ├── connect-koi-peer.sh # Idempotent peer/coordinator connect helper
│   └── test-federation.sh  # End-to-end federation test
├── ontology/               # Formal BKC ontology (JSON-LD)
│   └── bkc-ontology.jsonld
├── vault-seed/             # Seed entity notes exercising the full predicate chain
├── systemd/                # Service definitions
│   ├── koi-api.service     # Octo (port 8351)
│   └── gv-koi-api.service  # Greater Victoria (port 8352)
└── docs/                   # Strategy and implementation plans
    ├── join-the-network.md
    ├── koi-alignment.md
    ├── holonic-bioregional-knowledge-commons.md
    ├── ontological-architecture.md
    └── implementation-plan.md
```

## Deployment

### Prerequisites

- [OpenClaw](https://github.com/DarrenZal/openclaw) (our fork) installed and configured
- Docker and Docker Compose
- Python 3.12+
- An OpenAI API key (for semantic entity resolution)

### Quick Start (Single Agent)

```bash
git clone https://github.com/DarrenZal/Octo.git && cd Octo
cp koi-processor/config/personal.env.example koi-processor/config/personal.env
# Edit personal.env with your credentials

cd docker && docker compose up -d && cd ..
cd koi-processor && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cat migrations/038_bkc_predicates.sql | docker exec -i regen-koi-postgres psql -U postgres -d octo_koi

source config/personal.env
uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port 8351
```

### Adding a Leaf Node

```bash
# Recommended: run the interactive setup wizard
bash scripts/setup-node.sh

# Manual path (advanced): create DB + service/env yourself
bash docker/create-additional-dbs.sh gv_koi
```

### KOI-net Federation

Enable federation by setting `KOI_NET_ENABLED=true` in the agent's env file. This activates:
- Protocol endpoints at `/koi-net/*` (handshake, poll, broadcast, confirm, etc.)
- ECDSA P-256 signed envelopes for authenticated communication
- Background poller for event-driven cross-reference creation
- Auto-generated node identity (keypair stored in `/root/koi-state/`)

Federation readiness checklist (critical):
- Set `KOI_BASE_URL` to a peer-reachable URL (not localhost), e.g. `http://<public-ip>:8351`.
- Ensure peers can reach `/koi-net/*` on that URL (direct bind or reverse proxy).
- Use edge semantics correctly for polling:
  - `source_node` = node being polled (data provider)
  - `target_node` = node doing the polling
- Ensure each peer's `public_key` is present in `koi_net_nodes` on the other side.
- Use `POST /koi-net/events/poll` (legacy `POST /koi-net/poll` is not supported).
- Prefer `bash scripts/connect-koi-peer.sh --db <db> --peer-url <url>` for idempotent local setup.
- Keep strict validation disabled during bootstrap:
  - `KOI_STRICT_MODE=false`
  - `KOI_REQUIRE_SIGNED_ENVELOPES=false`
  - `KOI_REQUIRE_SIGNED_RESPONSES=false`
  - `KOI_ENFORCE_TARGET_MATCH=false`
  - `KOI_ENFORCE_SOURCE_KEY_RID_BINDING=false`
- Enable strict mode only after peer coordination confirms signed-envelope compatibility.

KOI endpoint model:
- Core protocol endpoints: `/koi-net/events/broadcast`, `/koi-net/events/poll`, `/koi-net/manifests/fetch`, `/koi-net/bundles/fetch`, `/koi-net/rids/fetch`
- Octo extensions: `/koi-net/handshake`, `/koi-net/events/confirm`, `/koi-net/health`

Quick federation sanity checks:
```bash
# Local node identity and advertised base URL
curl -s http://127.0.0.1:8351/koi-net/health | python3 -m json.tool

# Check edge orientation
docker exec regen-koi-postgres psql -U postgres -d <db_name> -c \
  "SELECT edge_rid, source_node, target_node, status FROM koi_net_edges;"

# Check peer keys
docker exec regen-koi-postgres psql -U postgres -d <db_name> -c \
  "SELECT node_rid, node_name, length(public_key) AS key_len FROM koi_net_nodes;"
```

### Discovery And Peer Selection

Current KOI-net discovery is **introduction-based**, not automatic gossip/discovery:
- Nodes discover each other by sharing `KOI_BASE_URL` + `node_rid` out-of-band (human coordination, registry docs, trusted intros).
- Each side verifies identity from `/koi-net/health` (`node_rid`, `public_key`) before creating edges.

How nodes decide who to connect to:
- **Leaf nodes** connect to one coordinator for their bioregion.
- **Peer networks** connect to a small set of trusted peers with overlapping goals/ontology.
- Edge `rid_types` define the exchange scope (principle of least exposure).
- Prefer explicit trust/governance agreements over broad, automatic peering.

Practical bootstrap pattern:
```bash
# Run on each side (or at least on the initiating side)
bash scripts/connect-koi-peer.sh --db <local_db> --peer-url http://<peer-ip>:8351
```

### Multi-Agent Management

```bash
bash scripts/manage-agents.sh status   # Health, RAM, PG connections
bash scripts/manage-agents.sh restart  # Restart all agents
bash scripts/test-federation.sh        # End-to-end federation test
```

## Context

Octo is an agent that aims to help the [BKC CoIP](https://www.r3-0.org/bkc-coip/) (Bioregional Knowledge Commons Community of Inquiry & Practice) — a collaborative initiative focused on building shared knowledge infrastructure for bioregional organizing worldwide.

The ontology is grounded in:
- **Bollier & Helfrich** — *Free, Fair & Alive* (pattern mining from commoning practices)
- **Joel Chan** — Discourse Graphs (progressive formalization: Question → Claim → Evidence)
- **OpenCivics** — Protocol/Playbook extension (general patterns + local implementations)
- **SKOS** — Concept hierarchies (broader/narrower/related)
- **Hyphal Tips** — Genealogical relationships (forked_from, builds_on, inspired_by)

## License

MIT
