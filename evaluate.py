"""Vyhodnotí včerejší tipy z trackeru proti box score v data/latest.json.

Použití:
  python evaluate.py data/latest.json <složka s dokumenty trackeru> > hits.json

Složka = výstup ArtifactData query s out_dir (soubory <doc_id>.json s daty dokumentu).
Výstup: [{"doc_id": ..., "hit": true|false|"void"}], jen pro dokumenty, které jde rozhodnout.
Párování: player_id, jinak iniciála + příjmení v rámci týmu (box score má "B. Tkachuk").
"""
import glob
import json
import os
import sys

from compute import norm

NEED = {"bod": "pts", "gol": "g", "asist": "a"}
FINAL = {"OFF", "FINAL"}


def short(name):
    parts = (name or "").split()
    return norm(parts[0][:1] + parts[-1]) if len(parts) >= 2 else norm(name)


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    name_to_ab = {t["name"]: ab for ab, t in data["teams"].items()}
    games = data["results_yesterday"]["games"]
    out = []
    for f in sorted(glob.glob(os.path.join(sys.argv[2], "**", "*.json"), recursive=True)):
        doc = json.load(open(f, encoding="utf-8"))
        if doc.get("hit") is not None or doc.get("market") not in NEED:
            continue
        ab = name_to_ab.get(doc.get("team"))
        g = next((x for x in games if ab in (x["away"], x["home"])), None)
        if not g or g.get("state") not in FINAL:
            continue
        team_rows = g["players"]
        row = None
        if doc.get("player_id"):
            row = next((r for r in team_rows if r["id"] == doc["player_id"]), None)
        if row is None:
            cands = [r for r in team_rows if short(r["name"]) == short(doc["player"]) or norm(r["name"]) == norm(doc["player"])]
            if len(cands) > 1:
                continue  # nejednoznačné jméno, nechat na ruční kontrolu
            row = cands[0] if cands else None
        doc_id = os.path.splitext(os.path.basename(f))[0]
        if row is None:
            out.append({"doc_id": doc_id, "hit": "void"})
        else:
            out.append({"doc_id": doc_id, "hit": row[NEED[doc["market"]]] >= 1})
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
