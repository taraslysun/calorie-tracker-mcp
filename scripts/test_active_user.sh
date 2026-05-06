#!/usr/bin/env bash
# Test MCP /tools/call get_active_user without going through Claude.
# Mints a bearer JWT locally using cloud secrets + your email/password,
# initializes an MCP session, calls get_active_user, prints result.
#
# Usage:
#   EMAIL=you@example.com PASSWORD='your-pwd' ./scripts/test_active_user.sh
#
# Requires: gcloud auth + jq + uv project root.
set -euo pipefail

: "${EMAIL:?set EMAIL}"
: "${PASSWORD:?set PASSWORD}"
URL=${URL:-https://tablycja-mcp-523891264975.europe-west1.run.app}
PROJECT=${PROJECT:-tablycja-mcp-prod}

JWT_SECRET=$(gcloud secrets versions access latest --secret=as-jwt-secret --project="$PROJECT")
FERNET_KEY=$(gcloud secrets versions access latest --secret=as-fernet-key --project="$PROJECT")

# Mint access token. Cookies left empty — server will auto-relogin via creds
# on the first 302.
TOKEN=$(JWT_SECRET="$JWT_SECRET" FERNET_KEY="$FERNET_KEY" \
        EMAIL="$EMAIL" PASSWORD="$PASSWORD" URL="$URL" uv run python -c '
import os
from auth_server.tokens import pack_access
print(pack_access(
    jwt_secret=os.environ["JWT_SECRET"],
    fernet_key=os.environ["FERNET_KEY"],
    issuer=os.environ["URL"],
    sub="curl-tester",
    aud=os.environ["URL"] + "/mcp",
    scope="mcp:tools",
    client_id="curl",
    cookies={"JSESSIONID": "stale"},   # forces auto-relogin
    creds={"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]},
    ttl_s=600,
))')

INIT=$(curl -sS -i -X POST "$URL/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}')

SID=$(printf '%s' "$INIT" | grep -i '^mcp-session-id:' | awk -F': ' '{print $2}' | tr -d '\r\n')
[[ -n "$SID" ]] || { echo "no mcp-session-id; init failed:"; printf '%s\n' "$INIT"; exit 1; }

curl -sS -X POST "$URL/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

curl -sS -X POST "$URL/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_active_user","arguments":{}}}'
