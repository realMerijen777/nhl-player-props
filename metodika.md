# NHL player props – metodika fair kurzů (v1.0, 26. 10. 2026)

Cíl: každý den vybrat nejlepší kandidáty na trhy **Získá bod / Dá gól / Získá asistenci**, spočítat fair kurz a minimální kurz pro sázku. Kurzy bookmakerů (Fortuna, Tipsport) porovnává uživatel sám.

## 1. Zdroje dat (v tomto pořadí)

| Data | Zdroj | Jak se k němu dostat |
|---|---|---|
| Zápasy dne | ESPN / NHL.com schedule | WebSearch "NHL schedule <datum>" |
| Lajny, PP1/PP2 | DailyFaceoff `dailyfaceoff.com/teams/<tym>/line-combinations` | WebSearch "DailyFaceoff <tým> line combinations" → WebFetch |
| Brankáři | DailyFaceoff starting goalies | WebSearch "DailyFaceoff starting goalies" → WebFetch |
| Aktuální sezóna (GP, G, A, PTS) | hockey-reference `leagues/NHL_2027_skaters.html` | WebSearch → WebFetch |
| TOI EV/PP | hockey-reference `leagues/NHL_2027_skaters-time-on-ice.html` | WebSearch → WebFetch |
| Minulá sezóna | hockey-reference `leagues/NHL_2026_skaters.html` | WebSearch → WebFetch |
| Obdržené góly týmů (GA/GP) | hockey-reference `leagues/NHL_2027.html` nebo ESPN standings | WebSearch → WebFetch |

Pravidlo: když data chybí nebo jsou zjevně stará, hráče **vyřaď**. Nikdy neodhaduj čísla z paměti.

## 2. Výpočet

**Krok 1 – blendovaná produkce na zápas (shrinkage):**
```
w = GP_akt / (GP_akt + 20)
PPG = w × PPG_akt + (1 − w) × PPG_min
```
- PPG = body/zápas (pro gól G/zápas, pro asistenci A/zápas).
- Nováček bez minulé sezóny: místo PPG_min použij 0,40 (útočník) / 0,25 (obránce) a do zdůvodnění napiš "nízká jistota".

**Krok 1b – forma (posledních 5 zápasů):**
```
rate_L5 = X za posledních 5 zápasů / 5
PPG_final = 0,80 × PPG + 0,20 × rate_L5
```
Váha formy je záměrně jen 20 %: 5 zápasů je statisticky hlavně šum.

**Krok 1c – čas na ledě (TOI):**
```
k_toi = (TOI_posl.5 / TOI_sezóna) ^ 0,8, omezeno na 0,85–1,15
```
TOI je lepší ukazatel změny role než body. Data: NHL API přes repo nhl-player-props (GitHub Action 05:10), výpočet v compute.py.

**Krok 2 – role (změna lajny / PP oproti minulé sezóně):**
- Hráč posunut do PP1, minule PP2/bez PP: ×1,08
- Hráč vypadl z PP1: ×0,90
- Posun do top-6 z bottom-6: ×1,08; opačně ×0,88
- Beze změny: ×1,00

**Krok 3 – zápasové koeficienty:**
- Soupeř: `k_opp = 1 + 0,5 × (GA/GP_soupeř / GA/GP_liga − 1)` (polovina efektu, raná sezóna je šum)
- Brankář soupeře: potvrzený záložník ×1,05; elitní jednička ×0,95; jinak ×1,00
- Domácí ×1,02, venku ×0,98
- Back-to-back týmu hráče ×0,97

**Krok 4 – pravděpodobnost:**
```
λ = PPG_final × k_toi × role × k_opp × k_brankář × k_dom × k_b2b × 0,97
P = 1 − e^(−λ)
fair kurz = 1 / P
min. kurz = fair × 1,08
```
Koeficient 0,97 koriguje přestřelení Poissona (overdispersion). Kalibrace po 100+ tipech.

**Kontrola na tipérově příkladu:** 52 b / 58 z → PPG 0,897 → P = 59,2 % → fair 1,69 (tipér uvedl 1,70). ✔

## 3. Výběr kandidátů (pravidla uživatele od 26. 10. 2026)

- **Trhy:** Získá bod (kanadský bod), Dá gól, Získá asistenci.
- **Názvy týmů vždy celé** (Edmonton Oilers, ne EDM).
- **Minimální kurz 1,90.** Min. kurz pro sázku = max(1,90; fair × 1,08).
- **Max. 1 sázka na zápas**, a to ta s nejvyšším EV. Vybírá ji tracker po zadání kurzů (značka "TOP zápasu").
- **Shortlist na zápas** (aby bylo z čeho vybrat): 3 nejlepší kandidáti na bod (P 40–62 %, tedy fair 1,60–2,50) + 1 nejlepší na gól + 1 nejlepší na asistenci (oba fair ≥ 1,60). Hráče s fair pod 1,60 nevypisovat, kurz 1,90+ u nich bookmaker nedá.
- Pokud uživatel pošle tipy tipéra na daný den, spočítej pro ně fair kurz stejnou metodikou a zapiš je se `source: "tiper"` (paralelní srovnání).
- Seřadit podle P sestupně v rámci trhu.

## 4. Vklad (uživatel ho určuje až podle kurzu)

| EV = kurz × P − 1 | Vklad |
|---|---|
| kurz < 1,90 | nesázet |
| < 8 % | nesázet |
| 8–12 % | 4/10 |
| 12–20 % | 5/10 |
| > 20 % | 6/10 (strop; > 30 % = prověřit, jestli nechybí info o sestavě) |

## 5. Formát výstupu

Jeden kompaktní přehled za den, seřazený podle trhu:

| Zápas (čas SEČ) | Hráč | Trh | P | Fair | Min. kurz | Důvod (1 řádek) |

Důvod obsahuje: lajna, PP jednotka, produkce (např. "L1, PP1, 0,95 b/z, soupeř 3,6 GA/z").

## 6. Vyhodnocení

- Každý kandidát se zapisuje do trackeru, i když se nevsadí. Výsledek (trefa ano/ne) se doplní automaticky další den.
- Kalibrace: po 100 kandidátech porovnat průměrné P a skutečnou úspěšnost po pásmech (40–50, 50–60, 60+ %). Odchylka > 5 p. b. → upravit koeficient 0,97.
- Uživatel doplňuje kurz a "vsazeno"; ROI se počítá jen ze vsazených.
