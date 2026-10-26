"""Spočítá fair kurzy a shortlist podle metodiky (metodika.md).

Použití:
  python compute.py data/latest.json lines.json > out.json

lines.json (doplňuje Claude z DailyFaceoff každé ráno):
{
  "EDM": {"roles": {"Connor McDavid": "L1", "Evan Bouchard": "D1", ...},
          "pp1": ["Connor McDavid", ...],
          "goalie_backup": false,        # brankář TOHOTO týmu je záložník
          "goalie_elite": false,         # brankář TOHOTO týmu je elitní jednička
          "updated": "2026-10-26T16:00Z"}
}
Hráč bez role v lines.json se nepočítá (nehraje / mimo sestavu).
"""
import json
import math
import re
import sys
import unicodedata

W_PRIOR_GP = 20        # shrinkage aktuální sezóny
W_FORM = 0.20          # váha formy posledních 5 zápasů
TOI_EXP, TOI_LO, TOI_HI = 0.8, 0.85, 1.15
K_POISSON = 0.97
EDGE = 1.08
MIN_ODDS = 1.90
ROOKIE = {"F": {"pts": 0.40, "g": 0.15, "a": 0.25}, "D": {"pts": 0.25, "g": 0.05, "a": 0.20}}
MARKETS = {"bod": "pts", "gol": "g", "asist": "a"}
LAB = {"bod": "b/z", "gol": "g/z", "asist": "a/z"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", "-", s).strip("-")


def fmt(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def rate_for(p, key):
    cur, prev, last = p["cur"], p["prev"], p["last"]
    gp = cur["gp"] or 0
    w = gp / (gp + W_PRIOR_GP)
    pos = "D" if p.get("pos") == "D" else "F"
    if prev["gp"] >= 10:
        prior = prev[key] / prev["gp"]
        low_conf = False
    else:
        prior = ROOKIE[pos][key]
        low_conf = True
    cur_rate = cur[key] / gp if gp else prior
    base = w * cur_rate + (1 - w) * prior
    if last["gp"] >= 3:
        form = last[key] / last["gp"]
        final = (1 - W_FORM) * base + W_FORM * form
    else:
        form = None
        final = base
    return final, base, form, low_conf


def k_toi(p):
    s, l = p["cur"].get("toi_avg"), p["last"].get("toi_avg")
    if not s or not l:
        return 1.0
    return min(TOI_HI, max(TOI_LO, (l / s) ** TOI_EXP))


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    lines = json.load(open(sys.argv[2], encoding="utf-8"))
    teams = data["teams"]
    lg = data.get("league_ga_pg") or 3.0
    games = {g["id"]: g for g in data["games"]}
    team_game = {}
    for g in data["games"]:
        team_game[g["away"]] = (g, False, g["home"])
        team_game[g["home"]] = (g, True, g["away"])

    cands = []
    for p in data["players"]:
        tg = team_game.get(p["team"])
        tl = lines.get(p["team"])
        if not tg or not tl:
            continue
        roles = {norm(k): v for k, v in tl.get("roles", {}).items()}
        role = roles.get(norm(p["name"]))
        if not role:
            continue
        pp1 = norm(p["name"]) in {norm(x) for x in tl.get("pp1", [])}
        # jen top-6 útočníků a top-4 obránců s PP1
        if role in ("L3", "L4") or (role.startswith("D") and not pp1):
            continue
        g, home, opp = tg
        ot = teams.get(opp, {})
        opp_ga = ot.get("ga_pg")
        if opp_ga and ot.get("gp", 0) >= 3:
            k_opp = 1 + 0.5 * (opp_ga / lg - 1)
        else:
            k_opp = 1.0
        ol = lines.get(opp, {})
        k_gk = 1.05 if ol.get("goalie_backup") else 0.95 if ol.get("goalie_elite") else 1.0
        k_home = 1.02 if home else 0.98
        k_b2b = 0.97 if teams.get(p["team"], {}).get("b2b") else 1.0
        kt = k_toi(p)

        for m, key in MARKETS.items():
            final, base, form, low = rate_for(p, key)
            lam = final * kt * k_opp * k_gk * k_home * k_b2b * K_POISSON
            if lam <= 0:
                continue
            P = 1 - math.exp(-lam)
            fair = 1 / P
            notes = []
            if form is not None:
                notes.append(f"forma {p['last'][key]} v {p['last']['gp']} z")
            if p["last"].get("toi_avg") and p["cur"].get("toi_avg"):
                notes.append(f"TOI {fmt(p['last']['toi_avg'],1)} vs {fmt(p['cur']['toi_avg'],1)} min")
            if k_gk > 1:
                notes.append("soupeř záložní brankář")
            if k_b2b < 1:
                notes.append("back-to-back")
            if low:
                notes.append("nízká jistota")
            opp_txt = f"{ot.get('name', opp)} {fmt(opp_ga,1)} GA/z" if opp_ga else f"{ot.get('name', opp)} GA n/a"
            reason = (f"{role}{', PP1' if pp1 else ''}; letos {p['cur'][key]} v {p['cur']['gp']} z, "
                      f"min. sez. {p['prev'][key]} v {p['prev']['gp']} z → {fmt(final)} {LAB[m]}; "
                      f"{'; '.join(notes) + '; ' if notes else ''}soupeř {opp_txt}")
            cands.append({
                "game_id": g["id"], "market": m, "p": P, "player": p["name"], "team_abbrev": p["team"],
                "doc": {
                    "date": g["date_prague"],
                    "game": f"{teams[g['away']]['name']} @ {teams[g['home']]['name']}",
                    "time": f"{g['start_prague']} SEČ",
                    "player": p["name"], "team": teams[p["team"]]["name"], "market": m,
                    "p": round(P, 3), "fair": round(fair, 2), "min": round(max(MIN_ODDS, fair * EDGE), 2),
                    "reason": reason, "hit": None, "odds": None, "bet": False, "source": "model",
                },
            })

    # Shortlist na zápas: 3× bod (fair 1,60–2,50), 1× gól, 1× asistence (fair ≥ 1,60)
    out = []
    for gid in games:
        gc = [c for c in cands if c["game_id"] == gid]
        def top(m, n, lo, hi):
            xs = [c for c in gc if c["market"] == m and lo <= 1 / c["p"] <= hi]
            return sorted(xs, key=lambda c: -c["p"])[:n]
        out += top("bod", 3, 1.60, 2.50) + top("gol", 1, 1.60, 4.50) + top("asist", 1, 1.60, 3.00)

    docs = []
    for c in out:
        d = c["doc"]
        docs.append({"doc_id": f"{d['date']}_{slug(d['player'])}_{d['market']}", "data": d})
    json.dump({"date": data["date"], "count": len(docs), "picks": docs}, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
