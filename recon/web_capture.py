"""Web SPA traffic capture harness.

Uses persistent Chrome profile (not bundled Chromium) so Google OAuth doesn't
flag us as "insecure browser". Profile dir: recon/.chrome-profile (gitignored).
First run = sign in once; subsequent runs reuse session.

Run:
    uv sync --group recon --group dev
    uv run playwright install chromium  # only needed for chromium fallback
    uv run python recon/web_capture.py

Drive UI through every flow: profile, food search, add food each meal,
delete entry, add activity, log weight, edit profile. Ctrl+C to stop.
Output: recon/captures/web-<ts>.har + recon/captures/web-<ts>.jsonl.

HAR may contain Set-Cookie / Authorization. JSONL redacts those headers.
Never commit captures.
"""
from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime
from pathlib import Path

from playwright.async_api import Request, Response, async_playwright

ROOT = Path(__file__).parent
CAPTURES = ROOT / "captures"
CAPTURES.mkdir(exist_ok=True)
PROFILE_DIR = ROOT / ".chrome-profile"
PROFILE_DIR.mkdir(exist_ok=True)

START_URL = "https://www.tablycjakalorijnosti.com.ua/"

SENSITIVE_HEADERS = {"cookie", "set-cookie", "authorization", "x-csrf-token"}

STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['uk-UA', 'uk', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || { runtime: {} };
"""


def _redact(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()}


async def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    har_path = CAPTURES / f"web-{stamp}.har"
    jsonl_path = CAPTURES / f"web-{stamp}.jsonl"

    stop = asyncio.Event()

    def _stop(*_):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            locale="uk-UA",
            viewport={"width": 1400, "height": 900},
            record_har_path=str(har_path),
            record_har_content="embed",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
            ],
            ignore_default_args=["--enable-automation"],
        )
        await ctx.add_init_script(STEALTH_INIT)

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        f = jsonl_path.open("w", encoding="utf-8")

        async def on_response(resp: Response):
            try:
                req: Request = resp.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                if req.url.startswith("data:"):
                    return
                try:
                    body_preview = (await resp.text())[:4000]
                except Exception:
                    body_preview = "<binary>"
                try:
                    req_headers = _redact(await req.all_headers())
                except Exception:
                    req_headers = {}
                try:
                    resp_headers = _redact(await resp.all_headers())
                except Exception:
                    resp_headers = {}
                row = {
                    "ts": datetime.now().isoformat(),
                    "method": req.method,
                    "url": req.url,
                    "status": resp.status,
                    "req_headers": req_headers,
                    "req_post_data": req.post_data,
                    "resp_headers": resp_headers,
                    "resp_body_preview": body_preview,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            except Exception:
                # Never let a logging error kill the capture loop.
                pass

        ctx.on("response", lambda r: asyncio.create_task(on_response(r)))

        await page.goto(START_URL)
        print(f"\n[recon] capturing -> {har_path.name} + {jsonl_path.name}")
        print(f"[recon] persistent profile -> {PROFILE_DIR}")
        print("[recon] sign in (Google OAuth should now work). Drive UI.")
        print("[recon] Ctrl+C in this terminal when done.\n")

        await stop.wait()

        f.close()
        await ctx.close()
        print(f"\n[recon] saved {har_path}\n[recon] saved {jsonl_path}")


if __name__ == "__main__":
    asyncio.run(main())
