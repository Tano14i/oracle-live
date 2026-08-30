"""Radar di valore prematch per OVER 0.5 HT.

A cosa serve
------------
Il filtro sul ritmo di primo tempo e' interamente storico: non usa nulla della
partita in corso. Si puo' quindi calcolare prima del fischio d'inizio e sapere
in anticipo quali partite della giornata sono candidate.

Perche' NON fa scommettere prematch
-----------------------------------
Le quote prematch di questo mercato sono piu' corte di quelle live: rilevate
fra 1.13 e 1.45, mediana 1.27, contro 1.40-1.53 al minuto 1-5. A 1.27 il
pareggio richiede il 78.7%, che nemmeno il tier CAUTION (75.0% misurato)
raggiunge. Aspettare i primi minuti vale circa 18 punti di quota.

Il radar serve quindi a **presidiare i calci d'inizio giusti**: il bot live
intercetta solo il 59% delle partite entro il minuto 5, e sapere in anticipo
quali contano elimina quella perdita.

Uso
---
  python prematch_radar.py                      # oggi
  python prematch_radar.py --date 2026-08-31
  python prematch_radar.py --with-odds          # aggiunge la quota prematch
"""
import argparse
import datetime
import json
import os
import re
import sys
import unicodedata

import pandas as pd
import requests

from config import API_KEY, CSV_PATH, LIVE_TRAINING_DATA_PATH

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_JSON = os.path.join(BASE_DIR, "prematch_radar_watchlist.json")
API_BASE = "https://v3.football.api-sports.io"
BET_HT_OVER_UNDER = 6           # "Goals Over/Under First Half"

# Stesse soglie di oracle_live.py (evaluate_signal_candidate, OVER 0.5 HT)
TIERS = [("APPROVED", 1.60), ("CAUTION", 1.30), ("GAMBLING", 1.10)]
MIN_TEAM_HT = 0.80
MIN_TOTAL_PACE = 2.10
HISTORY_WINDOW = 50
MIN_KNOWN = 6

# Win rate misurato nel backtest, per stimare il valore contro la quota
TIER_WINRATE = {"APPROVED": 0.814, "CAUTION": 0.750, "GAMBLING": 0.699}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def core_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    drop = {"football", "club", "association", "fc", "afc"}
    return " ".join(t for t in re.sub(r"[^a-z0-9 ]", " ", text).split() if t not in drop)


def load_history() -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    for col in ["FTHome", "FTAway", "HTHome", "HTAway", "HTKnown"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], errors="coerce")
    df = df.dropna(subset=["MatchDate", "FTHome", "FTAway"]).sort_values("MatchDate", kind="stable")
    df["ht"] = df["HTHome"].fillna(0) + df["HTAway"].fillna(0)
    df["ft"] = df["FTHome"] + df["FTAway"]
    df["known"] = (df["HTKnown"].fillna(0) > 0).astype(int)

    long = pd.concat([
        df[["HomeTeam", "ht", "ft", "known"]].rename(columns={"HomeTeam": "team"}),
        df[["AwayTeam", "ht", "ft", "known"]].rename(columns={"AwayTeam": "team"}),
    ], ignore_index=True)
    last = long.groupby("team").tail(HISTORY_WINDOW)

    stats = {}
    for team, part in last.groupby("team"):
        known = part[part["known"] == 1]
        stats[team] = {
            "matches": int(len(part)),
            "known": int(len(known)),
            # media del primo tempo sulle sole partite in cui il dato esiste
            "avg_ht": float(known["ht"].mean()) if len(known) else None,
            "avg_ft": float(part["ft"].mean()),
        }
    index = {}
    for team in stats:
        index.setdefault(core_name(team), team)
    return stats, index


def resolve(name: str, index: dict) -> str | None:
    return index.get(core_name(name))


def tier_for(pair_ht: float, worst_ht: float, pair_ft: float) -> str | None:
    if pair_ft < MIN_TOTAL_PACE or worst_ht < MIN_TEAM_HT:
        return None
    for label, threshold in TIERS:
        if pair_ht >= threshold:
            return label
    return None


def fetch_ht_odd(session: requests.Session, fixture_id: int):
    try:
        r = session.get(f"{API_BASE}/odds",
                        params={"fixture": fixture_id, "bet": BET_HT_OVER_UNDER},
                        timeout=25).json()
    except requests.RequestException:
        return None
    values = []
    for item in r.get("response", []):
        for bm in item.get("bookmakers", []):
            for bet in bm.get("bets", []):
                for v in bet.get("values", []):
                    if str(v.get("value", "")).strip().lower().replace(" ", "") == "over0.5":
                        try:
                            values.append(float(v.get("odd")))
                        except (TypeError, ValueError):
                            pass
    return round(sum(values) / len(values), 2) if values else None


def scan(date_value: str | None = None, min_tier: str = "GAMBLING",
         with_odds: bool = False, known_leagues: bool = False) -> dict:
    """Esegue il radar e restituisce le candidate. Usata anche dal bot Telegram."""
    date_value = date_value or datetime.date.today().isoformat()
    stats, index = load_history()
    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})
    fixtures = session.get(f"{API_BASE}/fixtures", params={"date": date_value},
                           timeout=30).json().get("response", [])
    upcoming = [f for f in fixtures
                if str((f["fixture"]["status"] or {}).get("short", "")) == "NS"]

    seen_leagues = set()
    if known_leagues:
        try:
            hist = pd.read_csv(LIVE_TRAINING_DATA_PATH, usecols=["Country", "LeagueName"])
            seen_leagues = {(str(c).strip().lower(), str(l).strip().lower())
                            for c, l in zip(hist["Country"], hist["LeagueName"])}
        except Exception:
            seen_leagues = set()

    rank = {"APPROVED": 3, "CAUTION": 2, "GAMBLING": 1}
    candidates, unknown_team, no_data, unseen_league = [], 0, 0, 0
    for f in upcoming:
        if seen_leagues:
            key = (str(f["league"]["country"]).strip().lower(),
                   str(f["league"]["name"]).strip().lower())
            if key not in seen_leagues:
                unseen_league += 1
                continue
        home_raw, away_raw = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
        home, away = resolve(home_raw, index), resolve(away_raw, index)
        if not home or not away:
            unknown_team += 1
            continue
        h, a = stats[home], stats[away]
        if h["known"] < MIN_KNOWN or a["known"] < MIN_KNOWN:
            no_data += 1
            continue
        pair_ht = (h["avg_ht"] + a["avg_ht"]) / 2
        worst_ht = min(h["avg_ht"], a["avg_ht"])
        pair_ft = (h["avg_ft"] + a["avg_ft"]) / 2
        tier = tier_for(pair_ht, worst_ht, pair_ft)
        if not tier or rank[tier] < rank[min_tier]:
            continue
        candidates.append({
            "fixture_id": f["fixture"]["id"],
            "kickoff_utc": f["fixture"]["date"],
            "country": f["league"]["country"],
            "league": f["league"]["name"],
            "home_team": home_raw,
            "away_team": away_raw,
            "match": f"{home_raw} vs {away_raw}",
            "tier": tier,
            "pair_ht_pace": round(pair_ht, 2),
            "worst_ht_pace": round(worst_ht, 2),
            "pair_ft_pace": round(pair_ft, 2),
            "known_matches": f"{h['known']}/{a['known']}",
            "prematch_odd": None,
        })

    candidates.sort(key=lambda c: (-rank[c["tier"]], -c["pair_ht_pace"]))
    if with_odds:
        for c in candidates:
            c["prematch_odd"] = fetch_ht_odd(session, c["fixture_id"])

    return {
        "date": date_value,
        "fixtures_total": len(upcoming),
        "candidates": candidates,
        "skipped_unknown_team": unknown_team,
        "skipped_no_ht_history": no_data,
        "skipped_unseen_league": unseen_league,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--with-odds", action="store_true",
                    help="recupera la quota prematch (1 chiamata per candidata)")
    ap.add_argument("--min-tier", choices=["GAMBLING", "CAUTION", "APPROVED"], default="GAMBLING")
    ap.add_argument("--known-leagues", action="store_true",
                    help="solo campionati che il bot ha gia' incontrato in diretta")
    args = ap.parse_args()
    if not API_KEY:
        print("API_KEY mancante nel .env")
        return 1

    print(f"Radar prematch OVER 0.5 HT - {args.date}\n")
    print("caricamento storico...")
    stats, index = load_history()
    print(f"  squadre con storico: {len(stats):,}")

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})
    fixtures = session.get(f"{API_BASE}/fixtures", params={"date": args.date},
                           timeout=30).json().get("response", [])
    upcoming = [f for f in fixtures
                if str((f["fixture"]["status"] or {}).get("short", "")) == "NS"]
    print(f"  partite in programma: {len(upcoming):,}\n")

    # Il ritmo alto premia le divisioni minori e le giovanili, dove spesso il
    # mercato non esiste: su 72 candidate APPROVED solo 9 avevano una quota.
    # Questo filtro tiene i campionati in cui il bot ha davvero operato.
    seen_leagues = set()
    if args.known_leagues:
        try:
            hist = pd.read_csv(LIVE_TRAINING_DATA_PATH, usecols=["Country", "LeagueName"])
            seen_leagues = {(str(c).strip().lower(), str(l).strip().lower())
                            for c, l in zip(hist["Country"], hist["LeagueName"])}
            print(f"  campionati gia' incontrati dal bot: {len(seen_leagues):,}\n")
        except Exception as exc:
            print(f"  impossibile leggere lo storico del bot: {exc}\n")

    rank = {"APPROVED": 3, "CAUTION": 2, "GAMBLING": 1}
    candidates, unknown_team, no_data, unseen_league = [], 0, 0, 0
    for f in upcoming:
        if seen_leagues:
            key = (str(f["league"]["country"]).strip().lower(),
                   str(f["league"]["name"]).strip().lower())
            if key not in seen_leagues:
                unseen_league += 1
                continue
        home_raw = f["teams"]["home"]["name"]
        away_raw = f["teams"]["away"]["name"]
        home, away = resolve(home_raw, index), resolve(away_raw, index)
        if not home or not away:
            unknown_team += 1
            continue
        h, a = stats[home], stats[away]
        if h["known"] < MIN_KNOWN or a["known"] < MIN_KNOWN:
            no_data += 1
            continue
        pair_ht = (h["avg_ht"] + a["avg_ht"]) / 2
        worst_ht = min(h["avg_ht"], a["avg_ht"])
        pair_ft = (h["avg_ft"] + a["avg_ft"]) / 2
        tier = tier_for(pair_ht, worst_ht, pair_ft)
        if not tier or rank[tier] < rank[args.min_tier]:
            continue
        candidates.append({
            "fixture_id": f["fixture"]["id"],
            "kickoff_utc": f["fixture"]["date"],
            "country": f["league"]["country"],
            "league": f["league"]["name"],
            "match": f"{home_raw} vs {away_raw}",
            "tier": tier,
            "pair_ht_pace": round(pair_ht, 2),
            "worst_ht_pace": round(worst_ht, 2),
            "pair_ft_pace": round(pair_ft, 2),
            "known_matches": f"{h['known']}/{a['known']}",
            "prematch_odd": None,
        })

    candidates.sort(key=lambda c: (-rank[c["tier"]], -c["pair_ht_pace"]))
    print(f"candidate: {len(candidates)}")
    print(f"  scartate per squadra sconosciuta: {unknown_team:,}")
    print(f"  scartate per storico HT insufficiente: {no_data:,}")
    if seen_leagues:
        print(f"  scartate per campionato mai incontrato: {unseen_league:,}")
    print()

    if args.with_odds and candidates:
        print("recupero quote prematch...")
        for c in candidates:
            c["prematch_odd"] = fetch_ht_odd(session, c["fixture_id"])
        print()

    if not candidates:
        print("Nessuna candidata per questa data.")
        return 0

    print(f"{'ora':<6} {'tier':<9} {'ritmo':>6} {'partita':<42} {'campionato':<24} {'quota':>7} {'valore':>8}")
    print("-" * 108)
    for c in candidates[:40]:
        ko = c["kickoff_utc"][11:16]
        odd = c["prematch_odd"]
        wr = TIER_WINRATE[c["tier"]]
        if odd:
            edge = (wr * odd - 1) * 100
            odd_s, edge_s = f"{odd:.2f}", f"{edge:+.1f}%"
        else:
            odd_s, edge_s = "-", "-"
        print(f"{ko:<6} {c['tier']:<9} {c['pair_ht_pace']:>6.2f} {c['match'][:41]:<42} "
              f"{(c['country'] + ' ' + c['league'])[:23]:<24} {odd_s:>7} {edge_s:>8}")

    if args.with_odds:
        priced = [c for c in candidates if c["prematch_odd"]]
        if priced:
            good = [c for c in priced
                    if TIER_WINRATE[c["tier"]] * c["prematch_odd"] > 1.0]
            print(f"\ncon quota prematch disponibile: {len(priced)}/{len(candidates)}")
            print(f"  di cui gia' sopra il pareggio prematch: {len(good)}")
            print("  sulle altre conviene attendere la quota live al minuto 1-5,")
            print("  storicamente piu' lunga di circa 18 punti.")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"date": args.date, "generated_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(), "candidates": candidates}, fh,
            indent=2, ensure_ascii=False)
    print(f"\nwatchlist salvata in {OUTPUT_JSON}")
    print(f"  {len(candidates)} calci d'inizio da presidiare")
    return 0


if __name__ == "__main__":
    sys.exit(main())
