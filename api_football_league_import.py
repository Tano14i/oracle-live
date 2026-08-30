"""Importa storico con primo tempo reale da API-FOOTBALL, un campionato alla volta.

Perche' per campionato e non per squadra
----------------------------------------
Una chiamata `/fixtures?league=X&season=Y` restituisce l'intera stagione, circa
380 partite e tutte le squadre insieme. Andare per squadra costa 3 chiamate a
testa e ripete le stesse partite una volta per ciascuna delle due contendenti:
per coprire i 313 campionati che il bot incontra servono ~939 chiamate invece di
~18.800.

Sicurezza dell'import
---------------------
Verificato su 223 fixture: il 96.9% e' del tutto assente da Matches.csv e lo
0% rischia di duplicare una partita gia' presente sotto altro nome. Le righe
importate quindi aggiungono storico nuovo, non doppioni. La fusione dà comunque
la precedenza alle righe che hanno il primo tempo reale, quindi il dato puo'
solo migliorare.

Uso
---
  python api_football_league_import.py --discover
  python api_football_league_import.py --import --limit 60 --season 2025 --season 2026
"""
import argparse
import json
import os
import sys
import time
import unicodedata
from collections import Counter

import pandas as pd
import requests

from api_football_ht_repair import api_get, fixture_to_row, merge_preferring_ht, ht_coverage
from config import API_KEY, CSV_PATH, LIVE_TRAINING_DATA_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(BASE_DIR, "api_football_leagues.json")
API_BASE = "https://v3.football.api-sports.io"
OUTPUT_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]
# Nel CSV "primo tempo 0-0" e "primo tempo sconosciuto" si scrivono entrambi 0.
# HTKnown distingue i due casi: e' l'ambiguita' che rende necessaria l'euristica
# in get_team_metrics e che mette un tetto artificiale alla misura di copertura.
KNOWN_COLUMN = "HTKnown"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in text.lower() if ch.isalnum())


def encountered_leagues() -> Counter:
    """I campionati che il bot ha davvero incontrato, per frequenza."""
    try:
        df = pd.read_csv(LIVE_TRAINING_DATA_PATH, usecols=["Country", "LeagueName"])
    except Exception as exc:
        print(f"Impossibile leggere lo storico del bot: {exc}")
        return Counter()
    pairs = zip(df["Country"].astype(str), df["LeagueName"].astype(str))
    return Counter(pairs)


def discover(session: requests.Session) -> dict:
    """Associa i campionati incontrati agli id di API-FOOTBALL."""
    counts = encountered_leagues()
    print(f"campionati incontrati dal bot: {len(counts):,}")
    rows = api_get(session, "/leagues", {})
    print(f"campionati esposti dall'API: {len(rows):,}")

    index = {}
    for row in rows:
        league = row.get("league", {}) or {}
        country = (row.get("country", {}) or {}).get("name", "")
        key = (norm(country), norm(league.get("name")))
        index.setdefault(key, league.get("id"))

    mapping, missing = {}, []
    for (country, name), n in counts.most_common():
        key = (norm(country), norm(name))
        league_id = index.get(key)
        if league_id is None:
            missing.append((country, name, n))
            continue
        mapping[str(league_id)] = {"country": country, "name": name, "seen": n}

    print(f"\nassociati: {len(mapping):,}")
    print(f"non trovati: {len(missing):,}")
    if missing:
        print("  i piu frequenti fra i non trovati:")
        for country, name, n in missing[:8]:
            print(f"    {n:>5}  {country} | {name}")
    with open(MAP_PATH, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, indent=2, ensure_ascii=False)
    print(f"\nmappa salvata in {MAP_PATH}")
    return mapping


def fetch_league(session: requests.Session, league_id: int, season: int) -> pd.DataFrame:
    rows = []
    for fixture in api_get(session, "/fixtures", {"league": league_id, "season": season}):
        row = fixture_to_row(fixture)
        if row is not None:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame(rows)
    # Solo il giorno: l'API restituisce l'orario di inizio, il CSV memorizza la
    # data. Tenendo l'orario la chiave di fusione non combacia mai e ogni import
    # duplica le partite invece di aggiornarle.
    out["MatchDate"] = out["MatchDate"].dt.tz_localize(None).dt.normalize()
    # fixture_to_row lascia NA quando l'API non espone il primo tempo
    out[KNOWN_COLUMN] = (out["HTHome"].notna() & out["HTAway"].notna()).astype(int)
    return out[OUTPUT_COLUMNS + [KNOWN_COLUMN]]


def load_target() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], errors="coerce", utc=True).dt.tz_localize(None)
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if KNOWN_COLUMN not in df.columns:
        # Righe senza provenienza: noto = 0. Dedurlo da "HT > 0" sembra
        # ragionevole ma marca come note solo le partite CON gol, escludendo le
        # 0-0 vere: la media sui soli noti risulterebbe sistematicamente gonfiata
        # e il campione selezionato sull'esito che si vuole prevedere.
        df[KNOWN_COLUMN] = 0
    else:
        df[KNOWN_COLUMN] = pd.to_numeric(df[KNOWN_COLUMN], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam"])
    df["HomeTeam"] = df["HomeTeam"].astype(str).str.strip().str.upper()
    df["AwayTeam"] = df["AwayTeam"].astype(str).str.strip().str.upper()
    return df[OUTPUT_COLUMNS + [KNOWN_COLUMN]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--import", dest="do_import", action="store_true")
    ap.add_argument("--limit", type=int, default=60, help="campionati per esecuzione")
    ap.add_argument("--season", action="append", type=int, default=[])
    args = ap.parse_args()
    if not args.season:
        args.season = [2025, 2026]
    if not API_KEY:
        print("API_KEY mancante nel .env")
        return 1

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})

    if args.discover:
        discover(session)
        if not args.do_import:
            return 0

    if not args.do_import:
        print("Niente da fare: usa --discover o --import")
        return 0

    if not os.path.exists(MAP_PATH):
        print("Mappa assente: esegui prima --discover")
        return 1
    with open(MAP_PATH, encoding="utf-8") as fh:
        mapping = json.load(fh)

    # priorita' ai campionati che il bot incontra piu' spesso
    ordered = sorted(mapping.items(), key=lambda kv: -kv[1].get("seen", 0))
    done_path = os.path.join(BASE_DIR, "api_football_leagues_done.json")
    done = set()
    if os.path.exists(done_path):
        with open(done_path, encoding="utf-8") as fh:
            done = set(json.load(fh))
    # Il tracciamento e' per campionato E stagione: altrimenti richiedere una
    # stagione nuova salterebbe tutti i campionati gia' importati per un'altra.
    todo = [(lid, info) for lid, info in ordered
            if any(f"{lid}:{s}" not in done for s in args.season)][: args.limit]
    print(f"campionati mappati: {len(mapping):,} | coppie lega-stagione gia fatte: {len(done):,}")
    print(f"campionati da lavorare ora: {len(todo)}")
    print(f"stagioni: {', '.join(str(s) for s in args.season)}\n")

    frames, ok, failed = [], 0, 0
    for i, (lid, info) in enumerate(todo, 1):
        got = 0
        for season in args.season:
            if f"{lid}:{season}" in done:
                continue
            try:
                part = fetch_league(session, int(lid), season)
            except Exception as exc:
                print(f"  [{i}/{len(todo)}] FAIL {info['country']} | {info['name']}: {str(exc)[:60]}")
                failed += 1
                continue
            done.add(f"{lid}:{season}")
            if len(part):
                frames.append(part)
                got += len(part)
        if got:
            ok += 1
        if i % 10 == 0:
            print(f"  [{i}/{len(todo)}] campionati con dati: {ok}, falliti: {failed}")

    with open(done_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(done), fh)

    if not frames:
        print("\nNessuna partita importata.")
        return 0

    new = pd.concat(frames, ignore_index=True)
    with_ht = int((new["HTHome"].notna() & new["HTAway"].notna()).sum())
    print(f"\npartite importate: {len(new):,} | con primo tempo reale: {with_ht:,}")

    target = load_target()
    before_cov = ht_coverage(target)
    merged, stats = merge_preferring_ht(target, new)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(CSV_PATH)
    backup = f"{base}_leagues_{stamp}{ext}"
    with open(CSV_PATH, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    out = merged.sort_values("MatchDate", kind="stable").copy()
    out["MatchDate"] = out["MatchDate"].dt.strftime("%Y-%m-%d")
    for col in ["FTHome", "FTAway", "HTHome", "HTAway", KNOWN_COLUMN]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out = out[OUTPUT_COLUMNS + [KNOWN_COLUMN]]
    out.to_csv(CSV_PATH, index=False)
    known = int(out[KNOWN_COLUMN].sum())
    print(f"  righe con primo tempo confermato: {known:,} ({known/len(out)*100:.1f}%)")

    print("\n" + "=" * 48)
    print("IMPORT PER CAMPIONATO COMPLETATO")
    print(f"  campionati importati: {ok} | falliti: {failed}")
    print(f"  righe che aggiornano una partita esistente: {stats['replaced']:,}")
    print(f"  righe nuove aggiunte: {stats['added']:,}")
    print(f"  righe: {len(target):,} -> {len(out):,}")
    print(f"  copertura HT: {before_cov*100:.1f}% -> {ht_coverage(merged)*100:.1f}%")
    print(f"  backup: {backup}")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    sys.exit(main())
