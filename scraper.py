#!/usr/bin/env python3
"""
scraper.py — Burraco Pinelle scraper
Gira su GitHub Actions, genera docs/partite.json
"""

import requests
import json
import re
import sys
import os
from bs4 import BeautifulSoup
from datetime import datetime
from collections import defaultdict
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL  = "https://www.burracoepinelle.com/burrachi_pinelle"
LOGIN_URL = f"{BASE_URL}/index.php?page=login"
HIST_URL  = f"{BASE_URL}/index.php?page=match_history_user&user=237071&p="
USER      = os.environ.get("BURRACO_USER", "ginola700")
PASSWD    = os.environ.get("BURRACO_PASS", "pippo")
PLAYER1   = "ginola700"
PLAYER2   = "zappaclaud"
OUT_FILE  = "docs/partite.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9",
}

MESI = {
    "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
    "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12,
    "gen":1,"feb":2,"mar":3,"apr":4,"mag":5,"giu":6,
    "lug":7,"ago":8,"set":9,"ott":10,"nov":11,"dic":12,
}

# ─── LOGIN ────────────────────────────────────────────────────────────────────

def login(s):
    print("Logging in...")
    try:
        r0 = s.get(LOGIN_URL, verify=False, timeout=20, headers=HEADERS)
        soup = BeautifulSoup(r0.text, "html.parser")
        form = soup.find("form")
        payload = {}
        action = LOGIN_URL
        if form:
            for inp in form.find_all("input"):
                n = inp.get("name", "")
                v = inp.get("value", "")
                if not n:
                    continue
                nl = n.lower()
                if any(k in nl for k in ("user","login","nome","nick")):
                    payload[n] = USER
                elif any(k in nl for k in ("pass","pwd","secret")):
                    payload[n] = PASSWD
                else:
                    payload[n] = v
            a = form.get("action") or ""
            if a:
                action = a if a.startswith("http") else BASE_URL + "/" + a.lstrip("/")
        else:
            payload = {"username": USER, "password": PASSWD, "submit": "entra"}

        s.post(
            action, data=payload, verify=False, timeout=20,
            headers={**HEADERS, "Referer": LOGIN_URL,
                     "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
        )
        print("Login attempted.")
        return True
    except Exception as e:
        print(f"Login error: {e}")
        return False

# ─── PARSING ──────────────────────────────────────────────────────────────────

def estrai_data(testi):
    for t in testi:
        m = re.search(r'\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b', t)
        if m:
            g, mo, a = m.groups()
            return f"{a}-{mo.zfill(2)}-{g.zfill(2)}", f"{g.zfill(2)}/{mo.zfill(2)}/{a}"
        m = re.search(r'\b(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})\b', t)
        if m:
            a, mo, g = m.groups()
            return f"{a}-{mo.zfill(2)}-{g.zfill(2)}", f"{g.zfill(2)}/{mo.zfill(2)}/{a}"
        m = re.search(r'\b(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})\b', t)
        if m:
            g, mese_s, a = m.groups()
            mo = MESI.get(mese_s.lower())
            if mo:
                return f"{a}-{str(mo).zfill(2)}-{g.zfill(2)}", f"{g.zfill(2)}/{str(mo).zfill(2)}/{a}"
    return None, None

def is_score(val):
    val = val.strip()
    if re.match(r'^-?\d{1,6}$', val):
        return -3000 <= int(val) <= 9999
    return False

def parse_row(row):
    tds   = row.find_all(["td","th"])
    testi = [td.get_text(" ", strip=True) for td in tds]
    raw   = " | ".join(testi)
    if "ITALIANO" not in raw.upper():
        return None

    data_iso, data_fmt = estrai_data(testi)
    punteggi, nomi = [], []

    SKIP_WORDS = ("italiano","classico","pinelle","burraco","data","gioco",
                  "tipo","risultato","partita","n°","num","id","stato","vs",
                  "vinci","perdi","pareggio")

    for t in testi:
        ts = t.strip()
        if is_score(ts):
            punteggi.append(int(ts))
        elif (len(ts) > 2
              and not re.match(r'^\d+$', ts)
              and not re.match(r'^\d{1,2}[\/\-]\d', ts)
              and ts not in ("-", "|")):
            if not any(k in ts.lower() for k in SKIP_WORDS):
                nomi.append(ts)

    if len(punteggi) < 2 or not data_fmt:
        return None

    return {
        "data_iso": data_iso,
        "data":     data_fmt,
        "nome1":    nomi[0] if len(nomi) > 0 else "",
        "nome2":    nomi[1] if len(nomi) > 1 else "",
        "score1":   punteggi[0],
        "score2":   punteggi[1],
        "raw":      testi,
    }

# ─── SCRAPING ─────────────────────────────────────────────────────────────────

def scrape_page(s, page):
    url = HIST_URL + str(page)
    try:
        r = s.get(url, verify=False, timeout=20, headers=HEADERS)
        if r.status_code != 200:
            return [], False
        soup = BeautifulSoup(r.text, "html.parser")
        if page == 0:
            os.makedirs("docs", exist_ok=True)
            with open("docs/debug_p0.html", "w", encoding="utf-8") as f:
                f.write(r.text)
        rows = []
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                p = parse_row(tr)
                if p:
                    rows.append(p)
        has_next = bool(re.search(rf'p={page+1}', r.text))
        return rows, has_next
    except Exception as e:
        print(f"  Error p={page}: {e}")
        return [], False

# ─── STATISTICHE ──────────────────────────────────────────────────────────────

def identifica(r):
    n1 = (r.get("nome1") or "").lower()
    n2 = (r.get("nome2") or "").lower()
    p1, p2 = PLAYER1.lower(), PLAYER2.lower()
    if p1 in n1 and p2 in n2:
        return r["score1"], r["score2"]
    if p2 in n1 and p1 in n2:
        return r["score2"], r["score1"]
    # solo il giocatore loggato visibile
    if p1 in n1:
        return r["score1"], r["score2"]
    if p1 in n2:
        return r["score2"], r["score1"]
    return None

def calcola(raw_rows):
    per_giorno = defaultdict(lambda: {
        "data_fmt":"", "ginola_v":0, "zappa_v":0,
        "ginola_pts":0, "zappa_pts":0, "partite":[]
    })
    tot_g = tot_z = 0

    for r in raw_rows:
        res = identifica(r)
        if res is None:
            continue
        gs, zs = res
        iso     = r.get("data_iso") or "0000-00-00"
        fmt     = r.get("data")     or "—"
        winner  = PLAYER1 if gs > zs else PLAYER2
        if gs > zs: tot_g += 1
        else:        tot_z += 1
        d = per_giorno[iso]
        d["data_fmt"]    = fmt
        d["ginola_pts"] += gs
        d["zappa_pts"]  += zs
        d["partite"].append({"ginola_score": gs, "zappa_score": zs, "winner": winner})
        if winner == PLAYER1: d["ginola_v"] += 1
        else:                  d["zappa_v"]  += 1

    giorni = []
    for iso, d in sorted(per_giorno.items(), key=lambda x: x[0], reverse=True):
        giorni.append({
            "data":              d["data_fmt"],
            "data_iso":          iso,
            "ginola_vittorie":   d["ginola_v"],
            "zappa_vittorie":    d["zappa_v"],
            "ginola_pts_totale": d["ginola_pts"],
            "zappa_pts_totale":  d["zappa_pts"],
            "n_partite":         len(d["partite"]),
            "partite":           d["partite"],
        })

    tot = tot_g + tot_z
    return {
        "aggiornato": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "giocatori":  [PLAYER1, PLAYER2],
        "totali": {
            "ginola_vittorie": tot_g,
            "zappa_vittorie":  tot_z,
            "totale_partite":  tot,
            "giorni_giocati":  len(giorni),
            "ginola_pct":      round(tot_g/tot*100, 1) if tot else 0,
            "zappa_pct":       round(tot_z/tot*100, 1) if tot else 0,
        },
        "per_giorno": giorni,
    }

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("Burraco Pinelle Scraper")
    print(f"{PLAYER1}  vs  {PLAYER2}")
    print("=" * 50)

    os.makedirs("docs", exist_ok=True)
    s = requests.Session()
    login(s)

    print("\nDownloading match history...")
    all_rows = []
    for page in range(100):
        rows, has_next = scrape_page(s, page)
        print(f"  p={page}: {len(rows)} rows")
        all_rows.extend(rows)
        if not has_next:
            print(f"  Last page: {page}")
            break

    print(f"\nTotal raw rows: {len(all_rows)}")
    dati = calcola(all_rows)
    t = dati["totali"]

    print(f"\nRESULTS:")
    print(f"  {PLAYER1}: {t['ginola_vittorie']} wins ({t['ginola_pct']}%)")
    print(f"  {PLAYER2}: {t['zappa_vittorie']} wins ({t['zappa_pct']}%)")
    print(f"  Total matches: {t['totale_partite']}")
    print(f"  Days played:   {t['giorni_giocati']}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {OUT_FILE}")

    if t["totale_partite"] == 0:
        print("\nWARNING: 0 matches found. Check docs/debug_p0.html")
        sys.exit(1)

if __name__ == "__main__":
    main()
