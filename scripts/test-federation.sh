#!/bin/bash
# End-to-end federation test: Source -> Octo
#
# Tests:
# 1. Register a practice in source node
# 2. Verify event appears in source's queue
# 3. Wait for Octo's poller to pick up the event
# 4. Verify cross-reference exists in Octo
#
# Usage:
#   # Default (GV -> Octo):
#   bash test-federation.sh
#
#   # FR -> Octo (run on Octo host where both are localhost):
#   SOURCE_URL=http://127.0.0.1:8355 SOURCE_DB=fr_koi \
#     SOURCE_SSH="" SOURCE_PG_CONTAINER=regen-koi-postgres \
#     SOURCE_LABEL=FR bash test-federation.sh
#
# Prerequisites:
#   - Both agents running
#   - KOI_NET_ENABLED=true on both
#   - Edges configured between source and Octo

set -e

OCTO_URL="${OCTO_URL:-http://127.0.0.1:8351}"
OCTO_PSQL="docker exec regen-koi-postgres psql -U postgres"

# Source node defaults (GV on poly)
GV_URL="${GV_URL:-http://37.27.48.12:8351}"
GV_SSH="${GV_SSH:-root@37.27.48.12}"
GV_PG_CONTAINER="${GV_PG_CONTAINER:-gv-koi-postgres}"
GV_DB="${GV_DB:-gv_koi}"

# Configurable source (defaults to GV)
SOURCE_URL="${SOURCE_URL:-${GV_URL}}"
SOURCE_SSH="${SOURCE_SSH:-${GV_SSH}}"
SOURCE_PG_CONTAINER="${SOURCE_PG_CONTAINER:-${GV_PG_CONTAINER}}"
SOURCE_DB="${SOURCE_DB:-${GV_DB}}"
SOURCE_LABEL="${SOURCE_LABEL:-GV}"

echo "=========================================="
echo "Federation Test: ${SOURCE_LABEL} -> Octo"
echo "  SOURCE_URL: ${SOURCE_URL}"
echo "  OCTO_URL:   ${OCTO_URL}"
echo "=========================================="

# Check both agents are healthy
echo ""
echo "[1] Checking agent health..."
OCTO_HEALTH=$(curl -s "${OCTO_URL}/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unhealthy'))" 2>/dev/null)
SOURCE_HEALTH=$(curl -s "${SOURCE_URL}/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unhealthy'))" 2>/dev/null)

echo "  Octo:           ${OCTO_HEALTH}"
echo "  ${SOURCE_LABEL}: ${SOURCE_HEALTH}"

if [ "$OCTO_HEALTH" != "healthy" ] || [ "$SOURCE_HEALTH" != "healthy" ]; then
    echo "FAIL: Both agents must be healthy"
    exit 1
fi

# Extract source node RID for cross-ref filtering
SOURCE_NODE_RID=$(curl -s "${SOURCE_URL}/koi-net/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('node',{}).get('node_rid',''))" 2>/dev/null)
if [ -z "$SOURCE_NODE_RID" ]; then
    echo "FAIL: Could not parse source node RID from ${SOURCE_URL}/koi-net/health"
    exit 1
fi
echo "  Source node RID: ${SOURCE_NODE_RID}"

# Check KOI-net is enabled on both
echo ""
echo "[2] Checking KOI-net endpoints..."
OCTO_KOI=$(curl -s -o /dev/null -w "%{http_code}" "${OCTO_URL}/koi-net/health")
SOURCE_KOI=$(curl -s -o /dev/null -w "%{http_code}" "${SOURCE_URL}/koi-net/health")

echo "  Octo /koi-net/health:           HTTP ${OCTO_KOI}"
echo "  ${SOURCE_LABEL} /koi-net/health: HTTP ${SOURCE_KOI}"

if [ "$OCTO_KOI" != "200" ]; then
    echo "FAIL: Octo needs KOI_NET_ENABLED=true"
    exit 1
fi
if [ "$SOURCE_KOI" != "200" ]; then
    echo "FAIL: ${SOURCE_LABEL} needs KOI_NET_ENABLED=true"
    exit 1
fi

# Register a test practice in source
echo ""
echo "[3] Registering test practice in ${SOURCE_LABEL}..."
TIMESTAMP=$(date -u +%Y%m%d%H%M%S)
TEST_NAME="Federation Test Practice ${TIMESTAMP}"

VAULT_RID="vault-fed-test-${TIMESTAMP}"
RESULT=$(curl -s -X POST "${SOURCE_URL}/register-entity" \
    -H "Content-Type: application/json" \
    -d "{
        \"name\": \"${TEST_NAME}\",
        \"entity_type\": \"Practice\",
        \"vault_rid\": \"${VAULT_RID}\",
        \"vault_path\": \"Practices/FederationTest-${TIMESTAMP}.md\",
        \"content_hash\": \"fedtest-${TIMESTAMP}\"
    }")

echo "  Result: ${RESULT}" | head -c 200
echo ""

ENTITY_URI=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('canonical_uri',''))" 2>/dev/null)
echo "  Entity URI: ${ENTITY_URI}"

if [ -z "$ENTITY_URI" ]; then
    echo "FAIL: Could not register entity in ${SOURCE_LABEL}"
    exit 1
fi

# Check source's event queue
echo ""
echo "[4] Checking ${SOURCE_LABEL} event queue..."
if [ -n "$SOURCE_SSH" ]; then
    # Remote source (e.g., GV on poly) — query via SSH
    SOURCE_EVENTS=$(ssh "${SOURCE_SSH}" "docker exec ${SOURCE_PG_CONTAINER} psql -U postgres -d ${SOURCE_DB} -t -c \"SELECT COUNT(*) FROM koi_net_events WHERE rid LIKE '%federation-test%' OR rid LIKE '%${TIMESTAMP}%'\"" 2>/dev/null | tr -d ' ')
else
    # Local source (e.g., FR on same host) — query directly
    SOURCE_EVENTS=$(docker exec ${SOURCE_PG_CONTAINER} psql -U postgres -d ${SOURCE_DB} -t -c "SELECT COUNT(*) FROM koi_net_events WHERE rid LIKE '%federation-test%' OR rid LIKE '%${TIMESTAMP}%'" 2>/dev/null | tr -d ' ')
fi
echo "  Events in ${SOURCE_LABEL} queue: ${SOURCE_EVENTS:-0}"

# Wait for Octo's poller to pick up the event
echo ""
echo "[5] Waiting for Octo poller (max 90s)..."
for i in $(seq 1 9); do
    sleep 10
    CROSS_REFS=$($OCTO_PSQL -d octo_koi -t -c "SELECT COUNT(*) FROM koi_net_cross_refs WHERE remote_node = '${SOURCE_NODE_RID}'" 2>/dev/null | tr -d ' ')
    echo "  ${i}0s: Cross-refs from ${SOURCE_LABEL} in Octo: ${CROSS_REFS:-0}"
    if [ "${CROSS_REFS:-0}" -gt 0 ]; then
        break
    fi
done

# Verify cross-reference
echo ""
echo "[6] Verifying cross-reference..."
$OCTO_PSQL -d octo_koi -c "SELECT local_uri, remote_rid, remote_node, relationship, confidence FROM koi_net_cross_refs WHERE remote_node = '${SOURCE_NODE_RID}' ORDER BY created_at DESC LIMIT 5" 2>/dev/null

echo ""
echo "=========================================="
if [ "${CROSS_REFS:-0}" -gt 0 ]; then
    echo "PASSED: Federation test successful!"
    echo "  ${SOURCE_LABEL} practice -> event -> Octo cross-reference"
else
    echo "RESULT: Cross-reference not yet created."
    echo "  This may be expected if the poller hasn't run yet."
    echo "  Check: journalctl -u koi-api -f (look for poller logs)"
fi
echo "=========================================="
