#!/bin/bash
# Interactive setup wizard for a new KOI federation node.
# Run this after completing Steps 1-3 of docs/join-the-network.md
# (VPS provisioned, Octo repo cloned, PostgreSQL running).
#
# Usage: bash /root/Octo/scripts/setup-node.sh

set -euo pipefail

OCTO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ─── Colors ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}→${NC} $1"; }
ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}!${NC} $1"; }
err()   { echo -e "${RED}✗${NC} $1"; }
header(){ echo -e "\n${BOLD}── $1 ──${NC}\n"; }

# ─── Pre-flight checks ───
header "KOI Node Setup Wizard"
echo "This will set up a new KOI federation node on this server."
echo "Make sure you've completed Steps 1-3 of the guide first:"
echo "  - VPS provisioned with Docker, Python 3, Node.js"
echo "  - Octo repo cloned to /root/Octo"
echo "  - PostgreSQL running (docker compose up -d)"
echo ""

# Check Docker is running
if ! docker exec regen-koi-postgres pg_isready -U postgres &>/dev/null; then
  err "PostgreSQL container not running. Start it first:"
  echo "  cd $OCTO_DIR/docker && docker compose up -d"
  exit 1
fi
ok "PostgreSQL is running"

# Check Python venv exists or can be created
if [ ! -d "$OCTO_DIR/koi-processor/venv" ]; then
  info "Python virtualenv not found. Creating it..."
  python3 -m venv "$OCTO_DIR/koi-processor/venv"
  "$OCTO_DIR/koi-processor/venv/bin/pip" install -q -r "$OCTO_DIR/koi-processor/requirements.txt"
  ok "Python virtualenv created and dependencies installed"
else
  ok "Python virtualenv exists"
fi

# ─── Gather info ───
header "Node Configuration"

# Node name
echo "What is your bioregion or node name?"
echo "  Examples: Cowichan Valley, Front Range, Boulder Creek"
read -rp "  Node name: " NODE_FULL_NAME

if [ -z "$NODE_FULL_NAME" ]; then
  err "Node name cannot be empty"
  exit 1
fi

# Derive short name (lowercase, hyphens for spaces)
NODE_SLUG=$(echo "$NODE_FULL_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')
# Derive even shorter name for DB (first letters of each word, or first 2 words abbreviated)
DB_SHORT=$(echo "$NODE_FULL_NAME" | tr '[:upper:]' '[:lower:]' | awk '{for(i=1;i<=NF;i++) printf substr($i,1,1)}' | sed 's/[^a-z]//g')
# If single word, use first 4 chars
if [ ${#DB_SHORT} -le 1 ]; then
  DB_SHORT=$(echo "$NODE_SLUG" | head -c 6)
fi

DB_NAME="${DB_SHORT}_koi"
AGENT_DIR="/root/${DB_SHORT}-agent"
SERVICE_NAME="${DB_SHORT}-koi-api"

echo ""
info "Based on \"$NODE_FULL_NAME\", here are your derived names:"
echo "  Database:        $DB_NAME"
echo "  Agent directory: $AGENT_DIR"
echo "  systemd service: $SERVICE_NAME"
echo "  KOI node name:   $NODE_SLUG"
echo ""
read -rp "  Look good? (Y/n) " CONFIRM
if [[ "${CONFIRM,,}" == "n" ]]; then
  echo ""
  read -rp "  Database name (e.g. cv_koi): " DB_NAME
  read -rp "  Agent directory (e.g. /root/cv-agent): " AGENT_DIR
  read -rp "  systemd service name (e.g. cv-koi-api): " SERVICE_NAME
  read -rp "  KOI node name (e.g. cowichan-valley): " NODE_SLUG
fi

# Node type
echo ""
echo "What type of node is this?"
echo "  1) Leaf node — sub-bioregion under a coordinator (e.g. under Salish Sea)"
echo "  2) Peer network — independent bioregion, exchanges knowledge as equals"
echo "  3) Personal/research — standalone, optional federation"
read -rp "  Choose (1/2/3): " NODE_TYPE_NUM

case "$NODE_TYPE_NUM" in
  1) NODE_TYPE="Leaf node" ;;
  2) NODE_TYPE="Peer network" ;;
  3) NODE_TYPE="Personal/research" ;;
  *) NODE_TYPE="Leaf node" ;;
esac

# PostgreSQL password
echo ""
if [ -f ~/.env ] && grep -q POSTGRES_PASSWORD ~/.env; then
  PG_PASS=$(grep POSTGRES_PASSWORD ~/.env | head -1 | cut -d= -f2)
  ok "Found PostgreSQL password in ~/.env"
else
  read -rp "  PostgreSQL password (from Step 3): " PG_PASS
  if [ -z "$PG_PASS" ]; then
    err "Password required"
    exit 1
  fi
fi

# OpenAI API key
echo ""
echo "OpenAI API key (for semantic entity resolution, ~\$1-2/month)."
echo "  Get one at: https://platform.openai.com/api-keys"
read -rp "  OpenAI API key: " OPENAI_KEY

if [ -z "$OPENAI_KEY" ]; then
  warn "No OpenAI key provided. Semantic matching will be disabled."
  warn "You can add it later in $AGENT_DIR/config/${DB_SHORT}.env"
fi

# API port
API_PORT=8351
echo ""
echo "KOI API port (default 8351). Change if running multiple nodes on one server."
read -rp "  API port [$API_PORT]: " INPUT_PORT
API_PORT="${INPUT_PORT:-$API_PORT}"

# Bind host + base URL defaults
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "")
if [ "$NODE_TYPE_NUM" = "3" ]; then
  API_BIND_HOST="127.0.0.1"
else
  API_BIND_HOST="0.0.0.0"
fi

if [ -n "$PUBLIC_IP" ]; then
  KOI_BASE_URL_DEFAULT="http://$PUBLIC_IP:$API_PORT"
else
  KOI_BASE_URL_DEFAULT="http://127.0.0.1:$API_PORT"
  warn "Could not detect public IP. KOI_BASE_URL defaults to localhost; update it for federation."
fi

# ─── Create everything ───
header "Setting Up Node"

# 1. Create database
info "Creating database $DB_NAME..."
if docker exec regen-koi-postgres psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
  warn "Database $DB_NAME already exists, skipping creation"
else
  bash "$OCTO_DIR/docker/create-additional-dbs.sh" "$DB_NAME"
  ok "Database $DB_NAME created"
fi

# 2. Create agent directory
info "Creating agent directory $AGENT_DIR..."
mkdir -p "$AGENT_DIR"/{config,workspace,vault}
mkdir -p "$AGENT_DIR"/vault/{Bioregions,Practices,Patterns,Organizations,Projects,Concepts,People,Locations,CaseStudies,Protocols,Playbooks,Questions,Claims,Evidence,Sources}
ok "Agent directory created with vault subdirectories"

# 3. Generate env file
info "Generating config file..."
ENV_FILE="$AGENT_DIR/config/${DB_SHORT}.env"
cat > "$ENV_FILE" << ENVEOF
# KOI Node Configuration — $NODE_FULL_NAME
# Generated by setup-node.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)

# PostgreSQL — the API reads POSTGRES_URL
POSTGRES_URL=postgresql://postgres:${PG_PASS}@localhost:5432/$DB_NAME

# OpenAI (for semantic entity resolution)
OPENAI_API_KEY=$OPENAI_KEY
EMBEDDING_MODEL=text-embedding-3-small

# Vault
VAULT_PATH=$AGENT_DIR/vault

# KOI-net federation
KOI_NET_ENABLED=true
KOI_NODE_NAME=$NODE_SLUG
KOI_STATE_DIR=/root/koi-state
KOI_BASE_URL=$KOI_BASE_URL_DEFAULT

# KOI protocol validation policy
# Leave strict mode off until all federation peers support signed envelopes.
KOI_STRICT_MODE=false
KOI_REQUIRE_SIGNED_ENVELOPES=false
KOI_REQUIRE_SIGNED_RESPONSES=false
KOI_ENFORCE_TARGET_MATCH=false
KOI_ENFORCE_SOURCE_KEY_RID_BINDING=false

# API
KOI_API_HOST=$API_BIND_HOST
KOI_API_PORT=$API_PORT
ENVEOF

# Also copy to koi-processor config for convenience
cp "$ENV_FILE" "$OCTO_DIR/koi-processor/config/${DB_SHORT}.env"
ok "Config written to $ENV_FILE"

# 4. Create base schema by starting API briefly
info "Creating base database schema (starting API briefly)..."
cd "$OCTO_DIR/koi-processor"
set -a; source "$ENV_FILE"; set +a
timeout 15 venv/bin/uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port "$API_PORT" &>/dev/null || true
sleep 2

# Verify base tables exist
TABLE_COUNT=$(docker exec regen-koi-postgres psql -U postgres -d "$DB_NAME" -tc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" | tr -d ' ')
if [ "$TABLE_COUNT" -gt 0 ]; then
  ok "Base schema created ($TABLE_COUNT tables)"
else
  warn "Base tables may not have been created. Trying again..."
  timeout 15 venv/bin/uvicorn api.personal_ingest_api:app --host 127.0.0.1 --port "$API_PORT" &>/dev/null || true
  sleep 2
fi

# 5. Run additional migrations
info "Running migrations..."
PSQL="docker exec -i regen-koi-postgres psql -U postgres -d $DB_NAME"

for MIG in 038_bkc_predicates 039_koi_net_events 039b_ontology_mappings 040_entity_koi_rids 041_cross_references 042_web_submissions; do
  MIG_FILE="$OCTO_DIR/koi-processor/migrations/${MIG}.sql"
  if [ -f "$MIG_FILE" ]; then
    cat "$MIG_FILE" | $PSQL &>/dev/null && ok "  $MIG" || warn "  $MIG (may already exist)"
  fi
done

# 6. Generate workspace files
info "Generating workspace files..."

cat > "$AGENT_DIR/workspace/IDENTITY.md" << IDEOF
# IDENTITY.md — $NODE_FULL_NAME Knowledge Agent

- **Name:** $NODE_FULL_NAME Node
- **Role:** Bioregional knowledge agent for $NODE_FULL_NAME
- **Node Type:** $NODE_TYPE

## What I Do

I am the knowledge backend for the $NODE_FULL_NAME bioregion. I track local
practices, patterns, and ecological knowledge specific to this place.

## Bioregional Context

TODO: Describe your bioregion here — the land, water, peoples, and ecology.

## Boundaries

- I serve the $NODE_FULL_NAME bioregion
IDEOF

cat > "$AGENT_DIR/workspace/SOUL.md" << SOEOF
# SOUL.md — $NODE_FULL_NAME Node Values

## Core Values

- **Knowledge as commons** — share freely, govern collectively
- **Epistemic justice** — respect diverse ways of knowing
- **Knowledge sovereignty** — communities govern their own knowledge
- **Federation over consolidation** — one node in a web, many centers

## Place-Specific Grounding

TODO: What makes this place unique? What does knowledge mean here?
SOEOF

ok "Workspace files created (edit them later to add bioregional detail)"

# 7. Create bioregion entity
info "Creating bioregion vault note..."
BIOREGION_FILE="$AGENT_DIR/vault/Bioregions/$(echo "$NODE_FULL_NAME" | sed 's/[\/:]/-/g').md"
cat > "$BIOREGION_FILE" << BIOEOF
---
"@type": "bkc:Bioregion"
name: $NODE_FULL_NAME
description: TODO — describe this bioregion
tags:
  - bioregion
---

# $NODE_FULL_NAME

TODO: Describe this bioregion — its watersheds, ecology, communities, and Indigenous territories.
BIOEOF
ok "Bioregion note created at vault/Bioregions/"

# 8. Create systemd service
info "Creating systemd service $SERVICE_NAME..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SVCEOF
[Unit]
Description=$NODE_FULL_NAME KOI API
After=network.target docker.service

[Service]
Type=simple
User=root
WorkingDirectory=$OCTO_DIR/koi-processor
Environment=PATH=$OCTO_DIR/koi-processor/venv/bin:/usr/bin
EnvironmentFile=$ENV_FILE
ExecStart=$OCTO_DIR/koi-processor/venv/bin/uvicorn api.personal_ingest_api:app --host $API_BIND_HOST --port $API_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" &>/dev/null
systemctl start "$SERVICE_NAME"
ok "Service $SERVICE_NAME started"

# 9. Wait and verify
info "Waiting for API to start..."
sleep 5

if curl -s "http://127.0.0.1:$API_PORT/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null | grep -qi healthy; then
  ok "API is healthy!"
else
  warn "API may still be starting. Check: journalctl -u $SERVICE_NAME -f"
fi

# 10. Seed the bioregion entity
info "Seeding bioregion entity into database..."
bash "$OCTO_DIR/scripts/seed-vault-entities.sh" "http://127.0.0.1:$API_PORT" "$AGENT_DIR/vault" 2>/dev/null || true

# ─── Federation Setup ───
header "Federation Setup"

# Get node RID + public key
NODE_HEALTH=$(curl -s "http://127.0.0.1:$API_PORT/koi-net/health" 2>/dev/null || echo "")
NODE_RID=$(echo "$NODE_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d.get('node') or {}; print(n.get('node_rid') or d.get('node_rid',''))" 2>/dev/null || echo "")
NODE_PUBLIC_KEY=$(echo "$NODE_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d.get('node') or {}; print(n.get('public_key') or '')" 2>/dev/null || echo "")
NODE_BASE_URL_FOR_COORD="$KOI_BASE_URL_DEFAULT"
COORD_HANDSHAKE_STATUS="not_attempted"

if [ -z "$NODE_RID" ]; then
  warn "Could not read node RID from /koi-net/health."
fi

if [ "$NODE_TYPE_NUM" = "3" ]; then
  info "Personal/research node — skipping federation (you can set it up later)"
else
  echo "Do you want to connect this node to the Salish Sea network (Octo coordinator)?"
  echo "  This lets your node exchange knowledge with the broader network."
  echo ""
  read -rp "  Set up federation now? (Y/n) " FED_CONFIRM

  if [[ "${FED_CONFIRM,,}" != "n" ]]; then
    # Coordinator defaults (Octo / Salish Sea)
    COORD_RID="orn:koi-net.node:octo-salish-sea+50a3c9eac05c807f"
    COORD_NAME="octo-salish-sea"
    COORD_URL="http://45.132.245.30:8351"

    echo ""
    echo "  Default coordinator: Octo (Salish Sea) at 45.132.245.30"
    read -rp "  Use default? (Y/n) " COORD_CONFIRM

    if [[ "${COORD_CONFIRM,,}" == "n" ]]; then
      read -rp "  Coordinator node RID: " COORD_RID
      read -rp "  Coordinator name: " COORD_NAME
      read -rp "  Coordinator URL (e.g. http://1.2.3.4:8351): " COORD_URL
    fi

    # Try to discover coordinator RID/public key from health endpoint
    COORD_HEALTH=$(curl -s --max-time 8 "$COORD_URL/koi-net/health" 2>/dev/null || echo "")
    COORD_PUBLIC_KEY=""
    if [ -n "$COORD_HEALTH" ]; then
      COORD_RID_DETECTED=$(echo "$COORD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d.get('node') or {}; print(n.get('node_rid') or d.get('node_rid',''))" 2>/dev/null || echo "")
      COORD_PUBLIC_KEY=$(echo "$COORD_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d.get('node') or {}; print(n.get('public_key') or '')" 2>/dev/null || echo "")
      if [ -n "$COORD_RID_DETECTED" ] && [ "$COORD_RID_DETECTED" != "$COORD_RID" ]; then
        warn "Coordinator RID mismatch (configured=$COORD_RID, detected=$COORD_RID_DETECTED). Using detected RID."
        COORD_RID="$COORD_RID_DETECTED"
      fi
    else
      warn "Could not fetch coordinator health from $COORD_URL"
    fi

    # Edge RID: shortname-polls-coordinator
    EDGE_RID="orn:koi-net.edge:${NODE_SLUG}-polls-${COORD_NAME}"
    RID_TYPES="{Practice,Pattern,CaseStudy,Bioregion}"

    PSQL_FED="docker exec -i regen-koi-postgres psql -U postgres -d $DB_NAME"
    if [ -n "$COORD_PUBLIC_KEY" ]; then
      COORD_PUBLIC_KEY_SQL="'$COORD_PUBLIC_KEY'"
    else
      COORD_PUBLIC_KEY_SQL="NULL"
      warn "Coordinator public key unavailable. Signed response verification may fail."
    fi
    if [ -n "$NODE_PUBLIC_KEY" ]; then
      NODE_PUBLIC_KEY_SQL="'$NODE_PUBLIC_KEY'"
    else
      NODE_PUBLIC_KEY_SQL="NULL"
      warn "Local node public key unavailable. Coordinator must add it manually."
    fi

    # Register coordinator as known node
    info "Registering coordinator node..."
    echo "INSERT INTO koi_net_nodes (node_rid, node_name, node_type, base_url, public_key, status, last_seen) VALUES ('$COORD_RID', '$COORD_NAME', 'FULL', '$COORD_URL', $COORD_PUBLIC_KEY_SQL, 'active', now()) ON CONFLICT (node_rid) DO UPDATE SET node_name = EXCLUDED.node_name, node_type = EXCLUDED.node_type, base_url = EXCLUDED.base_url, public_key = COALESCE(EXCLUDED.public_key, koi_net_nodes.public_key), status = 'active', last_seen = now();" | $PSQL_FED &>/dev/null
    ok "Coordinator registered: $COORD_NAME"

    # Create edge: this node polls the coordinator
    # Edge semantics: source = data provider (coordinator), target = poller (this node)
    info "Creating federation edge..."
    echo "INSERT INTO koi_net_edges (edge_rid, source_node, target_node, edge_type, status, rid_types) VALUES ('$EDGE_RID', '$COORD_RID', '$NODE_RID', 'POLL', 'APPROVED', '$RID_TYPES') ON CONFLICT (edge_rid) DO UPDATE SET source_node = EXCLUDED.source_node, target_node = EXCLUDED.target_node, edge_type = EXCLUDED.edge_type, status = 'APPROVED', rid_types = EXCLUDED.rid_types, updated_at = now();" | $PSQL_FED &>/dev/null
    ok "Edge created: $NODE_SLUG polls $COORD_NAME"

    # Proactively register this node profile on coordinator via handshake.
    # This reduces first-poll 400s from missing peer public keys.
    HANDSHAKE_PAYLOAD=$(echo "$NODE_HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); n=d.get('node') or {}; print(json.dumps({'type':'handshake','profile':n}, separators=(',',':'))) if n else print('')" 2>/dev/null || echo "")
    if [ -n "$HANDSHAKE_PAYLOAD" ]; then
      info "Sending handshake to coordinator..."
      HANDSHAKE_HTTP=$(curl -s --max-time 10 -o /dev/null -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -X POST "$COORD_URL/koi-net/handshake" \
        -d "$HANDSHAKE_PAYLOAD" || echo "000")
      if [ "$HANDSHAKE_HTTP" = "200" ]; then
        ok "Handshake accepted by coordinator (node/profile registered)"
        COORD_HANDSHAKE_STATUS="ok"
      else
        warn "Coordinator handshake returned HTTP $HANDSHAKE_HTTP. They may need to upsert your node manually."
        COORD_HANDSHAKE_STATUS="failed"
      fi
    else
      warn "Could not build local node profile for coordinator handshake."
      COORD_HANDSHAKE_STATUS="failed"
    fi

    # Check if port is open
    if [ -n "$PUBLIC_IP" ]; then
      info "Checking if port $API_PORT is reachable from outside..."
      if curl -s --max-time 5 "http://$PUBLIC_IP:$API_PORT/health" &>/dev/null; then
        ok "Port $API_PORT is open and reachable"
      else
        warn "Port $API_PORT may not be open. Make sure your firewall allows it:"
        echo "     ufw allow $API_PORT/tcp"
      fi
    fi

    FEDERATION_DONE=true
  fi
fi

# ─── Summary ───
header "Setup Complete!"

echo "Your node is running. Here's a summary:"
echo ""
echo "  Node name:        $NODE_FULL_NAME"
echo "  Node type:        $NODE_TYPE"
echo "  Database:         $DB_NAME"
echo "  Agent directory:  $AGENT_DIR"
echo "  Config file:      $ENV_FILE"
echo "  systemd service:  $SERVICE_NAME"
echo "  API (local):      http://127.0.0.1:$API_PORT"
echo "  API bind host:    $API_BIND_HOST"
echo "  KOI base URL:     $KOI_BASE_URL_DEFAULT"
if [ -n "$NODE_RID" ]; then
  echo "  Node RID:         $NODE_RID"
fi
if [ -n "$PUBLIC_IP" ]; then
  echo "  Public IP:        $PUBLIC_IP"
fi
echo ""

if [ "${FEDERATION_DONE:-}" = "true" ]; then
  echo -e "${GREEN}Federation (your side) is configured.${NC}"
  if [ "${COORD_HANDSHAKE_STATUS:-}" = "ok" ]; then
    echo "Coordinator handshake: succeeded (peer key/profile should already be registered)."
  elif [ "${COORD_HANDSHAKE_STATUS:-}" = "failed" ]; then
    echo "Coordinator handshake: failed (send the SQL block below to coordinator)."
  fi
  echo ""
  echo "Coordinator still needs to ensure/update reciprocal edge config. Send this one-liner:"
  echo ""
  echo -e "${BOLD}────────────────── copy this ──────────────────${NC}"
  echo ""
  echo "  docker exec -i regen-koi-postgres psql -U postgres -d octo_koi <<'SQL'"
  echo "  INSERT INTO koi_net_nodes (node_rid, node_name, node_type, base_url, public_key, status, last_seen)"
  echo "    VALUES ('$NODE_RID', '$NODE_SLUG', 'FULL', '$NODE_BASE_URL_FOR_COORD', $NODE_PUBLIC_KEY_SQL, 'active', now())"
  echo "    ON CONFLICT (node_rid) DO UPDATE SET"
  echo "      node_name = EXCLUDED.node_name,"
  echo "      node_type = EXCLUDED.node_type,"
  echo "      base_url = EXCLUDED.base_url,"
  echo "      public_key = COALESCE(EXCLUDED.public_key, koi_net_nodes.public_key),"
  echo "      status = 'active',"
  echo "      last_seen = now();"
  echo "  INSERT INTO koi_net_edges (edge_rid, source_node, target_node, edge_type, status, rid_types)"
  echo "    VALUES ('$EDGE_RID', '$COORD_RID', '$NODE_RID', 'POLL', 'APPROVED', '$RID_TYPES')"
  echo "    ON CONFLICT (edge_rid) DO UPDATE SET"
  echo "      source_node = EXCLUDED.source_node,"
  echo "      target_node = EXCLUDED.target_node,"
  echo "      edge_type = EXCLUDED.edge_type,"
  echo "      status = 'APPROVED',"
  echo "      rid_types = EXCLUDED.rid_types,"
  echo "      updated_at = now();"
  echo "  SQL"
  echo ""
  echo -e "${BOLD}────────────────────────────────────────────────${NC}"
  echo ""
else
  echo "To connect to the network later, send the coordinator your:"
  echo "  - Server IP:  ${PUBLIC_IP:-<your-ip>}"
  echo "  - API port:   $API_PORT"
  if [ -n "$NODE_RID" ]; then
    echo "  - Node RID:   $NODE_RID"
  fi
  echo ""
fi

echo "Next steps:"
echo ""
echo "  1. Edit your workspace files to add bioregional detail:"
echo "     nano $AGENT_DIR/workspace/IDENTITY.md"
echo "     nano $AGENT_DIR/workspace/SOUL.md"
echo ""
echo "  2. Add 2-3 practice vault notes:"
echo "     nano $AGENT_DIR/vault/Practices/Your Practice.md"
echo "     (see docs/join-the-network.md for the template)"
echo ""
echo "  3. Seed new vault notes into the database:"
echo "     bash $OCTO_DIR/scripts/seed-vault-entities.sh http://127.0.0.1:$API_PORT $AGENT_DIR/vault"
echo ""
echo "  4. Set up OpenClaw chat agent (optional):"
echo "     See docs/join-the-network.md → Step 10"
echo ""
echo "  5. Before enabling strict KOI mode:"
echo "     Coordinate with federation peers, then set KOI_STRICT_MODE=true and restart $SERVICE_NAME"
echo ""
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME    # Check service"
echo "  journalctl -u $SERVICE_NAME -f    # View logs"
echo "  curl http://127.0.0.1:$API_PORT/health  # Health check"
