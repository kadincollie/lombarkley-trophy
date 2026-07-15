#!/usr/bin/env python3
"""
fetch_league_web.py — pull your Yahoo league into data/league_data.json
WITHOUT the Yahoo API (no OAuth, no developer app, no approval).

HOW IT WORKS
============
Yahoo commissioners can flip "Make League Publicly Viewable" (Commissioner ->
League Settings). Once the league is publicly viewable, its standings and
scoreboard pages load without a login — so this script just reads those pages.

    python scripts/fetch_league_web.py --league 161092

It writes the same data/league_data.json as the API-based fetch_league.py and
reuses its merge logic, so your money config, Collie Coins, trophy history,
and season_complete flag are preserved on every refresh.

OFFLINE / PRIVATE-LEAGUE MODE
=============================
If you'd rather not make the league public (or scraping breaks), save the pages
from your logged-in browser instead (Ctrl+S -> "Webpage, HTML Only") into one
folder — the league home/standings page and the scoreboard/matchups page — then:

    python scripts/fetch_league_web.py --league 161092 --from-files saved_pages/

Same output, zero network.

DEBUGGING
=========
--dump saves the fetched HTML next to the data folder so parsing problems can
be diagnosed (send those files to whoever maintains this script).
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  python -m pip install requests")

# Reuse the merge logic (and defaults) from the API fetcher so refresh behavior
# is identical: config/champions/coins preserved, live data replaced.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch_league import merge as api_merge  # noqa: E402
    HAVE_MERGE = True
except Exception:
    HAVE_MERGE = False

BASE = "https://football.fantasysports.yahoo.com/f1"
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "league_data.json"))
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}

FLOAT = r"[-+]?\d{1,4}(?:\.\d{1,2})?"


def fetch(url, dump_as=None):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    if dump_as:
        with open(dump_as, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  (dumped {url} -> {dump_as})")
    low = html.lower()
    if "make this league viewable" in low or ("login.yahoo.com" in low and "standings" not in low):
        raise PermissionError(
            "This league page needs a login — the league isn't publicly viewable yet.\n"
            "Commissioner -> League Settings -> 'Make League Publicly Viewable' -> Yes,\n"
            "or use --from-files with pages saved from your logged-in browser.")
    if "there was a problem" in low and "error #" in low:
        raise RuntimeError("Yahoo served an error page (transient). Try again in a minute.")
    if "document you requested was not found" in low:
        raise RuntimeError("Yahoo says that page doesn't exist (common pre-draft).")
    return html


def parse_draft_time(html):
    """Yahoo renders a countdown node with data-seconds-till-date when a live
    draft is scheduled within ~7 days. Convert to an absolute epoch if found."""
    m = re.search(r'data-seconds-till-date="?(\d+)"?', html)
    if m:
        return int(time.time()) + int(m.group(1))
    return None


def strip_tags(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


# --------------------------------------------------------------------------
# Parsing. Yahoo's public pages are server-rendered tables. We parse
# defensively with patterns rather than exact CSS classes so cosmetic changes
# don't break us; --dump exists for when structural changes do.
# --------------------------------------------------------------------------
def parse_standings(html, league_id):
    """Return list of team dicts. Works on both layouts Yahoo uses:
    in-season standings (<tr> table rows) and the pre-draft team list
    (<li> items) — we anchor on team links and read a window after each."""
    teams, seen = [], set()
    link_re = re.compile(
        r'href="(?:https?://[^"]*?)?/f1/%s/(\d{1,2})(?:[?"/])[^>]*>(.*?)</a>' % league_id, re.S | re.I)
    for m in link_re.finditer(html):
        team_num, name = int(m.group(1)), strip_tags(m.group(2))
        if not name or name.lower() in ("view team",) or team_num in seen:
            continue  # skip avatar-only links (empty text) and duplicates
        window = strip_tags(html[m.end():m.end() + 500])
        rec = re.search(r"\b(\d{1,2})-(\d{1,2})(?:-(\d{1,2}))?\b", window)
        w = int(rec.group(1)) if rec else 0
        l = int(rec.group(2)) if rec else 0
        t = int(rec.group(3) or 0) if rec else 0
        floats = [float(x) for x in re.findall(r"\b\d{2,4}(?:\.\d{1,2})?\b", window) if float(x) > 20]
        rank_m = re.search(r"(?:^|\s)(\d{1,2})[.\s]", strip_tags(html[max(0, m.start() - 120):m.start()]))
        streak_m = re.search(r"\b([WL])-?(\d{1,2})\b", window)
        seen.add(team_num)
        teams.append({
            "yahoo_num": team_num, "name": name,
            "wins": w, "losses": l, "ties": t,
            "points_for": round(floats[0], 1) if floats else 0.0,
            "points_against": round(floats[1], 1) if len(floats) > 1 else 0.0,
            "rank": int(rank_m.group(1)) if rank_m else 0,
            "streak": (streak_m.group(1) + streak_m.group(2)) if streak_m else "—",
        })
    # rank-fill when the page doesn't show ranks (pre-draft: keeps page order)
    ranks = [t["rank"] for t in teams]
    if teams and (not any(ranks) or len(set(ranks)) != len(ranks)):
        teams.sort(key=lambda x: (x["wins"], x["points_for"]), reverse=True)
        for i, t in enumerate(teams, 1):
            t["rank"] = i
    return teams


def parse_current_week(html):
    m = re.search(r"week\s*(\d{1,2})", html, re.I)
    return int(m.group(1)) if m else 1


def parse_matchups(html, league_id, name_to_num):
    """Extract this week's matchup pairs with scores/projections from the
    scoreboard page: consecutive team links, each followed by numbers."""
    entries = []  # (team_num, [numbers near it])
    link_iter = re.finditer(
        r'href="(?:https?://[^"]*?)?/f1/%s/(\d{1,2})(?:[?"/])[^>]*>(.*?)</a>' % league_id, html, re.S | re.I)
    positions = [(m.end(), int(m.group(1)), strip_tags(m.group(2))) for m in link_iter]
    for i, (pos, num, name) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(html)
        end = min(nxt, pos + 300)   # scores/projections sit right after the link
        frag = html[pos:end]
        if frag.rfind("<") > frag.rfind(">"):
            frag = frag[:frag.rfind("<")]   # drop tag sliced open by the cap
        window = strip_tags(frag)
        nums = [float(x) for x in re.findall(r"(?<![\w.])" + FLOAT + r"(?![\w.])", window)]
        nums = [n for n in nums if 0 <= n <= 400]
        entries.append((num, name, nums))
    # pair consecutive distinct teams
    pairs, i = [], 0
    while i + 1 < len(entries):
        a, b = entries[i], entries[i + 1]
        if a[0] != b[0]:
            pairs.append((a, b)); i += 2
        else:
            i += 1
    matchups = []
    for (n1, nm1, x1), (n2, nm2, x2) in pairs:
        if max(x1 or [0]) <= 20 and max(x2 or [0]) <= 20:
            continue  # no plausible score/projection — e.g. a pre-draft team list
        s1 = x1[0] if x1 else 0.0
        s2 = x2[0] if x2 else 0.0
        p1 = x1[1] if len(x1) > 1 else s1
        p2 = x2[1] if len(x2) > 1 else s2
        live = (s1 or s2) and (s1 != p1 or s2 != p2)
        matchups.append({"home_num": n1, "away_num": n2,
                         "home_score": round(s1, 1), "away_score": round(s2, 1),
                         "home_proj": round(max(p1, s1), 1), "away_proj": round(max(p2, s2), 1),
                         "status": "live" if live else "pregame"})
    return matchups


# --------------------------------------------------------------------------
def assemble(league_id, standings_html, score_html):
    raw_teams = parse_standings(standings_html, league_id)
    if not raw_teams:
        raise RuntimeError(
            "Couldn't find a standings table on the page. If the season hasn't "
            "started, that's expected — otherwise re-run with --dump and inspect "
            "the saved HTML.")
    current_week = parse_current_week(score_html or standings_html)

    raw_teams.sort(key=lambda t: t["rank"])
    teams, num_to_id = [], {}
    for i, t in enumerate(raw_teams, 1):
        tid = f"t{i}"
        num_to_id[t["yahoo_num"]] = tid
        gp = max(1, t["wins"] + t["losses"] + t["ties"])
        teams.append({
            "id": tid, "name": t["name"],
            # Public pages don't show manager names; use team name so the
            # coin-balance merge still has a stable key.
            "manager": t["name"],
            "wins": t["wins"], "losses": t["losses"], "ties": t["ties"],
            "points_for": t["points_for"], "points_against": t["points_against"],
            "streak": t["streak"], "rank": t["rank"], "moves": 0, "trades": 0,
            "proj_avg": round(t["points_for"] / gp, 1),
        })

    current = []
    if score_html:
        for j, m in enumerate(parse_matchups(score_html, league_id, {}), 1):
            h, a = num_to_id.get(m["home_num"]), num_to_id.get(m["away_num"])
            if not (h and a):
                continue
            avg_h = next(t["proj_avg"] for t in teams if t["id"] == h)
            avg_a = next(t["proj_avg"] for t in teams if t["id"] == a)
            current.append({
                "id": f"w{current_week}m{j}", "week": current_week, "home": h, "away": a,
                "home_proj": max(m["home_proj"], avg_h) or 100.0,
                "away_proj": max(m["away_proj"], avg_a) or 100.0,
                "home_score": m["home_score"], "away_score": m["away_score"],
                "status": m["status"],
            })
    return teams, current, current_week


def naive_merge(existing, teams, current, current_week):
    """Fallback merge if fetch_league.py isn't importable."""
    meta = (existing or {}).get("meta", {})
    coins = (existing or {}).get("coins", {"start_balance": 100, "ledger": [], "open_bets": []})
    champs = (existing or {}).get("champions", [])
    weeks = (existing or {}).get("weeks", [])
    meta.update({"current_week": current_week, "num_teams": len(teams),
                 "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "data_source": "Yahoo Fantasy (web)"})
    return {"meta": meta, "teams": teams, "current_matchups": current,
            "weeks": weeks, "transactions": (existing or {}).get("transactions", []),
            "coins": coins, "champions": champs}


def snapshot_completed_week(existing, teams, current):
    """When a week finishes, fold final scores into weeks[] so weekly high-scorer
    money and bet settlement keep working (the web pages only show the current
    week, so we archive each week as it completes)."""
    if not existing:
        return []
    weeks = existing.get("weeks", [])
    old_cur = existing.get("current_matchups", [])
    if not old_cur:
        return weeks
    old_week = old_cur[0].get("week")
    new_week = current[0]["week"] if current else None
    if new_week and old_week and new_week > old_week:
        # the previously-current week is over; archive its last known scores
        done = [{"home": m["home"], "away": m["away"],
                 "home_score": m.get("home_score", 0), "away_score": m.get("away_score", 0)}
                for m in old_cur if (m.get("home_score") or m.get("away_score"))]
        if done and not any(w["week"] == old_week for w in weeks):
            weeks.append({"week": old_week, "matchups": done})
            weeks.sort(key=lambda w: w["week"])
            print(f"  archived completed week {old_week} ({len(done)} matchups)")
    return weeks


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape a publicly-viewable Yahoo league (no API)")
    ap.add_argument("--league", default=os.environ.get("YAHOO_LEAGUE_ID"),
                    help="Yahoo league id (the number in your league URL). "
                         "Defaults to the YAHOO_LEAGUE_ID env var.")
    ap.add_argument("--from-files", default=None,
                    help="Folder of saved .html pages instead of fetching (offline/private mode)")
    ap.add_argument("--dump", action="store_true", help="Save fetched HTML for debugging")
    args = ap.parse_args()

    if not args.league:
        sys.exit(
            "No Yahoo league id supplied.\n"
            "  In GitHub Actions: Settings -> Secrets and variables -> Actions -> the *Variables* tab\n"
            "    (not Secrets) -> New repository variable -> Name: YAHOO_LEAGUE_ID -> Value: your league number.\n"
            "  Locally:  python scripts/fetch_league_web.py --league 161092")
    lid = re.sub(r"\D", "", str(args.league))
    if args.from_files:
        folder = args.from_files
        htmls = []
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith((".html", ".htm")):
                htmls.append(open(os.path.join(folder, fn), encoding="utf-8", errors="ignore").read())
        if not htmls:
            sys.exit(f"No .html files found in {folder}")
        standings_html = max(htmls, key=lambda h: len(parse_standings(h, lid)))
        score_html = max(htmls, key=lambda h: len(parse_matchups(h, lid, {})))
        print(f"• Using {len(htmls)} saved page(s) from {folder}")
    else:
        dump = (lambda n: os.path.join(os.path.dirname(OUT), n)) if args.dump else (lambda n: None)
        print(f"• Fetching public league pages for {lid} …")
        standings_html = fetch(f"{BASE}/{lid}", dump_as=dump("dump_league.html"))
        time.sleep(1.0)
        try:
            score_html = fetch(f"{BASE}/{lid}/matchups", dump_as=dump("dump_matchups.html"))
        except Exception:
            score_html = standings_html  # matchups often render on the league home page too

    teams, current, current_week = assemble(lid, standings_html, score_html)
    pre_draft = all(t["wins"] + t["losses"] + t["ties"] == 0 for t in teams) and not current
    draft_epoch = parse_draft_time(standings_html) or parse_draft_time(score_html or "")
    print(f"  parsed {len(teams)} teams · {len(current)} current matchups · week {current_week}"
          + (" · PRE-DRAFT" if pre_draft else "")
          + (f" · draft in ~{(draft_epoch-int(time.time()))//3600}h" if draft_epoch else ""))

    existing = None
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT))
            print("• Found existing league_data.json — preserving config, champions & coin balances.")
        except Exception:
            print("• Existing file unreadable — starting fresh.")

    # First pull of REAL data over the bundled sample: drop the sample's fake
    # weeks/matchup history and coin rows so no demo scores leak into real money math.
    if existing and existing.get("meta", {}).get("data_source") == "sample":
        print("• Replacing sample data — clearing demo weeks, transactions, and coin rows"
              " (money config & trophy history kept).")
        existing["weeks"] = []
        existing["transactions"] = []
        existing["current_matchups"] = []
        existing.get("coins", {}).update({"ledger": [], "open_bets": []})

    weeks_archived = snapshot_completed_week(existing, teams, current)
    if existing is not None:
        existing["weeks"] = weeks_archived

    if HAVE_MERGE:
        payload = api_merge(existing, existing.get("meta", {}).get("league_name") if existing else "My League",
                            current_week, 14, 6, teams, current, weeks_archived,
                            (existing or {}).get("transactions", []))
        payload["meta"]["data_source"] = "Yahoo Fantasy (web)"
        payload["meta"]["season"] = (existing or {}).get("meta", {}).get("season") or datetime.date.today().year
    else:
        payload = naive_merge(existing, teams, current, current_week)

    payload["meta"]["pre_draft"] = pre_draft
    if draft_epoch:
        payload["meta"]["draft_time"] = draft_epoch   # auto-detected from Yahoo
    # (a manually-set meta.draft_time survives refreshes via the merge)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, "w"), indent=2)
    print(f"✓ Wrote {OUT}")
    print("  Open index.html to preview, then push so the league sees the update.")

