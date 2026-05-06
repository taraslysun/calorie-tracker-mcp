# Recon

Reverse-engineering harness for tablycjakalorijnosti.com.ua. Output feeds `docs/api-map.md`.

## Setup (uv)

```bash
uv sync --group recon --group dev
uv run playwright install chromium
```

## Web SPA capture (primary)

```bash
uv run python recon/web_capture.py
```

Drive UI through every flow we plan to expose as MCP tools:
- Login (Google OAuth)
- View profile + edit
- Search food, view food details
- Add food to diary (each meal type)
- Delete diary entry
- Add activity
- Log weight
- View daily summary

Ctrl+C → writes `captures/web-<ts>.har` + `captures/web-<ts>.jsonl`.

## Android app capture (fallback / verification)

If web traffic ambiguous, capture native app traffic:
1. `uv sync --group recon` (installs mitmproxy).
2. `uv run mitmweb -w recon/captures/android-<ts>.flow`.
3. Real Android device, point Wi-Fi proxy at host:8080.
4. Install mitm CA via `http://mitm.it`. Android 7+ pinned apps need `apk-mitm` first.
5. Use app, save flow.
6. Convert: `uv run mitmdump -nr recon/captures/android-*.flow -s recon/dump_flows.py`.

## After capture

1. Skim `jsonl` for unique `(method, url-without-query)` pairs.
2. Fill `docs/api-map.md` rows.
3. Note auth header / cookie shape under "Auth / Session".
4. **Never commit captures with live cookies/tokens.** `.gitignore` excludes them.
