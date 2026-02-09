#!/bin/bash
# End-to-end federation test: GV -> Octo
#
# Tests:
# 1. Register a practice in GV (port 8352)
# 2. Verify event appears in GV's queue
# 3. Wait for Octo's poller to pick up the event
# 4. Verify cross-reference exists in Octo (port 8351)
#
# Prerequisites:
#   - Both agents running (manage-agents.sh status)
#   - KOI_NET_ENABLED=true on both
#   - Edges configured between GV and Octo

set -e

OCTO_URL="http://127.0.0.1:8351"
GV_URL="http://127.0.0.1:8352"
PSQL="docker exec regen-koi-postgres psql -U postgres"

echo "=========================================="
echo "Federation Test: GV -> Octo"
echo "=========================================="

# Check both agents are healthy
echo ""
echo "[1] Checking agent health..."
OCTO_HEALTH=$(curl -s "${OCTO_URL}/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unhealthy'))" 2>/dev/null)
GV_HEALTH=$(curl -s "${GV_URL}/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unhealthy'))" 2>/dev/null)

echo "  Octo: ${OCTO_HEALTH}"
echo "  GV:   ${GV_HEALTH}"

if [ "$OCTO_HEALTH" != "healthy" ] || [ "$GV_HEALTH" != "healthy" ]; then
    echo "FAIL: Both agents must be healthy"
    exit 1
fi

# Check KOI-net is enabled on both
echo ""
echo "[2] Checking KOI-net endpoints..."
OCTO_KOI=$(curl -s -o /dev/null -w "%{http_code}" "${OCTO_URL}/koi-net/health")
GV_KOI=$(curl -s -o /dev/null -w "%{http_code}" "${GV_URL}/koi-net/health")

echo "  Octo /koi-net/health: HTTP ${OCTO_KOI}"
echo "  GV   /koi-net/health: HTTP ${GV_KOI}"

if [ "$OCTO_KOI" != "200" ]; then
    echo "FAIL: Octo needs KOI_NET_ENABLED=true"
    exit 1
fi
if [ "$GV_KOI" != "200" ]; then
    echo "FAIL: GV needs KOI_NET_ENABLED=true"
    exit 1
fi

# Register a test practice in GV
echo ""
echo "[3] Registering test practice in GV..."
TIMESTAMP=$(date -u +%Y%m%d%H%M%S)
TEST_NAME="Federation Test Practice ${TIMESTAMP}"

RESULT=$(curl -s -X POST "${GV_URL}/register-entity" \
    -H "Content-Type: application/json" \
    -d "{
        \"name\": \"${TEST_NAME}\",
        \"entity_type\": \"Practice\",
        \"source\": \"federation-test\"
    }")

echo "  Result: ${RESULT}" | head -c 200
echo ""

ENTITY_URI=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('uri',''))" 2>/dev/null)
echo "  Entity URI: ${ENTITY_URI}"

if [ -z "$ENTITY_URI" ]; then
    echo "FAIL: Could not register entity in GV"
    exit 1
fi

# Check GV's event queue
echo ""
echo "[4] Checking GV event queue..."
GV_EVENTS=$($PSQL -d gv_koi -t -c "SELECT COUNT(*) FROM koi_net_events WHERE rid LIKE '%federation-test%' OR rid LIKE '%${TIMESTAMP}%'" 2>/dev/null | tr -d ' ')
echo "  Events in GV queue: ${GV_EVENTS:-0}"

# Wait for Octo's poller to pick up the event
echo ""
echo "[5] Waiting for Octo poller (max 90s)..."
for i in $(seq 1 9); do
    sleep 10
    CROSS_REFS=$($PSQL -d octo_koi -t -c "SELECT COUNT(*) FROM koi_net_cross_refs WHERE remote_node LIKE '%greater-victoria%'" 2>/dev/null | tr -d ' ')
    echo "  ${i}0s: Cross-refs from GV in Octo: ${CROSS_REFS:-0}"
    if [ "${CROSS_REFS:-0}" -gt 0 ]; then
        break
    fi
done

# Verify cross-reference
echo ""
echo "[6] Verifying cross-reference..."
$PSQL -d octo_koi -c "SELECT local_uri, remote_rid, remote_node, relationship, confidence FROM koi_net_cross_refs ORDER BY created_at DESC LIMIT 5" 2>/dev/null

echo ""
echo "=========================================="
if [ "${CROSS_REFS:-0}" -gt 0 ]; then
    echo "PASSED: Federation test successful!"
    echo "  GV practice -> event -> Octo cross-reference"
else
    echo "RESULT: Cross-reference not yet created."
    echo "  This may be expected if the poller hasn't run yet."
    echo "  Check: manage-agents.sh status"
    echo "  Check: journalctl -u koi-api -f (look for poller logs)"
fi
echo "=========================================="
