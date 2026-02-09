# CLAUDE.md — Octo Project Instructions

## Overview

Octo is a bioregional knowledge commoning agent built on OpenClaw, deployed on a VPS at `45.132.245.30`. It runs a KOI (Knowledge Organization Infrastructure) backend with a PostgreSQL knowledge graph and serves as the AI agent for the BKC CoIP (Bioregional Knowledge Commons Community of Inquiry & Practice).

## Production Server

- **Host:** `45.132.245.30`
- **User:** `root`
- **OS:** Ubuntu 24.04 LTS
- **SSH:** `ssh root@45.132.245.30` (key-based auth configured)
- **Resources:** 4 vCPU, 8GB RAM, 247GB disk

## Services

| Service | How it runs | Port | Details |
|---------|------------|------|---------|
| **KOI API** | systemd (`koi-api.service`) | 8351 (localhost) | uvicorn, Python 3.12 |
| **PostgreSQL** | Docker (`regen-koi-postgres`) | 5432 (localhost) | pgvector + Apache AGE |
| **OpenClaw** | OpenClaw runtime (v2026.2.2-3) | — | Telegram + Discord channels |
| **Quartz** | nginx + cron rebuild | 80 | Static knowledge site |
| **Octo Chat** | systemd (`octo-chat.service`) | 3847 (localhost) | Chat API → OpenClaw agent |

## File Layout on Server

```
/root/
├── koi-processor/              # KOI backend (Python)
│   ├── api/
│   │   ├── personal_ingest_api.py   # Main API (FastAPI/uvicorn)
│   │   ├── entity_schema.py         # 15 entity types, resolution config
│   │   └── vault_parser.py          # YAML→predicate mapping (27 predicates)
│   ├── config/
│   │   └── personal.env             # DB creds, OpenAI key, vault path
│   ├── migrations/
│   │   └── 038_bkc_predicates.sql   # BKC ontology predicates
│   ├── requirements.txt
│   └── venv/                        # Python virtualenv
├── koi-stack/                  # Docker config
│   ├── docker-compose.yml
│   ├── Dockerfile.postgres-age
│   └── init-extensions.sql
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
│           └── Concepts/
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

**URL:** `http://45.132.245.30`

Quartz renders Octo's vault as a browsable static site with wikilinks, backlinks, graph view, and full-text search.

**Privacy:** The `People/` folder is excluded via `ignorePatterns` — no personal names/info are published. Entity files still reference People via wikilinks internally, but those pages don't render on the public site.

### Config
- **nginx:** `/etc/nginx/sites-available/octo-quartz`
- **Quartz config:** `/root/octo-quartz/quartz.config.ts`
- **Landing page:** `/root/.openclaw/workspace/vault/index.md`
- **Auto-rebuild:** Cron every 15 minutes → `/var/log/quartz-rebuild.log`

### Manual rebuild
```bash
ssh root@45.132.245.30 "/root/octo-quartz/rebuild.sh"
```

### Update domain (when ready)
1. Edit `baseUrl` in `/root/octo-quartz/quartz.config.ts`
2. Update `server_name` in `/etc/nginx/sites-available/octo-quartz`
3. Rebuild and restart: `/root/octo-quartz/rebuild.sh && systemctl restart nginx`

## Common Operations

### SSH to server
```bash
ssh root@45.132.245.30
```

### Check service status
```bash
ssh root@45.132.245.30 "systemctl status koi-api && docker ps"
```

### KOI API health check
```bash
ssh root@45.132.245.30 "curl -s http://127.0.0.1:8351/health"
```

### Restart KOI API (after code changes)
```bash
ssh root@45.132.245.30 "systemctl restart koi-api"
```

### Deploy updated Python files
```bash
scp koi-processor/api/entity_schema.py koi-processor/api/vault_parser.py root@45.132.245.30:~/koi-processor/api/
ssh root@45.132.245.30 "systemctl restart koi-api"
```

### Run a database migration
```bash
cat koi-processor/migrations/038_bkc_predicates.sql | ssh root@45.132.245.30 "docker exec -i regen-koi-postgres psql -U postgres -d octo_koi"
```

### Query the database
```bash
ssh root@45.132.245.30 "docker exec regen-koi-postgres psql -U postgres -d octo_koi -c 'SELECT * FROM allowed_predicates;'"
```

### Resolve an entity via API
```bash
ssh root@45.132.245.30 'curl -s -X POST http://127.0.0.1:8351/entity/resolve -H "Content-Type: application/json" -d "{\"label\": \"Herring Monitoring\", \"type_hint\": \"Practice\"}"'
```

### View OpenClaw logs
```bash
ssh root@45.132.245.30 "journalctl -u koi-api -f"
```

### Edit workspace files
```bash
ssh root@45.132.245.30 "nano ~/.openclaw/workspace/KNOWLEDGE.md"
# Or SCP from local:
scp workspace/KNOWLEDGE.md root@45.132.245.30:~/.openclaw/workspace/
```

## Database

- **Name:** `octo_koi`
- **User:** `postgres`
- **Extensions:** pgvector, Apache AGE, pg_trgm, fuzzystrmatch, uuid-ossp
- **Graph:** `regen_graph` (AGE)
- **Key tables:**
  - `entity_registry` — All registered entities (57 as of Feb 2026)
  - `entity_relationships` — Typed relationships between entities (31)
  - `allowed_predicates` — Valid predicate definitions (27)
  - `pending_relationships` — Unresolved relationship targets
  - `document_entity_links` — Document↔entity mention tracking

## Backups

Automated via cron (daily at 3am CET):
- **DB:** `pg_dump | gzip` → `/root/backups/octo_koi_YYYYMMDD.sql.gz`
- **Vault:** `tar czf` → `/root/backups/vault_YYYYMMDD.tar.gz`
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
| `docker/` | `/root/koi-stack/` |
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
