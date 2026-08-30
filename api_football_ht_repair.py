"""Ripara il dato di primo tempo (HT) in Matches.csv usando API-FOOTBALL.

Perche' serve
-------------
Il 60% delle squadre ha HT assente nelle ultime 12 partite, quelle che il bot
usa per calcolare `avg_ht_goals`. Quando se ne accorge, `get_team_metrics` in
oracle_live.py NON usa il dato reale: lo inventa come `avg_total_goals * 0.38`
limitato tra 0.8 e 1.35. Siccome il minimo inventato (0.8) coincide con la
soglia richiesta dal filtro (`avg_ht_goals >= 0.80`), il filtro sul ritmo di
primo tempo passa quasi sempre ed e' di fatto inattivo. OVER 0.5 HT e' il market
su cui il bot punta, quindi sta selezionando le partite quasi alla cieca.

Cosa fa
-------
Per le squadre con HT compromesso reimporta le stagioni indicate da
API-FOOTBALL, che espone `score.halftime`, e fonde le righe dando precedenza a
quelle che l'HT ce l'hanno davvero.

Due errori che questo script evita, presenti negli import precedenti:
  - `halftime.get("home", 0) or 0` trasforma un HT assente (null) in 0-0,
    cioe' fabbrica un dato falso invece di lasciarlo mancante;
  - le date dell'API hanno il fuso orario mentre quelle del CSV no: concatenare
    le due produce una colonna object e il to_datetime successivo le azzera in
    NaT, facendo sparire in silenzio tutte le righe importate.

Uso
---
  python api_football_ht_repair.py --limit 200 --season 2025 --season 2026
  python api_football_ht_repair.py --dry-run          # solo diagnosi
"""
import argparse
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests

from config import API_KEY, CSV_PATH

API_BASE = "https://v3.football.api-sports.io"
FINAL_STATUSES = {"FT", "AET", "PEN"}
OUTPUT_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Il piano espone due limiti distinti: uno giornaliero, ampio, e uno al minuto.
# E' il secondo a mordere: senza freno, 300 squadre (900 chiamate) prendono 429
# quasi subito e il lotto si perde quasi tutto.
RATE_LIMIT_PER_MINUTE = 400
_request_times = []


def _throttle() -> None:
    now = time.time()
    while _request_times and now - _request_times[0] > 60:
        _request_times.pop(0)
    if len(_request_times) >= RATE_LIMIT_PER_MINUTE:
        wait = 60 - (now - _request_times[0]) + 0.5
        if wait > 0:
            print(f"  (limite al minuto raggiunto, attendo {wait:.0f}s)")
            time.sleep(wait)
        _request_times.clear()
    _request_times.append(time.time())


def api_get(session: requests.Session, endpoint: str, params: dict, attempts: int = 5) -> list:
    """GET con freno sul rate limit e ritentativi su 429 e 5xx."""
    last_error = None
    for attempt in range(attempts):
        _throttle()
        try:
            response = session.get(f"{API_BASE}{endpoint}", params=params, timeout=30)
            if response.status_code == 429:
                # Quota al minuto esaurita: aspettare la finestra successiva.
                last_error = requests.HTTPError("429 rate limited")
                print("  (429: attendo la finestra successiva)")
                time.sleep(20 * (attempt + 1))
                _request_times.clear()
                continue
            if response.status_code >= 500:
                last_error = requests.HTTPError(f"{response.status_code} server error")
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            # L'API puo' rispondere 200 con l'errore nel corpo ("bug"/"5xEr"):
            # senza questo controllo il guasto passa per "nessun risultato" e
            # la squadra viene marcata irrisolvibile invece che da ritentare.
            errors = payload.get("errors")
            if errors and (isinstance(errors, dict) and errors):
                last_error = requests.HTTPError(f"errore lato API: {errors}")
                time.sleep(2.0 * (attempt + 1))
                continue
            return payload.get("response", [])
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error if last_error else RuntimeError("api_get failed")


def load_matches(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway"])
    df["HomeTeam"] = df["HomeTeam"].astype(str).str.strip().str.upper()
    df["AwayTeam"] = df["AwayTeam"].astype(str).str.strip().str.upper()
    return df[OUTPUT_COLUMNS]


def teams_needing_repair(df: pd.DataFrame) -> pd.DataFrame:
    """Squadre per cui il bot attiverebbe il fallback su avg_ht_goals.

    Replica il criterio di get_team_metrics sulle ultime 12 partite.
    """
    d = df.copy()
    d["ht"] = d["HTHome"].fillna(0) + d["HTAway"].fillna(0)
    d["ft"] = d["FTHome"] + d["FTAway"]
    long = pd.concat([
        d[["MatchDate", "HomeTeam", "ht", "ft"]].rename(columns={"HomeTeam": "team"}),
        d[["MatchDate", "AwayTeam", "ht", "ft"]].rename(columns={"AwayTeam": "team"}),
    ], ignore_index=True).sort_values("MatchDate", kind="stable")

    last12 = long.groupby("team").tail(12)
    stat = last12.groupby("team").agg(
        n=("ft", "size"),
        avg_ft=("ft", "mean"),
        avg_ht=("ht", "mean"),
        ht_pos=("ht", lambda s: int((s > 0).sum())),
        last_match=("MatchDate", "max"),
    )
    stat["susp_ratio"] = (
        last12.assign(s=((last12["ht"] == 0) & (last12["ft"] >= 2)).astype(int))
        .groupby("team")["s"].mean()
    )
    stat = stat[stat["n"] >= 6]
    broken = stat[(stat["avg_ft"] >= 2.2) & (stat["avg_ht"] <= 0.35)
                  & (stat["susp_ratio"] >= 0.6) & (stat["ht_pos"] <= 2)]
    # Priorita' alle squadre che giocano adesso: sono quelle che il bot incontra live.
    return broken.sort_values("last_match", ascending=False)


def fixture_to_row(fixture: dict):
    info = fixture.get("fixture", {}) or {}
    teams = fixture.get("teams", {}) or {}
    goals = fixture.get("goals", {}) or {}
    score = fixture.get("score", {}) or {}
    if str((info.get("status", {}) or {}).get("short", "")).upper() not in FINAL_STATUSES:
        return None
    home = str((teams.get("home", {}) or {}).get("name") or "").strip()
    away = str((teams.get("away", {}) or {}).get("name") or "").strip()
    date_value = info.get("date")
    if not home or not away or not date_value:
        return None
    halftime = score.get("halftime", {}) or {}
    # HT assente resta assente: trasformarlo in 0 fabbricherebbe un dato falso.
    ht_home = halftime.get("home")
    ht_away = halftime.get("away")
    return {
        "MatchDate": pd.to_datetime(date_value, errors="coerce", utc=True),
        "HomeTeam": home.upper(),
        "AwayTeam": away.upper(),
        "FTHome": goals.get("home") or 0,
        "FTAway": goals.get("away") or 0,
        "HTHome": ht_home if ht_home is not None else pd.NA,
        "HTAway": ht_away if ht_away is not None else pd.NA,
    }


def normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def resolve_team_id(session: requests.Session, team_name: str):
    rows = api_get(session, "/teams", {"search": team_name})
    target = normalize_name(team_name)
    best, best_score = None, -1
    for row in rows:
        name = str((row.get("team", {}) or {}).get("name", "")).strip()
        norm = normalize_name(name)
        score = 100 if norm == target else (80 if target and target in norm else
                                            (70 if norm and norm in target else 0))
        if score > best_score:
            best_score, best = score, row.get("team", {}).get("id")
    return best if best_score >= 70 else None


def fetch_history(session: requests.Session, team_id: int, seasons: list) -> pd.DataFrame:
    rows = []
    for season in seasons:
        for fx in api_get(session, "/fixtures", {"team": team_id, "season": season}):
            row = fixture_to_row(fx)
            if row is not None:
                rows.append(row)
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame(rows)
    # Solo il giorno: conservare l'orario impedisce alla chiave di fusione di
    # combaciare con le righe gia' presenti.
    out["MatchDate"] = out["MatchDate"].dt.tz_localize(None).dt.normalize()
    return out[OUTPUT_COLUMNS]


def merge_preferring_ht(old: pd.DataFrame, new: pd.DataFrame):
    """Fonde dando precedenza alle righe che hanno davvero l'HT.

    Fra due righe con la stessa chiave vince quella con HT valorizzato; a parita'
    vince quella appena importata. Cosi' il dato puo' solo migliorare, mai
    peggiorare, e una riga buona non viene mai sovrascritta da una senza HT.
    """
    old = old.copy()
    new = new.copy()
    old["_new"] = 0
    new["_new"] = 1
    combined = pd.concat([old, new], ignore_index=True)
    if "HTKnown" in combined.columns:
        # Con la colonna esplicita la precedenza e' esatta: uno 0-0 confermato
        # batte uno zero ambiguo, cosa impossibile guardando solo i gol.
        combined["_has_ht"] = pd.to_numeric(combined["HTKnown"], errors="coerce").fillna(0) > 0
    else:
        combined["_has_ht"] = combined["HTHome"].notna() & combined["HTAway"].notna()
    # sort stabile: senza kind="stable" l'ordine fra pari e' arbitrario
    # e keep="last" diventa imprevedibile.
    combined = combined.sort_values(
        ["MatchDate", "_has_ht", "_new"], kind="stable"
    )
    combined = combined.drop_duplicates(subset=["MatchDate", "HomeTeam", "AwayTeam"], keep="last")
    combined = combined.drop(columns=["_new", "_has_ht"])

    # Conteggi separati: sommare i duplicati gia' presenti nel CSV alle righe
    # davvero sostituite faceva sembrare enorme un aggiornamento minuscolo.
    def keys(frame):
        return set(zip(frame["MatchDate"], frame["HomeTeam"], frame["AwayTeam"]))

    old_keys, new_keys = keys(old), keys(new)
    stats = {
        "pre_existing_duplicates": len(old) - len(old_keys),
        "replaced": len(new_keys & old_keys),
        "added": len(new_keys - old_keys),
    }
    return combined, stats


def ht_coverage(df: pd.DataFrame) -> float:
    scored = df[(df["FTHome"] + df["FTAway"]) >= 2]
    if not len(scored):
        return 0.0
    ht = scored["HTHome"].fillna(0) + scored["HTAway"].fillna(0)
    return float((ht > 0).mean())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=150, help="squadre da riparare per esecuzione")
    parser.add_argument("--season", action="append", type=int, default=[])
    parser.add_argument("--dry-run", action="store_true", help="solo diagnosi, nessuna scrittura")
    args = parser.parse_args()
    if not args.season:
        args.season = [datetime.now().year - 1, datetime.now().year]
    if not API_KEY:
        print("API_KEY mancante nel .env")
        return 1

    print("Analisi di Matches.csv...")
    df = load_matches(CSV_PATH)
    print(f"  righe: {len(df):,}")
    print(f"  copertura HT attuale (partite con 2+ gol e HT>0): {ht_coverage(df)*100:.1f}%")

    broken = teams_needing_repair(df)
    print(f"\n  squadre con avg_ht_goals inventato: {len(broken):,}")
    if args.dry_run or broken.empty:
        print(broken.head(15)[["n", "avg_ft", "avg_ht", "ht_pos", "last_match"]].to_string())
        return 0

    targets = list(broken.index[: args.limit])
    print(f"  in riparazione ora: {len(targets)} (le piu recenti)")
    print(f"  stagioni: {', '.join(str(s) for s in args.season)}\n")

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})
    frames, ok, failed = [], 0, 0
    for i, team in enumerate(targets, 1):
        try:
            team_id = resolve_team_id(session, team)
        except Exception as exc:
            print(f"  [{i}/{len(targets)}] SEARCH_FAIL {team}: {exc}")
            failed += 1
            continue
        if not team_id:
            failed += 1
            continue
        try:
            hist = fetch_history(session, int(team_id), args.season)
        except Exception as exc:
            print(f"  [{i}/{len(targets)}] FIXTURES_FAIL {team}: {exc}")
            failed += 1
            continue
        with_ht = int((hist["HTHome"].notna() & hist["HTAway"].notna()).sum()) if len(hist) else 0
        if with_ht:
            frames.append(hist)
            ok += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(targets)}] risolte {ok}, fallite {failed}")

    if not frames:
        print("\nNessuna riga con HT recuperata.")
        return 0

    new = pd.concat(frames, ignore_index=True)
    merged, merge_stats = merge_preferring_ht(df, new)
    after = ht_coverage(merged)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(CSV_PATH)
    backup = f"{base}_ht_repair_{timestamp}{ext}"
    with open(CSV_PATH, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())

    out = merged.sort_values("MatchDate", kind="stable").copy()
    out["MatchDate"] = out["MatchDate"].dt.strftime("%Y-%m-%d")
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out.to_csv(CSV_PATH, index=False)

    still = teams_needing_repair(load_matches(CSV_PATH))
    print("\n" + "=" * 46)
    print("HT REPAIR COMPLETATO")
    print(f"  squadre riparate: {ok} | fallite: {failed}")
    print(f"  righe importate con HT: {len(new):,}")
    print(f"  di cui hanno aggiornato una riga esistente: {merge_stats['replaced']:,}")
    print(f"  righe nuove aggiunte: {merge_stats['added']:,}")
    print(f"  duplicati gia presenti nel CSV, rimossi: {merge_stats['pre_existing_duplicates']:,}")
    print(f"  copertura HT: {ht_coverage(df)*100:.1f}% -> {after*100:.1f}%")
    print(f"  squadre con HT inventato: {len(broken):,} -> {len(still):,}")
    print(f"  backup: {backup}")
    print("=" * 46)
    return 0


if __name__ == "__main__":
    sys.exit(main())
