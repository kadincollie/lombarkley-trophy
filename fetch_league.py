#!/usr/bin/env python3
"""
fetch_league.py — pull your real Yahoo league into data/league_data.json
=========================================================================
Run AFTER the one-time Yahoo login (see README, Step 3).

    python scripts/fetch_league.py --season 2026 --league 12345

- --season : NFL season year (e.g. 2026)
- --league : your Yahoo league_id (from your league URL). Optional — if omitted,
             the script lists your leagues so you can pick one.
- --game   : sport code, defaults to 'nfl'.

MERGE BEHAVIOR (important): if data/league_data.json already exists, this script
PRESERVES your league configuration and betting state across weekly refreshes:
  - meta: league_name, payouts, weekly_bonus, entry_fee, currency_name,
          coin_start, regular_season_weeks, commissioner
  - champions (trophy history)
  - coins.ledger  (matched to people by manager name, so balances follow the
                   right person even if standings reshuffle team order)
  - coins.open_bets
It refreshes the live stuff (teams, standings, matchups, weeks, transactions,
current_week). So: configure the money model once, then just re-run weekly.
"""
import argparse, json, os, sys, datetime

try:
    from yahoofantasy import Context
except ImportError:
    sys.exit("Missing dependency. Run:  pip install -r requirements.txt\n"
             "Then do the one-time login:  yahoofantasy login")

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "league_data.json"))

# Defaults used only on a FIRST run (no existing file to preserve).
DEFAULT_META = {
    "entry_fee": 100,
    "payouts": {"1st": 500, "2nd": 260, "3rd": 100},
    "weekly_bonus": 10,
    "currency_name": "Collie Coins",
    "coin_start": 100,
    "regular_season_weeks": 14,
    "playoff_teams": 6,
    "commissioner": "",
    "season_complete": False,
}
DEFAULT_CHAMPIONS = []   # fill in via the JSON or keep your existing history


# ---------- helpers to survive Yahoo's nested/inconsistent objects -----------
def g(obj, *names, default=None):
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default

def num(x, default=0.0):
    try:
        return round(float(x), 1)
    except (TypeError, ValueError):
        return default

def manager_name(team):
    m = g(team, "managers", default=None)
    try:
        if isinstance(m, (list, tuple)) and m:
            first = m[0]
            return g(first, "nickname", "name") or g(getattr(first, "manager", first), "nickname", "name") or "Manager"
        return g(m, "nickname", "name", default="Manager")
    except Exception:
        return "Manager"

def team_record(team):
    ts = g(team, "team_standings", default=None)
    ot = g(ts, "outcome_totals", default=None) if ts else None
    wins = int(g(ot, "wins", default=g(ts, "wins", default=0)) or 0)
    losses = int(g(ot, "losses", default=g(ts, "losses", default=0)) or 0)
    ties = int(g(ot, "ties", default=0) or 0)
    rank = int(g(ts, "rank", default=0) or 0)
    pf = num(g(team, "points_for", default=g(ts, "points_for", default=0)))
    pa = num(g(team, "points_against", default=g(ts, "points_against", default=0)))
    st_type = str(g(ts, "streak_type", default="")).lower()
    st_val = g(ts, "streak_value", default="")
    streak = (("W" if st_type.startswith("win") else "L" if st_type.startswith("los") else "") + str(st_val)) or "—"
    return wins, losses, ties, rank, pf, pa, streak


# ---- best-available-lineup projection ------------------------------------
# Set BEST_LINEUP=1 (env) or pass --best-lineup to turn on the roster optimizer.
# It builds each team's strongest legal lineup from their FULL roster (bench
# included), so an empty/unset starting slot is backfilled by the best AVAILABLE
# player instead of counting as zero.
#
# Injuries & byes: players Yahoo flags as out for the week are excluded before the
# lineup is built — anyone on IR, ruled Out/Doubtful, suspended, on PUP/NFI/NA, or on
# a bye that week can't be slotted in and won't project any points. Their starting
# slot is instead backfilled by the best healthy replacement on the roster. Players
# are valued by their season scoring average (Yahoo's API doesn't expose forward
# per-player projections through this library). The caller then floors the result at
# the team's season average, so even if a status is missing the odds can't blow out.
USE_BEST_LINEUP = os.environ.get("BEST_LINEUP", "").lower() in ("1", "true", "yes")

_FLEX = {"W/R/T": {"RB", "WR", "TE"}, "WRT": {"RB", "WR", "TE"}, "FLEX": {"RB", "WR", "TE"},
         "W/R": {"RB", "WR"}, "W/T": {"WR", "TE"}, "R/W/T": {"RB", "WR", "TE"},
         "Q/W/R/T": {"QB", "RB", "WR", "TE"}}

# statuses that mean "not playing this week" — exclude from the optimal lineup
_OUT_STATUS = {"O", "D", "IR", "IR-R", "IR-LT", "IR-ELIG", "SUSP", "PUP-R", "PUP-P",
               "NFI-R", "NFI-A", "NA", "DNR", "COVID-19", "DEC"}

def _eligible(pl):
    dp = str(g(pl, "display_position", "primary_position", default="")).upper()
    return {x.strip() for x in dp.replace("/", ",").split(",") if x.strip()}

def _slot_ok(slot, elig):
    slot = slot.upper()
    if slot in _FLEX:
        return bool(elig & _FLEX[slot])
    return slot in elig

def _available(pl, wk):
    """False if the player is injured-out, IR/suspended, or on bye this week."""
    sp = str(g(g(pl, "selected_position", default=None), "position", default="") or "").upper()
    if sp == "IR":
        return False
    st = str(g(pl, "status", default="") or "").upper().strip()
    if st in _OUT_STATUS:
        return False
    bw = g(pl, "bye_weeks", default=None)
    bye = g(bw, "week", default=None) if bw is not None else None
    try:
        if bye is not None and int(bye) == int(wk):
            return False
    except (TypeError, ValueError):
        pass
    return True

def _player_value(pl, weeks_done):
    try:
        total = float(pl.get_points(None) or 0)   # season total to date
    except Exception:
        return 0.0
    return total / max(1, weeks_done)

def best_lineup_proj(team_obj, wk, weeks_done, fallback):
    if team_obj is None:
        return fallback
    try:
        roster = team_obj.roster(wk)
        players = list(roster.players)
        # only healthy, non-bye players can fill a slot (injury handling)
        avail = [p for p in players if _available(p, wk)]
        vals = [(_player_value(p, weeks_done), _eligible(p)) for p in avail]
        # starting slots come from the real (non-bench) lineup config, including any
        # slot left empty by an injured/benched starter — so it gets backfilled.
        slots = [str(g(g(p, "selected_position", default=None), "position", default="") or "")
                 for p in players]
        slots = [s for s in slots if s and s not in ("BN", "IR")]
        if len(slots) < 6:   # lineup largely unset/empty -> use a standard template
            slots = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "K", "DEF"]
        used, total = set(), 0.0
        # assign scarcest slots first (fewest eligible), then take the best value
        order = sorted(range(len(slots)),
                       key=lambda i: sum(1 for _, e in vals if _slot_ok(slots[i], e)))
        for i in order:
            best, bi = -1.0, None
            for j, (v, e) in enumerate(vals):
                if j in used or not _slot_ok(slots[i], e):
                    continue
                if v > best:
                    best, bi = v, j
            if bi is not None:
                used.add(bi); total += max(0.0, best)
        return total if total > 0 else fallback
    except Exception as e:
        print(f"  (best-lineup fallback for a team: {e})")
        return fallback


def ensure_game_id(ctx, game, season):
    """yahoofantasy ships a hardcoded season->game_id table that lags new seasons.
    If the requested season is missing, look the id up live from Yahoo and inject it,
    so the script keeps working every year without waiting for a library update."""
    try:
        from yahoofantasy.api.games import games as GAMES
    except Exception:
        return  # nothing we can do; let the normal path raise
    if str(season) in GAMES.get(game, {}):
        return
    gid = None
    try:                                   # preferred: the library's own resolver
        from yahoofantasy.api.games import _find_game_id
        gid = _find_game_id(game, season, ctx)
    except Exception:
        pass
    if not gid:                            # fallback: ask Yahoo directly
        try:
            from yahoofantasy.api.parse import parse_response
            from pydash import get as _get
            resp = ctx.make_request(f"games;game_codes={game};seasons={season}")
            gid = _get(parse_response(resp), "fantasy_content.games.game.game_key.$")
        except Exception as e:
            sys.exit(f"Couldn't resolve the Yahoo game id for {game} {season}: {e}\n"
                     f"(If the {season} season hasn't opened on Yahoo yet, try again once it has.)")
    if not gid:
        sys.exit(f"Yahoo returned no game id for {game} {season} — has that season started yet?")
    GAMES.setdefault(game, {})[str(season)] = int(gid)
    print(f"  (resolved {game} {season} → Yahoo game id {gid})")


def build(season, league_id, game):
    # In CI (GitHub Actions) we build the Context straight from secrets.
    # Locally we fall back to the token saved by `yahoofantasy login`.
    cid = os.environ.get("YAHOO_CLIENT_ID")
    csec = os.environ.get("YAHOO_CLIENT_SECRET")
    rtok = os.environ.get("YAHOO_REFRESH_TOKEN")
    if cid and csec and rtok:
        ctx = Context(client_id=cid, client_secret=csec, refresh_token=rtok)
    else:
        ctx = Context()
    ensure_game_id(ctx, game, season)
    leagues = ctx.get_leagues(game, season)
    if not leagues:
        sys.exit(f"No {game} leagues found for {season} on this account.")

    league = None
    if league_id:
        for lg in leagues:
            if str(g(lg, "league_id", "id", default="")) == str(league_id):
                league = lg; break
        if league is None:
            print(f"League {league_id} not found. Available:")
    if league is None:
        for i, lg in enumerate(leagues):
            print(f"  [{i}] {g(lg,'name',default='?')}  (id {g(lg,'league_id','id',default='?')})")
        if league_id:
            sys.exit("Re-run with a matching --league id.")
        league = leagues[int(input("Pick a league number: ").strip())]

    lname = g(league, "name", default="My League")
    current_week = int(g(league, "current_week", default=1) or 1)
    playoff_teams = int(g(league, "num_playoff_teams", default=6) or 6)
    reg_weeks = int(g(league, "end_week", default=g(league, "playoff_start_week", default=15)) or 15)
    reg_weeks = max(1, reg_weeks - 1) if reg_weeks else 14
    print(f"→ {lname} · season {season} · current week {current_week} · {playoff_teams} playoff teams")

    # ---- teams / standings ----
    teams, id_map, team_objs = [], {}, {}
    for t in league.standings():
        tid = f"t{len(teams)+1}"
        team_objs[tid] = t
        for k in (str(g(t, "team_id", default="")), str(g(t, "team_key", default="")), str(g(t, "name", default=""))):
            if k: id_map[k] = tid
        w, l, ti, rank, pf, pa, streak = team_record(t)
        teams.append({
            "id": tid, "name": g(t, "name", default=f"Team {len(teams)+1}"),
            "manager": manager_name(t), "wins": w, "losses": l, "ties": ti,
            "points_for": pf, "points_against": pa, "streak": streak,
            "rank": rank or (len(teams) + 1),
            "moves": int(g(t, "number_of_moves", default=0) or 0),
            "trades": int(g(t, "number_of_trades", default=0) or 0),
            "proj_avg": round(pf / max(1, (w + l + ti)), 1) if (w + l + ti) else pf,
        })
    season_avg = {t["id"]: t["proj_avg"] for t in teams}
    weeks_done = max(1, current_week - 1)
    if not any(t["rank"] for t in teams):
        teams.sort(key=lambda x: (x["wins"], x["points_for"]), reverse=True)
        for i, t in enumerate(teams, 1): t["rank"] = i

    def resolve(obj):
        for k in (str(g(obj, "team_id", default="")), str(g(obj, "team_key", default="")), str(g(obj, "name", default=""))):
            if k in id_map: return id_map[k]
        return None

    # ---- weeks + current matchups ----
    weeks, current = [], []
    for week in league.weeks():
        wk = int(g(week, "week", default=0) or 0)
        completed = []
        for mm in g(week, "matchups", default=[]) or []:
            t1, t2 = g(mm, "team1", default=None), g(mm, "team2", default=None)
            if not (t1 and t2): continue
            id1, id2 = resolve(t1), resolve(t2)
            if not (id1 and id2): continue
            p1 = num(g(mm, "team1_points", default=g(t1, "team_points", default=0)))
            p2 = num(g(mm, "team2_points", default=g(t2, "team_points", default=0)))
            proj1 = num(g(mm, "team1_projected_points", default=p1))
            proj2 = num(g(mm, "team2_projected_points", default=p2))
            status = str(g(mm, "status", default="")).lower()
            done = "post" in status or wk < current_week
            if done and (p1 or p2):
                completed.append({"home": id1, "away": id2, "home_score": p1, "away_score": p2})
            elif wk == current_week:
                # Best-available-lineup projection: optionally optimize from the full
                # roster (opt-in), then FLOOR at the team's season average so an unset
                # or empty lineup can never drag a team's number down and distort odds.
                hp = best_lineup_proj(team_objs.get(id1), wk, weeks_done, proj1) if USE_BEST_LINEUP else proj1
                ap = best_lineup_proj(team_objs.get(id2), wk, weeks_done, proj2) if USE_BEST_LINEUP else proj2
                hp = max(hp or 0, season_avg.get(id1, 0), 1.0)
                ap = max(ap or 0, season_avg.get(id2, 0), 1.0)
                current.append({"id": f"w{wk}m{len(current)+1}", "week": wk, "home": id1, "away": id2,
                                "home_proj": round(hp, 1), "away_proj": round(ap, 1),
                                "home_score": p1, "away_score": p2,
                                "status": "pregame" if not (p1 or p2) else "live"})
        if completed:
            weeks.append({"week": wk, "matchups": completed})

    # ---- transactions ----
    transactions = []
    try:
        for tx in league.transactions():
            ttype = str(g(tx, "type", default="")).lower()
            wk = int(g(tx, "week", default=current_week) or current_week)
            ts = g(tx, "timestamp", default=None)
            date = (datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d") if ts
                    else datetime.date.today().isoformat())
            players = g(tx, "players", default=[]) or []
            if ttype == "trade":
                names = [str(g(p, "name", "full_name", default="a player")) for p in players]
                transactions.append({"type": "trade", "week": wk, "date": date, "teams": [],
                                     "detail": "Trade: " + (", ".join(names) if names else "see Yahoo") + "."})
            elif ttype in ("add", "add/drop"):
                for p in players:
                    transactions.append({"type": "add", "week": wk, "date": date,
                                         "team": _tx_team(tx, id_map),
                                         "player": str(g(p, "name", "full_name", default="a player")),
                                         "faab": int(g(p, "faab_bid", default=0) or 0)})
            elif ttype == "drop":
                for p in players:
                    transactions.append({"type": "drop", "week": wk, "date": date,
                                         "team": _tx_team(tx, id_map),
                                         "player": str(g(p, "name", "full_name", default="a player"))})
    except Exception as e:
        print(f"  (transactions unavailable: {e})")
    transactions = transactions[:20]

    return lname, current_week, reg_weeks, playoff_teams, teams, current, weeks, transactions


def _tx_team(tx, id_map):
    for attr in ("source_team_key", "destination_team_key", "team_key", "team_name"):
        v = getattr(tx, attr, None)
        if v is not None and str(v) in id_map:
            return id_map[str(v)]
    return None


def merge(existing, lname, current_week, reg_weeks, playoff_teams, teams, current, weeks, transactions):
    """Refresh live data; preserve config, champions, and coin balances (by manager)."""
    meta = dict(DEFAULT_META)
    champions = list(DEFAULT_CHAMPIONS)
    coin_start = DEFAULT_META["coin_start"]
    old_ledger_by_mgr, open_bets = {}, []

    if existing:
        em = existing.get("meta", {})
        for k in ("entry_fee", "payouts", "weekly_bonus", "currency_name",
                  "coin_start", "regular_season_weeks", "playoff_teams",
                  "commissioner", "season_complete", "draft_time"):
            if k in em:
                meta[k] = em[k]
        # a league that already stored a playoff count keeps it; otherwise take Yahoo's
        if "playoff_teams" not in em:
            meta["playoff_teams"] = playoff_teams
        # preserve a manually-set league name if present
        preserved_name = em.get("league_name")
        champions = existing.get("champions", champions)
        coin_start = meta.get("coin_start", coin_start)
        oc = existing.get("coins", {})
        open_bets = oc.get("open_bets", [])
        for row in oc.get("ledger", []):
            # map old team id -> manager name using old teams
            old_team = next((t for t in existing.get("teams", []) if t["id"] == row["team"]), None)
            if old_team:
                old_ledger_by_mgr[old_team["manager"]] = row
    else:
        preserved_name = None
        meta["playoff_teams"] = playoff_teams

    # rebuild ledger for current teams, carrying balances forward by manager
    ledger = []
    for t in teams:
        prev = old_ledger_by_mgr.get(t["manager"])
        if prev:
            ledger.append({"team": t["id"], "balance": prev.get("balance", coin_start),
                           "bets_won": prev.get("bets_won", 0), "bets_lost": prev.get("bets_lost", 0),
                           "net": prev.get("balance", coin_start) - coin_start})
        else:
            ledger.append({"team": t["id"], "balance": coin_start,
                           "bets_won": 0, "bets_lost": 0, "net": 0})

    meta.update({
        "league_name": preserved_name or lname,
        "season": existing.get("meta", {}).get("season") if existing else None,
        "current_week": current_week,
        "regular_season_weeks": meta.get("regular_season_weeks") or reg_weeks,
        "num_teams": len(teams),
        "pot": meta["entry_fee"] * len(teams),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "data_source": "Yahoo Fantasy",
    })
    return {
        "meta": meta, "teams": teams, "current_matchups": current, "weeks": weeks,
        "transactions": transactions,
        "coins": {"start_balance": coin_start, "ledger": ledger, "open_bets": open_bets},
        "champions": champions,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pull a Yahoo Fantasy league into league_data.json")
    ap.add_argument("--season", type=int, default=int(os.environ["SEASON"]) if os.environ.get("SEASON") else None)
    ap.add_argument("--league", type=str, default=os.environ.get("YAHOO_LEAGUE_ID"))
    ap.add_argument("--game", type=str, default=os.environ.get("YAHOO_GAME", "nfl"))
    ap.add_argument("--best-lineup", action="store_true",
                    help="Project each team off its best available lineup (optimizes from the "
                         "full roster; heavier—many API calls). Off by default; the season-average "
                         "floor still applies either way.")
    args = ap.parse_args()
    if args.best_lineup:
        globals()["USE_BEST_LINEUP"] = True
    if not args.season:
        ap.error("--season is required (or set the SEASON env var)")

    existing = None
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT))
            print("• Found existing league_data.json — preserving config, champions & coin balances.")
        except Exception:
            print("• Existing file unreadable — starting fresh.")

    lname, cw, rw, pt, teams, current, weeks, transactions = build(args.season, args.league, args.game)
    payload = merge(existing, lname, cw, rw, pt, teams, current, weeks, transactions)
    payload["meta"]["season"] = args.season

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, "w"), indent=2)
    print(f"✓ Wrote {OUT}")
    print(f"  {len(teams)} teams · {len(weeks)} completed weeks · {len(current)} current matchups · "
          f"{len(transactions)} transactions")
    print("  Preview locally, then push/re-host so the league sees the update.")
