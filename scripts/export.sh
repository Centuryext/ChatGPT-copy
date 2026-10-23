#!/usr/bin/env bash
# Dump the four dataset tables to ./exports as CSV. Run from the stock-roundtable folder.
set -euo pipefail
cd "$(dirname "$0")/.."
TOKEN=$(grep '^ROUNDTABLE_TOKEN=' .env | cut -d= -f2-)
BASE="${ROUNDTABLE_URL:-http://127.0.0.1:8787}"
mkdir -p exports
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
for t in tickets fills messages snapshots; do
  curl -sf -H "Authorization: Bearer ${TOKEN}" "${BASE}/api/export/${t}.csv" -o "exports/${t}_${STAMP}.csv"
  echo "exports/${t}_${STAMP}.csv"
done
