"""Fair kurzy na střely hráčů na branku (SOG). Samostatné od bodů.

Použití:
  python compute_shots.py data/latest.json lines.json > out.json

Metodika (metodika.md, sekce Střely):
- rate = shrinkage sezóna/min. sezóna (jako u bodů) + 20 % forma posledních 5 zápasů
- × čas na ledě (TOI posl. 5 / TOI sezóna)^0,8, omezeno 0,85–1,15
- × soupeř: 1 + 0,5·(střely proti soupeři za zápas / průměr ligy − 1)
- × doma 1,02 / venku 0,98, back-to-back 0,97
- rozdělení: negativně binomické (střely jsou rozptýlenější než Poisson), r = 12
- linie 1,5 / 2,5 / 3,5 / 4,5; u hráče se bere nejvyšší linie s fair 1,60–2,50
"""
import json
import math
import sys

from compute import norm, slug, fmt, k_toi, W_PRIOR_GP, W_FORM, EDGE, MIN_ODDS

NB_R = 12.0
LINES = [1.5, 2.5, 3.5, 4.5]
ROOKIE_SOG = {"F": 1.6, "D": 1.1}


def nb_cdf_below(k, mu, r=NB_R):
    """P(X <= k) pro negativně binomické rozdělení se střední hodnotou mu a parametrem r."""
    p = r / (r + mu)
    pmf = p ** r  # P(X=0)
    total = pmf
    for x in range(1, k + 1):
        pmf *= (x - 1 + r) / x * (1 - p)
        total += pmf
    return total


def shot_rate(p):
    cur, prev, last = p["cur"], p["prev"], p["last"]
    gp = cur["gp"] or 0
    w = gp / (gp + W_PRIOR_GP)
    pos = "D" if p.get("pos") == "D" else "F"
    if prev.get("gp", 0) >= 10 and "sog" in prev:
        prior, low = prev["sog"] / prev["gp"], False
    else:
        prior, low = ROOKIE_SOG[pos], True
    cur_rate = cur.get("sog", 0) / gp if gp else prior
    base = w * cur_rate + (1 - w) * prior
    if last["gp"] >= 3 and "sog" in last:
        form = last["sog"] / last["gp"]
        return (1 - W_FORM) * base + W_FORM * form, form, low
    return base, None, low


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    lines = json.load(open(sys.argv[2], encoding="utf-8"))
    teams = data["teams"]
    lg_sa = data.get("league_sa_pg") or 28.5
    team_game = {}
    for g in data["games"]:
        team_game[g["away"]] = (g, False, g["home"])
        team_game[g["home"]] = (g, True, g["away"])

    def last(n):
        return norm(n.split()[-1]) if n else ""

    cands = []
    for p in data["players"]:
        tg, tl = team_game.get(p["team"]), lines.get(p["team"])
        if not tg or not tl:
            continue
        roles = tl.get("roles", {})
        role = None
        for k, v in roles.items():
            if norm(k) == norm(p["name"]):
                role = v
        if not role:
            same = [v for k, v in roles.items() if last(k) == last(p["name"])]
            team_same = [x for x in data["players"] if x["team"] == p["team"] and last(x["name"]) == last(p["name"])]
            role = same[0] if len(same) == 1 and len(team_same) == 1 else None
        if not role or role in ("L4", "D3"):
            continue
        pp1 = any(norm(x) == norm(p["name"]) or last(x) == last(p["name"]) for x in tl.get("pp1", []))
        g, home, opp = tg
        ot = teams.get(opp, {})
        osa = ot.get("sa_pg")
        k_opp = 1 + 0.5 * (osa / lg_sa - 1) if osa and ot.get("gp", 0) >= 3 else 1.0
        k_home = 1.02 if home else 0.98
        k_b2b = 0.97 if teams.get(p["team"], {}).get("b2b") else 1.0
        rate, form, low = shot_rate(p)
        mu = rate * k_toi(p) * k_opp * k_home * k_b2b
        if mu <= 0:
            continue
        best = None
        for ln in LINES:
            P = 1 - nb_cdf_below(int(ln), mu)
            fair = 1 / P if P > 0 else 99
            if 1.60 <= fair <= 2.50:
                best = (ln, P, fair)  # nejvyšší linie, která splní pásmo
        if not best:
            continue
        ln, P, fair = best
        notes = []
        if form is not None:
            notes.append(f"forma {p['last']['sog']} stř. v {p['last']['gp']} z")
        if p["last"].get("toi_avg") and p["cur"].get("toi_avg"):
            notes.append(f"TOI {fmt(p['last']['toi_avg'],1)} vs {fmt(p['cur']['toi_avg'],1)} min")
        if k_b2b < 1:
            notes.append("back-to-back")
        if low:
            notes.append("nízká jistota")
        opp_txt = f"{ot.get('name', opp)} povoluje {fmt(osa,1)} stř./z" if osa else f"{ot.get('name', opp)} n/a"
        reason = (f"{role}{', PP1' if pp1 else ''}; letos {p['cur'].get('sog',0)} stř. v {p['cur']['gp']} z, "
                  f"min. sez. {p['prev'].get('sog',0)} v {p['prev']['gp']} z → očekáváno {fmt(mu)} stř.; "
                  f"{'; '.join(notes) + '; ' if notes else ''}soupeř {opp_txt}")
        market = f"sog{str(ln).replace('.', '')}"
        cands.append({
            "game_id": g["id"], "p": P,
            "doc_id": f"{g['date_prague']}_{slug(p['name'])}_{market}",
            "data": {
                "date": g["date_prague"],
                "game": f"{teams[g['away']]['name']} @ {teams[g['home']]['name']}",
                "time": f"{g['start_prague']} SEČ",
                "player": p["name"], "team": teams[p["team"]]["name"],
                "market": market, "line": ln, "mu": round(mu, 2),
                "p": round(P, 3), "fair": round(fair, 2), "min": round(max(MIN_ODDS, fair * EDGE), 2),
                "reason": reason, "hit": None, "odds": None, "bet": False, "source": "model",
            },
        })

    # Shortlist: 4 hráči na zápas s nejvyšší P, max. 2 z jednoho týmu
    out = []
    for g in data["games"]:
        gc = sorted([c for c in cands if c["game_id"] == g["id"]], key=lambda c: -c["p"])
        per_team, picked = {}, []
        for c in gc:
            t = c["data"]["team"]
            if per_team.get(t, 0) >= 2:
                continue
            per_team[t] = per_team.get(t, 0) + 1
            picked.append(c)
            if len(picked) == 4:
                break
        out += picked
    json.dump({"date": data["date"], "count": len(out),
               "picks": [{"doc_id": c["doc_id"], "data": c["data"]} for c in out]},
              sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
