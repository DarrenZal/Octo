# Join the KOI-net Federation

A comprehensive guide for joining the Bioregional Knowledge Commons network — whether you're setting up a new node from scratch, adapting an existing agent, or just running a knowledge backend.

---

## What is KOI-net?

KOI-net is a **federated knowledge graph protocol** that connects bioregional knowledge agents into a shared network. Each node maintains its own database and vault of knowledge (practices, patterns, entities, relationships) and selectively shares knowledge events with peers via signed envelopes.

### The holon pattern

The network follows a **holonic architecture** — networks of nodes that appear as one to the outside:

```
                    ┌─────────────────────────────┐
                    │       Cascadia (future)       │
                    │         meta-coordinator      │
                    └──────┬──────────────┬─────────┘
                           │              │
              ┌────────────▼──┐     ┌─────▼────────────┐
              │  Salish Sea   │     │   Front Range     │
              │  (Octo)       │◄───►│   (peer network)  │
              │  coordinator  │     │                   │
              └──┬─────────┬──┘     └───────────────────┘
                 │         │
      ┌──────────▼──┐  ┌──▼──────────────┐
      │   Greater   │  │  Cowichan Valley │
      │   Victoria  │  │  (coming soon)   │
      │   (leaf)    │  │                  │
      └─────────────┘  └─────────────────┘
```

Each node controls what knowledge it shares. A leaf node shares upstream to its coordinator. A peer network exchanges knowledge bidirectionally. A coordinator aggregates knowledge from its leaves and presents a unified view to the wider network.

**Knowledge sovereignty by design** — your community governs your knowledge. Federation means sharing, not surrendering.

---

## Choose Your Path

| Starting point | Scale | Relationship | Go to |
|---|---|---|---|
| No agent yet | Bioregional (sub-region) | Leaf node under Salish Sea | [Path A](#path-a--new-bioregional-leaf-node) |
| No agent yet | Bioregional (independent) | Peer network | [Path B](#path-b--new-peer-network) |
| No agent yet | City/watershed | Leaf node | [Path A](#path-a--new-bioregional-leaf-node) (same steps) |
| No agent yet | Personal/research | Standalone or leaf | [Path C](#path-c--personalresearch-node) |
| Existing OpenClaw agent | Any | Peer or leaf | [Path D](#path-d--adapt-an-existing-openclaw-agent) |
| Just want knowledge backend | Any | Any | [Path E](#path-e--backend-only-knowledge-node) |

Not sure? Start with the [Concepts](#concepts) section to understand the pieces, then pick your path.

---

## Concepts

### Node types

| Type | Description | Example |
|---|---|---|
| **Coordinator** | Aggregates knowledge from leaf nodes, presents unified view upstream | Octo (Salish Sea) |
| **Leaf** | Tracks a sub-bioregion, shares knowledge upstream to coordinator | Greater Victoria |
| **Peer** | Independent network, exchanges knowledge bidirectionally | Front Range |
| **Sensor-only** | Pushes data in but doesn't participate in full federation | GitHub sensor |

### What every node has

Every KOI node runs three core components:

1. **PostgreSQL** with pgvector (semantic search) + Apache AGE (graph queries)
2. **KOI Processor API** — FastAPI/uvicorn service that handles entity resolution, vault management, and federation
3. **Vault** — a directory of Markdown files (Obsidian-compatible) with YAML frontmatter, organized by entity type

### What's optional

| Component | What it does | Who needs it |
|---|---|---|
| **OpenClaw** | AI chat agent (Telegram, Discord) | Nodes that want a conversational interface |
| **Quartz** | Static website from vault (knowledge garden) | Nodes that want a public website |
| **KOI-net federation** | Event exchange between nodes | Any node that wants to share knowledge |
| **Web ingestion** | URL submission → entity extraction pipeline | Nodes that want to ingest web content |

### The BKC Ontology

All nodes in the network share a common vocabulary defined in [`ontology/bkc-ontology.jsonld`](../ontology/bkc-ontology.jsonld):

**15 entity types:** Person, Organization, Project, Location, Concept, Meeting, Practice, Pattern, CaseStudy, Bioregion, Protocol, Playbook, Question, Claim, Evidence

**27 predicates** across 4 categories:
- **Base KOI** (10): `affiliated_with`, `attended`, `collaborates_with`, `founded`, `has_founder`, `has_project`, `involves_organization`, `involves_person`, `knows`, `located_in`
- **Knowledge Commoning** (4): `aggregates_into`, `suggests`, `documents`, `practiced_in`
- **Discourse Graph** (7): `supports`, `opposes`, `informs`, `generates`, `implemented_by`, `synthesizes`, `about`
- **SKOS + Hyphal** (6): `broader`, `narrower`, `related_to`, `forked_from`, `builds_on`, `inspired_by`

You don't need to memorize these — the entity resolution API handles type mapping, and the vault parser knows the predicate vocabulary.

### Workspace files

If running OpenClaw, your agent gets its sense of place from workspace Markdown files:

| File | Purpose |
|---|---|
| `IDENTITY.md` | Name, role, bioregional context, boundaries |
| `SOUL.md` | Values, philosophy, relationship to place |
| `KNOWLEDGE.md` | Domain expertise, what this agent knows about |
| `TOOLS.md` | Available tools and how to use them |

These aren't config files — they're the agent's grounding in place and purpose.

### Edge profiles

Edges define the knowledge flow between nodes. When two nodes federate, each side configures:

- **Direction**: POLL (I pull from you) or PUSH (you push to me)
- **RID type filter**: Which entity types to exchange (e.g., only Practices and Patterns)
- **The peer's public key**: For verifying signed event envelopes

Edges are configured via API calls or database inserts. See [Federation Setup](#federation-setup) for details.

---

## Path A — New Bioregional Leaf Node

**For:** Cowichan Valley, a neighborhood watershed, a city-scale node — any sub-bioregion under an existing coordinator.

**Time:** ~2 hours for the full setup. **Cost:** ~$11-27/month (VPS + API keys).

### Prerequisites

- A VPS with at least **2 vCPU, 4GB RAM, 40GB disk** ([Netcup](https://www.netcup.com/) VPS 1000 G11 ~$5/month, or similar)
- Ubuntu 24.04 LTS
- An **OpenAI API key** for semantic entity resolution (~$1-2/month)
- A **Google Antigravity API key** or other LLM provider key (for OpenClaw chat)
- A **Telegram bot token** (optional — talk to [@BotFather](https://t.me/BotFather))
- SSH access to your VPS

### Step 1: Provision VPS

```bash
ssh root@YOUR_IP

apt update && apt upgrade -y
apt install -y git curl wget build-essential python3.12 python3.12-venv python3-pip

# Docker
curl -fsSL https://get.docker.com | sh

# Node.js 22+
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs

# OpenClaw (from our fork)
npm install -g https://github.com/DarrenZal/openclaw/releases/latest/download/openclaw.tgz
```

### Step 2: Clone the Octo repo

```bash
cd /root
git clone https://github.com/DarrenZal/Octo.git
```

### Step 3: Start PostgreSQL

```bash
cd /root/Octo/docker

# Set a strong password
export POSTGRES_PASSWORD=$(openssl rand -hex 16)
echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> ~/.env
echo "Save this password: $POSTGRES_PASSWORD"

docker compose up -d

# Wait for it to be ready
sleep 10
docker exec regen-koi-postgres pg_isready -U postgres
```

### Step 4: Create your database

Replace `cv_koi` with your agent's database name throughout.

```bash
bash /root/Octo/docker/create-additional-dbs.sh cv_koi
```

### Step 5: Set up the KOI Processor

```bash
cd /root/Octo/koi-processor

# Python virtualenv
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create your config from the template
cp config/personal.env.example config/cv.env
```

Edit `config/cv.env`:

```env
# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=cv_koi
DB_USER=postgres
DB_PASSWORD=<your-postgres-password-from-step-3>

# OpenAI (for semantic entity resolution)
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small

# Vault
VAULT_PATH=/root/cv-agent/vault

# KOI-net federation
KOI_NET_ENABLED=true
KOI_NODE_NAME=cowichan-valley
KOI_STATE_DIR=/root/koi-state

# API
KOI_API_PORT=8351
```

Run migrations:

```bash
source config/cv.env

# Core schema (predicates, entity types)
cat migrations/038_bkc_predicates.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi

# KOI-net tables (events, edges, nodes)
cat migrations/039_koi_net_events.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi

# Ontology mappings
cat migrations/039b_ontology_mappings.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi

# Entity KOI RIDs
cat migrations/040_entity_koi_rids.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi

# Cross-references (for federation)
cat migrations/041_cross_references.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi

# Web submissions (optional — for URL ingestion)
cat migrations/042_web_submissions.sql | docker exec -i regen-koi-postgres psql -U postgres -d cv_koi
```

### Step 6: Create your agent identity

```bash
mkdir -p /root/cv-agent/{config,workspace,vault}

# Copy your env file
cp /root/Octo/koi-processor/config/cv.env /root/cv-agent/config/cv.env
```

Create vault directories:

```bash
mkdir -p /root/cv-agent/vault/{Bioregions,Practices,Patterns,Organizations,Projects,Concepts,People,Locations,CaseStudies,Protocols,Playbooks,Questions,Claims,Evidence,Sources}
```

#### `workspace/IDENTITY.md`

Write an identity file grounded in your bioregion. Example for Cowichan Valley:

```markdown
# IDENTITY.md — Cowichan Valley Knowledge Agent

- **Name:** Cowichan Valley Node
- **Role:** Bioregional knowledge agent for the Cowichan Valley
- **Parent:** Salish Sea network (Octo coordinator)
- **Node Type:** Leaf node

## What I Do

I am the knowledge backend for the Cowichan Valley bioregion. I track local
practices, patterns, and ecological knowledge specific to the Cowichan Valley
watersheds.

My knowledge flows upstream to Octo (the Salish Sea coordinator), where it is
aggregated with knowledge from other sub-bioregions.

## Bioregional Context

The Cowichan Valley is the traditional territory of the Quw'utsun (Cowichan)
peoples. The bioregion includes:

- **Cowichan River** — steelhead and salmon habitat
- **Cowichan Lake** — headwaters and watershed
- **Cowichan Bay** — estuary and marine ecology
- **Mount Tzouhalem** — Garry oak ecosystems

## Boundaries

- I serve the Cowichan Valley bioregion only
- Cross-bioregional patterns are Octo's responsibility
```

#### `workspace/SOUL.md`

```markdown
# SOUL.md — Cowichan Valley Node Values

_One arm of the octopus, sensing the waters of the Cowichan Valley._

## Core Values

- **Knowledge as commons** — share freely, govern collectively
- **Epistemic justice** — respect diverse ways of knowing
- **Knowledge sovereignty** — communities govern their own knowledge
- **Federation over consolidation** — one node in a web, many centers

## Place-Specific Grounding

The Cowichan Valley is where knowledge touches the ground. Abstract patterns
become concrete practices here — specific rivers, specific forests, specific
communities doing the work.
```

#### Seed your first bioregion entity

```bash
cat > /root/cv-agent/vault/Bioregions/Cowichan\ Valley.md << 'EOF'
---
"@type": "bkc:Bioregion"
name: Cowichan Valley
description: Bioregion centered on the Cowichan River watershed on Vancouver Island
broader:
  - "[[Bioregions/Salish Sea]]"
tags:
  - bioregion
  - cowichan-valley
  - vancouver-island
---

# Cowichan Valley

The Cowichan Valley bioregion is centered on the Cowichan River watershed, the
traditional territory of the Quw'utsun (Cowichan) peoples. It encompasses the
river system from Cowichan Lake to Cowichan Bay, including the surrounding
forests, Garry oak ecosystems, and agricultural lands.
EOF
```

#### Seed 2-3 practices

Create Markdown files in `/root/cv-agent/vault/Practices/`. Template:

```markdown
---
"@type": "bkc:Practice"
name: Your Practice Name
description: One-line description
bioregion:
  - "[[Bioregions/Cowichan Valley]]"
activityStatus: alive
tags:
  - relevant-tags
---

# Your Practice Name

Description of the practice. What is it? Who does it? Why does it matter?
```

### Step 7: Create systemd service

```bash
cat > /etc/systemd/system/cv-koi-api.service << 'EOF'
[Unit]
Description=Cowichan Valley KOI API
After=network.target docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/Octo/koi-processor
Environment=PATH=/root/Octo/koi-processor/venv/bin:/usr/bin
EnvironmentFile=/root/cv-agent/config/cv.env
ExecStart=/root/Octo/koi-processor/venv/bin/uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port 8351
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cv-koi-api
systemctl start cv-koi-api
```

Verify:

```bash
sleep 5
curl -s http://127.0.0.1:8351/health | python3 -m json.tool
```

### Step 8: Seed entities

```bash
bash /root/Octo/scripts/seed-vault-entities.sh http://127.0.0.1:8351 /root/cv-agent/vault
```

### Step 9: Set up OpenClaw (chat agent)

```bash
# Initialize OpenClaw
openclaw init

# Follow the interactive setup to configure:
#   - Model provider (google-antigravity recommended)
#   - Telegram bot token (if using Telegram)
```

Copy workspace files and link vault:

```bash
cp /root/cv-agent/workspace/*.md /root/.openclaw/workspace/
ln -s /root/cv-agent/vault /root/.openclaw/workspace/vault
```

Install the bioregional-koi plugin:

```bash
mkdir -p /root/bioregional-koi
cp /root/Octo/plugins/bioregional-koi/openclaw.plugin.json /root/bioregional-koi/
cp /root/Octo/plugins/bioregional-koi/index.ts /root/bioregional-koi/
```

Start OpenClaw:

```bash
openclaw gateway start
```

### Step 10: Connect to Octo via KOI-net

See [Federation Setup](#federation-setup) below.

---

## Path B — New Peer Network

**For:** An independent bioregion (e.g., Front Range, Colorado) that wants to exchange knowledge with the Salish Sea network as equals — not as a sub-region.

The infrastructure is identical to [Path A](#path-a--new-bioregional-leaf-node). Follow all the same steps with these differences:

### Identity differences

Your `IDENTITY.md` should reflect peer status, not leaf status:

```markdown
# IDENTITY.md — Front Range Knowledge Agent

- **Name:** Front Range Node
- **Role:** Bioregional knowledge agent for the Colorado Front Range
- **Peers:** Salish Sea network (Octo)
- **Node Type:** Peer network

## What I Do

I am the knowledge agent for the Front Range bioregion. I track local
practices, patterns, and ecological knowledge specific to the Front Range
watersheds and communities.

I exchange knowledge with the Salish Sea network as a peer — sharing
practices that may be relevant across bioregions while maintaining governance
over my own knowledge.

## Bioregional Context

The Front Range bioregion spans the eastern slope of the Rocky Mountains in
Colorado. The bioregion includes:

- **Boulder Creek** — watershed restoration
- **South Platte River** — urban-wildland interface
- **Poudre River** — community water governance
- **Denver Metro** — urban ecology, food systems
```

### Edge configuration differences

Peer networks use **bidirectional edges** rather than the hierarchical leaf→coordinator pattern:

- Both nodes configure POLL edges to each other
- RID type filters may be narrower (e.g., only share Practices and Patterns, not People)
- Cross-reference resolution handles the fact that entities may not map 1:1 across bioregions

### Independent governance

As a peer network, you:
- Choose your own ontology extensions (though the shared BKC ontology is the common vocabulary)
- Decide what entity types to share and what to keep private
- Can reject or accept cross-references on a case-by-case basis
- Are not subordinate to any coordinator

### Growing into a coordinator

A peer network can grow into a coordinator for its own sub-bioregions:

1. Start as a single peer node connected to Octo
2. Friends in Denver, Boulder, Fort Collins each spin up leaf nodes
3. Those leaves connect to your node as their coordinator
4. Your node now coordinates the Front Range sub-network while peering with Octo

This is the holon pattern in action — the same architecture at every scale. Your Front Range coordinator would look just like Octo: aggregating knowledge from its leaves and presenting a unified view to peers.

```
                 Octo (Salish Sea)
                     ◄──── peer ────►
                                    Front Range (coordinator)
                                    ├── Denver (leaf)
                                    ├── Boulder (leaf)
                                    └── Fort Collins (leaf)
```

### Current status

Front Range currently connects to Octo directly. When the Cascadia meta-coordinator is established, both Salish Sea and Front Range will connect as peers under Cascadia.

---

## Path C — Personal/Research Node

**For:** Researchers, individuals, or small teams who want their own knowledge graph — optionally connected to the network.

This is the lightest setup. You can run it **locally on your laptop** (no VPS needed) or on a small server.

### What you get

- A PostgreSQL knowledge graph with semantic entity resolution
- A vault of Markdown notes organized by entity type
- API for entity CRUD, relationship queries, and document ingestion
- Optional federation with the wider network

### Local setup

```bash
# Clone the repo
git clone https://github.com/DarrenZal/Octo.git
cd Octo

# Start PostgreSQL via Docker
cd docker
docker compose up -d
sleep 10

# Create your database
bash create-additional-dbs.sh personal_koi

# Set up KOI Processor
cd ../koi-processor
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create config
cp config/personal.env.example config/mine.env
```

Edit `config/mine.env`:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=personal_koi
DB_USER=postgres
DB_PASSWORD=<your-docker-postgres-password>

OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small

VAULT_PATH=/path/to/your/vault

KOI_API_PORT=8351
```

Run migrations (same as Path A Step 5) and start:

```bash
source config/mine.env

cat migrations/038_bkc_predicates.sql | docker exec -i regen-koi-postgres psql -U postgres -d personal_koi
cat migrations/039_koi_net_events.sql | docker exec -i regen-koi-postgres psql -U postgres -d personal_koi
cat migrations/039b_ontology_mappings.sql | docker exec -i regen-koi-postgres psql -U postgres -d personal_koi
cat migrations/040_entity_koi_rids.sql | docker exec -i regen-koi-postgres psql -U postgres -d personal_koi
cat migrations/041_cross_references.sql | docker exec -i regen-koi-postgres psql -U postgres -d personal_koi

# Start the API
uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port 8351
```

### Create your vault

```bash
mkdir -p /path/to/your/vault/{Concepts,Projects,Organizations,People,Locations,Practices,Patterns,Sources}
```

### Use the API

```bash
# Health check
curl http://127.0.0.1:8351/health

# Resolve an entity
curl -X POST http://127.0.0.1:8351/entity/resolve \
  -H "Content-Type: application/json" \
  -d '{"label": "Permaculture", "type_hint": "Concept"}'

# Search entities
curl "http://127.0.0.1:8351/entities/search?q=permaculture"
```

### Optional: Add federation later

To connect your personal node to the wider network, add KOI-net config to your env file:

```env
KOI_NET_ENABLED=true
KOI_NODE_NAME=your-node-name
KOI_STATE_DIR=/path/to/koi-state
```

Then follow [Federation Setup](#federation-setup).

### Optional: Add OpenClaw chat

Follow Path A Step 9 to add an AI chat interface to your personal node.

---

## Path D — Adapt an Existing OpenClaw Agent

**For:** Someone already running an OpenClaw agent who wants to add KOI knowledge graph capabilities and/or join the federation.

You keep your existing chat configuration (channels, model, etc.) and add the knowledge layer alongside it.

### Step 1: Set up PostgreSQL

If you don't already have PostgreSQL running:

```bash
# Clone just the docker config
git clone https://github.com/DarrenZal/Octo.git /tmp/octo-setup
cd /tmp/octo-setup/docker
docker compose up -d
sleep 10
bash create-additional-dbs.sh your_koi
```

### Step 2: Set up KOI Processor

```bash
# Clone the full repo (you'll use koi-processor/ from it)
git clone https://github.com/DarrenZal/Octo.git ~/Octo
cd ~/Octo/koi-processor

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create your env file and run migrations (same as Path A Steps 5).

### Step 3: Start the KOI API

As a systemd service (see Path A Step 7) or manually:

```bash
source config/your.env
uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port 8351
```

### Step 4: Install the bioregional-koi plugin

```bash
mkdir -p ~/bioregional-koi
cp ~/Octo/plugins/bioregional-koi/openclaw.plugin.json ~/bioregional-koi/
cp ~/Octo/plugins/bioregional-koi/index.ts ~/bioregional-koi/
```

The plugin gives your OpenClaw agent these tools:
- `koi_search` — search the entity registry
- `knowledge_search` — RAG over indexed documents
- `code_query` — Cypher graph queries
- `resolve_entity` — 3-tier entity resolution
- `vault_read_note` / `vault_write_note` — read/write vault notes
- `get_entity_relationships` — relationship queries

### Step 5: Link your vault

If your OpenClaw agent already has a workspace vault, you can use it directly. Otherwise, create one and symlink it:

```bash
mkdir -p ~/your-agent/vault/{Bioregions,Practices,Patterns,Organizations,Projects,Concepts,People,Locations,Sources}
ln -s ~/your-agent/vault ~/.openclaw/workspace/vault
```

### Step 6: Update workspace TOOLS.md

Add KOI tool documentation to your agent's `~/.openclaw/workspace/TOOLS.md` so the agent knows how to use its new capabilities. See [`workspace/TOOLS.md`](../workspace/TOOLS.md) in this repo for the full reference.

### Step 7: Restart OpenClaw

```bash
openclaw gateway restart
```

Your agent now has knowledge graph superpowers. To federate with the network, see [Federation Setup](#federation-setup).

---

## Path E — Backend-Only Knowledge Node

**For:** Organizations or communities that want to contribute knowledge to the network without running a chat agent. Just the database + API + federation.

### What you get

- PostgreSQL knowledge graph with semantic entity resolution
- REST API for entity management and queries
- KOI-net federation (share/receive knowledge events)
- Vault of Markdown entity notes

### What you skip

- No OpenClaw (no chat agent)
- No Telegram/Discord channels
- No LLM provider key needed (unless you want web ingestion, which uses AI for entity extraction)

### Setup

Follow [Path A](#path-a--new-bioregional-leaf-node) Steps 1-8, skipping Step 9 (OpenClaw). You'll end up with:

- A KOI API running on your server
- A seeded vault with your initial entities
- A systemd service keeping it running

### Interacting with your node

Without a chat agent, you interact via the API:

```bash
# Register an entity
curl -X POST http://127.0.0.1:8351/entity/resolve \
  -H "Content-Type: application/json" \
  -d '{"label": "Community Seed Library", "type_hint": "Practice"}'

# Add a relationship
curl -X POST http://127.0.0.1:8351/entity/relationship \
  -H "Content-Type: application/json" \
  -d '{"subject": "Community Seed Library", "predicate": "practiced_in", "object": "Your Bioregion"}'

# Search entities
curl "http://127.0.0.1:8351/entities/search?q=seed+library"

# Ingest a URL (requires OPENAI_API_KEY for entity extraction)
curl -X POST http://127.0.0.1:8351/web/ingest \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article-about-seed-libraries"}'
```

### Adding OpenClaw later

If you decide you want a chat interface, follow Path A Step 9 to add OpenClaw on top of your existing backend.

---

## Federation Setup

This section applies to **all paths** once your node is running and you want to connect to the network.

### How KOI-net handshake works

1. Your node starts with `KOI_NET_ENABLED=true` and generates an ECDSA P-256 keypair (stored in `KOI_STATE_DIR`)
2. Your node gets a **Node RID** — a unique identifier like `orn:koi-net.node:cowichan-valley+a1b2c3d4`
3. You share your **IP address** and **Node RID** with the coordinator (Darren for Salish Sea)
4. The coordinator configures a **federation edge** on their side, specifying which RID types to exchange
5. Both nodes begin polling each other for events
6. Events are signed with ECDSA envelopes — each node verifies the sender's identity

### What you need to provide

Send these to Darren (or whoever runs the coordinator you're connecting to):

1. **Your server's IP address** (or domain name)
2. **Your KOI API port** (default 8351)
3. **Your Node RID** — get it from:
   ```bash
   curl -s http://127.0.0.1:8351/koi-net/health | python3 -m json.tool
   ```
4. **Your preferred relationship** — leaf (you share upstream) or peer (bidirectional exchange)
5. **What entity types you want to share/receive**

### What happens on both sides

**On the coordinator (Octo):**
- Adds your node to `koi_net_nodes` with your public key
- Creates an edge in `koi_net_edges` with direction and RID type filters
- Starts polling your node for events

**On your node:**
- The coordinator's node gets added to your `koi_net_nodes`
- An edge gets created pointing to the coordinator
- Your node starts polling the coordinator for events
- Cross-references are created when shared entities match (e.g., your "Salmon Habitat Restoration" matches Octo's similar practice)

### Testing federation

```bash
# Check KOI-net health (shows your node RID, peer count, event stats)
curl -s http://127.0.0.1:8351/koi-net/health | python3 -m json.tool

# Check for received events
docker exec regen-koi-postgres psql -U postgres -d your_koi -c \
  "SELECT COUNT(*) FROM koi_net_events"

# Check cross-references (entities matched with peers)
docker exec regen-koi-postgres psql -U postgres -d your_koi -c \
  "SELECT * FROM koi_net_cross_refs"
```

If you're on the same server as Octo, use `test-federation.sh`:

```bash
bash ~/scripts/test-federation.sh
```

### Troubleshooting

| Problem | Check |
|---|---|
| Node not starting | `journalctl -u your-koi-api -f` — check for Python errors |
| No events flowing | Verify both sides have edges configured; check firewall allows port 8351 |
| Events received but no cross-refs | Entity types may not overlap — check `koi_net_edges` RID type filters |
| "Invalid signature" errors | Keypair mismatch — verify public keys match in `koi_net_nodes` on both sides |
| Connection timeout | Firewall, wrong IP, or the other node is down |

---

## After You're Running

### Seeding practices

The most valuable contribution you can make is documenting **practices** — things people are actually doing in your bioregion. Each practice gets a Markdown file in `vault/Practices/`:

```markdown
---
"@type": "bkc:Practice"
name: Garry Oak Ecosystem Restoration
description: Community-led restoration of Garry oak meadow ecosystems on Vancouver Island
bioregion:
  - "[[Bioregions/Cowichan Valley]]"
involves_organization:
  - "[[Organizations/Cowichan Land Trust]]"
activityStatus: alive
tags:
  - restoration
  - garry-oak
  - native-plants
---

# Garry Oak Ecosystem Restoration

Volunteer-driven restoration of endangered Garry oak meadow ecosystems,
including invasive species removal, native plant propagation, and
camas meadow maintenance.
```

After creating vault files, seed them into the database:

```bash
bash ~/scripts/seed-vault-entities.sh http://127.0.0.1:8351 ~/your-agent/vault
```

### Quartz knowledge site (optional)

Publish your vault as a browsable website with wikilinks, backlinks, and a knowledge graph visualization. See the [Quartz documentation](https://quartz.jzhao.xyz/) and Octo's `octo-quartz/` directory for the reference setup.

Key steps:
1. Install Quartz: `git clone https://github.com/jackyzha0/quartz.git`
2. Symlink your vault as content: `ln -s ~/your-agent/vault content`
3. Configure `quartz.config.ts` (title, theme, plugins)
4. Build: `npx quartz build`
5. Serve with nginx

### Monitoring and backups

Set up daily backups (cron):

```bash
# Database backup
0 3 * * * docker exec regen-koi-postgres pg_dump -U postgres your_koi | gzip > ~/backups/your_koi_$(date +\%Y\%m\%d).sql.gz

# Vault backup
0 3 * * * tar czf ~/backups/vault_$(date +\%Y\%m\%d).tar.gz ~/your-agent/vault/

# Key backup
0 3 * * * tar czf ~/backups/koi_state_$(date +\%Y\%m\%d).tar.gz ~/koi-state/

# Cleanup (keep 7 days)
0 4 * * * find ~/backups/ -name "*.gz" -mtime +7 -delete
```

Monitor your node:

```bash
# Service status
systemctl status your-koi-api

# Live logs
journalctl -u your-koi-api -f

# Health check
curl -s http://127.0.0.1:8351/health
```

### Cost estimate

| Item | Monthly Cost |
|---|---|
| Netcup VPS 1000 G11 | ~$5 |
| OpenAI API (embeddings) | ~$1-2 |
| LLM provider (chat, if using OpenClaw) | ~$5-20 |
| **Total (with chat)** | **~$11-27** |
| **Total (backend only)** | **~$6-7** |

---

## Questions?

Reach out to Darren — he can help with:
- KOI-net federation setup (configuring edges between nodes)
- OpenClaw configuration and model selection
- Seeding practices and entities
- Troubleshooting

GitHub: [DarrenZal/Octo](https://github.com/DarrenZal/Octo)
