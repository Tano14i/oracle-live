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
    report = build_report(path)
    print(report)
    return 0 if not report.startswith("Dataset non trovato") else 1


def build_report(path: str | None = None) -> str:
    """Costruisce il report come testo (usato dalla CLI e dal comando /analisi del bot)."""
    if not path:
        path = LIVE_TRAINING_DATA_PATH
    if not os.path.exists(path):
        return f"Dataset non trovato: {path}"

    lines = []
    df = pd.read_csv(path)
    settled = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    lines.append(f"Dataset: {path}")
    lines.append(f"Righe totali: {len(df)} | settled WIN/LOSS: {len(settled)}")
    if settled.empty:
        lines.append("Nessuna riga settled: niente da analizzare.")
        return "\n".join(lines)

    public = settled[settled["Tier"].isin(PUBLIC_TIERS)].copy()
    shadow = settled[~settled["Tier"].isin(PUBLIC_TIERS)]
    lines.append(f"Segnali pubblici: {len(public)} | shadow/learning: {len(shadow)}")
    lines.append(f"Breakeven a quota {QUOTA}: WR {breakeven_wr(QUOTA) * 100:.1f}%")

    if public.empty:
        lines.append("Nessun segnale pubblico settled.")
        return "\n".join(lines)

    lines.append("\n== WR per MERCATO (segnali pubblici) ==")
    lines.append(wr_table(public, "Market", QUOTA).to_string())

    lines.append("\n== WR per TIER ==")
    lines.append(wr_table(public, "Tier", QUOTA).to_string())

    if "MinuteBucket" in public.columns:
        lines.append("\n== WR per MERCATO x FASCIA MINUTI ==")
        lines.append(wr_table(public, ["Market", "MinuteBucket"], QUOTA).to_string())

    if "LeagueName" in public.columns:
        by_league = wr_table(public, "LeagueName", QUOTA)
        lines.append("\n== WR per LEGA (>= 10 bet) ==")
        lines.append(by_league[by_league["bets"] >= 10].to_string())

    if "Prob" in public.columns:
        probs = pd.to_numeric(public["Prob"], errors="coerce")
        public["prob_bin"] = pd.cut(probs, [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        lines.append("\n== CALIBRAZIONE: WR reale per fascia di Prob del modello ==")
        lines.append("(se WR reale << fascia, il modello e' sovraconfidente e l'EV gate va stretto)")
        lines.append(wr_table(public.dropna(subset=["prob_bin"]), "prob_bin", QUOTA).to_string())

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

            lines.append("\n== ROI con QUOTA REALE per fascia di quota (righe con OddsAtOpen) ==")
            lines.append(with_odds.groupby("odds_bin", observed=True).apply(roi_real, include_groups=False).to_string())
        else:
            lines.append("\nNessuna riga con OddsAtOpen valorizzata (il campo si popola dai nuovi segnali).")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
