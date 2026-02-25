# New Bioregion Quick-Start Guide

> **Audience:** Someone setting up their first BKC node. Total time: ~2 hours.
> **Full reference:** [`join-the-network.md`](./join-the-network.md) (1,100+ lines, covers everything in depth)
> **Last updated:** 2026-02-19

---

## Overview

You're setting up a **KOI node** — a bioregional knowledge backend with a PostgreSQL knowledge graph, entity resolution, and federation. Your node will store local knowledge (practices, patterns, case studies) and exchange events with the wider BKC network via signed envelopes.

## Governance Prep (1–2 hours, before touching servers)

Before technical setup, define what your bioregion is commoning. Copy the governance template from GitHub:

- **[Pilot template directory](https://github.com/DarrenZal/BioregionalKnowledgeCommoning/tree/main/pilots/template-regional-pilot)** — 6 files to fill in
- **[Front Range example](https://github.com/DarrenZal/BioregionalKnowledgeCommoning/tree/main/pilots/front-range-cascadia-2026)** — a completed pilot for reference

Key files to fill in:
1. **`pilot-charter.md`** — bioregion name, objective, co-stewards, participation profile
2. **`tooling-and-authority-map.md`** — what is shared, who attests, who can use/how
3. **`decision-log.md`** — start empty, record decisions as you go

You don't need to finish everything — a rough charter is enough to start.

## Prerequisites

| Item | Details |
|------|---------|
| **VPS** | Netcup VPS 1000 G11 (~$5/mo) or equivalent. Ubuntu 24.04 LTS, 2+ vCPU, 4GB+ RAM |
| **SSH access** | Root or sudo on the VPS |
| **OpenAI API key** | For embeddings (`text-embedding-3-small`), ~$1–2/mo |
| **Domain (optional)** | sslip.io works for HTTPS without a domain |
| **Budget** | $6–7/mo backend-only, $11–27/mo with OpenClaw chat agent |

## Step 1: Server Setup (30 min)

SSH into your VPS and install dependencies:

```bash
apt update && apt install -y git python3.12 python3.12-venv python3-pip docker.io docker-compose-v2 ufw
```

Clone the Octo repo:

```bash
cd /root
git clone https://github.com/DarrenZal/Octo.git
cd Octo
```

Start the PostgreSQL container:

```bash
cd koi-stack
docker compose up -d
cd ..
```

## Step 2: Run Setup Wizard (15 min)

```bash
bash scripts/setup-node.sh
```

The wizard will interactively configure:
- Database name, user, password
- Node name and slug (e.g., `willamette-valley`)
- Port assignment (default 8351)
- `.env` file with all config
- systemd service file
- Workspace files (IDENTITY.md, SOUL.md)
- ECDSA key generation for signed federation envelopes
- Federation handshake with the coordinator (Octo)

> **Safe to re-run.** The wizard is idempotent — re-running won't break existing config.

## Step 3: Customize Your Node (30 min)

Edit workspace files to give your agent its identity:

```bash
nano ~/your-agent/workspace/IDENTITY.md   # Who is your agent?
nano ~/your-agent/workspace/SOUL.md       # What values guide it?
```

Reference examples:
- [GV agent IDENTITY.md](https://github.com/DarrenZal/Octo/blob/main/gv-agent/workspace/IDENTITY.md)
- [FR agent IDENTITY.md](https://github.com/DarrenZal/Octo/blob/main/fr-agent/workspace/IDENTITY.md)

## Step 4: Seed First Content (30 min)

Create 2–3 Practice notes in your vault to give the node something to work with. Use the templates in [`vault-seed/TEMPLATES/`](../vault-seed/TEMPLATES/):

1. Copy `Practice-template.md` → `~/your-agent/vault/Practices/Your Practice.md`
2. Copy `Bioregion-template.md` → `~/your-agent/vault/Bioregions/Your Bioregion.md`
3. Fill in the YAML frontmatter fields (see templates for field descriptions)

Then ingest them:

```bash
bash ~/scripts/seed-vault-entities.sh http://127.0.0.1:PORT ~/your-agent/vault
```

Replace `PORT` with the port your wizard assigned (default 8351).

## Step 5: Join the Federation (15 min)

The setup wizard already attempted a handshake with the coordinator. Two things need to happen:

1. **Your side (done by wizard):** Registered the coordinator's node info locally.
2. **Coordinator's side (manual):** The wizard printed a SQL block at the end — it looks like:

```
────────────────── copy this ──────────────────
docker exec -i regen-koi-postgres psql -U postgres -d octo_koi <<'SQL'
INSERT INTO koi_net_nodes ...
INSERT INTO koi_net_edges ...
SQL
──────────────────────────────────────────────
```

**Send this SQL block to the network coordinator** (Darren). The coordinator runs it on the Octo server, and federation begins.

Then open your firewall:

```bash
ufw allow PORT
```

## You're Done When...

Run these checks to verify everything is working:

```bash
# 1. Health check — should return {"status":"ok", ...}
curl -s http://127.0.0.1:PORT/health | python3 -m json.tool

# 2. KOI-net health — should show your node_rid and edge info
curl -s http://127.0.0.1:PORT/koi-net/health | python3 -m json.tool

# 3. Seeded entities — should return count > 0
docker exec -i regen-koi-postgres psql -U postgres -d YOUR_DB \
  -c "SELECT count(*) FROM entity_registry;"

# 4. Service logs — should show "Poller started" with no errors
journalctl -u your-koi-api -n 50 --no-pager

# 5. Federation — ask the coordinator to confirm events are flowing
```

## Top 5 First-Timer Issues

| Problem | Fix |
|---------|-----|
| Node won't start | `journalctl -u your-koi-api -f` — check for Python import errors or missing env vars |
| Federation not connecting | Firewall open? `KOI_BASE_URL` correct in your `.env`? Port matches `ufw allow`? |
| Wizard fails mid-run | Safe to re-run (idempotent). Check error output for missing dependencies |
| Entity resolution feels weak | Verify `OPENAI_API_KEY` is set in your `.env` file |
| Lost private key | Restore from `koi-state/` backup. **Back up `koi-state/` early** — the key is your node identity |

Full troubleshooting table: [`join-the-network.md` § Troubleshooting](./join-the-network.md#troubleshooting)

## Practice Note Template

See [`vault-seed/TEMPLATES/Practice-template.md`](../vault-seed/TEMPLATES/Practice-template.md) for the full annotated template. Quick example:

```yaml
---
"@type": "bkc:Practice"
name: Salmon Habitat Restoration
description: Community-led stream restoration for salmon spawning habitat
bioregion:
  - "[[Bioregions/Willamette Valley]]"
aggregatesInto:
  - "[[Patterns/Commons Resource Monitoring]]"
activityStatus: alive
tags:
  - salmon
  - restoration
---
```

All YAML field names (like `bioregion`, `aggregatesInto`, `parentOrg`) are parsed by `vault_parser.py` and mapped to ontology predicates. See the template files for the full list.
