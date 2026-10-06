# Koszt 100 km

Strona porównująca koszt przejechania 100 km: gniazdko (G12w), ładowarka AC, szybkie DC, benzyna Pb95 i wodór. Wygląd 1:1 jak grafika, liczby liczone z `data.json`.

## Pliki

| Plik | Do czego |
|---|---|
| `index.html` | Strona. Wczytuje `data.json`; gdy się nie uda, pokazuje dane wbudowane (te z grafiki). |
| `data.json` | Aktualne ceny i źródła. Nadpisywany przez skrypt. |
| `config.json` | Wartości ręczne (G12w, wodór) i założenia zużycia. |
| `update_prices.py` | Pobiera ceny z sieci i zapisuje `data.json`. |
| `.github/workflows/update.yml` | Uruchamia skrypt 2× dziennie na GitHubie. |

## Skąd są dane

| Pozycja | Źródło | Tryb |
|---|---|---|
| Pb95 | Obwieszczenie Ministra Energii o cenie maksymalnej (Monitor Polski, API ELI Sejmu: `api.sejm.gov.pl/eli/acts/MP/{rok}`) | automat |
| Diesel (ON) | To samo obwieszczenie (cena maksymalna oleju napędowego); gdy nie obowiązuje — średnia e-petrol | automat |
| LPG | Średnia krajowa e-petrol.pl (tabela „Średnie ceny detaliczne paliw w Polsce”, aktualizacja co tydzień) | automat |
| Pb95 (gdy cena maks. nie obowiązuje) | Średnia krajowa e-petrol.pl — etykieta zmienia się z „Maks.” na „Śr.” | automat |
| AC | GreenWay Energia PLUS, z rankingu cen ładowania elektromobilni.pl | automat |
| DC | od: min(GreenWay MAX, IONITY Motion), do: max(GreenWay STANDARD, IONITY Go) — ten sam ranking | automat |
| G12w | Taryfa URE (strefa tania, brutto z dystrybucją) | ręcznie w `config.json`, raz w roku |
| Wodór | Cena Orlen na stacjach H2 | ręcznie w `config.json` — Orlen nie publikuje cennika do pobrania |

Gdy źródło nie odpowie albo zmieni układ strony, skrypt zostawia poprzednią wartość.

## Obliczenia

- EV: średnia z 17–18 kWh/100 km (gniazdko i AC); DC: stawka minimalna × 17 kWh, maksymalna × 18 kWh
- Pb95: cena × 7,0 l; diesel: × 6,0 l; LPG: × 8,8 l (ok. 25% więcej niż benzyna); wodór: × 1,09 kg (wyświetlane jako ~1,1)
- Zużycie realne, nie katalogowe: wg danych KE (OBFCM) auta spalają w praktyce ok. 20% więcej niż według WLTP. Wartości zmienisz w `config.json`.
- Lider / najdroższa opcja wybierane automatycznie; „+X% drożej” zaokrąglane w dół

## Pobierz obrazek

Przycisk w nagłówku zapisuje PNG (1628 px szerokości) w układzie oryginalnej grafiki, z dopiskiem „Pobrano z serwisu https://techlove.pl/100km/ · dane z …”. Adres zmienisz przez `window.KOSZT100_SITE_URL`.

## Uruchomienie (GitHub Pages, za darmo)

1. Repozytorium `norbertcala/100km` — pliki już są w środku.
2. Settings → Pages → Deploy from branch → `main` / root.
3. Settings → Actions → General → Workflow permissions → **Read and write**.
4. Actions → „Aktualizuj ceny” → **Run workflow** (pierwsze uruchomienie ręcznie).

## Osadzenie na WordPressie

Wklej całe `index.html` (albo wgraj go jako `/100km/index.html`). Poza GitHub Pages strona sama pobiera dane z `https://raw.githubusercontent.com/norbertcala/100km/main/data.json`, więc nic nie trzeba ustawiać.

## Lokalnie / QNAP

```bash
pip install pypdf
python3 update_prices.py   # cron np. 47 10,15 * * *
```
