"""Inline HTML templates for the AS consent pages. Tiny, no Jinja dep."""
from __future__ import annotations

from html import escape


CSS = """
body { font: 14px/1.5 -apple-system, system-ui, sans-serif; max-width: 480px;
       margin: 60px auto; padding: 0 20px; color: #222; }
h1 { font-size: 20px; margin: 0 0 8px; }
p.muted { color: #666; }
input[type=text], input[type=password], textarea { width: 100%; padding: 10px;
       border: 1px solid #ccc; border-radius: 6px; font: inherit;
       box-sizing: border-box; }
button { background: #1a73e8; color: #fff; border: 0; padding: 10px 18px;
         border-radius: 6px; font: inherit; cursor: pointer; }
button:hover { background: #185ec0; }
.row { margin: 12px 0; }
label { display: block; font-weight: 600; margin-bottom: 4px; }
code { background: #f3f3f3; padding: 1px 5px; border-radius: 3px; }
.warn { background: #fff7e0; border: 1px solid #ecc94b; padding: 10px;
        border-radius: 6px; }
"""


def consent_cookie_page(
    *, state: str, client_name: str, scope: str, resource: str | None
) -> str:
    cn = escape(client_name or "an MCP client")
    sc = escape(scope)
    rs = escape(resource or "")
    return f"""<!doctype html><meta charset=utf-8><title>Authorize MCP</title>
<style>{CSS}</style>
<h1>Connect {cn}</h1>
<p class=muted>This MCP client is requesting access to your
<b>tablycjakalorijnosti.com.ua</b> account.</p>
<p>Scopes: <code>{sc}</code>{f' · Resource: <code>{rs}</code>' if rs else ''}</p>

<div class=warn>
<b>Dev bind mode.</b> Open <a href="https://www.tablycjakalorijnosti.com.ua"
target=_blank>tablycjakalorijnosti.com.ua</a> while logged in,
DevTools (F12) → Network → click any request → Request Headers →
copy the entire <code>cookie:</code> value and paste below. Required cookies:
<code>JSESSIONID</code>, <code>kaloricketabulky_token</code>.
</div>

<form method=POST action="/authorize/bind">
  <input type=hidden name=state value="{escape(state)}">
  <div class=row>
    <label>Cookie header</label>
    <textarea name=cookie_header rows=5 required autocomplete=off
      placeholder="JSESSIONID=...; kaloricketabulky_token=...; ..."></textarea>
  </div>
  <div class=row>
    <label>Email (optional, for record)</label>
    <input type=text name=email autocomplete=off>
  </div>
  <div class=row><button type=submit>Authorize</button></div>
</form>
"""


def consent_password_page(
    *, state: str, client_name: str, scope: str, resource: str | None
) -> str:
    cn = escape(client_name or "an MCP client")
    sc = escape(scope)
    rs = escape(resource or "")
    return f"""<!doctype html><meta charset=utf-8><title>Authorize MCP</title>
<style>{CSS}</style>
<h1>Connect {cn}</h1>
<p class=muted>This MCP client is requesting access to your
<b>tablycjakalorijnosti.com.ua</b> account.</p>
<p>Scopes: <code>{sc}</code>{f' · Resource: <code>{rs}</code>' if rs else ''}</p>

<div class=warn>
<b>Sign in once</b>. Your email + password are encrypted (Fernet) and stored
inside the bearer token only — they let the server refresh the upstream
session automatically when it expires, so you never have to re-authorize.
Revoke any time by changing your password on the website.
</div>

<form method=POST action="/authorize/bind/password">
  <input type=hidden name=state value="{escape(state)}">
  <div class=row>
    <label>Email</label>
    <input type=text name=email required autocomplete=email>
  </div>
  <div class=row>
    <label>Password</label>
    <input type=password name=password required autocomplete=current-password>
  </div>
  <div class=row><button type=submit>Sign in & authorize</button></div>
</form>
"""


def error_page(msg: str, status: int = 400) -> tuple[str, int]:
    return f"""<!doctype html><meta charset=utf-8><title>Error</title>
<style>{CSS}</style><h1>Authorization error</h1>
<p>{escape(msg)}</p>""", status
