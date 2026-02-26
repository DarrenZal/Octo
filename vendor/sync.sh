#!/bin/bash
set -euo pipefail

# Configuration - update this to the canonical repo location
CANONICAL_REPO="${CANONICAL_REPO:-/Users/darrenzal/projects/RegenAI/koi-processor}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIN=$(cat "$SCRIPT_DIR/pin.txt")
VENDOR_DIR="$SCRIPT_DIR/koi-processor"

echo "Syncing koi-processor at commit $PIN"
echo "Source: $CANONICAL_REPO"

# Verify the commit exists
cd "$CANONICAL_REPO"
if ! git cat-file -e "$PIN" 2>/dev/null; then
    echo "ERROR: Commit $PIN not found in $CANONICAL_REPO"
    exit 1
fi

# Create vendor directory if needed
mkdir -p "$VENDOR_DIR"

# Use git archive to extract at pinned commit, then rsync
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

git archive "$PIN" | tar -x -C "$TMPDIR"

# Sync only the relevant directories
rsync -a --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='venv/' \
    --exclude='.env' \
    "$TMPDIR/" "$VENDOR_DIR/"

echo "Vendored koi-processor at $PIN"
echo "Files synced to $VENDOR_DIR"
