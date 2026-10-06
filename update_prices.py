#!/usr/bin/env python3
"""
Aktualizuje data.json dla strony "Koszt 100 km".

Źródła pobierane automatycznie:
  - Pb95 i ON: najnowsze obwieszczenie Ministra Energii o cenie maksymalnej (Monitor Polski,
          publiczne API ELI Sejmu). Gdy cena maksymalna nie obowiązuje -> średnia e-petrol.pl.
  - LPG: średnia krajowa e-petrol.pl (aktualizowana co tydzień).
  - AC / DC: ranking cen ładowania elektromobilni.pl (stawki GreenWay i IONITY).
Wartości ręczne (config.json): średnia cena prądu w domu (G11 z dystrybucją) i cena wodoru Orlen.

Gdy któreś źródło nie odpowie albo zmieni układ strony, zostaje poprzednia wartość
z data.json - strona nigdy nie pokaże pustego miejsca.

Wymaga: Python 3.9+, pypdf (pip install pypdf).
Użycie:  python3 update_prices.py            (zapisuje data.json obok skryptu)
"""
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover
    WARSAW = timezone(timedelta(hours=2))

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
DATA = HERE / "data.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
ELI_BASE = "https://api.sejm.gov.pl/eli/acts/MP"
RANKING_URL = "https://elektromobilni.pl/ranking-cen-ladowania-w-polsce/"
EPETROL_URL = "https://www.e-petrol.pl/notowania/rynek-krajowy/ceny-stacje-paliw"
AUTOCENTRUM_URL = "https://www.autocentrum.pl/paliwa/ceny-paliw/"
MAX_PRICE_AGE_DAYS = 5  # starsze obwieszczenie = cena maksymalna już nie obowiązuje


def log(msg):
    print(msg, file=sys.stderr)


def http_get(url, binary=False, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "pl-PL,pl;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json,application/pdf,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw if binary else raw.decode("utf-8", errors="replace")


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


# ---------- Pb95 i ON: cena maksymalna z Monitora Polskiego ----------

def parse_max_price_text(text):
    """Z tekstu obwieszczenia wyciąga ceny brutto (z VAT) za litr: {'pb95': .., 'on': ..}."""
    t = re.sub(r"\s+", " ", text)
    out = {}
    for key, label in (("pb95", r"bezołowiowej 95"), ("on", r"oleju napędowego")):
        m = re.search(label + r".*?powiększona o podatek od towarów i usług wynosi (\d+,\d{2}) zł",
                      t, flags=re.IGNORECASE)
        if m:
            out[key] = num(m.group(1))
    return out


def fetch_max_prices(today):
    from pypdf import PdfReader  # import tutaj, żeby reszta działała bez pypdf

    items = []
    for year in {today.year, (today - timedelta(days=7)).year}:
        data = json.loads(http_get(f"{ELI_BASE}/{year}"))
        for it in data.get("items", []):
            if "maksymalnej ceny paliw" in (it.get("title") or "").lower():
                items.append(it)
    if not items:
        raise RuntimeError("brak obwieszczeń o cenie maksymalnej")

    def ann(it):
        return (it.get("announcementDate") or it.get("promulgation") or "")[:10]

    items.sort(key=lambda it: (ann(it), it.get("pos", 0)), reverse=True)
    today_s = today.strftime("%Y-%m-%d")
    # Obwieszczenie obowiązuje od dnia następnego -> dziś obowiązuje to sprzed dzisiaj.
    current = next((it for it in items if ann(it) < today_s), items[0])
    ann_date = datetime.strptime(ann(current), "%Y-%m-%d").date()
    if (today - ann_date).days > MAX_PRICE_AGE_DAYS:
        raise RuntimeError(f"ostatnie obwieszczenie z {ann_date} - cena maksymalna nie obowiązuje")

    pdf = http_get(f"{ELI_BASE}/{current['year']}/{current['pos']}/text.pdf", binary=True)
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    prices = parse_max_price_text(text)
    if "pb95" not in prices:
        raise RuntimeError("nie znaleziono ceny Pb95 w obwieszczeniu")
    url = f"https://api.sejm.gov.pl/eli/acts/MP/{current['year']}/{current['pos']}/text.pdf"
    return prices, url, ann_date


# ---------- e-petrol: średnie ceny detaliczne (LPG zawsze, Pb95/ON gdy brak ceny maks.) ----------

EPETROL_KEYS = {"Pb98": "pb98", "Pb95": "pb95", "ON": "on", "LPG": "lpg"}


def parse_epetrol(html):
    """Tabela 'Średnie ceny detaliczne paliw w Polsce': Aktualizacja | Pb98 | Pb95 | ON | LPG.
    Zwraca {'date': 'YYYY-MM-DD', 'pb98':.., 'pb95':.., 'on':.., 'lpg':..} dla najnowszego wiersza."""
    t = re.sub(r"</t[dh]>|<br\s*/?>|</tr>|</p>|</div>", " ", html, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"&nbsp;|\s+", " ", t)
    order = ["pb98", "pb95", "on", "lpg"]
    h = t.find("Aktualizacja")
    if h >= 0:
        found = re.findall(r"\b(Pb ?98|Pb ?95|ON|LPG)\b", t[h:h + 200])
        keys = [EPETROL_KEYS[f.replace(" ", "")] for f in found]
        if sorted(keys[:4]) == sorted(order):
            order = keys[:4]
    num_re = r"(\d{1,2}[,.]\d{2})"
    rows = []
    date_re = r"(\d{4}-\d{2}-\d{2}|\d{2}[./-]\d{2}[./-]\d{4})"
    for m in re.finditer(date_re + r"\s+" + r"\s+".join([num_re] * 4), t):
        d = m.group(1)
        if not d[:4].isdigit():  # DD.MM.YYYY -> YYYY-MM-DD
            d = f"{d[6:10]}-{d[3:5]}-{d[0:2]}"
        rows.append((d,) + m.groups()[1:])
    if not rows:
        return None
    date, *vals = max(rows, key=lambda r: r[0])
    out = {"date": date}
    for k, v in zip(order, vals):
        out[k] = num(v)
    if not (4 < out.get("pb95", 0) < 15 and 1 < out.get("lpg", 0) < 8):
        return None
    return out


def parse_autocentrum(html):
    """Średnia krajowa LPG z autocentrum.pl (przycisk 'LPG 3,16 zł')."""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;|\s+", " ", t)
    m = re.search(r"\bLPG\s*(\d,\d{2})\s*zł", t)
    if not m:
        return None
    v = num(m.group(1))
    return v if 1 < v < 8 else None


# ---------- AC / DC: ranking elektromobilni.pl ----------

def parse_ranking(html):
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;|\s+", " ", t)
    out = {}
    gw = {}
    for plan in ("STANDARD", "PLUS", "MAX"):
        m = re.search(rf"Energia {plan}[^:]*:\s*AC\s*(\d+,\d+)\s*zł/kWh,\s*DC\s*(\d+,\d+)", t)
        if m:
            gw[plan] = (num(m.group(1)), num(m.group(2)))
    ion = {}
    for plan in ("Direct", "Go", "Motion", "Power"):
        m = re.search(rf"IONITY {plan}:\s*(\d+,\d+)\s*zł/kWh", t)
        if m:
            ion[plan] = num(m.group(1))

    if "PLUS" in gw:
        out["ac"] = gw["PLUS"][0]  # GreenWay Energia PLUS - typowy słupek miejski
    lows = [v for v in (gw.get("MAX", (None, None))[1], ion.get("Motion")) if v]
    highs = [v for v in (gw.get("STANDARD", (None, None))[1], ion.get("Go")) if v]
    if lows:
        out["dc_min"] = min(lows)
    if highs:
        out["dc_max"] = max(highs)
    m = re.search(r"Stan na:\s*(\d{2}/\d{2}/\d{4})", t)
    if m:
        out["as_of"] = m.group(1)
    return out


# ---------- main ----------

def main():
    cfg = json.loads(CONFIG.read_text("utf-8"))
    old = json.loads(DATA.read_text("utf-8")) if DATA.exists() else {}
    fb = cfg["fallback"]
    prices = {
        "ac": fb["ac_pln_kwh"], "dc_min": fb["dc_min_pln_kwh"], "dc_max": fb["dc_max_pln_kwh"],
        "pb95": fb["pb95_pln_l"], "pb95_kind": fb["pb95_kind"],
        "on": fb["on_pln_l"], "on_kind": fb["on_kind"], "lpg": fb["lpg_pln_l"],
    }
    prices.update({k: v for k, v in old.get("prices", {}).items()})
    prices.pop("g12w", None)
    prices["home"] = cfg["manual"]["home_pln_kwh"]
    prices["home_night"] = cfg["manual"]["home_night_pln_kwh"]
    prices["h2"] = cfg["manual"]["h2_pln_kg"]
    sources = old.get("sources", {})
    used = []
    status = {}
    now = datetime.now(WARSAW)

    # e-petrol: LPG zawsze, Pb95/ON jako zapas
    ep = None
    try:
        ep = parse_epetrol(http_get(EPETROL_URL))
        if not ep:
            raise RuntimeError("nie rozpoznano tabeli cen")
        log(f"e-petrol: {ep}")
        status["e-petrol"] = "ok"
    except Exception as e:
        log(f"e-petrol niedostępny ({e})")
        status["e-petrol"] = f"błąd: {e}"[:200]
        ep = None
    if ep:
        d = datetime.strptime(ep["date"], "%Y-%m-%d")
        prices["lpg"] = ep["lpg"]
        sources["lpg"] = {"name": f"e-petrol.pl – średnia krajowa z {d:%d.%m.%Y}", "url": EPETROL_URL, "auto": True}
        used.append("e-petrol")
    else:
        try:
            v = parse_autocentrum(http_get(AUTOCENTRUM_URL))
            if not v:
                raise RuntimeError("nie rozpoznano ceny LPG")
            prices["lpg"] = v
            sources["lpg"] = {"name": f"AutoCentrum.pl – średnia krajowa z {now:%d.%m.%Y}", "url": AUTOCENTRUM_URL, "auto": True}
            used.append("AutoCentrum")
            status["autocentrum"] = "ok"
            log(f"LPG (AutoCentrum): {v}")
        except Exception as e:
            status["autocentrum"] = f"błąd: {e}"[:200]
            log(f"LPG: zostaje poprzednia wartość ({e})")

    # Pb95 i ON: cena maksymalna, a gdy nie obowiązuje - średnia e-petrol
    try:
        mx, url, ann_date = fetch_max_prices(now.date())
        name = f"Monitor Polski – obwieszczenie ME z {ann_date:%d.%m.%Y}"
        for k in ("pb95", "on"):
            if k in mx:
                prices[k], prices[k + "_kind"] = mx[k], "max"
                sources[k] = {"name": name, "url": url, "auto": True}
        used.insert(0, "Monitor Polski")
        status["monitor-polski"] = "ok"
        log(f"Ceny maks.: {mx}")
    except Exception as e:
        status["monitor-polski"] = f"błąd: {e}"[:200]
        log(f"Ceny maks. niedostępne ({e}) - biorę średnie e-petrol")
        if ep:
            d = datetime.strptime(ep["date"], "%Y-%m-%d")
            for k in ("pb95", "on"):
                prices[k], prices[k + "_kind"] = ep[k], "avg"
                sources[k] = {"name": f"e-petrol.pl – średnia krajowa z {d:%d.%m.%Y}", "url": EPETROL_URL, "auto": True}
        else:
            log("Pb95/ON: zostają poprzednie wartości")

    # AC / DC
    try:
        r = parse_ranking(http_get(RANKING_URL))
        for k in ("ac", "dc_min", "dc_max"):
            if k in r:
                prices[k] = r[k]
        note = f" (stan na {r['as_of']})" if "as_of" in r else ""
        for k in ("ac", "dc"):
            sources[k] = {"name": "Ranking cen ładowania – elektromobilni.pl" + note, "url": RANKING_URL, "auto": True}
        used.append("elektromobilni.pl")
        status["elektromobilni"] = "ok"
        log(f"Ładowanie: {r}")
    except Exception as e:
        status["elektromobilni"] = f"błąd: {e}"[:200]
        log(f"Ranking ładowania: zostają poprzednie wartości ({e})")

    sources.pop("g12w", None)
    sources["home"] = {"name": "Prąd w domu: średnia G11 2026 z dystrybucją i opłatami (PGE, Tauron, Enea, Energa, E.ON)",
                       "url": "https://biznes.interia.pl/gospodarka/news-ile-kosztuje-1-kwh-w-2026-roku-ceny-pradu-w-tauronie-pge-i-u,nId,23478259",
                       "auto": False}
    sources["home_night"] = {"name": "Prąd w nocy: średnia strefy tańszej G12/G12w 2026 z dystrybucją (Enea, Tauron, PGE, Energa)",
                             "url": "https://biznes.interia.pl/gospodarka/news-ile-kosztuje-1-kwh-w-2026-roku-ceny-pradu-w-tauronie-pge-i-u,nId,23478259",
                             "auto": False}
    sources.setdefault("h2", {"name": "Orlen H2", "url": "https://www.orlen.pl", "auto": False})
    sources.setdefault("consumption", {"name": "Zużycie: KE – dane OBFCM (realne spalanie ~20% powyżej WLTP)",
                                       "url": "https://climate.ec.europa.eu/news-other-reads/news/first-commission-report-real-world-co2-emissions-cars-and-vans-using-data-board-fuel-consumption-2024-03-18_en",
                                       "auto": False})

    seen = []
    for u in ["Orlen H2", "Taryfy URE"] + used:
        if u not in seen:
            seen.append(u)
    data = {
        "updated": now.isoformat(timespec="seconds"),
        "distance_km": cfg["distance_km"],
        "consumption": cfg["consumption"],
        "prices": prices,
        "sources": sources,
        "footer": "Dane: " + " / ".join(seen),
        "status": status,
    }
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    log("Zapisano data.json")
    return 0  # częściowa porażka nie blokuje publikacji; szczegóły w logu


if __name__ == "__main__":
    sys.exit(main())
