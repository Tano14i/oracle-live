"""Backtest della strategia OVER 0.5 HT sul dataset del bot.

Metodo
------
Per ogni partita si calcola il ritmo di primo tempo delle due squadre usando
SOLO le partite giocate prima di quella (rolling con shift), esattamente come
fa il bot in diretta. Nessuna informazione dal futuro entra nella decisione.

Si contano solo le partite in cui entrambe le squadre hanno almeno
`--min-known` partite a primo tempo noto: e' la stessa condizione che in
produzione impedisce a `get_team_metrics` di ricadere sul valore inventato.

Cosa NON riproduce
------------------
Il filtro del modello ML (la soglia v2) e i circuit breaker per lega, che
dipendono dallo stato runtime del bot. Il backtest misura il vantaggio del
filtro sul ritmo, che e' il cuore della strategia, non il sistema completo.

Le quote storiche di questo mercato non esistono in nessuna fonte gratuita:
si usa una quota fissa (rilevata dal vivo fra 1.40 e 1.53 al minuto 1-5) e si
riporta la quota di pareggio, che e' il dato che non dipende da assunzioni.

Uso
---
  python backtest_ht.py
  python backtest_ht.py --quota 1.45 --from 2021 --min-known 12
"""
import argparse
import sys

import numpy as np
import pandas as pd

from config import CSV_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Soglie in produzione in oracle_live.py (evaluate_signal_candidate)
TIERS = [("APPROVED", 1.60), ("CAUTION", 1.30), ("GAMBLING", 1.10)]
MIN_TEAM_HT = 0.80          # guardia per singola squadra
WINDOW = 50                 # TEAM_HISTORY_WINDOW


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    for col in ["FTHome", "FTAway", "HTHome", "HTAway", "HTKnown"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], errors="coerce")
    df = df.dropna(subset=["MatchDate", "FTHome", "FTAway"])
    df = df.sort_values("MatchDate", kind="stable").reset_index(drop=True)
    df["ht"] = df["HTHome"].fillna(0) + df["HTAway"].fillna(0)
    df["known"] = (df["HTKnown"].fillna(0) > 0).astype(int)
    return df


def build_features(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Ritmo HT di ogni squadra prima della partita corrente, senza lookahead."""
    df = df.copy()
    df["mid"] = np.arange(len(df))
    long = pd.concat([
        df[["mid", "MatchDate", "HomeTeam", "ht", "known"]].rename(columns={"HomeTeam": "team"}),
        df[["mid", "MatchDate", "AwayTeam", "ht", "known"]].rename(columns={"AwayTeam": "team"}),
    ], ignore_index=True).sort_values(["team", "MatchDate"], kind="stable")

    # media dei soli primi tempi noti: somma dei gol noti / numero di partite note
    long["ht_known"] = long["ht"] * long["known"]
    grp = long.groupby("team", sort=False)
    # shift(1) esclude la partita corrente: e' cio' che impedisce il lookahead
    sum_ht = grp["ht_known"].transform(lambda s: s.rolling(window, min_periods=1).sum().shift(1))
    cnt = grp["known"].transform(lambda s: s.rolling(window, min_periods=1).sum().shift(1))
    long["pace"] = sum_ht / cnt.replace(0, np.nan)
    long["n_known"] = cnt

    wide = long.pivot_table(index="mid", values=["pace", "n_known"], aggfunc=["min", "mean"])
    wide.columns = ["_".join(c) for c in wide.columns]
    out = df.join(wide, on="mid")
    out = out.rename(columns={"mean_pace": "pair_pace", "min_pace": "worst_pace",
                              "min_n_known": "min_known"})
    return out


def tier_of(pair_pace: float, worst_pace: float) -> str | None:
    if not np.isfinite(pair_pace) or not np.isfinite(worst_pace):
        return None
    if worst_pace < MIN_TEAM_HT:
        return None
    for name, threshold in TIERS:
        if pair_pace >= threshold:
            return name
    return None


def report(part: pd.DataFrame, label: str, quota: float) -> None:
    n = len(part)
    if n == 0:
        print(f"  {label:<24} nessuna partita")
        return
    wr = part["win"].mean()
    roi = (wr * quota - 1) * 100
    be = 1 / wr if wr > 0 else float("inf")
    print(f"  {label:<24} {n:>7,} {wr*100:>7.1f}% {roi:>+9.1f}% {be:>10.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quota", type=float, default=1.45)
    ap.add_argument("--from", dest="year_from", type=int, default=2021)
    ap.add_argument("--min-known", type=int, default=12,
                    help="partite a primo tempo noto richieste per entrambe le squadre")
    ap.add_argument("--stake", type=float, default=10.0)
    args = ap.parse_args()

    df = load()
    print(f"dataset: {len(df):,} righe")
    feats = build_features(df, WINDOW)
    feats = feats[feats["MatchDate"].dt.year >= args.year_from]
    # la partita e' valutabile solo se il primo tempo della PARTITA e' noto,
    # altrimenti l'esito non e' verificabile
    feats = feats[feats["known"] == 1]
    print(f"partite con esito verificabile dal {args.year_from}: {len(feats):,}")

    # Controllo di sanita': il tasso base sul campione deve somigliare a quello
    # noto del calcio (circa 65-70% di partite con almeno un gol nel primo
    # tempo). Uno scostamento grande significa campione selezionato sull'esito,
    # non una strategia che funziona.
    base = float((feats["ht"] >= 1).mean())
    print(f"tasso base P(gol nel 1T) sul campione: {base*100:.1f}%")
    if not 0.55 <= base <= 0.78:
        print("\n*** ATTENZIONE: tasso base fuori dall'intervallo plausibile (55-78%).")
        print("*** Il campione e' probabilmente selezionato sull'esito: i risultati")
        print("*** che seguono NON sono attendibili.\n")

    feats = feats[feats["min_known"] >= args.min_known].copy()
    print(f"con storico sufficiente su entrambe le squadre: {len(feats):,}")
    feats["tier"] = [tier_of(p, w) for p, w in zip(feats["pair_pace"], feats["worst_pace"])]
    feats["win"] = (feats["ht"] >= 1).astype(int)

    played = feats[feats["tier"].notna()]
    skipped = feats[feats["tier"].isna()]
    print(f"\npartite che il filtro avrebbe giocato: {len(played):,} "
          f"({len(played)/max(len(feats),1)*100:.1f}%)")
    print(f"partite scartate dal filtro: {len(skipped):,}")

    print(f"\n=== risultato per tier (quota {args.quota}) ===")
    print(f"  {'tier':<24} {'n':>7} {'WR':>8} {'ROI':>10} {'quota pari':>11}")
    for name, _ in TIERS:
        report(played[played["tier"] == name], name, args.quota)
    report(played, "TUTTI I GIOCATI", args.quota)
    report(skipped, "(scartati, controllo)", args.quota)

    print(f"\n=== tenuta anno per anno (tier CAUTION + APPROVED) ===")
    good = played[played["tier"].isin(["CAUTION", "APPROVED"])]
    print(f"  {'anno':<24} {'n':>7} {'WR':>8} {'ROI':>10} {'quota pari':>11}")
    for year, part in good.groupby(good["MatchDate"].dt.year):
        report(part, str(int(year)), args.quota)

    print(f"\n=== simulazione bankroll (stake fisso {args.stake:.0f}, quota {args.quota}) ===")
    g = good.sort_values("MatchDate")
    pnl = np.where(g["win"] == 1, args.stake * (args.quota - 1), -args.stake)
    equity = np.cumsum(pnl)
    if len(equity):
        peak = np.maximum.accumulate(equity)
        dd = float((peak - equity).max())
        print(f"  puntate: {len(g):,}")
        print(f"  profitto finale: {equity[-1]:+,.0f}")
        print(f"  capitale impiegato: {len(g)*args.stake:,.0f}")
        print(f"  rendimento sul totale puntato: {equity[-1]/(len(g)*args.stake)*100:+.1f}%")
        print(f"  drawdown massimo: {dd:,.0f}")

    print(f"\n=== sensibilita alla quota (tier CAUTION + APPROVED) ===")
    wr = good["win"].mean()
    print(f"  win rate misurato: {wr*100:.1f}% -> pareggio a quota {1/wr:.2f}")
    for q in [1.35, 1.40, 1.45, 1.50, 1.55, 1.60]:
        print(f"    a quota {q:.2f}: ROI {(wr*q-1)*100:+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
