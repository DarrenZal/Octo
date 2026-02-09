#!/bin/bash
# Create additional databases for multi-agent KOI deployment
# Usage: ./create-additional-dbs.sh [db_name ...]
# Examples:
#   ./create-additional-dbs.sh gv_koi cascadia_koi    # Phase 2
#   ./create-additional-dbs.sh gi_koi                  # Phase 4.5
#   ./create-additional-dbs.sh                         # No args = default set

CONTAINER="regen-koi-postgres"
PSQL="docker exec -i $CONTAINER psql -U postgres"

create_koi_db() {
  local DB_NAME=$1
  echo "Creating database $DB_NAME..."
  $PSQL -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    $PSQL -c "CREATE DATABASE $DB_NAME"

  # Extensions must be created per-database
  $PSQL -d "$DB_NAME" <<EOF
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF

  # AGE requires LOAD per session
  $PSQL -d "$DB_NAME" -c "LOAD 'age'; SET search_path = ag_catalog, \"\$user\", public; SELECT create_graph('regen_graph');"

  # Bootstrap predicates
  echo "Bootstrapping predicates for $DB_NAME..."
  cat /root/koi-processor/migrations/038_bkc_predicates.sql | $PSQL -d "$DB_NAME"

  echo "$DB_NAME ready."
}

# Accept DB names as arguments, or default set
DBS="${@:-gv_koi cascadia_koi}"
for DB in $DBS; do
  create_koi_db "$DB"
done

echo "All databases created."
