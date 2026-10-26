# NHL player props – metodika fair kurzů (v2.0, 26. 10. 2026)

Cíl: každý den shortlist kandidátů na trhy **Získá bod / Dá gól / Získá asistenci** s fair kurzem a minimálním kurzem pro sázku. Kurzy Fortuny a Tipsportu porovnává uživatel sám v deníku. Výpočet je v kódu (`compute.py`), takže je každý den stejný.

## 1. Zdroje dat

| Data | Zdroj | Kdy |
|---|---|---|
| Rozpis, statistiky hráčů, forma 5 zápasů, čas na ledě, minulá sezóna, góly týmů, včerejší box score | **NHL API** (`fetch_data.py`, GitHub Action) | 05:10 SEČ |
| Lajny, PP1, potvrzení brankáři | **DailyFaceoff** (ranní úloha Claude) | 06:43 SEČ |

Pravidlo: hráč bez role v lajnách nebo bez dat se vyřadí. Nic se nedoplňuje z paměti.

## 2. Výpočet

**Krok 1 – produkce na zápas (shrinkage):**
```
w = GP_akt / (GP_akt + 20)
rate = w × X_akt/GP_akt + (1 − w) × X_min/GP_min
```
X = body (bod), góly (gól), asistence (asistence). Bez minulé sezóny (pod 10 z): 0,40 / 0,15 / 0,25 útočník, 0,25 / 0,05 / 0,20 obránce, "nízká jistota".

**Krok 2 – forma (posledních 5 zápasů):**
```
rate_final = 0,80 × rate + 0,20 × (X za posl. 5 z / 5)
```
Váha jen 20 %: 5 zápasů je hlavně šum.

**Krok 3 – čas na ledě:**
```
k_toi = (TOI posl. 5 z / TOI sezóna) ^ 0,8, omezeno 0,85–1,15
```

**Krok 4 – zápasové koeficienty:**
- Soupeř: `k_opp = 1 + 0,5 × (GA/z soupeře / GA/z ligy − 1)` (polovina efektu, raná sezóna je šum)
- Brankář soupeře: potvrzený záložník ×1,05, elitní jednička ×0,95, jinak ×1,00
- Domácí ×1,02, venku ×0,98

Kurzy na zápas (Pinnacle apod.) se do modelu záměrně nepoužívají (rozhodnutí uživatele 26. 10. 2026).

**Krok 5 – pravděpodobnost:**
```
λ = rate_final × k_toi × k_opp × k_brankář × k_dom × k_b2b × 0,97      (k_b2b = 0,97 při back-to-back)
P = 1 − e^(−λ)
fair = 1 / P,  min. kurz = max(1,70; fair × 1,08)
```
Koeficient 0,97 koriguje přestřelení Poissona. Kalibrace po 100+ tipech.

## 3. Výběr kandidátů

- **Trhy:** bod, gól, asistence. Názvy týmů vždy celé.
- **Minimální kurz 1,70** (od 26. 10. 2026, předtím 1,90).
- **Max. 1 sázka na zápas**: ta s nejvyšším EV. Vybírá ji deník po zadání kurzů (štítek "TOP zápasu").
- **Shortlist na zápas:** jen útočníci z top-6 a obránci z top-4 s PP1. 3 kandidáti na bod (fair 1,55–2,50), 1 na gól (fair 1,55–4,50), 1 na asistenci (fair 1,55–3,00).

## 4. Vklad (1 jednotka = 1 % banku)

Podmínky: kurz ≥ min. kurz a EV = kurz × P − 1 ≥ 8 %.
```
Kelly = EV / (kurz − 1)
vklad = round(Kelly × 25), omezeno na 3–6 jednotek
```

| Příklad | Kelly | Vklad |
|---|---|---|
| kurz 2,00, EV 10 % | 0,10 | 3/10 |
| kurz 2,00, EV 20 % | 0,20 | 5/10 |
| kurz 1,75, EV 10 % | 0,13 | 3/10 |
| kurz 3,00, EV 20 % | 0,10 | 3/10 |

EV > 30 % = prověřit sestavu, něco pravděpodobně chybí.

## 5. Vyhodnocení

- Každý kandidát se zapisuje do deníku, i nevsazený. Výsledek doplní ranní běh z box score podle ID hráče (`evaluate.py`).
- Kalibrace po 100 kandidátech po pásmech P (40–50, 50–60, 60+ %). Odchylka > 5 p. b. → upravit koeficient 0,97.
- ROI se počítá jen ze vsazených.

## 6. Střely hráčů (připraveno, zatím vypnuto)

`compute_shots.py`: stejná logika (shrinkage, forma, TOI), soupeř podle povolených střel, negativně binomické rozdělení (r = 12), linie 1,5–4,5.
