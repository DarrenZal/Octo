#!/bin/bash
# Start/stop/status for all KOI agents
# Config-driven: reads agent definitions from agents.conf
# Usage: ./manage-agents.sh {start|stop|status|restart}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS_CONF="${SCRIPT_DIR}/agents.conf"

if [ ! -f "$AGENTS_CONF" ]; then
  echo "Error: agents.conf not found at $AGENTS_CONF"
  exit 1
fi

usage() {
  echo "Usage: $0 {start|stop|status|restart}"
  exit 1
}

[ -z "$1" ] && usage

case "$1" in
  start|stop|restart)
    while IFS=: read -r name service port; do
      [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
      echo "$1: $name ($service on port $port)"
      systemctl "$1" "$service"
    done < "$AGENTS_CONF"
    ;;
  status)
    echo "=== KOI Agents ==="
    while IFS=: read -r name service port; do
      [[ "$name" =~ ^#.*$ || -z "$name" ]] && continue
      printf "%-20s " "$name"
      if systemctl is-active --quiet "$service"; then
        health=$(curl -s --max-time 3 "http://127.0.0.1:${port}/health" 2>/dev/null)
        if [ $? -eq 0 ]; then
          echo "HEALTHY (port $port)"
        else
          echo "RUNNING but health check failed (port $port)"
        fi
      else
        echo "NOT RUNNING"
      fi
    done < "$AGENTS_CONF"
    echo ""
    echo "=== Resources ==="
    free -m | awk '/Mem:/{printf "RAM: %dMB / %dMB (%.0f%%)\n", $3, $2, $3/$2*100}'
    echo ""
    echo "=== PostgreSQL ==="
    docker exec regen-koi-postgres psql -U postgres -t -c \
      "SELECT datname || ': ' || numbackends || ' connections' FROM pg_stat_database WHERE datname LIKE '%_koi' ORDER BY datname" 2>/dev/null
    ;;
  *)
    usage
    ;;
esac
