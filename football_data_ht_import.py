"""Integra i risultati di primo tempo da football-data.co.uk in Matches.csv.

Perche'
-------
In Matches.csv il primo tempo e' assente nel 91% delle partite con 2+ gol, e il
bot se ne accorge e lo sostituisce con un valore inventato
(`avg_total_goals * 0.38`, limitato a [0.8, 1.35]). Siccome il minimo inventato
coincide con la soglia del filtro, il filtro sul ritmo di primo tempo non
filtra. OVER 0.5 HT e' il market su cui il bot punta.

football-data.co.uk pubblica CSV gratuiti con le colonne HTHG e HTAG per 22
divisioni europee. Coprono circa il 44% dei segnali che il bot pubblica.

Uso
---
  python football_data_ht_import.py --download        # scarica i CSV
  python football_data_ht_import.py --report          # quante righe correggerebbe
  python football_data_ht_import.py --write           # applica (fa backup)
"""
import argparse
import os
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher

import pandas as pd
import requests

from config import CSV_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "football_data")
SOURCE = "https://www.football-data.co.uk/mmz4281"

DIVISIONS = [
    "E0", "E1", "E2", "E3", "EC",          # Inghilterra
    "SC0", "SC1", "SC2", "SC3",            # Scozia
    "D1", "D2",                            # Germania
    "I1", "I2",                            # Italia
    "SP1", "SP2",                          # Spagna
    "F1", "F2",                            # Francia
    "N1", "B1", "P1", "T1", "G1",          # Olanda, Belgio, Portogallo, Turchia, Grecia
]
def season_codes(first_year: int, last_year: int) -> list:
    """Codici stagione nel formato del sito: 1993/94 -> "9394", 2025/26 -> "2526"."""
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first_year, last_year + 1)]


# Lo storico parte dal 1993/94. Serve profondita': la finestra di 50 partite
# pesca indietro nel tempo, e se li' l'HT manca il fallback si riattiva.
FIRST_SEASON_YEAR = 1993
SEASONS = season_codes(FIRST_SEASON_YEAR, time.localtime().tm_year)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


# Parole che non aiutano a distinguere un club dall'altro.
NOISE = {"fc", "cf", "sc", "ac", "as", "ss", "us", "sv", "vf", "vfl", "vfb", "bv",
         "afc", "cd", "ud", "rc", "sd", "ca", "club", "de", "the", "city", "town",
         "united", "calcio", "spor", "kulubu", "if", "ff", "bk", "ik"}


def core_tokens(value: str) -> frozenset:
    return frozenset(t for t in normalize(value).split() if t not in NOISE and len(t) > 1)


def download() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "oracle-live-ht-import/1.0"})
    ok = skipped = failed = 0
    total_bytes = 0
    for season in SEASONS:
        for div in DIVISIONS:
            dest = os.path.join(DATA_DIR, f"{season}_{div}.csv")
            if os.path.exists(dest) and os.path.getsize(dest) > 200:
                skipped += 1
                continue
            url = f"{SOURCE}/{season}/{div}.csv"
            try:
                r = session.get(url, timeout=30)
                if r.status_code != 200 or len(r.content) < 200:
                    failed += 1
                    continue
                with open(dest, "wb") as fh:
                    fh.write(r.content)
                total_bytes += len(r.content)
                ok += 1
            except requests.RequestException:
                failed += 1
            time.sleep(0.25)
        print(f"  stagione {season}: totale scaricati {ok}, gia presenti {skipped}, non disponibili {failed}")
    print(f"\nscaricati {ok} file ({total_bytes/1024/1024:.1f} MB) in {DATA_DIR}")


def load_source() -> pd.DataFrame:
    frames = []
    for name in sorted(os.listdir(DATA_DIR)) if os.path.isdir(DATA_DIR) else []:
        if not name.endswith(".csv"):
            continue
        path = os.path.join(DATA_DIR, name)
        try:
            raw = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip", low_memory=False)
        except Exception:
            continue
        need = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HTHG", "HTAG"}
        if not need.issubset(set(raw.columns)):
            continue
        part = raw[list(need)].copy()
        part["src"] = name
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # Le date sono in formato giorno/mese/anno, a volte con anno a 2 cifre.
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in ["FTHG", "FTAG", "HTHG", "HTAG"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "HTHG", "HTAG"])
    df["HomeTeam"] = df["HomeTeam"].astype(str).str.strip()
    df["AwayTeam"] = df["AwayTeam"].astype(str).str.strip()
    return df


def build_name_map(source_names, target_names) -> dict:
    """Associa i nomi di football-data a quelli gia' presenti in Matches.csv."""
    by_norm = {}
    by_tokens = {}
    for name in target_names:
        by_norm.setdefault(normalize(name), name)
        by_tokens.setdefault(core_tokens(name), name)

    mapping = {}
    unresolved = []
    for name in source_names:
        n = normalize(name)
        if n in by_norm:
            mapping[name] = by_norm[n]
            continue
        t = core_tokens(name)
        if t and t in by_tokens:
            mapping[name] = by_tokens[t]
            continue
        unresolved.append((name, n, t))

    # fuzzy solo sui rimasti: costoso, quindi limitato ai candidati che
    # condividono almeno un token significativo
    token_index = {}
    for name in target_names:
        for tok in core_tokens(name):
            token_index.setdefault(tok, []).append(name)
    for name, n, t in unresolved:
        candidates = set()
        for tok in t:
            candidates.update(token_index.get(tok, []))
        best, best_ratio = None, 0.0
        for cand in candidates:
            ratio = SequenceMatcher(None, n, normalize(cand)).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, cand
        if best and best_ratio >= 0.82:
            mapping[name] = best
    return mapping


def load_target() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], errors="coerce")
    for c in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam"])


def analyze(target: pd.DataFrame, source: pd.DataFrame):
    names = set(target["HomeTeam"].astype(str)) | set(target["AwayTeam"].astype(str))
    src_names = set(source["HomeTeam"]) | set(source["AwayTeam"])
    print(f"  squadre nella fonte: {len(src_names):,}")
    mapping = build_name_map(src_names, names)
    print(f"  agganciate a Matches.csv: {len(mapping):,} ({len(mapping)/len(src_names)*100:.1f}%)")

    s = source.copy()
    s["H"] = s["HomeTeam"].map(mapping)
    s["A"] = s["AwayTeam"].map(mapping)
    s = s.dropna(subset=["H", "A"])
    print(f"  partite con entrambe le squadre agganciate: {len(s):,} su {len(source):,}")

    # indice del bersaglio per (data, casa, trasferta), con tolleranza di un giorno
    t = target.copy()
    t["_row"] = range(len(t))
    idx = {}
    for row, d, h, a in zip(t["_row"], t["MatchDate"], t["HomeTeam"], t["AwayTeam"]):
        idx[(d.normalize(), h, a)] = row

    hits, misses = [], 0
    for date, h, a, hthg, htag in zip(s["Date"], s["H"], s["A"], s["HTHG"], s["HTAG"]):
        found = None
        for delta in (0, -1, 1):
            key = ((date + pd.Timedelta(days=delta)).normalize(), h, a)
            if key in idx:
                found = idx[key]
                break
        if found is None:
            misses += 1
        else:
            hits.append((found, hthg, htag))
    print(f"  righe agganciate a una partita esistente: {len(hits):,}")
    print(f"  righe della fonte senza corrispondenza: {misses:,}")
    return t, hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if args.download:
        print("Download da football-data.co.uk...")
        download()
        if not (args.report or args.write):
            return 0

    source = load_source()
    if source.empty:
        print("Nessun dato locale: esegui prima --download")
        return 1
    print(f"\nFonte: {len(source):,} partite con HT reale "
          f"({source['Date'].min().date()} - {source['Date'].max().date()})")

    target = load_target()
    print(f"Matches.csv: {len(target):,} righe\n")
    t, hits = analyze(target, source)
    if not hits:
        print("\nNessuna riga da correggere.")
        return 0

    ht_old = t["HTHome"].fillna(0) + t["HTAway"].fillna(0)
    rows = [h[0] for h in hits]
    gained = int((ht_old.iloc[rows] == 0).sum())
    print(f"\n  di cui oggi hanno HT a zero (verrebbero corrette): {gained:,}")

    scored = (t["FTHome"] + t["FTAway"]) >= 2
    before = float((ht_old[scored] > 0).mean())
    print(f"  copertura HT attuale: {before*100:.1f}%")

    if not args.write:
        print("\n(solo report: usa --write per applicare)")
        return 0

    if "HTKnown" not in t.columns:
        # Righe senza provenienza: noto = 0. Dedurlo da "HT > 0" marcherebbe
        # come note solo le partite con gol, distorcendo verso l'alto ogni media
        # calcolata sui soli noti.
        t["HTKnown"] = 0
    else:
        t["HTKnown"] = pd.to_numeric(t["HTKnown"], errors="coerce").fillna(0).astype(int)

    known_col = t.columns.get_loc("HTKnown")
    for row, hthg, htag in hits:
        t.iat[row, t.columns.get_loc("HTHome")] = hthg
        t.iat[row, t.columns.get_loc("HTAway")] = htag
        # La fonte espone sempre il primo tempo: anche uno 0-0 e' un dato certo.
        t.iat[row, known_col] = 1

    ht_new = t["HTHome"].fillna(0) + t["HTAway"].fillna(0)
    after = float((ht_new[scored] > 0).mean())

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(CSV_PATH)
    backup = f"{base}_fdht_{stamp}{ext}"
    with open(CSV_PATH, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())

    out = t.drop(columns=["_row"]).copy()
    out["MatchDate"] = out["MatchDate"].dt.strftime("%Y-%m-%d")
    for c in ["FTHome", "FTAway", "HTHome", "HTAway", "HTKnown"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    out.to_csv(CSV_PATH, index=False)

    known = int(out["HTKnown"].sum())
    print(f"\n  copertura HT: {before*100:.1f}% -> {after*100:.1f}%")
    print(f"  righe corrette: {gained:,}")
    print(f"  righe con primo tempo confermato: {known:,} ({known/len(out)*100:.1f}%)")
    print(f"  backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
