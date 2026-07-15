"""
make_sample_data.py
-------------------
Generates a realistic, internally-consistent league_data.json so the app is
fully browsable before Yahoo is connected. Also documents the exact schema that
fetch_league.py produces from real Yahoo data.

Money model (real dollars, 1 Collie Coin = $1):
  entry = -$100 (collected after the season)
  placement: 1st $500 / 2nd $260 / 3rd $100(money back)   = $860
  weekly high scorer: $10 x 14 regular-season weeks       = $140
  ---------------------------------------------------------  $1,000 pot
  bets: everyone starts with 100 Collie Coins (=$100). Only the NET
        (balance - 100) counts toward the season money.
"""
import json, random, datetime, os

random.seed(1213)
CURRENT_WEEK, SEASON, REG_WEEKS = 7, 2026, 14
COIN_START, WEEKLY_BONUS = 100, 10

TEAMS = [
    ("t1",  "Barkley's Bunch",         "Daki"),
    ("t2",  "Gronk If You're Horny",   "Kadin"),
    ("t3",  "The Waterboys",           "Drew"),
    ("t4",  "Purdy Good Team",         "Matt"),
    ("t5",  "Ja'Marr the Merrier",     "Jack"),
    ("t6",  "Saquon My Wayward Son",   "Cam"),
    ("t7",  "Bijan Mustard",           "Mitch"),
    ("t8",  "CeeDee LaFlame",          "Marlon"),
    ("t9",  "Kittle Caesars",          "Shayne"),
    ("t10", "Fourth & Long Islands",   "Zach"),
]
base = [(5,121,14),(5,118,12),(4,113,16),(4,110,11),(3,108,15),
        (3,105,13),(3,104,17),(2,99,12),(2,96,14),(1,92,18)]

teams = []
for (tid, name, mgr), (wins, pf_avg, var) in zip(TEAMS, base):
    gp = 6; losses = gp - wins
    pf = round(sum(random.gauss(pf_avg, var) for _ in range(gp)), 1)
    pa = round(sum(random.gauss(108, 14) for _ in range(gp)), 1)
    st = ("W" if wins >= losses else "L") + str(random.randint(1,3))
    teams.append({"id":tid,"name":name,"manager":mgr,"wins":wins,"losses":losses,
        "ties":0,"points_for":pf,"points_against":pa,"streak":st,
        "moves":random.randint(3,22),"trades":random.randint(0,3),
        "proj_avg":round(pf_avg+random.uniform(-3,3),1)})
teams.sort(key=lambda t:(t["wins"],t["points_for"]),reverse=True)
for i,t in enumerate(teams,1): t["rank"]=i
by_id = {t["id"]:t for t in teams}

def gen_score(t): return round(random.gauss(t["proj_avg"],18),1)
pairings = {
 1:[("t1","t10"),("t2","t9"),("t3","t8"),("t4","t7"),("t5","t6")],
 2:[("t1","t9"),("t2","t8"),("t3","t7"),("t4","t6"),("t5","t10")],
 3:[("t1","t8"),("t2","t7"),("t3","t6"),("t4","t5"),("t9","t10")],
 4:[("t1","t7"),("t2","t6"),("t3","t5"),("t4","t10"),("t8","t9")],
 5:[("t1","t6"),("t2","t5"),("t3","t4"),("t7","t10"),("t8","t9")],
 6:[("t1","t5"),("t2","t4"),("t3","t9"),("t6","t10"),("t7","t8")],
}
weeks=[]
for wk in range(1,CURRENT_WEEK):
    ms=[{"home":h,"away":a,"home_score":gen_score(by_id[h]),"away_score":gen_score(by_id[a])}
        for h,a in pairings[wk]]
    weeks.append({"week":wk,"matchups":ms})

week7=[("t1","t4"),("t2","t3"),("t5","t8"),("t6","t7"),("t9","t10")]
current=[]
for i,(h,a) in enumerate(week7,1):
    current.append({"id":f"w{CURRENT_WEEK}m{i}","week":CURRENT_WEEK,"home":h,"away":a,
        "home_proj":round(by_id[h]["proj_avg"]+random.uniform(-4,6),1),
        "away_proj":round(by_id[a]["proj_avg"]+random.uniform(-4,6),1),
        "home_score":0.0,"away_score":0.0,"status":"pregame"})

transactions=[
 {"type":"trade","week":6,"date":"2026-10-14","teams":["t2","t5"],
  "detail":"Gronk If You're Horny traded WR DK Metcalf to Ja'Marr the Merrier for RB Kenneth Walker III + a 2027 pick."},
 {"type":"trade","week":5,"date":"2026-10-07","teams":["t1","t7"],
  "detail":"Barkley's Bunch traded TE Trey McBride to Bijan Mustard for WR Jaylen Waddle."},
 {"type":"trade","week":4,"date":"2026-09-30","teams":["t3","t9"],
  "detail":"The Waterboys traded RB Tony Pollard to Kittle Caesars for WR Chris Olave."},
 {"type":"add","week":6,"date":"2026-10-15","team":"t4","player":"RB Tyjae Spears","faab":23},
 {"type":"add","week":6,"date":"2026-10-15","team":"t8","player":"WR Jalen McMillan","faab":11},
 {"type":"drop","week":6,"date":"2026-10-15","team":"t10","player":"WR Romeo Doubs","faab":0},
 {"type":"add","week":5,"date":"2026-10-08","team":"t6","player":"QB Bo Nix","faab":34},
]

coin_nets={"t1":62,"t2":28,"t3":-15,"t4":0,"t5":41,"t6":-33,"t7":9,"t8":-22,"t9":0,"t10":-18}
ledger=[]
for t in teams:
    net=coin_nets[t["id"]]
    won,lost=(0,0) if net==0 else (random.randint(2,7),random.randint(2,7))
    ledger.append({"team":t["id"],"balance":COIN_START+net,"bets_won":won,"bets_lost":lost,"net":net})
ledger.sort(key=lambda r:r["balance"],reverse=True)
open_bets=[
 {"id":"b1","week":7,"bettor":"t2","market":"moneyline","pick":"t2","matchup":"w7m2","stake":15,"odds":135,"status":"open"},
 {"id":"b2","week":7,"bettor":"t6","market":"spread","pick":"t6","line":-3.5,"matchup":"w7m4","stake":10,"odds":-110,"status":"open"},
]
champions=[
 {"year":2025,"first":"Daki","second":"Kadin","third":"Drew"},
 {"year":2024,"first":"Daki","second":"Matt","third":"Drew"},
 {"year":2023,"first":"Kadin","second":"Daki","third":"Jack"},
]
data={
 "meta":{"league_name":"The LomBarkley Trophy","season":SEASON,"current_week":CURRENT_WEEK,
   "num_teams":len(teams),"regular_season_weeks":REG_WEEKS,"entry_fee":100,"pot":100*len(teams),
        "playoff_teams": 6,
        "season_complete": False,
   "payouts":{"1st":500,"2nd":260,"3rd":100},"weekly_bonus":WEEKLY_BONUS,
   "currency_name":"Collie Coins","coin_start":COIN_START,
   "updated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
   "data_source":"sample","commissioner":"Kadin"},
 "teams":teams,"current_matchups":current,"weeks":weeks,"transactions":transactions,
 "coins":{"start_balance":COIN_START,"ledger":ledger,"open_bets":open_bets},
 "champions":champions,
}
out=os.path.abspath(os.path.join(os.path.dirname(__file__),"..","data","league_data.json"))
json.dump(data,open(out,"w"),indent=2)
print(f"Wrote {out}")
print(f"{len(teams)} teams · payouts {data['meta']['payouts']} · weekly ${WEEKLY_BONUS} · coins start {COIN_START}")
