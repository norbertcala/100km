#!/usr/bin/env python3
"""Tworzy tomek.html z index.html (wersja z pozycją „Auto Tomka”). Uruchom po każdej zmianie index.html."""
from pathlib import Path

here = Path(__file__).resolve().parent
h = (here / "index.html").read_text("utf-8")
flag = '<script>window.KOSZT100_TOMEK = true; window.KOSZT100_SITE_URL = "https://techlove.pl/100km/tomek.html";</script>\n'
marker = '<script src="https://cdn.jsdelivr.net/npm/html-to-image'
assert marker in h
t = h.replace(marker, flag + marker, 1)
t = t.replace("<title>Koszt 100 km</title>", "<title>Koszt 100 km – Auto Tomka</title>")
t = t.replace('<meta name="description"', '<meta name="robots" content="noindex">\n<meta name="description"', 1)
(here / "tomek.html").write_text(t, "utf-8")
print("Zapisano tomek.html")
