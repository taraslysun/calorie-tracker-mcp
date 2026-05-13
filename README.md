# calorie-integration

MCP server that bridges [tablycjakalorijnosti.com.ua](https://www.tablycjakalorijnosti.com.ua)
(a Ukrainian calorie-tracking site with no public API) to LLM clients via
the [Model Context Protocol](https://modelcontextprotocol.io). Ships with a
stateless OAuth 2.1 Authorization Server so any MCP client (Claude Desktop,
Cursor, VS Code, etc.) can connect without storing a database.

```
┌──────────────┐  OAuth 2.1 + PKCE  ┌─────────────────────┐  cookies / md5(pwd)  ┌─────────────────────────────┐
│ MCP client   │ ─────────────────► │ auth_server (AS)    │ ───────────────────► │ tablycjakalorijnosti.com.ua │
│ (Claude etc) │ ◄───────────────── │ + mcp_server (RS)   │ ◄─────────────────── │ (upstream PHP app)          │
└──────────────┘  Bearer JWT        └─────────┬───────────┘  envelope JSON       └─────────────────────────────┘
                                              │ e5-small 384d cosine
                                              ▼
                                    ┌─────────────────────┐
                                    │ Qdrant Cloud mirror │  ~205k foodstuff rows
                                    │ collection:         │  pre-embedded titles
                                    │   foodstuff_uk      │  + full payload
                                    └─────────────────────┘
```

## What it does

The upstream site has no public REST API. We reverse-engineered its SPA's
internal endpoints (`/user/diary/...`, `/user/foodstuff/add`, etc.) using
Playwright (`recon/`), then wrapped them in a typed Python client
(`tablycja_client/`) and exposed a curated subset as MCP tools
(`mcp_server/tools/`). The OAuth front (`auth_server/`) lets MCP clients
bind once (cookie paste **or** email/password) and get a long-lived bearer
JWT that carries the encrypted upstream session.

### MCP tools exposed

| Tool | Description |
|------|-------------|
| `get_active_user` | Compact account record (id, email, lang). Auth probe. |
| `get_profile` | Full profile: height, weight, target, AMR, energy + macro goals. |
| `get_day` | Diary for a date (6 meal slots, items, totals). |
| `get_summary` | Daily totals + macro breakdown. |
| `semantic_search_food` | **[DEFAULT]** Semantic search over local Qdrant mirror (~205k rows, e5-small 384d cosine). Matches by meaning, cross-lingual (UA/EN). |
| `search_food` | [FALLBACK] Upstream regex autocomplete (foodstuff/activity/meal). Use only for strict substring match. |
| `search_activity` | Activity-only autocomplete. |
| `get_food_detail` | Full nutrient detail + unit options for a foodstuff. |
| `search_food_with_macros` | [FALLBACK] Upstream regex DB search with per-100g macros + energy filter. Prefer `semantic_search_food`. |
| `log_food` | Add a food entry to the diary (grams, meal, day). |
| `log_activity` | Log an activity entry (minutes, day). |
| `log_weight` | Log body weight. |
| `list_my_recipes` | Paginated list of user's saved recipes ("Мої рецепти"). |
| `get_my_recipe` | Full detail for a personal recipe. |
| `log_recipe` | Add personal recipe to diary, with optional ingredient excludes/scaling. |
| `get_diary_entry` | Editable form for an already-logged diary entry. |
| `edit_diary_entry` | Mutate a logged entry: drop ingredients, scale counts, change meal slot. |

Date inputs accept ISO `YYYY-MM-DD` or upstream's `DD.MM.YYYY`. Meal slot
accepts numeric `1`..`6` or names `breakfast`/`snack1`/`lunch`/`snack2`/
`dinner`/`snack3` (and Ukrainian aliases).

## Repo layout

```
auth_server/         FastAPI Authorization Server (stateless, JWT + Fernet)
mcp_server/          FastMCP server + per-tool wrappers
  tools/             one file per MCP tool family
tablycja_client/     async httpx client for the upstream site
  session.py         cookie jar + envelope unwrap + auto-relogin
  client.py          composition façade
  {profile,diary,activity,weight,catalog,meals,models,errors}.py
server.py            combined ASGI app (AS + MCP mounted under /mcp)
recon/               Playwright capture harness for upstream RE
docs/api-map.md      reverse-engineered upstream endpoint map
tests/               pytest suite (httpx.MockTransport, recon-shaped fixtures)
scripts/             utility scripts:
                       build_index.py        paginated drain → embed → Qdrant
                       bucket_ingest.py      bigram-bucket workaround (10k cap)
                       bucket_ingest_notify  ingest + macOS notification wrapper
Dockerfile           Cloud Run-ready multi-stage build
docker-compose.yml   local container build
.mcp.json            sample MCP client config
```

## Module reference

### `auth_server/` — Authorization Server (OAuth 2.1 + PKCE)

Stateless. No database. Every artifact (client_id, auth code, refresh,
access, state) is a signed (HS256) JWT. Upstream cookies + optional creds
are Fernet-encrypted inside the JWT.

| File | Role |
|------|------|
| `app.py` | FastAPI app: `/.well-known/*`, `/register` (DCR), `/authorize`, `/authorize/bind` (cookie), `/authorize/bind/password` (email + md5 pwd), `/oauth/google/callback`, `/token`. |
| `tokens.py` | `pack_*` / `unpack_*` for client_id, state, auth_code, access, refresh. In-memory `TTLSet` for auth-code single-use replay protection. |
| `crypto.py` | HS256 JWT encode/decode, Fernet wrap, PKCE (S256 + plain) verify. |
| `config.py` | `Settings` dataclass loaded from env once per process (`@lru_cache`). |
| `templates.py` | Inline HTML (no Jinja dep) for cookie-paste and password-bind consent pages. |
| `google.py` | Google OAuth helpers (used only when `AS_BIND_MODE=google`). |
| `__main__.py` | `python -m auth_server` standalone runner. |

**Endpoints exposed:**
- `GET /.well-known/oauth-authorization-server` — RFC 8414 metadata
- `GET /.well-known/oauth-protected-resource` — RFC 9728 PRM
- `POST /register` — RFC 7591 dynamic client registration
- `GET /authorize` — OAuth 2.1 + PKCE + RFC 8707 resource indicator
- `POST /authorize/bind` — cookie-mode submit
- `POST /authorize/bind/password` — password-mode submit
- `GET /oauth/google/callback` — Google bind redirect target
- `POST /token` — `authorization_code` + `refresh_token` grants

### `mcp_server/` — MCP server (FastMCP)

| File | Role |
|------|------|
| `server.py` | Builds the `FastMCP` instance and registers every `@mcp.tool()` wrapper. |
| `auth_middleware.py` | ASGI middleware: validates Bearer JWT, decrypts cookies, pushes them onto ContextVars. Returns 401 + `WWW-Authenticate` w/ resource_metadata pointer on failure. |
| `context.py` | `get_client()` resolves to a per-request `TablycjaClient`. Two modes: `dev` (singleton from env) or `oauth` (per-request from middleware-decrypted cookies). |
| `tools/profile.py` | `get_profile`, `get_active_user`. |
| `tools/diary.py` | `get_day`, `get_summary`, `log_food` + meal/date parsing helpers. |
| `tools/catalog.py` | `search_food`, `search_activity`, `get_food_detail`, `search_food_with_macros` (all upstream-regex, fallback path). |
| `tools/semantic.py` | `semantic_search_food` — default food lookup. Embeds query w/ e5-small ("query:" prefix), runs cosine top-k over Qdrant mirror. Returns `{count, items}` (drop-in shape with `search_food_with_macros`). |
| `tools/activity.py` | `log_activity`. |
| `tools/weight.py` | `log_weight`. |
| `tools/recipes.py` | `list_my_recipes`, `get_my_recipe`, `log_recipe`, `get_diary_entry`, `edit_diary_entry`. |
| `__main__.py` | `python -m mcp_server [--transport stdio|streamable-http|sse]`. |

### `tablycja_client/` — async httpx client for the upstream site

Permissive Pydantic models (extra fields ignored), envelope unwrap, typed
errors, transparent re-login on session expiry.

| File | Role |
|------|------|
| `client.py` | `TablycjaClient` façade composing one session + sub-APIs. |
| `session.py` | `TablycjaSession`: cookie jar, default headers, `get_json`/`post_json` w/ envelope unwrap. `login_password` (md5-hashes plaintext like upstream's web client). `_with_relogin` retries once on 3xx if creds were provided. |
| `models.py` | Pydantic models: `ActiveUser`, `Profile`, `DiaryDay`, `DaySummary`, `FoodAddForm`, `ActivityAddForm`, `SearchHit`, etc. `fmt_date()` helper. |
| `errors.py` | `TablycjaError` base, `AuthRequiredError`, `UpstreamError` (carries `code` + `status`). |
| `profile.py` | `active_user`, `get` (full profile). |
| `diary.py` | `get_day`, `get_summary`, `get_food_add_form`, `add_food`, `quick_add_food`. |
| `activity.py` | `get_add_form`, `add`, `quick_add`. |
| `weight.py` | `add` (POST `/user/weight/add`). |
| `catalog.py` | `autocomplete`, `autocomplete_activity`, `filter_foodstuff`, `food_detail`. |
| `embeddings.py` | Lazy singleton e5-small (intfloat/multilingual-e5-small, 384d, 100 langs via xlm-roberta backbone). Auto-picks MPS / CUDA / CPU. `embed(texts)` returns L2-normalized vectors ready for cosine. |
| `cache.py` | Async Qdrant wrapper. `ensure_collection`, `upsert_rows`, `existing_ids` (resumable ingest), `semantic_search` (top-k + optional energy range filter). Upstream GUIDs (32-hex) → UUID-format Qdrant point IDs. |
| `meals.py` | Personal recipes: `list`, `detail`, `get_add_form`, `add_to_diary`, `quick_add_to_diary`, `get_diary_entry_form`, `save_diary_entry`, `edit_diary_entry`. |

### `recon/` — reverse-engineering harness

`web_capture.py` runs a persistent-profile Chromium and logs all XHR/fetch
to `captures/web-<ts>.har` + `.jsonl`. Sensitive headers redacted in JSONL.
Used to populate `docs/api-map.md`. Captures are gitignored.

### `tests/`

Pytest with `httpx.MockTransport` and recon-shaped fixtures (`conftest.py`).
Covers: session envelope/relogin, every tablycja sub-API, every MCP tool,
auth middleware, AS endpoints (incl. password bind), DCR, /token grants.

```bash
uv run pytest -q
```

## Semantic search (default food lookup)

`semantic_search_food` is the **default** food-lookup tool. It queries a
local Qdrant mirror of the upstream foodstuff catalog instead of hitting
the upstream regex endpoint. The old `search_food` /
`search_food_with_macros` tools remain as substring-match fallbacks.

### Why

- Upstream `/foodstuff/filter-list` does plain regex on Cyrillic titles —
  no synonym/intent handling, no English queries, no fuzzy match.
- Every call is a round-trip (~150 ms + 302 relogin risk).
- Mirror lets us run cosine top-k locally: sub-50 ms warm, no upstream
  dependency, and the embedding model speaks Ukrainian, English, and a
  handful of others (e5-small covers 100 langs via xlm-roberta backbone).

### Architecture

```
[scripts/bucket_ingest.py]                      [mcp_server/tools/semantic.py]
        │                                                   │
        │ drain upstream catalog (~206k rows)               │ semantic_search_food(query)
        │ workaround 10k offset cap via                     │   1. embed query (e5-small + "query:" prefix)
        │   bigram bucket scan over UA+LAT alphabet         │   2. Qdrant query_points top-k
        │ embed titles → e5-small (384d cosine, "passage:" prefix)              │   3. return payload rows
        │ upsert into Qdrant Cloud collection foodstuff_uk  │      ({count, items} envelope)
```

| Layer | Choice |
|-------|--------|
| Vector store | Qdrant Cloud free tier (1 GB cluster — fits 206k × 1024d) |
| Embedding model | intfloat/multilingual-e5-small (118M params, 384d, 100 langs, cosine, asymmetric `query:`/`passage:` prefixes) |
| Inference | `sentence-transformers` + `torch`; auto-picks MPS / CUDA / CPU |
| Ingest | Local script, resumable via `scripts/.bucket_state.json` |
| Search surface | New MCP tool `semantic_search_food`; payload-compatible with `search_food_with_macros` |

### Ingest (one-shot)

```bash
uv sync --group ingest
# Pre-condition: QDRANT_URL, QDRANT_API_KEY, TABLYCJA_EMAIL, TABLYCJA_PASSWORD in .env
uv run --group ingest python scripts/bucket_ingest.py \
    --page-limit 200 --embed-batch 32 --bucket-concurrency 1
```

The bigram bucket scan iterates 3550 query strings (singles + bigrams of
UA+LAT chars) because upstream caps each filter at ~10k unique rows.
Coverage achieved on a typical run: 99.7% (~205k of 206k). Re-running
picks up where it left off via the state file.

### Cloud Run notes

- Container memory: **1 Gi** (e5-small ≈ 600 MB RAM + headroom).
- `QDRANT_URL` + `QDRANT_API_KEY` injected from Secret Manager.
- e5-small weights baked into the image (`Dockerfile` runs
  `SentenceTransformer('intfloat/multilingual-e5-small')` at build time
  → cache copied to runtime stage). Avoids cold-start download.
- Image size ~1.5 GB. First query in a fresh container embeds in ~1-2 s
  (model warm-up); warm queries ~70-130 ms on 2 vCPU.

## Installation

### Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (`brew install uv` or
  `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- For `recon/` only: `uv run playwright install chromium` and Chrome installed
  for the persistent profile to use as `channel="chrome"`

### Setup

```bash
git clone <this-repo>
cd calorie-integration
uv sync
```

For the recon harness:

```bash
uv sync --group recon --group dev
uv run playwright install chromium
```

### Configure

Generate a fresh Fernet key and pick a long random JWT secret:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
openssl rand -hex 32
```

Create `.env` (gitignored). A working dev template:

```dotenv
# Public URLs (no trailing slash). Match what your MCP client will hit.
AS_ISSUER=http://127.0.0.1:3000
MCP_RESOURCE=http://127.0.0.1:3000/mcp

# Secrets — rotate in prod.
AS_JWT_SECRET=<openssl rand -hex 32>
AS_FERNET_KEY=<Fernet.generate_key()>

# Bind mode: "cookie" (paste header), "password" (email + pwd, auto-relogin),
#            or "google" (Google OAuth — also requires GOOGLE_CLIENT_*).
AS_BIND_MODE=password

# MCP transport auth: "oauth" requires Bearer JWT; "dev" reads TABLYCJA_COOKIES.
MCP_AUTH_MODE=oauth

# Only for AS_BIND_MODE=google.
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...

# Semantic search mirror (Qdrant Cloud). Required for semantic_search_food.
QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io:6333
QDRANT_API_KEY=...
QDRANT_COLLECTION=foodstuff_uk
EMBED_MODEL=intfloat/multilingual-e5-small

# Required for ingest scripts only (NOT for serving).
# TABLYCJA_EMAIL=...
# TABLYCJA_PASSWORD=...
```

For a **dev shortcut** that skips OAuth entirely, set `MCP_AUTH_MODE=dev`
plus `TABLYCJA_COOKIES` to a JSON object holding the upstream cookie jar
(grab from DevTools → Application → Cookies):

```dotenv
MCP_AUTH_MODE=dev
TABLYCJA_COOKIES={"JSESSIONID":"...","kaloricketabulky_token":"..."}
```

## Running

### Combined AS + MCP (recommended)

```bash
uv run python server.py --host 127.0.0.1 --port 3000
```

Routes:

- `/.well-known/oauth-authorization-server` — AS metadata
- `/.well-known/oauth-protected-resource` — PRM (also under `/mcp/`)
- `/authorize`, `/authorize/bind[/password]`, `/oauth/google/callback`, `/register`, `/token` — AS
- `/mcp` (and `/mcp/`) — MCP streamable HTTP (Bearer JWT required unless
  `MCP_AUTH_MODE=dev`)

### Components separately

```bash
uv run python -m auth_server  --host 127.0.0.1 --port 3000
uv run python -m mcp_server   --transport streamable-http --port 3001
uv run python -m mcp_server   --transport stdio                    # for stdio MCP clients
```

### Docker

```bash
AS_JWT_SECRET=$(openssl rand -hex 32) \
AS_FERNET_KEY=$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())') \
docker compose up --build
```

Container exposes `:3000` mapped to internal `:8080` (Cloud Run convention).

### Cloud Run (sketch)

The `Dockerfile` is multi-stage and Cloud Run-ready. Set `AS_ISSUER` /
`MCP_RESOURCE` to the public Cloud Run URL and inject `AS_JWT_SECRET` /
`AS_FERNET_KEY` via Secret Manager. `scripts/test_active_user.sh` shows a
local probe that mints a JWT against cloud secrets and round-trips a
`tools/call`.

## Connecting an MCP client

Add the resource URL to the client. Sample `.mcp.json`:

```json
{
  "mcpServers": {
    "tablycja": {
      "type": "http",
      "url": "https://your-host.example/mcp"
    }
  }
}
```

The first call triggers the OAuth flow: client hits `/.well-known/...` →
`/register` → `/authorize` → user lands on the consent page (cookie or
password) → redirect back with `code` → `/token` → Bearer JWT. The JWT
embeds the encrypted upstream session, so all subsequent MCP calls just
hit `/mcp` with the same bearer.

If `AS_BIND_MODE=password`, the JWT also embeds Fernet-encrypted
email+password so the server transparently re-logs into upstream when
`JSESSIONID` expires (no need to re-bind in the client).

## Auth modes summary

| `AS_BIND_MODE` | What user provides | UX | Notes |
|----------------|-------------------|-----|-------|
| `cookie` | Pasted `Cookie:` header from DevTools | Dev-only | No re-login on session expiry — re-bind required. |
| `password` | Email + password | Smoothest | md5-hashed before sending (matches upstream's web client). Plaintext stored encrypted in JWT. |
| `google` | Google OAuth | Smoothest if upstream accepts our `aud` | Upstream often pins audience to its own Google client and rejects ours; cookie/password is more reliable. |

| `MCP_AUTH_MODE` | Who can call `/mcp` | Use when |
|-----------------|---------------------|----------|
| `oauth` (default in prod) | Anyone with valid Bearer JWT issued by AS | Production / shared deployment |
| `dev` | Anyone reaching the port | Local dev with `TABLYCJA_COOKIES` set |

## Security notes

- `AS_JWT_SECRET` rotation invalidates every outstanding token (no `kid` /
  JWKS rotation).
- In `password` mode, cleartext email + password live inside the bearer
  JWT, Fernet-encrypted with `AS_FERNET_KEY`. Anyone with both the JWT and
  `AS_FERNET_KEY` can recover them. Treat both as equally sensitive.
- Auth-code replay protection is in-memory (`TTLSet`, 60s); behind multiple
  Cloud Run instances the window becomes per-instance. Codes are still
  single-use within an instance and PKCE-bound.
- Recon HAR/JSONL captures contain live cookies — gitignored, never commit.
- Upstream password hashing is md5 (their choice, not ours). The plaintext
  is never sent over the wire.

## Development

```bash
uv run pytest -q                                            # 63 tests, runs in <1s
uv run ruff check .                                         # if you have ruff configured
uv run basedpyright auth_server mcp_server tablycja_client  # type check
```

Recon a new endpoint:

1. `uv run python recon/web_capture.py`
2. Drive the SPA through the new flow.
3. Ctrl-C, inspect `recon/captures/web-<ts>.jsonl`.
4. Add the route to `docs/api-map.md`.
5. Wrap it in `tablycja_client/`, expose via `mcp_server/tools/`, write a
   test against `httpx.MockTransport`.

## License

Personal project. Upstream service is not affiliated with this client.
