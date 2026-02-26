#!/bin/bash
set -euo pipefail

# KOI Runtime Deployment Script
# Usage: ./deploy.sh [--target fr|gv|cv|octo|all] [--dry-run] [--skip-sync] [--allow-missing-migrations]

TARGET="all"
DRY_RUN=false
SKIP_SYNC=false
ALLOW_MISSING=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --target) TARGET="$2"; shift 2;;
        --dry-run) DRY_RUN=true; shift;;
        --skip-sync) SKIP_SYNC=true; shift;;
        --allow-missing-migrations) ALLOW_MISSING=true; shift;;
        *) echo "Unknown option: $1"; exit 1;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENDOR_KOI="$SCRIPT_DIR/vendor/koi-processor"

# Server configuration
OCTO_HOST="root@45.132.245.30"
OCTO_PATH="/root/koi-processor"
OCTO_SERVICE="koi-api"
OCTO_DB="octo_koi"

FR_HOST="root@45.132.245.30"
FR_PATH="/root/fr-koi-processor"  # Separate path from Octo to avoid backup collision
FR_SERVICE="fr-koi-api"
FR_DB="fr_koi"

GV_HOST="root@37.27.48.12"
GV_PATH="/home/koi/koi-processor"
GV_SERVICE="gv-koi-api"
GV_DB="gv_koi"

CV_HOST="root@202.61.242.194"
CV_PATH="/root/Octo/koi-processor"
CV_SERVICE="cv-koi-api"
CV_DB="cv_koi"

# Step 1: Vendor sync
if [ "$SKIP_SYNC" = false ]; then
    echo "=== Step 1: Vendor Sync ==="
    bash "$SCRIPT_DIR/vendor/sync.sh"
fi

if [ ! -d "$VENDOR_KOI" ]; then
    echo "ERROR: Vendored koi-processor not found at $VENDOR_KOI"
    echo "Run vendor/sync.sh first or remove --skip-sync"
    exit 1
fi

deploy_node() {
    local name=$1 host=$2 path=$3 service=$4 db=$5

    echo ""
    echo "=== Deploying to $name ==="

    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would rsync $VENDOR_KOI/api/ to $host:$path/api/"
        echo "[DRY RUN] Would rsync $VENDOR_KOI/migrations/ to $host:$path/migrations/"
        echo "[DRY RUN] Would run pending migrations on $db"
        echo "[DRY RUN] Would restart $service"
        echo "[DRY RUN] Would verify health"
        return 0
    fi

    # Backup current version
    echo "Backing up current version..."
    ssh "$host" "cp -r $path ${path}.bak" 2>/dev/null || true

    # Sync code
    echo "Syncing code..."
    rsync -avz --delete \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='venv/' \
        --exclude='.env' \
        --exclude='config/' \
        "$VENDOR_KOI/api/" "$host:$path/api/"
    rsync -avz "$VENDOR_KOI/migrations/" "$host:$path/migrations/"

    # Fix permissions for GV (runs as koi user)
    if [ "$name" = "gv" ]; then
        ssh "$host" "chown -R koi:koi $path"
    fi

    # Run pending migrations (manifest-driven).
    # The baseline manifest defines exactly which migrations belong to this DB,
    # with their canonical migration_id and expected checksum.
    echo "Running pending migrations for $db..."
    local pg_container="regen-koi-postgres"
    if [ "$name" = "gv" ]; then
        pg_container="gv-koi-postgres"
    fi
    local migration_dir="$path/migrations"
    local manifest="$path/migrations/baselines/${db}.json"

    # Build a migration plan from the manifest on the remote host.
    # For each entry: check if already applied, apply if not, record with correct ID.
    ssh "$host" "
        # Ensure koi_migrations registry table exists before any lookups.
        # Idempotent — safe to run on nodes that already have the table.
        docker exec $pg_container psql -U postgres -d $db -c \"
            CREATE TABLE IF NOT EXISTS koi_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW(),
                checksum TEXT NOT NULL
            )\" || {
            echo '  ERROR: Could not ensure koi_migrations table exists'
            exit 1
        }

        if [ ! -f '$manifest' ]; then
            if [ '$ALLOW_MISSING' = 'true' ]; then
                echo '  WARNING: No manifest at $manifest — skipping migrations (--allow-missing-migrations)'
                exit 0
            else
                echo '  ERROR: No manifest at $manifest'
                echo '  Manifests are required for safe migration. Use --allow-missing-migrations to override.'
                exit 1
            fi
        fi

        migration_failed=0

        # Parse manifest entries: id|file|checksum|note (one per line)
        entries=\$(python3 -c \"
import json, sys
with open('$manifest') as f:
    m = json.load(f)
for e in m['migrations']:
    note = e.get('note', '')
    print(e['id'] + '|' + e['file'] + '|' + e['checksum'] + '|' + note)
\")

        while IFS='|' read -r mid mfile expected_checksum mnote; do
            [ -n \"\$mid\" ] || continue

            # Check if already applied by exact migration_id
            applied=\$(docker exec $pg_container psql -U postgres -d $db -tAc \
                \"SELECT 1 FROM koi_migrations WHERE migration_id = '\$mid' LIMIT 1\" 2>/dev/null || echo '')
            if [ -n \"\$applied\" ]; then
                continue
            fi

            # Locate migration file
            fpath=\"$migration_dir/\$mfile\"
            if [ ! -f \"\$fpath\" ]; then
                # Entries with 'sourced from' note are expected to be missing locally
                if echo \"\$mnote\" | grep -q 'sourced from'; then
                    echo \"  SKIP \$mid — not local (\$mnote)\"
                    continue
                fi
                if [ '$ALLOW_MISSING' = 'true' ]; then
                    echo \"  WARNING: \$mid — file \$mfile not found (--allow-missing-migrations)\"
                    continue
                else
                    echo \"  ERROR: \$mid — file \$mfile not found in $migration_dir\"
                    echo \"  All manifest migrations must be present. Use --allow-missing-migrations to override.\"
                    migration_failed=1
                    break
                fi
            fi

            # Verify checksum before applying
            actual_checksum=\$(sha256sum \"\$fpath\" | cut -d' ' -f1)
            if [ \"\$actual_checksum\" != \"\$expected_checksum\" ]; then
                echo \"  ERROR: Checksum mismatch for \$mid\"
                echo \"    expected: \$expected_checksum\"
                echo \"    actual:   \$actual_checksum\"
                migration_failed=1
                break
            fi

            echo \"  Applying \$mid (\$mfile)...\"
            if ! docker exec -i $pg_container psql -U postgres -d $db -v ON_ERROR_STOP=1 < \"\$fpath\" 2>&1; then
                echo \"  ERROR: Migration \$mid FAILED\"
                migration_failed=1
                break
            fi

            # Record with the manifest's canonical migration_id
            if docker exec $pg_container psql -U postgres -d $db -c \
                \"INSERT INTO koi_migrations (migration_id, checksum) VALUES ('\$mid', '\$actual_checksum') ON CONFLICT (migration_id) DO UPDATE SET checksum = EXCLUDED.checksum, applied_at = NOW()\"; then
                echo \"  Recorded \$mid\"
            else
                echo \"  WARNING: Applied \$mid but failed to record in koi_migrations\"
            fi
        done <<< \"\$entries\"

        if [ \"\$migration_failed\" = \"1\" ]; then
            echo \"  Migration failure — aborting deploy for $name\"
            exit 1
        fi
        echo \"  Migrations complete for $db\"
    " || {
        echo "MIGRATION FAILED for $name — rolling back..."
        ssh "$host" "mv $path ${path}.failed && mv ${path}.bak $path && systemctl restart $service"
        echo "Rolled back $name to previous version"
        return 1
    }

    # Restart service
    echo "Restarting $service..."
    ssh "$host" "systemctl restart $service"

    # Wait for startup
    sleep 3

    # Health check — prefer /koi-net/health (fast, no heavy DB introspection),
    # fall back to /health. Use --max-time 10 to avoid hanging on slow endpoints.
    local port
    if [ "$name" = "fr" ]; then
        port=8355
    else
        port=8351
    fi

    echo "Checking health..."
    local health
    health=$(ssh "$host" "curl -sf --max-time 10 http://127.0.0.1:$port/koi-net/health 2>/dev/null || curl -sf --max-time 10 http://127.0.0.1:$port/health 2>/dev/null") || {
        echo "HEALTH CHECK FAILED for $name!"
        echo "Rolling back..."
        ssh "$host" "mv $path ${path}.failed && mv ${path}.bak $path && systemctl restart $service"
        echo "Rolled back $name to previous version"
        return 1
    }

    echo "Health OK: $health"

    # Stamp version
    cat "$SCRIPT_DIR/vendor/pin.txt" | ssh "$host" "cat > $path/.version"
    echo "$name deployed successfully"
}

# Step 2: Deploy to target(s) — order: FR first (lowest risk), then GV, CV, then Octo
case $TARGET in
    fr)   deploy_node "fr" "$FR_HOST" "$FR_PATH" "$FR_SERVICE" "$FR_DB" ;;
    gv)   deploy_node "gv" "$GV_HOST" "$GV_PATH" "$GV_SERVICE" "$GV_DB" ;;
    cv)   deploy_node "cv" "$CV_HOST" "$CV_PATH" "$CV_SERVICE" "$CV_DB" ;;
    octo) deploy_node "octo" "$OCTO_HOST" "$OCTO_PATH" "$OCTO_SERVICE" "$OCTO_DB" ;;
    all)
        deploy_node "fr" "$FR_HOST" "$FR_PATH" "$FR_SERVICE" "$FR_DB" || exit 1
        deploy_node "gv" "$GV_HOST" "$GV_PATH" "$GV_SERVICE" "$GV_DB" || exit 1
        deploy_node "cv" "$CV_HOST" "$CV_PATH" "$CV_SERVICE" "$CV_DB" || exit 1
        deploy_node "octo" "$OCTO_HOST" "$OCTO_PATH" "$OCTO_SERVICE" "$OCTO_DB" || exit 1
        ;;
    *) echo "Unknown target: $TARGET (use fr|gv|cv|octo|all)"; exit 1 ;;
esac

echo ""
echo "=== Deployment complete ==="
