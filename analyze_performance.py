"""Analisi delle performance del bot sul dataset live.

Uso:  python analyze_performance.py

Legge LIVE_TRAINING_DATA_PATH (default live_training_data.csv) e stampa:
- WR per mercato, tier e fascia di minuti (con ROI alla quota configurata)
- curva di calibrazione: WR reale per fascia di probabilita' del modello
- ROI per fascia di quota (dove OddsAtOpen e' presente)

Serve a decidere DOVE il bot perde: mercati/fasce sotto il breakeven vanno
spenti o rivisti, e se la curva di calibrazione non e' monotona il modello
non e' affidabile per l'EV gate.
"""
import os
import sys

import pandas as pd

from config import LIVE_TRAINING_DATA_PATH, QUOTA

PUBLIC_TIERS = {"APPROVED", "CAUTION", "GAMBLING"}


def breakeven_wr(odds: float) -> float:
    return 1.0 / odds if odds and odds > 1.0 else 1.0


def wr_table(frame: pd.DataFrame, by, odds: float) -> pd.DataFrame:
    def agg(group: pd.DataFrame) -> pd.Series:
        wins = int((group["Outcome"] == "WIN").sum())
        total = len(group)
        wr = wins / total if total else 0.0
        roi = (wins * (odds - 1.0) - (total - wins)) / total * 100 if total else 0.0
        return pd.Series({"bets": total, "WR%": round(wr * 100, 1), f"ROI%@{odds}": round(roi, 1)})

    return frame.groupby(by, observed=True).apply(agg, include_groups=False).sort_values("bets", ascending=False)


def main() -> int:
    path = LIVE_TRAINING_DATA_PATH
    if len(sys.argv) > 1:
        path = sys.argv[1]
    if not os.path.exists(path):
        print(f"Dataset non trovato: {path}")
        return 1

    df = pd.read_csv(path)
    settled = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    print(f"Dataset: {path}")
    print(f"Righe totali: {len(df)} | settled WIN/LOSS: {len(settled)}")
    if settled.empty:
        print("Nessuna riga settled: niente da analizzare.")
        return 0

    public = settled[settled["Tier"].isin(PUBLIC_TIERS)].copy()
    shadow = settled[~settled["Tier"].isin(PUBLIC_TIERS)]
    print(f"Segnali pubblici: {len(public)} | shadow/learning: {len(shadow)}")
    print(f"Breakeven a quota {QUOTA}: WR {breakeven_wr(QUOTA) * 100:.1f}%")

    if public.empty:
        print("Nessun segnale pubblico settled.")
        return 0

    print("\n== WR per MERCATO (segnali pubblici) ==")
    print(wr_table(public, "Market", QUOTA).to_string())

    print("\n== WR per TIER ==")
    print(wr_table(public, "Tier", QUOTA).to_string())

    if "MinuteBucket" in public.columns:
        print("\n== WR per MERCATO x FASCIA MINUTI ==")
        print(wr_table(public, ["Market", "MinuteBucket"], QUOTA).to_string())

    if "LeagueName" in public.columns:
        by_league = wr_table(public, "LeagueName", QUOTA)
        print("\n== WR per LEGA (>= 10 bet) ==")
        print(by_league[by_league["bets"] >= 10].to_string())

    if "Prob" in public.columns:
        probs = pd.to_numeric(public["Prob"], errors="coerce")
        public["prob_bin"] = pd.cut(probs, [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        print("\n== CALIBRAZIONE: WR reale per fascia di Prob del modello ==")
        print("(se WR reale << fascia, il modello e' sovraconfidente e l'EV gate va stretto)")
        print(wr_table(public.dropna(subset=["prob_bin"]), "prob_bin", QUOTA).to_string())

    if "OddsAtOpen" in public.columns:
        odds = pd.to_numeric(public["OddsAtOpen"], errors="coerce")
        with_odds = public[odds.notna()].copy()
        if not with_odds.empty:
            with_odds["odds_bin"] = pd.cut(
                pd.to_numeric(with_odds["OddsAtOpen"], errors="coerce"),
                [1.0, 1.5, 1.75, 2.0, 2.5, 10.0],
            )
            wins = (with_odds["Outcome"] == "WIN").astype(float)
            odd_values = pd.to_numeric(with_odds["OddsAtOpen"], errors="coerce")
            with_odds["unit_pl"] = wins * (odd_values - 1.0) - (1.0 - wins)

            def roi_real(group: pd.DataFrame) -> pd.Series:
                return pd.Series({
                    "bets": len(group),
                    "WR%": round((group["Outcome"] == "WIN").mean() * 100, 1),
                    "ROI% quota reale": round(group["unit_pl"].mean() * 100, 1),
                })

            print("\n== ROI con QUOTA REALE per fascia di quota (righe con OddsAtOpen) ==")
            print(with_odds.groupby("odds_bin", observed=True).apply(roi_real, include_groups=False).to_string())
        else:
            print("\nNessuna riga con OddsAtOpen valorizzata (il campo si popola dai nuovi segnali).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
