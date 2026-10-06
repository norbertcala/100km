#!/usr/bin/env python3
"""
Aktualizuje data.json dla strony "Koszt 100 km".

Źródła pobierane automatycznie:
  - Pb95: najnowsze obwieszczenie Ministra Energii o cenie maksymalnej (Monitor Polski,
          publiczne API ELI Sejmu). Gdy cena maksymalna nie obowiązuje -> średnia e-petrol.pl.
  - AC / DC: ranking cen ładowania elektromobilni.pl (stawki GreenWay i IONITY).
Wartości ręczne (config.json): taryfa G12w (URE) i cena wodoru Orlen.

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

UA = "Mozilla/5.0 (koszt-100km updater; +https://techlove.pl)"
ELI_BASE = "https://api.sejm.gov.pl/eli/acts/MP"
RANKING_URL = "https://elektromobilni.pl/ranking-cen-ladowania-w-polsce/"
EPETROL_URL = "https://www.e-petrol.pl/notowania/rynek-krajowy/ceny-stacje-paliw"
MAX_PRICE_AGE_DAYS = 5  # starsze obwieszczenie = cena maksymalna już nie obowiązuje


def log(msg):
    print(msg, file=sys.stderr)


def http_get(url, binary=False, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pl-PL,pl"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw if binary else raw.decode("utf-8", errors="replace")


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


# ---------- Pb95: cena maksymalna z Monitora Polskiego ----------

def parse_max_price_text(text):
    """Z tekstu obwieszczenia wyciąga cenę Pb95 brutto (z VAT) za litr."""
    t = re.sub(r"\s+", " ", text)
    m = re.search(
        r"bezołowiowej 95.*?powiększona o podatek od towarów i usług wynosi (\d+,\d{2}) zł",
        t, flags=re.IGNORECASE)
    return num(m.group(1)) if m else None


def fetch_pb95_max(today):
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
    price = parse_max_price_text(text)
    if not price:
        raise RuntimeError("nie znaleziono ceny Pb95 w obwieszczeniu")
    url = f"https://api.sejm.gov.pl/eli/acts/MP/{current['year']}/{current['pos']}/text.pdf"
    return price, url, ann_date


# ---------- Pb95: średnia e-petrol (gdy brak ceny maksymalnej) ----------

def parse_epetrol(html):
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t)
    m = re.search(r"(?:Pb\s?95|Eurosuper 95|benzyna 95)\D{0,40}?(\d,\d{2})", t, flags=re.IGNORECASE)
    if not m:
        return None
    v = num(m.group(1))
    return v if 4.0 < v < 12.0 else None


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
    prices = dict(cfg["fallback"])
    prices = {
        "ac": prices["ac_pln_kwh"], "dc_min": prices["dc_min_pln_kwh"],
        "dc_max": prices["dc_max_pln_kwh"], "pb95": prices["pb95_pln_l"],
        "pb95_kind": prices["pb95_kind"],
    }
    prices.update({k: v for k, v in old.get("prices", {}).items()})
    prices["g12w"] = cfg["manual"]["g12w_pln_kwh"]
    prices["h2"] = cfg["manual"]["h2_pln_kg"]
    sources = old.get("sources", {})
    footer_fuel = "E-petrol"
    now = datetime.now(WARSAW)
    ok = True

    # Pb95
    try:
        price, url, ann_date = fetch_pb95_max(now.date())
        prices["pb95"], prices["pb95_kind"] = price, "max"
        sources["pb95"] = {"name": f"Monitor Polski – obwieszczenie ME z {ann_date:%d.%m.%Y}", "url": url, "auto": True}
        footer_fuel = "Monitor Polski"
        log(f"Pb95 (cena maks.): {price}")
    except Exception as e:
        log(f"Pb95 maks. niedostępna ({e}) - próbuję e-petrol")
        try:
            v = parse_epetrol(http_get(EPETROL_URL))
            if not v:
                raise RuntimeError("nie rozpoznano ceny na stronie")
            prices["pb95"], prices["pb95_kind"] = v, "avg"
            sources["pb95"] = {"name": "e-petrol.pl – średnia krajowa", "url": EPETROL_URL, "auto": True}
            log(f"Pb95 (średnia e-petrol): {v}")
        except Exception as e2:
            ok = False
            log(f"Pb95: zostaje poprzednia wartość ({e2})")

    # AC / DC
    try:
        r = parse_ranking(http_get(RANKING_URL))
        for k in ("ac", "dc_min", "dc_max"):
            if k in r:
                prices[k] = r[k]
        note = f" (stan na {r['as_of']})" if "as_of" in r else ""
        for k in ("ac", "dc"):
            sources[k] = {"name": "Ranking cen ładowania – elektromobilni.pl" + note, "url": RANKING_URL, "auto": True}
        log(f"Ładowanie: {r}")
        if not {"ac", "dc_min", "dc_max"} <= r.keys():
            ok = False
    except Exception as e:
        ok = False
        log(f"Ranking ładowania: zostają poprzednie wartości ({e})")

    sources.setdefault("g12w", {"name": "Taryfy URE", "url": "https://www.ure.gov.pl/pl/energia-elektryczna/taryfy", "auto": False})
    sources.setdefault("h2", {"name": "Orlen H2", "url": "https://www.orlen.pl", "auto": False})

    data = {
        "updated": now.isoformat(timespec="seconds"),
        "distance_km": cfg["distance_km"],
        "consumption": cfg["consumption"],
        "prices": prices,
        "sources": sources,
        "footer": f"Dane: Orlen H2 / Taryfy URE / {footer_fuel} / elektromobilni.pl",
    }
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    log("Zapisano data.json")
    return 0  # częściowa porażka nie blokuje publikacji; szczegóły w logu


if __name__ == "__main__":
    sys.exit(main())
