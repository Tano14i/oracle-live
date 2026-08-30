"""Unifica le grafie diverse della stessa squadra in Matches.csv.

Il problema
-----------
La stessa partita compare piu' volte sotto nomi diversi, per esempio
`LIVERPOOL vs BOURNEMOUTH` e `LIVERPOOL FOOTBALL CLUB vs ASSOCIATION FOOTBALL
CLUB BOURNEMOUTH`. Le conseguenze sono due: lo storico di una squadra e' spezzato
fra le varianti, quindi le medie sono calcolate su meno partite e sono piu'
rumorose; e `trova_squadra` puo' agganciare la variante sbagliata, per esempio
quella senza dati di primo tempo.

Le due verifiche di sicurezza
-----------------------------
Accorpare nomi diversi e' rischioso: una normalizzazione ingenua che toglie
"city" e "united" fonde Manchester City con Manchester United. Qui i candidati
vengono proposti da una regola conservativa (si tolgono solo i marcatori
generici: football, club, association, fc, afc) e poi devono superare due prove
che dimostrerebbero il contrario:

  1. si sono mai affrontate? due squadre che giocano l'una contro l'altra sono
     per definizione distinte;
  2. hanno giocato lo stesso giorno contro avversari diversi E con punteggio
     diverso? una squadra sola non puo' essere in due posti.

Il punteggio serve a evitare falsi allarmi: se la riga e' la stessa partita
duplicata, l'avversario puo' comparire con grafie diverse ("brighton" contro
"brighton and hove albion", "ath madrid" contro "atletico madrid") ma il
risultato e' identico. Chiedere che divergano entrambi rende la prova specifica.

Un gruppo che fallisce anche una sola prova non viene accorpato.

Uso
---
  python normalize_team_names.py --report     # elenco fusioni proposte e scartate
  python normalize_team_names.py --write      # applica (fa backup)
"""
import argparse
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict

import pandas as pd

from config import CSV_PATH

# Solo marcatori generici di "societa' calcistica". Non si toccano city, united,
# town, B, II, CD, SC, SV: distinguono squadre diverse.
GENERIC = {"football", "club", "association", "fc", "afc"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def core_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", text).split() if t not in GENERIC]
    return " ".join(tokens)


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["MatchDate"] = df["MatchDate"].astype(str)
    df["HomeTeam"] = df["HomeTeam"].astype(str)
    df["AwayTeam"] = df["AwayTeam"].astype(str)
    return df


def candidate_groups(df: pd.DataFrame) -> dict:
    names = set(df["HomeTeam"]) | set(df["AwayTeam"])
    groups = defaultdict(list)
    for name in names:
        core = core_name(name)
        if core:
            groups[core].append(name)
    return {core: sorted(v) for core, v in groups.items() if len(v) > 1}


def verify(df: pd.DataFrame, groups: dict):
    """Applica le due prove. Restituisce (approvati, respinti con motivo)."""
    core_map = {}
    for core, variants in groups.items():
        for v in variants:
            core_map[v] = core

    # prova 1: si sono mai affrontate?
    faced = set()
    hv = df["HomeTeam"].map(core_map)
    av = df["AwayTeam"].map(core_map)
    same = (hv.notna()) & (hv == av)
    for h, a in zip(df.loc[same, "HomeTeam"], df.loc[same, "AwayTeam"]):
        if h != a:
            faced.add(core_map[h])

    # prova 2: stesso giorno, avversario diverso E punteggio diverso
    seen = defaultdict(lambda: defaultdict(set))  # (core, data) -> variante -> {(avv, punteggio)}
    conflict = set()
    sub = df[df["HomeTeam"].isin(core_map) | df["AwayTeam"].isin(core_map)]
    for date, home, away, fh, fa in zip(sub["MatchDate"], sub["HomeTeam"],
                                        sub["AwayTeam"], sub["FTHome"], sub["FTAway"]):
        score = (fh, fa)
        for team, opponent in ((home, away), (away, home)):
            core = core_map.get(team)
            if core is None:
                continue
            seen[(core, date)][team].add((core_name(opponent), score))

    for (core, _date), per_variant in seen.items():
        if core in conflict or len(per_variant) < 2:
            continue
        variants = list(per_variant.items())
        for i in range(len(variants)):
            for j in range(i + 1, len(variants)):
                a_entries, b_entries = variants[i][1], variants[j][1]
                a_opps = {o for o, _ in a_entries}
                b_opps = {o for o, _ in b_entries}
                a_scores = {s for _, s in a_entries}
                b_scores = {s for _, s in b_entries}
                if not (a_opps & b_opps) and not (a_scores & b_scores):
                    conflict.add(core)
                    break
            if core in conflict:
                break

    approved, rejected = {}, {}
    for core, variants in groups.items():
        if core in faced:
            rejected[core] = (variants, "si sono affrontate: squadre distinte")
        elif core in conflict:
            rejected[core] = (variants, "stesso giorno contro avversari diversi")
        else:
            approved[core] = variants
    return approved, rejected


def choose_canonical(df: pd.DataFrame, variants: list) -> str:
    """La grafia piu' usata: e' quella con cui il resto del dataset e' scritto."""
    counts = {}
    for v in variants:
        counts[v] = int((df["HomeTeam"] == v).sum() + (df["AwayTeam"] == v).sum())
    return sorted(variants, key=lambda v: (-counts[v], len(v), v))[0]


def dedupe_matches(df: pd.DataFrame, apply_changes: bool) -> int:
    """Elimina le righe che sono la stessa partita sotto nomi non accorpabili.

    Alcuni nomi restano ambigui e non si possono unificare senza rischio:
    "ARSENAL" e' anche Arsenal Tula, "LIVERPOOL" e' anche il Liverpool di
    Montevideo. La singola partita pero' e' riconoscibile: stessa data, stesso
    punteggio e stesso nome ridotto per entrambe le squadre. Tre coincidenze
    insieme rendono implausibile che siano due partite diverse.
    """
    names = sorted(set(df["HomeTeam"]) | set(df["AwayTeam"]))
    cmap = {n: core_name(n) for n in names}
    key = (df["MatchDate"] + "|" + df["HomeTeam"].map(cmap).astype(str)
           + "|" + df["AwayTeam"].map(cmap).astype(str)
           + "|" + df["FTHome"].astype(str) + "|" + df["FTAway"].astype(str))
    dup = key.duplicated(keep=False)
    print(f"righe: {len(df):,}")
    print(f"righe che sono la stessa partita sotto nomi diversi: {int(dup.sum()):,}")

    work = df.assign(_key=key)
    work["_ht"] = (work["HTHome"].fillna(0) + work["HTAway"].fillna(0)) > 0
    gained = int(work[dup].groupby("_key")["_ht"].agg(lambda s: s.any() and not s.all()).sum())
    print(f"  partite che guadagnano il primo tempo reale: {gained:,}")

    if not apply_changes:
        print("\n(solo report: aggiungi --write per applicare)")
        return 0

    work = work.sort_values(["MatchDate", "_ht"], kind="stable")
    out = work.drop_duplicates(subset=["_key"], keep="last")
    out = out.drop(columns=["_key", "_ht"]).sort_values("MatchDate", kind="stable")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(CSV_PATH)
    backup = f"{base}_matchdedupe_{stamp}{ext}"
    with open(CSV_PATH, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out.to_csv(CSV_PATH, index=False)

    ht = (out["HTHome"] + out["HTAway"]) > 0
    scored = (out["FTHome"] + out["FTAway"]) >= 2
    print(f"\n  righe: {len(df):,} -> {len(out):,}")
    print(f"  copertura HT: {(ht[scored]).mean()*100:.1f}%")
    print(f"  backup: {backup}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dedupe-matches", action="store_true",
                    help="rimuove le righe che sono la stessa partita sotto nomi non unificabili")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    df = load()
    if args.dedupe_matches:
        return dedupe_matches(df, apply_changes=args.write)
    print(f"righe: {len(df):,}")
    names = set(df["HomeTeam"]) | set(df["AwayTeam"])
    print(f"nomi squadra distinti: {len(names):,}\n")

    groups = candidate_groups(df)
    print(f"gruppi candidati (regola conservativa): {len(groups):,}")
    approved, rejected = verify(df, groups)
    print(f"  approvati dalle due prove: {len(approved):,}")
    print(f"  respinti: {len(rejected):,}")

    if rejected:
        print("\n--- respinti (NON verranno accorpati) ---")
        for core, (variants, why) in list(rejected.items())[: args.show]:
            print(f"  {variants} -> {why}")

    renames = {}
    for core, variants in approved.items():
        canonical = choose_canonical(df, variants)
        for v in variants:
            if v != canonical:
                renames[v] = canonical
    print(f"\nnomi da riscrivere: {len(renames):,} -> {len(approved):,} squadre")
    if approved:
        print("\n--- esempi di fusione ---")
        for core, variants in list(approved.items())[: args.show]:
            canonical = choose_canonical(df, variants)
            others = [v for v in variants if v != canonical]
            print(f"  {others} -> {canonical!r}")

    if not args.write:
        print("\n(solo report: usa --write per applicare)")
        return 0

    out = df.copy()
    out["HomeTeam"] = out["HomeTeam"].replace(renames)
    out["AwayTeam"] = out["AwayTeam"].replace(renames)

    before = len(out)
    # fra due copie della stessa partita vince quella con il primo tempo reale
    out["_ht"] = (out["HTHome"].fillna(0) + out["HTAway"].fillna(0)) > 0
    out = out.sort_values(["MatchDate", "_ht"], kind="stable")
    out = out.drop_duplicates(subset=["MatchDate", "HomeTeam", "AwayTeam"], keep="last")
    out = out.drop(columns=["_ht"]).sort_values("MatchDate", kind="stable")
    removed = before - len(out)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(CSV_PATH)
    backup = f"{base}_names_{stamp}{ext}"
    with open(CSV_PATH, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out.to_csv(CSV_PATH, index=False)

    new_names = set(out["HomeTeam"]) | set(out["AwayTeam"])
    ht = (out["HTHome"] + out["HTAway"]) > 0
    scored = (out["FTHome"] + out["FTAway"]) >= 2
    print("\n" + "=" * 48)
    print("UNIFICAZIONE COMPLETATA")
    print(f"  nomi: {len(names):,} -> {len(new_names):,}")
    print(f"  righe: {before:,} -> {len(out):,} (duplicati rimossi: {removed:,})")
    print(f"  copertura HT: {(ht[scored]).mean()*100:.1f}%")
    print(f"  backup: {backup}")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    sys.exit(main())
