# The LomBarkley Trophy 🏈

A phone-installable app for your 10-man fantasy league: live scoreboard, standings
with the money line, a Collie Coins sportsbook (real odds, real-money settle-up), a
season **Money** ledger, a weekly recap with awards, a trade/waiver wire, and the
trophy history — all pulled automatically from Yahoo Fantasy.

No app store. Everyone opens a link, taps **Add to Home Screen**, and it behaves
like a native app (icon, fullscreen, offline).

```
gridiron/
├─ index.html              ← the app (open this to preview)
├─ manifest.webmanifest    ← makes "Add to Home Screen" work
├─ sw.js                   ← offline caching
├─ icons/                  ← app icons
├─ data/league_data.json   ← the data the app reads (regenerated weekly)
├─ requirements.txt
└─ scripts/
   ├─ fetch_league.py       ← pulls YOUR Yahoo league into league_data.json
   ├─ make_sample_data.py   ← the demo data you're seeing now
   └─ make_icons.py         ← regenerates the icon set
```

Right now the app shows **sample data** so you can see everything working. The steps
below swap in your real league.

---

## Preview it right now

Just open `index.html` in a browser (double-click it). It runs on the built-in
sample league. This is the fastest way to see the design before you connect Yahoo.

---

## Connect your real Yahoo league

> **Heads up (2026):** Yahoo has closed self-serve Fantasy API access — new apps
> must apply at <https://sports.yahoo.com/developer/access/> and wait for approval.
> Until/unless you're approved, use **Option A** below; it needs no API at all.
> If you already have working API credentials, skip to **Option B**.

### Option A — no API needed (publicly-viewable league)

1. On Yahoo (desktop site): your league → **Commissioner → League Settings →
   Make League Publicly Viewable → Yes.** This makes the league *readable* by
   anyone with the URL — nobody can join or change anything. If that tradeoff is
   fine for your league, this is the simplest path by far.
2. Pull the data:

   ```bash
   python scripts/fetch_league_web.py --league YOUR_LEAGUE_ID
   ```

That's it — same `data/league_data.json`, same merge behavior (money config,
Collie Coins, trophy history, and `season_complete` are preserved on refresh).
The weekly GitHub Action uses this automatically when no API secrets are set
(just add the `YAHOO_LEAGUE_ID` repository variable).

Notes on this mode:
- Manager display names come from **team names** (public pages don't show
  Yahoo account names). Team renames mid-season will re-key local coin ledgers,
  so encourage people to pick a team name and stick with it.
- The pages only show the current week, so the script **archives each week's
  final scores as the season rolls forward** — that history drives the weekly
  high-scorer money and bet auto-settlement. Practical upshot: let the Action
  run at least weekly so no week is skipped.
- Scrapers depend on Yahoo's page structure. If Yahoo redesigns and parsing
  breaks, run with `--dump` and inspect/share the saved HTML; the parser is
  intentionally pattern-based so fixes are small.
- Private-league fallback: save the standings and matchups pages from your
  logged-in browser (Ctrl+S → HTML only) into a folder and run
  `python scripts/fetch_league_web.py --league YOUR_LEAGUE_ID --from-files thatfolder/`.

### Option B — the official Yahoo API (requires Yahoo approval)

### Step 1 — Register a Yahoo developer app (5 min, one time)

1. Go to **https://developer.yahoo.com/apps/create/**
2. Fill it in:
   - **Application Name:** `LomBarkley Trophy` (anything)
   - **Application Type:** Confidential Client
   - **Redirect URI (OAuth Callback):** `https://localhost:8000`
   - **API Permissions:** check **Fantasy Sports** → **Read**
3. Create it, then copy your **Client ID** and **Client Secret**.

> You do **not** need commissioner access for this. Any league member's Yahoo
> login can authorize read access to the whole league. (You still want commish
> access for renewing the league and settings — that's separate.)

### Step 2 — Install the pipeline

```bash
cd gridiron
pip install -r requirements.txt
```

### Step 3 — One-time login

```bash
yahoofantasy login
```

Paste your Client ID and Secret when prompted, then approve in the browser that
opens. This saves a token so future pulls run without logging in again (it
auto-refreshes). This is the OAuth handshake — it's what actually authorizes the
data pull.

### Step 4 — Find your league_id

Open your league on Yahoo. The URL looks like:

```
https://football.fantasysports.yahoo.com/f1/123456
                                              ^^^^^^  ← that's your league_id
```

### Step 5 — Pull the data

```bash
python scripts/fetch_league.py --season 2026 --league 123456
```

That overwrites `data/league_data.json` with your real teams, matchups, standings,
and transactions. (Leave off `--league` and it lists your leagues so you can pick.)

Reload `index.html` — you're now looking at your actual league.

---

## Get it on everyone's phone (hosting)

The app is just static files, so any static host works. **GitHub Pages is free**
and you already use GitHub:

1. Put this folder in a repo and push it.
2. Repo → **Settings → Pages** → deploy from your branch, root folder.
3. You'll get a URL like `https://yourname.github.io/regime/`.
4. Drop that link in the league group chat.

**Add to Home Screen:**
- **iPhone (Safari):** Share button → *Add to Home Screen*
- **Android (Chrome):** ⋮ menu → *Install app* / *Add to Home Screen*

It installs with the seal icon and opens fullscreen.

### Weekly update loop

Once a week (or after games):

```bash
python scripts/fetch_league.py --season 2026 --league 123456
git add data/league_data.json && git commit -m "Week update" && git push
```

Everyone's app pulls the fresh data next time they open it. That's the whole
maintenance routine.

### Automatic weekly refresh (GitHub Action)

There's a workflow at `.github/workflows/weekly-refresh.yml` that runs the fetch and
commits the result for you — no manual runs. It fires every **Tuesday morning**
(after Monday Night Football closes the week) and can also be triggered by hand from
the Actions tab.

One-time setup in your repo → **Settings → Secrets and variables → Actions**:

**Secrets** (New repository secret):
- `YAHOO_CLIENT_ID` — from your Yahoo developer app
- `YAHOO_CLIENT_SECRET` — from your Yahoo developer app
- `YAHOO_REFRESH_TOKEN` — the `Refresh Token:` line that `yahoofantasy login` prints

**Variables** (Variables tab):
- `YAHOO_LEAGUE_ID` — the number in your league URL
- `SEASON` — e.g. `2026`

That's it. `fetch_league.py` builds its Yahoo connection straight from those three
secrets, so nothing else needs to live in CI. Yahoo refresh tokens last ~1 year; if
one ever expires, re-run `yahoofantasy login` and update the secret. Want more
frequent pulls (e.g. Sunday-night scores)? Add another `cron` line — there's a
commented example in the workflow.

> **This won't clobber anything.** The fetch preserves your league config, the
> trophy history, and — in local betting mode — Collie Coins balances, matched to
> people by **manager name** so a balance follows the right person even when the
> standings reshuffle. It only refreshes the live game data. (In Firebase betting
> mode, balances live in Firebase and aren't touched by the fetch at all.)

---

## The money ($1,000 pot)

The **Money** tab is the season ledger — what each person wins or owes, all in.

```
10 × $100 entry ............................  $1,000 pot
  1st place .....  $500
  2nd place .....  $260
  3rd place .....  $100  (money back)
  ------------------------  $860 placement
  weekly high scorer: $10 × 14 weeks .....  $140
  ------------------------------------------  $1,000  (fully allocated)
```

Each person's bottom line =
`− $100 entry  +  placement  +  weekly high-scorer cash  +  betting net`.

- **Entry** is −$100 (collected after the season).
- **Placement** ($500 / $260 / $100) is **only paid to the final top 3 at season's
  end** — it is *not* credited to whoever's leading mid-season. While the season is
  live, the Money tab shows a non-monetary "on pace" hint next to the current top 3,
  but their totals don't include the money yet.
- **Weekly** is $10 for each week you were the single highest scorer.
- **Betting net** is your Collie Coins balance minus your $100 starting stake
  (see below). Don't bet → $0 impact.

**Marking the season done:** when it's over, set `"season_complete": true` in
`data/league_data.json` under `meta` (and add the year to `champions`). That flips the
Money tab to final mode — placement money lands on the final top 3 by standings, and
the summary switches to an "in the black" count. Make sure the data reflects the
**final** (post-playoff) standings when you flip it. The weekly auto-refresh preserves
this flag, so it won't get reset.

Set the payouts, entry fee, and weekly bonus in `data/league_data.json` under
`meta` — the Money tab math follows automatically.

---

## Playoffs & the bracket

The **Standings** tab marks the playoff field: the top 6 seeds are highlighted, a
green line shows the cut after 6th, and the top 2 seeds carry a **BYE** tag with a gold
"first-round bye" divider after 2nd. The number of playoff teams is `meta.playoff_teams`
(auto-detected from Yahoo, default 6).

The **Bracket** tab lays out a 6-team, single-elimination bracket and lets you play it
out — tap a team to advance it:

- **Wild Card:** 3 vs 6 and 4 vs 5 (seeds 1 and 2 are on bye).
- **Semifinals — re-seeded:** seed **1 draws the lowest remaining seed** (the weakest
  survivor) and seed **2 draws the highest remaining seed**. So if 6 and 4 win the wild
  card, 1 plays 6 and 2 plays 4; if 3 and 5 win, 1 plays 5 and 2 plays 3.
- **The Barkley Bowl:** the two semifinal winners meet for the title.

Your taps are saved on your device, so it works as a prediction bracket. "Clear picks"
resets it. (It's a what-if projector seeded from the live standings; it doesn't pull
Yahoo's actual playoff results — those play out in the app week to week.)

---

## Identity, PINs & who can change what

The app is honor-system-plus: no accounts, but light PIN protection so nobody can
casually act as someone else.

- **Claiming a team (The Book):** the first time you pick your name, you create a
  **4-digit PIN**. From then on, betting as that name — posting, taking, or canceling
  bets — requires the PIN (asked once per device, remembered after that). PINs are
  stored hashed in the shared store and sync everywhere in Firebase mode.
- **Mark paid (Money tab):** gated behind a separate **commissioner PIN**. The pay
  buttons don't render at all until the commish unlocks. **Important: whoever sets
  the commish PIN first *is* the commish — so the commissioner should open the app
  and do "Commish unlock" once BEFORE sharing the link with the league.**
- **What this is and isn't:** it stops name-picking mischief and accidental bets for
  the wrong team, which is the realistic threat in a 10-friend league. It is *not*
  bank-grade security — the database rules are open-write and a determined, technical
  member could bypass it. Every action is visible to everyone in real time, which is
  the real enforcement. If the league ever wants hard security, the upgrade is
  Firebase Anonymous Auth + validation rules — ask and it can be wired in.
- **Forgot a PIN?** In local mode, clear it from the browser storage; in Firebase
  mode the commish can delete the entry under `leagues/<key>/pins` in the Firebase
  console and the person re-claims.


## The Book (peer-to-peer betting)

Betting runs on **Collie Coins** — everyone starts the season with **100 coins =
$100** (1 coin = $1). Your season **net** (coins won or lost) carries into the Money
tab as real dollars.

Betting is **head-to-head**: you post a bet, another member takes the other side, and
coins move only between the two of you. That makes the whole thing **perfectly
zero-sum**, so at season end the winners and losers net out to the penny — no house,
no leakage.

**How it works in the app (The Book tab):**
1. Tap your name once to say who you are (stored on your device; change anytime).
2. **Post a Bet** on any matchup — pick moneyline, spread, or total, choose your
   side, set your odds (pre-filled from the projections, adjustable), and your stake.
   Your stake is escrowed immediately.
3. Your offer shows up under **Open Action** for everyone else. When someone taps
   **Take it**, they put up the matching risk and the bet is locked in.
4. When the game finishes, the app **settles automatically** off the final score and
   moves the pot to the winner. The Collie Coins standings and the Money tab update
   themselves.

### How the projections (and odds) are set

The pre-filled odds come from each matchup's projections, and the weekly refresh
builds them off each team's **best available lineup** (`BEST_LINEUP=1` is set in the
GitHub Action). It optimizes the strongest legal lineup from the whole roster, so an
empty or unset starting slot is backfilled by the best bench option instead of
counting as zero.

**Injuries & byes:** the optimizer only fields players who can actually play. Anyone
Yahoo flags as **Out, Doubtful, on IR, suspended, on PUP/NFI/NA, or on a bye that
week** is excluded, and their slot is backfilled by the best *healthy* replacement on
the roster — so an injured star never inflates a projection, and a benched-because-hurt
starter doesn't tank one either. (Questionable players are still counted, since they
usually suit up.) Players are valued by their season scoring average, because Yahoo's
API doesn't expose forward per-player projections through this library.

On top of that, every team's number is **floored at its season scoring average**, so
even if a status is missing or a lineup is untouched, a team can't be priced below what
it normally puts up and can't hand its opponent free odds. That floor is always on; the
full optimizer is what `BEST_LINEUP` adds (it makes more Yahoo API calls, so a weekly
refresh may take a couple of minutes). To turn the optimizer off and rely on the floor
alone, remove `BEST_LINEUP` from the workflow env.

### Two modes

**Local demo (default, no setup):** bets live on your device and sync across browser
tabs — great for trying it out, and it works offline. Open the app in two tabs, pick
two different names, and you can watch an offer post in one and get taken in the
other. It is *not* shared across different people's phones.

**Live (shared across the whole league):** connect a free Firebase Realtime Database
and everyone's bets sync in real time across all phones. Setup below.

### Going live with Firebase (free)

1. Create a project at <https://console.firebase.google.com> (no billing needed).
2. **Build → Realtime Database → Create database** → start in **test mode** (or use
   the rules below). Note the database URL (looks like
   `https://your-project-default-rtdb.firebaseio.com`).
3. **Project settings → General → Your apps → Web app** → register an app and copy
   the `firebaseConfig` object.
4. In the app: The Book tab → *connect a free backend* → paste the config, and add
   two fields to it: `"databaseURL": "…"` (from step 2) and
   `"leagueKey": "lombarkley2026"` (any id for this season). Tap **Connect & go live**.
5. Have everyone else do step 4 with the **same** config (drop it in the group chat).

A Firebase web config isn't a secret — it's a public identifier. Security comes from
your **database rules**. For a 10-person friend league, this simple ruleset (paste in
the Realtime Database **Rules** tab) keeps randoms out while trusting league members:

```json
{
  "rules": {
    "leagues": {
      "$league": {
        ".read": true,
        ".write": true
      }
    }
  }
}
```

That's open-write, which is fine for friends sharing one config. If you want it
locked down harder (auth, per-field validation, tamper-proofing), that's a bigger
lift — ping me and we'll add Firebase Anonymous Auth plus validation rules.

> **Identity is honor-system** in this version: you pick your name, there's no
> password. For a friend league that's usually the right call (every action is
> visible to everyone in real time). If you want PIN-protected identities, that's a
> quick add.

The `coins.ledger` in `data/league_data.json` is only used as the fallback in local
mode / before Firebase is connected. Once you're live, Firebase is the source of
truth for balances and the weekly Yahoo fetch never touches them.

---

## Trophy history

Past champions live in `data/league_data.json` under `champions` and show on the
League tab. Yours are already in there (2023–2025). Add a new entry each year:

```json
{ "year": 2026, "first": "Name", "second": "Name", "third": "Name" }
```

---

## Customizing

Money model and content live in `data/league_data.json`:

- `meta.league_name`, `meta.payouts` (`1st`/`2nd`/`3rd`), `meta.entry_fee`
- `meta.weekly_bonus` (the $10) and `meta.regular_season_weeks` (the 14)
- `meta.season_complete` — `false` during the year, `true` to pay out the final top 3
- `meta.draft_time` — draft day as a unix timestamp; drives the Scores-tab
  countdown pre-draft. The web fetch auto-fills it once Yahoo shows the countdown
  (inside ~7 days of a scheduled draft); set it manually for an earlier countdown
  (e.g. `python -c "import datetime;print(int(datetime.datetime(2026,8,29,19,0).timestamp()))"`).
- `meta.playoff_teams` — how many seeds make the playoffs (drives the Standings cut
  line; auto-detected from Yahoo on first fetch, default 6)
- `meta.currency_name` — rename "Collie Coins" to anything
- `coins.start_balance` / `meta.coin_start` — everyone's starting stake ($100)
- `champions` — the trophy history

Colors and fonts are CSS variables at the top of `index.html` (`--gold`, `--turf`,
`--red`, etc.). The icon is regenerated with `python scripts/make_icons.py`.

---

*Fantasy data provided by Yahoo Fantasy.* (Yahoo requires this attribution — it's
in the app footer, keep it there.)
