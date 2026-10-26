"""Stáhne z NHL API data pro dnešní noc a vyhodnocení včerejška.

Výstup: data/<YYYY-MM-DD>.json a data/latest.json
Datum = dnešní datum v Praze; zápasy s tímto datem (US) se hrají v noci SEČ.
Spouští GitHub Action každé ráno. Jen standardní knihovna.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://api-web.nhle.com/v1"
PRAGUE = ZoneInfo("Europe/Prague")
FORM_GAMES = 5


def get(path, retries=3):
    url = f"{API}{path}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nhl-player-props/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                print(f"WARN {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def toi_to_min(s):
    if not s:
        return None
    try:
        m, sec = s.split(":")
        return int(m) + int(sec) / 60
    except ValueError:
        return None


def season_id(d):
    start = d.year if d.month >= 9 else d.year - 1
    return f"{start}{start + 1}"


def games_on(date_str):
    data = get(f"/schedule/{date_str}") or {}
    for day in data.get("gameWeek", []):
        if day.get("date") == date_str:
            return [g for g in day.get("games", []) if g.get("gameType") == 2]
    return []


def fetch_odds(teams):
    """Kurzy na vítěze a total z The Odds API (Pinnacle, jinak medián EU bookmakerů).

    Vrací {"<AWAY>@<HOME>": {"bookmaker", "p_home", "total", "p_over"}} s odstraněnou marží.
    Bez ODDS_API_KEY vrací {} a model použije obdržené góly soupeře.
    """
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return {}
    url = ("https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"
           f"?regions=eu&markets=h2h,totals&oddsFormat=decimal&apiKey={key}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nhl-player-props/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            events = json.load(r)
            print("Odds API zbývá kreditů:", r.headers.get("x-requests-remaining"))
    except Exception as e:  # noqa: BLE001
        print(f"WARN odds: {e}", file=sys.stderr)
        return {}
    by_name = {t["name"].lower(): ab for ab, t in teams.items()}
    out = {}
    for ev in events:
        h, a = by_name.get(ev["home_team"].lower()), by_name.get(ev["away_team"].lower())
        if not h or not a:
            continue
        books = ev.get("bookmakers", [])
        books = sorted(books, key=lambda b: b["key"] != "pinnacle")  # Pinnacle první
        rows = []
        for b in books:
            mk = {m["key"]: m for m in b.get("markets", [])}
            if "h2h" not in mk or "totals" not in mk:
                continue
            ml = {o["name"]: o["price"] for o in mk["h2h"]["outcomes"]}
            tot = mk["totals"]["outcomes"]
            over = next((o for o in tot if o["name"] == "Over"), None)
            under = next((o for o in tot if o["name"] == "Under"), None)
            if ev["home_team"] not in ml or ev["away_team"] not in ml or not over or not under:
                continue
            ih, ia = 1 / ml[ev["home_team"]], 1 / ml[ev["away_team"]]
            io, iu = 1 / over["price"], 1 / under["price"]
            rows.append({"bookmaker": b["key"], "p_home": ih / (ih + ia), "total": over.get("point"), "p_over": io / (io + iu)})
        if not rows:
            continue
        if rows[0]["bookmaker"] == "pinnacle":
            pick = rows[0]
        else:  # medián přes knihy se stejnou linií totalu
            line = sorted(r["total"] for r in rows)[len(rows) // 2]
            same = [r for r in rows if r["total"] == line]
            pick = {"bookmaker": "median", "total": line,
                    "p_home": sorted(r["p_home"] for r in same)[len(same) // 2],
                    "p_over": sorted(r["p_over"] for r in same)[len(same) // 2]}
        out[f"{a}@{h}"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pick.items()}
    return out


def team_name(t):
    place = (t.get("placeName") or {}).get("default", "")
    common = (t.get("commonName") or {}).get("default", "")
    return f"{place} {common}".strip() or t.get("abbrev")


def main():
    today = datetime.now(PRAGUE).date()
    if len(sys.argv) > 1:
        today = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    yesterday = today - timedelta(days=1)
    t_str, y_str = today.isoformat(), yesterday.isoformat()
    cur_season = season_id(today)
    prev_season = str(int(cur_season[:4]) - 1) + cur_season[:4]

    # Zápasy dnes a včera (včera = vyhodnocení + back-to-back)
    games_today = games_on(t_str)
    games_yday = games_on(y_str)
    played_yday = set()
    for g in games_yday:
        played_yday.add(g["awayTeam"]["abbrev"])
        played_yday.add(g["homeTeam"]["abbrev"])

    # Tabulka: obdržené góly, plné názvy
    teams = {}
    st = get("/standings/now") or {}
    for row in st.get("standings", []):
        ab = row["teamAbbrev"]["default"]
        gp = row.get("gamesPlayed") or 0
        ga = row.get("goalAgainst") or 0
        gf = row.get("goalFor") or 0
        teams[ab] = {
            "name": row["teamName"]["default"],
            "gp": gp,
            "ga": ga,
            "ga_pg": round(ga / gp, 3) if gp else None,
            "gf": gf,
            "gf_pg": round(gf / gp, 3) if gp else None,
            "b2b": ab in played_yday,
        }
    # Střely proti: součet shotsAgainst brankářů týmu / odehrané zápasy (všechny týmy, kvůli průměru ligy)
    club_cache = {}
    for ab, t in teams.items():
        cs = get(f"/club-stats/{ab}/now") or {}
        club_cache[ab] = cs
        sa = sum(gk.get("shotsAgainst", 0) or 0 for gk in cs.get("goalies", []))
        t["sa"] = sa
        t["sa_pg"] = round(sa / t["gp"], 3) if t["gp"] else None
        time.sleep(0.1)
    sa_gp = sum(t["gp"] for t in teams.values() if t.get("sa"))
    league_sa_pg = round(sum(t.get("sa", 0) for t in teams.values()) / sa_gp, 3) if sa_gp else 28.5

    gp_sum = sum(t["gp"] for t in teams.values())
    league_ga_pg = round(sum(t["ga"] for t in teams.values()) / gp_sum, 3) if gp_sum else 3.0

    out_games = []
    for g in games_today:
        start = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
        a, h = g["awayTeam"], g["homeTeam"]
        for t in (a, h):
            teams.setdefault(t["abbrev"], {"name": team_name(t), "gp": 0, "ga": 0, "ga_pg": None, "sa": 0, "sa_pg": None, "b2b": t["abbrev"] in played_yday})
        out_games.append({
            "id": g["id"],
            "start_utc": g["startTimeUTC"],
            "start_prague": start.astimezone(PRAGUE).strftime("%H:%M"),
            "date_prague": start.astimezone(PRAGUE).date().isoformat(),
            "away": a["abbrev"],
            "home": h["abbrev"],
        })

    # Hráči týmů, které dnes hrají
    players = []
    for ab in sorted({x for g in out_games for x in (g["away"], g["home"])}):
        cs = club_cache.get(ab) or get(f"/club-stats/{ab}/now") or {}
        for sk in cs.get("skaters", []):
            pid = sk["playerId"]
            name = f'{sk["firstName"]["default"]} {sk["lastName"]["default"]}'
            gl = get(f"/player/{pid}/game-log/{cur_season}/2") or {}
            log = gl.get("gameLog", [])  # nejnovější první
            last = log[:FORM_GAMES]
            tois = [toi_to_min(x.get("toi")) for x in log]
            tois = [t for t in tois if t is not None]
            last_tois = [toi_to_min(x.get("toi")) for x in last]
            last_tois = [t for t in last_tois if t is not None]

            landing = get(f"/player/{pid}/landing") or {}
            prev = {"gp": 0, "g": 0, "a": 0, "pts": 0, "sog": 0}
            for s in landing.get("seasonTotals", []):
                if str(s.get("season")) == prev_season and s.get("leagueAbbrev") == "NHL" and s.get("gameTypeId") == 2:
                    prev["gp"] += s.get("gamesPlayed", 0)
                    prev["g"] += s.get("goals", 0)
                    prev["a"] += s.get("assists", 0)
                    prev["pts"] += s.get("points", 0)
                    prev["sog"] += s.get("shots", 0) or 0

            players.append({
                "id": pid,
                "name": name,
                "team": ab,
                "pos": sk.get("positionCode"),
                "cur": {
                    "gp": sk.get("gamesPlayed", 0),
                    "g": sk.get("goals", 0),
                    "a": sk.get("assists", 0),
                    "pts": sk.get("points", 0),
                    "sog": sk.get("shots", 0) or 0,
                    "ppp": sk.get("powerPlayGoals", 0),  # PP góly (club-stats nemá PPP vždy)
                    "toi_avg": round(sum(tois) / len(tois), 2) if tois else None,
                },
                "last": {
                    "gp": len(last),
                    "g": sum(x.get("goals", 0) for x in last),
                    "a": sum(x.get("assists", 0) for x in last),
                    "pts": sum(x.get("points", 0) for x in last),
                    "sog": sum(x.get("shots", 0) or 0 for x in last),
                    "ppp": sum(x.get("powerPlayPoints", 0) for x in last),
                    "toi_avg": round(sum(last_tois) / len(last_tois), 2) if last_tois else None,
                    "dates": [x.get("gameDate") for x in last],
                },
                "prev": prev,
            })
            time.sleep(0.15)

    # Výsledky včerejška (pro vyhodnocení trackeru)
    results = []
    for g in games_yday:
        bs = get(f"/gamecenter/{g['id']}/boxscore") or {}
        pbg = bs.get("playerByGameStats", {})
        rows = []
        for side in ("awayTeam", "homeTeam"):
            for grp in ("forwards", "defense"):
                for p in pbg.get(side, {}).get(grp, []):
                    rows.append({
                        "id": p.get("playerId"),
                        "name": (p.get("name") or {}).get("default"),
                        "g": p.get("goals", 0),
                        "a": p.get("assists", 0),
                        "pts": p.get("points", 0),
                        "sog": p.get("sog", p.get("shots", 0)) or 0,
                    })
        results.append({
            "id": g["id"],
            "away": g["awayTeam"]["abbrev"],
            "home": g["homeTeam"]["abbrev"],
            "state": bs.get("gameState"),
            "players": rows,
        })

    odds = fetch_odds(teams)

    payload = {
        "odds": odds,
        "date": t_str,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": cur_season,
        "league_ga_pg": league_ga_pg,
        "league_sa_pg": league_sa_pg,
        "games": out_games,
        "teams": teams,
        "players": players,
        "results_yesterday": {"date": y_str, "games": results},
    }
    os.makedirs("data", exist_ok=True)
    for path in (f"data/{t_str}.json", "data/latest.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"{t_str}: {len(out_games)} zápasů, {len(players)} hráčů, včera {len(results)} zápasů")


if __name__ == "__main__":
    main()
