#!/usr/bin/env bash
# One-shot install on aiserver. Run from the stock-roundtable folder:  bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null; then echo "docker is required"; exit 1; fi

if [ ! -f .env ]; then
  cp .env.example .env
  TOKEN=$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(24))')
  PGPW=$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')
  sed -i "s|^ROUNDTABLE_TOKEN=.*|ROUNDTABLE_TOKEN=${TOKEN}|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PGPW}|" .env
  echo "Wrote .env with a fresh token and database password."
fi

PROFILE=""
if [ "${1:-}" = "--critic" ]; then PROFILE="--profile critic"; fi

docker compose $PROFILE up -d --build

TOKEN=$(grep '^ROUNDTABLE_TOKEN=' .env | cut -d= -f2-)
PUB=$(grep '^ROUNDTABLE_PUBLIC_URL=' .env | cut -d= -f2-)
BASE=$(grep '^ROUNDTABLE_BASE_PATH=' .env | cut -d= -f2-)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "Stock Roundtable is up."
echo "  Board (LAN):   http://${IP}:8787/?token=${TOKEN}"
echo "  Board (public, after the funnel step): ${PUB}${BASE}/?token=${TOKEN}"
echo
echo "  MCP URL for claude.ai and ChatGPT connectors:"
echo "    ${PUB}${BASE}/key/${TOKEN}/mcp"
echo
echo "Expose it on your existing Tailscale Funnel under the ${BASE:-/} path:"
echo "    sudo tailscale funnel --bg --set-path ${BASE:-/} http://127.0.0.1:8787${BASE}"
echo "Check with:  tailscale funnel status"
