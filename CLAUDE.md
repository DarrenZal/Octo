# CLAUDE.md — Octo Project Instructions

## Overview

Octo is a bioregional knowledge commoning agent built on OpenClaw, deployed on a VPS at `<SERVER_IP>`. It runs a KOI (Knowledge Organization Infrastructure) backend with a PostgreSQL knowledge graph and serves as the AI agent for the BKC CoIP (Bioregional Knowledge Commons Community of Inquiry & Practice).

## Production Server

- **Host:** `<SERVER_IP>`
- **User:** `root`
- **OS:** Ubuntu 24.04 LTS
- **SSH:** `ssh root@<SERVER_IP>` (key-based auth configured)
- **Resources:** 4 vCPU, 8GB RAM, 247GB disk

## Services

| Service | How it runs | Port | Details |
|---------|------------|------|---------|
| **Octo KOI API** | systemd (`koi-api.service`) | 8351 (localhost) | uvicorn, Python 3.12, KOI-net enabled |
| **GV KOI API** | systemd (`gv-koi-api.service`) | 8352 (localhost) | Greater Victoria leaf node, KOI-net enabled |
| **PostgreSQL** | Docker (`regen-koi-postgres`) | 5432 (localhost) | pgvector + Apache AGE, multiple DBs |
| **OpenClaw** | OpenClaw runtime (v2026.2.2-3) | — | Telegram + Discord channels |
| **Quartz** | nginx + cron rebuild | 80 | Static knowledge site |
| **Octo Chat** | systemd (`octo-chat.service`) | 3847 (localhost) | Chat API → OpenClaw agent |

### KOI-net Node Identities

| Node | RID | Public Key (truncated) |
|------|-----|----------------------|
| **Octo** | `orn:koi-net.node:octo-salish-sea+50a3c9eac05c807f` | `MFkwEwYH...` |
| **GV** | `orn:koi-net.node:greater-victoria+81ec47d80f231444` | `MFkwEwYH...` |

Private keys stored at `/root/koi-state/{node_name}_private_key.pem`.

## File Layout on Server

```
/root/
├── koi-processor/              # KOI backend (Python, shared by all agents)
│   ├── api/
│   │   ├── personal_ingest_api.py   # Main API (FastAPI/uvicorn)
│   │   ├── entity_schema.py         # 15 entity types, resolution config
│   │   ├── vault_parser.py          # YAML→predicate mapping (27 predicates)
│   │   ├── web_fetcher.py           # URL fetch + Playwright + content extraction
│   │   ├── koi_net_router.py        # KOI-net protocol endpoints (8 endpoints)
│   │   ├── koi_envelope.py          # ECDSA P-256 signed envelopes
│   │   ├── koi_poller.py            # Background federation poller
│   │   ├── koi_protocol.py          # Wire format models (Pydantic)
│   │   ├── event_queue.py           # DB-backed event queue
│   │   └── node_identity.py         # Keypair + node RID generation
│   ├── config/
│   │   └── personal.env             # Octo DB creds, OpenAI key, vault path
│   ├── migrations/
│   │   ├── 038_bkc_predicates.sql   # BKC ontology predicates
│   │   ├── 039_koi_net_events.sql   # Event queue, edges, nodes tables
│   │   ├── 039b_ontology_mappings.sql # Source schemas + ontology mappings
│   │   ├── 040_entity_koi_rids.sql  # KOI RID column on entity_registry
│   │   ├── 041_cross_references.sql # Federation cross-references
│   │   └── 042_web_submissions.sql  # URL submission tracking
│   ├── scripts/
│   │   └── backfill_koi_rids.py     # One-time RID backfill
│   ├── tests/
│   │   └── test_koi_interop.py      # KOI-net protocol interop tests
│   ├── requirements.txt
│   └── venv/                        # Python virtualenv
├── gv-agent/                   # Greater Victoria leaf node
│   ├── config/gv.env               # GV-specific: DB=gv_koi, port=8352
│   ├── workspace/                   # GV agent identity
│   └── vault/                       # GV seed entities
├── koi-state/                  # Node identity keys
│   ├── octo-salish-sea_private_key.pem
│   └── greater-victoria_private_key.pem
├── scripts/                    # Multi-agent management
│   ├── manage-agents.sh
│   ├── agents.conf
│   └── test-federation.sh
├── koi-stack/                  # Docker config
│   ├── docker-compose.yml
│   ├── Dockerfile.postgres-age
│   ├── init-extensions.sql
│   └── create-additional-dbs.sh
├── personal-koi-mcp/          # MCP server (TypeScript, from regen-koi-mcp fork)
├── bioregional-koi/           # OpenClaw plugin
│   ├── openclaw.plugin.json
│   └── index.ts
├── .openclaw/
│   ├── openclaw.json               # OpenClaw config (channels, auth, model)
│   ├── credentials/                # Telegram pairing, etc.
│   └── workspace/
│       ├── IDENTITY.md             # Octo's identity
│       ├── SOUL.md                 # Philosophy and values
│       ├── KNOWLEDGE.md            # BKC domain expertise
│       ├── USER.md                 # About Darren
│       ├── AGENTS.md               # Agent routing rules
│       ├── TOOLS.md                # Environment config
│       ├── HEARTBEAT.md            # Periodic tasks
│       └── vault/                  # Entity notes (Obsidian-style)
│           ├── Bioregions/
│           ├── Practices/
│           ├── Patterns/
│           ├── CaseStudies/
│           ├── Protocols/
│           ├── Playbooks/
│           ├── Questions/
│           ├── Claims/
│           ├── Evidence/
│           ├── People/
│           ├── Organizations/
│           ├── Projects/
│           ├── Concepts/
│           └── Sources/             # Ingested web sources
├── octo-quartz/                # Quartz static site generator
│   ├── quartz.config.ts          # Site config (title, theme, plugins)
│   ├── content -> vault/         # Symlink to vault
│   ├── public/                   # Built site (served by nginx)
│   └── rebuild.sh                # Build + inject chat widget
├── octo-chat/                  # Chat API server
│   └── server.js                 # Node.js proxy → openclaw agent
└── backups/                    # Daily DB + vault backups (7-day retention)
```

## Quartz Knowledge Site — "Salish Sea Knowledge Garden"

**URL:** `http://<SERVER_IP>`

Quartz renders Octo's vault as a browsable static site with wikilinks, backlinks, graph view, and full-text search.

**Privacy:** The `People/` folder is excluded via `ignorePatterns` — no personal names/info are published. Entity files still reference People via wikilinks internally, but those pages don't render on the public site.

### Config
- **nginx:** `/etc/nginx/sites-available/octo-quartz`
- **Quartz config:** `/root/octo-quartz/quartz.config.ts`
- **Landing page:** `/root/.openclaw/workspace/vault/index.md`
- **Auto-rebuild:** Cron every 15 minutes → `/var/log/quartz-rebuild.log`

### Manual rebuild
```bash
ssh root@<SERVER_IP> "/root/octo-quartz/rebuild.sh"
```

### Update domain (when ready)
1. Edit `baseUrl` in `/root/octo-quartz/quartz.config.ts`
2. Update `server_name` in `/etc/nginx/sites-available/octo-quartz`
3. Rebuild and restart: `/root/octo-quartz/rebuild.sh && systemctl restart nginx`

## Common Operations

### SSH to server
```bash
ssh root@<SERVER_IP>
```

### Check all agents status
```bash
ssh root@<SERVER_IP> "bash ~/scripts/manage-agents.sh status"
```

### KOI API health check
```bash
ssh root@<SERVER_IP> "curl -s http://127.0.0.1:8351/health"   # Octo
ssh root@<SERVER_IP> "curl -s http://127.0.0.1:8352/health"   # GV
```

### KOI-net health check
```bash
ssh root@<SERVER_IP> "curl -s http://127.0.0.1:8351/koi-net/health"
```

### Restart agents (after code changes)
```bash
ssh root@<SERVER_IP> "bash ~/scripts/manage-agents.sh restart"
# Or individually:
ssh root@<SERVER_IP> "systemctl restart koi-api"       # Octo
ssh root@<SERVER_IP> "systemctl restart gv-koi-api"    # GV
```

### Deploy updated Python files
```bash
scp koi-processor/api/*.py root@<SERVER_IP>:~/koi-processor/api/
ssh root@<SERVER_IP> "bash ~/scripts/manage-agents.sh restart"
```

### Deploy updated plugin + restart OpenClaw
```bash
scp plugins/bioregional-koi/index.ts root@<SERVER_IP>:~/bioregional-koi/index.ts
ssh root@<SERVER_IP> "openclaw gateway restart"
```

### Run federation test
```bash
ssh root@<SERVER_IP> "bash ~/scripts/test-federation.sh"
```

### Run interop test
```bash
ssh root@<SERVER_IP> "cd ~/koi-processor && venv/bin/python tests/test_koi_interop.py"
```

### Run a database migration
```bash
cat koi-processor/migrations/038_bkc_predicates.sql | ssh root@<SERVER_IP> "docker exec -i regen-koi-postgres psql -U postgres -d octo_koi"
```

### Query the database
```bash
ssh root@<SERVER_IP> "docker exec regen-koi-postgres psql -U postgres -d octo_koi -c 'SELECT * FROM allowed_predicates;'"
```

### Resolve an entity via API
```bash
ssh root@<SERVER_IP> 'curl -s -X POST http://127.0.0.1:8351/entity/resolve -H "Content-Type: application/json" -d "{\"label\": \"Herring Monitoring\", \"type_hint\": \"Practice\"}"'
```

### Test web URL preview
```bash
ssh root@<SERVER_IP> 'curl -s -X POST http://127.0.0.1:8351/web/preview -H "Content-Type: application/json" -d "{\"url\": \"https://example.com\"}" | python3 -m json.tool'
```

### View OpenClaw logs
```bash
ssh root@<SERVER_IP> "journalctl -u koi-api -f"
```

### Edit workspace files
```bash
ssh root@<SERVER_IP> "nano ~/.openclaw/workspace/KNOWLEDGE.md"
# Or SCP from local:
scp workspace/KNOWLEDGE.md root@<SERVER_IP>:~/.openclaw/workspace/
```

## Databases

All databases share one PostgreSQL container (`regen-koi-postgres`) with pgvector, Apache AGE, pg_trgm, fuzzystrmatch, uuid-ossp.

| Database | Agent | Entities |
|----------|-------|----------|
| `octo_koi` | Octo (Salish Sea) | 70 |
| `gv_koi` | Greater Victoria | 5 |

### Key tables (per database)

- `entity_registry` — All registered entities with `koi_rid` for federation
- `entity_relationships` — Typed relationships between entities
- `allowed_predicates` — Valid predicate definitions (27 BKC predicates)
- `pending_relationships` — Unresolved relationship targets
- `document_entity_links` — Document↔entity mention tracking
- `web_submissions` — URL submission lifecycle (preview → evaluate → ingest)

### Federation tables (KOI-net, per database)

- `koi_net_events` — Event queue (delivered_to, confirmed_by arrays, TTL)
- `koi_net_edges` — Node-to-node relationships (POLL/PUSH, rid_types filter)
- `koi_net_nodes` — Peer registry with public keys
- `koi_net_cross_refs` — Cross-references linking local entities to remote RIDs

### Schema infrastructure tables (octo_koi only)

- `source_schemas` — Schema registry with consent tracking
- `ontology_mappings` — Source→BKC field mappings

## Backups

Automated via cron (daily at 3am CET):
- **DB:** `pg_dump | gzip` → `/root/backups/{db_name}_YYYYMMDD.sql.gz` (both `octo_koi` and `gv_koi`)
- **Vault:** `tar czf` → `/root/backups/vault_YYYYMMDD.tar.gz`
- **Keys:** `tar czf` → `/root/backups/koi_state_YYYYMMDD.tar.gz` (node identity keys)
- **Retention:** 7 days (old backups auto-deleted at 4am)

## BKC Ontology

The formal ontology is at `ontology/bkc-ontology.jsonld`. It defines:

**15 entity types:** Person, Organization, Project, Location, Concept, Meeting + Practice, Pattern, CaseStudy, Bioregion, Protocol, Playbook, Question, Claim, Evidence

**27 predicates** across 4 categories:
- **Base KOI** (10): affiliated_with, attended, collaborates_with, founded, has_founder, has_project, involves_organization, involves_person, knows, located_in
- **Knowledge Commoning** (4): aggregates_into, suggests, documents, practiced_in
- **Discourse Graph** (7): supports, opposes, informs, generates, implemented_by, synthesizes, about
- **SKOS + Hyphal** (6): broader, narrower, related_to, forked_from, builds_on, inspired_by

**Parser aliases** (not stored as separate predicates):
- `documentedBy` → `documents` (direction swap)
- `implements` → `implemented_by` (direction swap)
- `protocol` → `implemented_by` (direction swap)

## Local Development

The source files in this repo map to server paths:

| Repo path | Server path |
|-----------|-------------|
| `koi-processor/api/` | `/root/koi-processor/api/` |
| `koi-processor/migrations/` | `/root/koi-processor/migrations/` |
| `koi-processor/scripts/` | `/root/koi-processor/scripts/` |
| `koi-processor/tests/` | `/root/koi-processor/tests/` |
| `docker/` | `/root/koi-stack/` |
| `scripts/` | `/root/scripts/` |
| `systemd/` | `/etc/systemd/system/` |
| `gv-agent/` | `/root/gv-agent/` |
| `workspace/` | `/root/.openclaw/workspace/` |
| `plugins/bioregional-koi/` | `/root/bioregional-koi/` |
| `vault-seed/` | `/root/.openclaw/workspace/vault/` (subset) |
| `ontology/` | Local vault (`~/Documents/Notes/Ontology/`) |

### Workflow: Edit locally → deploy to server

1. Edit files in this repo
2. SCP changed files to server (see deploy commands above)
3. Restart relevant service
4. Test via API health check or entity resolution

## Related Local Projects

| Path | What |
|------|------|
| `~/projects/regenai/koi-processor/` | Full KOI processor (superset of what's deployed here) |
| `~/projects/personal-koi-mcp/` | Personal KOI MCP server (TypeScript) |
| `~/Documents/Notes/Ontology/` | Local vault ontology schemas |

## Current Status

**Date:** 2026-02-09
**Status:** HEALTHY — Ready for multi-agent expansion (CV + FR)

### What's Done
- Sprints 1-3 deployed: KOI-net federation working between Octo (coordinator) and GV (leaf)
- Cleanup sprint complete: AGE extension bug, ensure_schema columns (phonetic_code, vault_rid, koi_rid), event confirmation e2e, cross-ref upgrade logic
- 70 entities in Octo across 14 types, seeded via `seed-vault-entities.sh`
- Event confirmation flow working end-to-end (event_id added to WireEvent + poll response)
- Cross-reference resolution verified: Herring Monitoring = `same_as` (confidence 1.0)
- Interop tests 8/8 passing, federation test passing, both agents healthy (14% RAM)
- Architecture updated: Cowichan Valley replaces Gulf Islands, Front Range added as peer network
- Phase 5.7 planned: GitHub sensor for self-knowledge (adapt RegenAI sensor)
- Test artifacts cleaned up (stale cross-refs + test entities removed from GV)

### What's Left
1. **Launch Cowichan Valley + Front Range agents** — create agent dirs, databases, workspace files, systemd services, configure edges, test cross-references (Darren's friends will help seed practices)
2. **Phase 5.7: GitHub sensor** — adapt `RegenAI/koi-sensors/sensors/github/` to index `DarrenZal/Octo` into Octo's KOI API for self-knowledge
3. **Phase 0.5: BKC CoIP vault audit** — blocked on access from Andrea Farias / Vincent Arena
4. **Phase 5: Cascadia coordinator** — after CV is running, proves holon pattern

### Open Questions
- Front Range: connect to Octo directly for now (since Cascadia doesn't exist yet) or wait?
- What practices will CV and FR friends seed? (they should prepare 2-3 each)

### Adding a New Agent (Quick Reference)

```bash
# 1. Create database
ssh root@<SERVER_IP> "bash ~/koi-stack/create-additional-dbs.sh cv_koi"

# 2. Create agent directory (follow gv-agent/ pattern)
ssh root@<SERVER_IP> "mkdir -p ~/cv-agent/{config,workspace,vault}"

# 3. Create env file (copy gv.env, change DB_NAME, port, node name)

# 4. Create systemd service (copy gv-koi-api.service, change paths/ports)

# 5. Generate identity + configure edges

# 6. Seed entities
bash ~/scripts/seed-vault-entities.sh http://127.0.0.1:8354 ~/cv-agent/vault

# 7. Start and verify
systemctl start cv-koi-api
curl -s http://127.0.0.1:8354/health
```

## Session History

| Session ID | Date | Scope | Key Work |
|------------|------|-------|----------|
| `eca2a0ec` | 2026-02-08 | Holonic infra | Strategy docs, implementation plan, SSH setup, hyperlinks |
| `7aead4bb` | 2026-02-08 | Cleanup sprint | Fix deployment bugs, seed 70 entities, event_id confirm flow, architecture update (CV + FR), GitHub sensor plan (Phase 5.7) |
