#!/usr/bin/env python3
"""
get_token.py — one-time Yahoo login WITHOUT the finicky localhost callback server.

Why this exists: `yahoofantasy login` spins up a local HTTPS server to catch Yahoo's
redirect, and on Windows the browser often can't reach it (self-signed localhost cert),
so it never captures your code. This script does the exact same OAuth handshake, but
lets you paste the code in by hand — no local server needed.

Run it from inside the gridiron folder:

    python get_token.py

It prints a URL. Open it, click Agree, and when the browser lands on a
"this site can't be reached" localhost page, copy the WHOLE address out of the
address bar and paste it back here. Your token gets saved where fetch_league.py
looks for it, so the normal fetch command then just works.
"""
import os
import sys
from time import time
from urllib.parse import urlencode, urlparse, parse_qs

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  python -m pip install -r requirements.txt")

try:
    from yahoofantasy.util.persistence import save, get_persistence_filename
except ImportError:
    sys.exit("yahoofantasy isn't installed. Run:  python -m pip install -r requirements.txt")

OAUTH = "https://api.login.yahoo.com/oauth2"

cid = (os.environ.get("YAHOO_CLIENT_ID") or input("Paste your Client ID: ")).strip()
csec = (os.environ.get("YAHOO_CLIENT_SECRET") or input("Paste your Client Secret: ")).strip()
if not cid or not csec:
    sys.exit("Client ID and Client Secret are both required.")

auth_url = OAUTH + "/request_auth?" + urlencode({
    "client_id": cid,
    "redirect_uri": "https://localhost:8000",
    "response_type": "code",
    # Yahoo's app form no longer offers a "Fantasy Sports" permission checkbox, so we
    # request the fantasy read scope explicitly here. Without this the token is valid
    # but every fantasy endpoint returns 401 Unauthorized.
    "scope": "fspt-r",
})

print("\n" + "=" * 72)
print("STEP 1 — open this URL in your browser and click Agree:\n")
print(auth_url)
print("\nSTEP 2 — the browser will land on a 'this site can't be reached'")
print("localhost page. THAT IS EXPECTED. Copy the FULL web address from the")
print("address bar (it contains ?code=...).")
print("=" * 72)
pasted = input("\nPaste that address (or just the code) here: ").strip()

code = pasted
if "code=" in pasted:
    qs = parse_qs(urlparse(pasted).query)
    code = (qs.get("code") or [pasted])[0]
code = code.strip()
if not code:
    sys.exit("Couldn't find an authorization code in what you pasted. Re-run and try again.")

body = {}
tokens = None
for ruri in ("https://localhost:8000", "oob"):
    resp = requests.post(OAUTH + "/get_token", data={
        "client_id": cid,
        "client_secret": csec,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": ruri,
    })
    try:
        body = resp.json()
    except Exception:
        body = {"error": resp.text}
    if body.get("refresh_token"):
        tokens = body
        break

if not tokens:
    err_txt = str(body).upper()
    print("\nToken exchange failed. Yahoo said:\n", body)
    if "INVALID_CONSUMER_KEY" in err_txt or "CLIENT ID" in err_txt:
        print("\n>>> Yahoo doesn't recognize this Client ID.")
        print(">>> On your app page (developer.yahoo.com/apps), use the")
        print(">>> 'Client ID (Consumer Key)' — the LONG string that starts with 'dj0y...'.")
        print(">>> Do NOT use the short 'App ID' at the top of the page.")
        print(">>> (If you JUST created the app, give it a minute and try again.)")
    else:
        print("\nMost common cause: the code is single-use and expires fast, so it was")
        print("already used or went stale. Just re-run this script for a fresh code.")
    sys.exit(1)

save("auth", {
    "client_id": cid,
    "client_secret": csec,
    "access_token": tokens["access_token"],
    "access_token_expires": time() + tokens.get("expires_in", 3600),
    "refresh_token": tokens["refresh_token"],
}, overwrite=True)

print("\nSuccess — token saved to " + get_persistence_filename(""))
print("\nRefresh Token (keep this for the weekly auto-refresh Action):\n")
print(tokens["refresh_token"])
print("\nNow pull your league (use your REAL numeric league id):")
print("    python scripts\\fetch_league.py --season 2026 --league 123456")
print("Tip: leave off --league to have it list your leagues so you can pick.")
