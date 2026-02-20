# CLAUDE.md — Octo Project Instructions

## Overview

Octo is a bioregional knowledge commoning agent built on OpenClaw, deployed on a VPS at `45.132.245.30`. It runs a KOI (Knowledge Organization Infrastructure) backend with a PostgreSQL knowledge graph and serves as the AI agent for the BKC CoIP (Bioregional Knowledge Commons Community of Inquiry & Practice).

## Production Server

- **Host:** `45.132.245.30`
- **Public Site (canonical):** `https://45.132.245.30.sslip.io`
- **Public Site (legacy/raw IP):** `http://45.132.245.30` (HTTPS on raw IP uses self-signed fallback cert)
- **User:** `root`
- **OS:** Ubuntu 24.04 LTS
- **SSH:** `ssh root@45.132.245.30` (key-based auth configured)
- **Resources:** 4 vCPU, 8GB RAM, 247GB disk

## Services

| Service | How it runs | Port | Details |
|---------|------------|------|---------|
| **Octo KOI API** | systemd (`koi-api.service`) | 8351 (localhost) | uvicorn, Python 3.12, KOI-net enabled |
| **FR KOI API** | systemd (`fr-koi-api.service`) | 8355 (localhost) | Front Range peer node, localhost-only |
| **KOI Federation Gateway** | nginx (`octo-koi-net-8351`) | 8351 (public IP) | Proxies only `/koi-net/*` and `/health` to Octo API |
| **GV KOI API** | **Remote** on `37.27.48.12` (poly) | 8351 (public) | Greater Victoria leaf node, migrated 2026-02-18 |
| **PostgreSQL** | Docker (`regen-koi-postgres`) | 5432 (localhost) | pgvector + Apache AGE, multiple DBs |
| **OpenClaw** | OpenClaw runtime (v2026.2.2-3) | — | Telegram + Discord channels |
| **Quartz** | nginx + cron rebuild | 80/443 | Static knowledge site (HTTPS on `45.132.245.30.sslip.io`) |
| **Octo Chat** | systemd (`octo-chat.service`) | 3847 (localhost) | Chat API → OpenClaw agent |

### KOI-net Node Identities

Node RID hash mode: `b64_64` = `sha256(base64(DER(pubkey)))` — BlockScience canonical (64 hex chars).
Legacy `legacy16` RIDs (16 hex chars) still accepted during migration via `KOI_ALLOW_LEGACY16_NODE_RID=true`.

| Node | Node RID | Public Key (truncated) |
|------|----------|----------------------|
| **Octo** | `orn:koi-net.node:octo-salish-sea+50a3c9eac05c807f7f0ad114aad3b50b67bbbe1015664e39988f967f9ef4502b` | `MFkwEwYH...` |
| **FR** | `orn:koi-net.node:front-range+b5429ae7981decb0ddf5a45551b176846e6121f964543259eccf4a0a1a6ff21c` | `MFkwEwYH...` |
| **GV** | `orn:koi-net.node:greater-victoria+81ec47d80f2314449b0f4342c087eb91dabf7811fc2d846233c389ef2b0b6f58` | `MFkwEwYH...` |

> **RID migration complete (2026-02-18):** Node RIDs migrated from legacy16 (16-char) to b64_64 (64-char BlockScience canonical). Same keypairs, full SHA-256 hash suffix.

Octo's key: `/root/koi-state/octo-salish-sea_private_key.pem` (on 45.132.245.30).
FR's key: `/root/koi-state/front-range_private_key.pem` (on 45.132.245.30).
GV's key: `/home/koi/koi-state/greater-victoria_private_key.pem` (on poly 37.27.48.12).

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
├── fr-agent/                   # Front Range peer node (port 8355, localhost-only)
│   ├── config/
│   │   └── fr.env
│   ├── workspace/
│   │   ├── IDENTITY.md
│   │   └── SOUL.md
│   └── vault/
│       ├── Bioregions/
│       └── Practices/
├── gv-agent/                   # Greater Victoria (LEGACY local copy — deployed on poly at /home/koi/)
├── koi-state/                  # Node identity keys
│   └── octo-salish-sea_private_key.pem
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

**Canonical URL:** `https://45.132.245.30.sslip.io`
**Legacy URL:** `http://45.132.245.30`

Quartz renders Octo's vault as a browsable static site with wikilinks, backlinks, graph view, and full-text search.

**Privacy:** The `People/` folder is excluded via `ignorePatterns` — no personal names/info are published. Entity files still reference People via wikilinks internally, but those pages don't render on the public site.

### Config
- **nginx:** `/etc/nginx/sites-available/octo-quartz`
- **KOI gateway nginx:** `/etc/nginx/sites-available/octo-koi-net-8351`
- **Quartz config:** `/root/octo-quartz/quartz.config.ts`
- **TLS cert deployment:** `/etc/nginx/ssl/octo-sslip-fullchain.pem` + `/etc/nginx/ssl/octo-sslip.key`
- **ACME client:** `~/.acme.sh/acme.sh` (ZeroSSL)
- **Landing page:** `/root/.openclaw/workspace/vault/index.md`
- **Auto-rebuild:** Cron every 15 minutes → `/var/log/quartz-rebuild.log`
- **Cert renew cron:** `34 0 * * * "/root/.acme.sh"/acme.sh --cron --home "/root/.acme.sh" > /dev/null`

### Manual rebuild
```bash
ssh root@45.132.245.30 "/root/octo-quartz/rebuild.sh"
```

### Update domain (when ready)
1. Edit `baseUrl` in `/root/octo-quartz/quartz.config.ts`
2. Issue/install cert for new host via ACME and update nginx cert paths/server_name in `/etc/nginx/sites-available/octo-quartz`
3. Rebuild and reload: `/root/octo-quartz/rebuild.sh && systemctl reload nginx`

## Common Operations

### SSH to server
```bash
ssh root@45.132.245.30
```

### Check all agents status
```bash
ssh root@45.132.245.30 "bash ~/scripts/manage-agents.sh status"
```

### KOI API health check
```bash
ssh root@45.132.245.30 "curl -s http://127.0.0.1:8351/health"   # Octo
curl -s http://37.27.48.12:8351/health                           # GV (remote on poly)
```

### KOI-net health check
```bash
ssh root@45.132.245.30 "curl -s http://127.0.0.1:8351/koi-net/health"
curl -s http://45.132.245.30:8351/koi-net/health   # Public KOI gateway path
```

### Restart agents (after code changes)
```bash
ssh root@45.132.245.30 "systemctl restart koi-api"                # Octo
ssh root@37.27.48.12 "sudo systemctl restart gv-koi-api"          # GV (remote on poly)
```

### Deploy updated Python files (both servers)
```bash
# Sync to Octo
rsync -avz --delete koi-processor/api/ root@45.132.245.30:/root/koi-processor/api/
rsync -avz koi-processor/migrations/ root@45.132.245.30:/root/koi-processor/migrations/

# Sync to GV (poly)
rsync -avz --delete koi-processor/api/ root@37.27.48.12:/home/koi/koi-processor/api/
rsync -avz koi-processor/migrations/ root@37.27.48.12:/home/koi/koi-processor/migrations/
ssh root@37.27.48.12 "chown -R koi:koi /home/koi/koi-processor"

# Restart both
ssh root@45.132.245.30 "systemctl restart koi-api"
ssh root@37.27.48.12 "systemctl restart gv-koi-api"

# Stamp version
git rev-parse --short HEAD | ssh root@45.132.245.30 "cat > /root/koi-processor/.version"
git rev-parse --short HEAD | ssh root@37.27.48.12 "cat > /home/koi/koi-processor/.version"
```

### Deploy updated plugin + restart OpenClaw
```bash
scp plugins/bioregional-koi/index.ts root@45.132.245.30:~/bioregional-koi/index.ts
ssh root@45.132.245.30 "openclaw gateway restart"
```

### Run federation test
```bash
ssh root@45.132.245.30 "bash ~/scripts/test-federation.sh"
```

### Run interop test
```bash
ssh root@45.132.245.30 "cd ~/koi-processor && venv/bin/python tests/test_koi_interop.py"
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

### Test web URL preview
```bash
ssh root@45.132.245.30 'curl -s -X POST http://127.0.0.1:8351/web/preview -H "Content-Type: application/json" -d "{\"url\": \"https://example.com\"}" | python3 -m json.tool'
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

## KOI-net Federation Debugging

### Fast checks
```bash
# Idempotent local peer connect (upsert node+edge, send handshake, print reciprocal SQL)
bash scripts/connect-koi-peer.sh --db <local_db> --peer-url http://<peer-ip>:8351

# Is Cowichan polling Octo?
ssh root@45.132.245.30 "journalctl -u koi-api --since '10 min ago' --no-pager | grep -E '202\\.61\\.242\\.194:0 - \\\"POST /koi-net/events/poll|Delivered .*cowichan|Confirmed .*cowichan'"

# Do we have peer public keys?
ssh root@45.132.245.30 "docker exec regen-koi-postgres psql -U postgres -d octo_koi -c \"SELECT node_rid, node_name, length(public_key) AS key_len, base_url FROM koi_net_nodes ORDER BY node_name;\""

# Is edge orientation correct? (source = provider, target = poller)
ssh root@45.132.245.30 "docker exec regen-koi-postgres psql -U postgres -d octo_koi -c \"SELECT edge_rid, source_node, target_node, status FROM koi_net_edges WHERE edge_rid LIKE '%polls%';\""
```

### Known failure modes
- `POST /koi-net/events/poll` returns `400` with `No public key for ...`:
  - Poller now retries with handshake automatically; if it persists, upsert peer `public_key` in `koi_net_nodes`.
- Poller runs but never polls peers:
  - Edge is flipped. For POLL, `target_node` must equal self.
- `404` on `/koi-net/poll`:
  - Use `/koi-net/events/poll` (legacy path removed).
- Peer cannot reach Octo:
  - Ensure nginx KOI gateway is up (`/etc/nginx/sites-available/octo-koi-net-8351`) and `KOI_BASE_URL` is public.

## Databases

Octo's databases are in the local PostgreSQL container (`regen-koi-postgres`). GV's database is on poly (`37.27.48.12`, container `gv-koi-postgres`, port 5433).

| Database | Agent | Host | Entities |
|----------|-------|------|----------|
| `octo_koi` | Octo (Salish Sea) | `45.132.245.30` (local) | 70 |
| `fr_koi` | Front Range | `45.132.245.30` (local) | 4 |
| `gv_koi` | Greater Victoria | `37.27.48.12` (poly, port 5433) | 5 |

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

### Octo (`45.132.245.30`)
Automated via cron (daily at 3am CET):
- **DB:** `pg_dump | gzip` → `/root/backups/octo_koi_YYYYMMDD.sql.gz`
- **Vault:** `tar czf` → `/root/backups/vault_YYYYMMDD.tar.gz`
- **Keys:** `tar czf` → `/root/backups/koi_state_YYYYMMDD.tar.gz` (Octo node identity key)
- **Retention:** 7 days (old backups auto-deleted at 4am)

### GV on poly (`37.27.48.12`)
Automated via systemd timer (`gv-backup.timer`, daily at 3am CET):
- **DB:** `pg_dump -Fc` → `/home/koi/backups/gv_koi_YYYYMMDD.dump` + `.sha256`
- **Vault:** `tar czf` → `/home/koi/backups/gv_vault_YYYYMMDD.tar.gz` + `.sha256`
- **Retention:** 7 days
- **Off-host copy:** Weekly rsync to `root@45.132.245.30:/root/backups/poly-mirror/` (`gv-backup-offhost.timer`, Sundays 4am)

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
| `fr-agent/` | `/root/fr-agent/` (on `45.132.245.30`) |
| `gv-agent/` | `/home/koi/gv-agent/` (on poly `37.27.48.12`) |
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
| `~/projects/personal-koi-mcp/` | KOI MCP server (TypeScript). Implements the `koi-tool-contract` (15 tools) + 27 personal-only tools (email search, sessions, vault ETL, meeting prep). Currently a hybrid personal+BKC system — the 15 contract tools are identical to what `plugins/bioregional-koi/` provides for OpenClaw. Future plan: split into `commoning-koi-mcp` (15 contract tools only, deployable on any BKC node) + keep personal tools here. See `docs/koi-protocol-alignment-master.md` §8C. |
| `~/Documents/Notes/Ontology/` | Local vault ontology schemas |

## Current Status

**Date:** 2026-02-19
**Status:** HEALTHY — 3-node cross-network federation active

### What's Done
- Sprints 1-3 deployed: KOI-net federation working between Octo (coordinator) and GV (leaf)
- **GV migrated to remote server** (2026-02-18): `37.27.48.12` (poly), port 8351, user `koi`, own PostgreSQL container (port 5433). Same keypair, RID preserved. 3-node topology: Octo + GV (remote) + CV (Shawn)
- **Old GV decommissioned** (2026-02-19): Removed gv-koi-api service, gv_koi DB, /root/gv-agent/, and old private key from 45.132.245.30. Final backups: `/root/backups/gv_koi_final_20260219.sql.gz` + `gv_agent_final_20260219.tar.gz`
- P0-P9 protocol alignment complete (98 tests, deployed), keys encrypted at rest (P9)
- **Front Range agent deployed** (2026-02-19): `127.0.0.1:8355` on Octo server, `fr_koi` DB, bidirectional federation with Octo, localhost-only (peer through coordinator topology)
- Node RID migration to b64_64 (BlockScience canonical) complete
- 70 entities in Octo across 14 types, seeded via `seed-vault-entities.sh`
- Cross-reference resolution verified: Herring Monitoring = `same_as` (confidence 1.0)
- Cowichan Valley (Shawn's node) live at `202.61.242.194:8351`
- **Phase 5.7: GitHub sensor activated** (2026-02-19): 4 repos (Octo, openclaw, koi-net, personal-koi-mcp), 35k+ code artifacts, tree-sitter Python/TS extraction, vault notes in `Sources/GitHub/`, 6-hour auto-scan interval

### GV Remote Node (poly)
- **Host:** `37.27.48.12` (poly server, shared with AlgoTrading)
- **SSH:** `ssh root@37.27.48.12` (or `koi` user for KOI work)
- **Service:** `gv-koi-api.service` (systemd, runs as `koi` user)
- **DB:** `gv_koi` in Docker container `gv-koi-postgres` on port 5433
- **Code:** `/home/koi/koi-processor/`
- **Vault:** `/home/koi/gv-agent/vault/`
- **Key:** `/home/koi/koi-state/greater-victoria_private_key.pem`
- **Env:** `/home/koi/gv-agent/config/gv.env`
- **Logs:** `ssh root@37.27.48.12 "journalctl -u gv-koi-api -f"`
- **Firewall:** iptables `KOI_FEDERATION` chain on poly — only Octo + CV IPs can reach port 8351. Persistent via `netfilter-persistent`.
- **Version stamp:** `/home/koi/koi-processor/.version` (git SHA, stamped after each deploy)
- **Backups:** `gv-backup.timer` (daily 3am), `gv-backup-offhost.timer` (weekly Sun 4am → Octo). See Backups section.

### What's Left
1. **Phase 0.5: BKC CoIP vault audit** — blocked on access from Andrea Farias / Vincent Arena
2. **Phase 5: Cascadia coordinator** — after CV is running, proves holon pattern

### Adding a New Agent (Quick Reference)

```bash
# 1. Create database
ssh root@45.132.245.30 "bash ~/koi-stack/create-additional-dbs.sh cv_koi"

# 2. Create agent directory (follow gv-agent/ pattern)
ssh root@45.132.245.30 "mkdir -p ~/cv-agent/{config,workspace,vault}"

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
