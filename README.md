# nhl-player-props

Denní fair kurzy pro NHL player props (Získá bod / Dá gól / Asistence).

- `fetch_data.py`: GitHub Action ho spouští každé ráno v 05:10 SEČ. Stáhne z NHL API rozpis, statistiky, formu za posledních 5 zápasů, čas na ledě, obdržené góly týmů a včerejší box score do `data/latest.json`.
- `compute.py`: plánovaná úloha Claude ho v 7:00 spustí nad daty a nad `lines.json` (lajny, PP1, brankáři z DailyFaceoff) a výsledky zapíše do trackeru.
- `metodika.md`: vzorce a pravidla výběru.

Ruční spuštění: záložka Actions → "Denní data NHL" → Run workflow.
