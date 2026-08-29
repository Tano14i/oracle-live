"""Analizza gli esiti dei segnali (reali + shadow LEARNING) in live_training_data.csv.

Scopo: decidere con i dati se allargare le finestre di apertura senza perdere win rate.
In particolare risponde a:
  1. WR per market / tier / fascia minuto (segnali reali vs shadow).
  2. La finestra HT estesa 21-28' sotto pressione regge il breakeven della sua quota?
     -> se si', attivare HT_PRESSURE_WINDOW_ENABLED=1 nel .env
  3. Le fasce minuto di NEXT GOAL confermano il filtro contestuale?

Uso (sullo Space HF o in locale, dove esiste live_training_data.csv):
  python analyze_shadow_signals.py [--csv path/al/file.csv] [--min-sample 30]
"""
import argparse
import sys

import pandas as pd

from config import (
    LIVE_TRAINING_DATA_PATH,
    QUOTA_NEXT_GOAL,
    QUOTA_O05_HT,
    QUOTA_O15_HT,
    QUOTA,
)

MARKET_QUOTAS = {
    "OVER 0.5 HT": QUOTA_O05_HT,
    "OVER 1.5 HT": QUOTA_O15_HT,
    "NEXT GOAL LIVE": QUOTA_NEXT_GOAL,
}


def breakeven_wr(quota: float) -> float:
    return 1.0 / quota if quota > 1.0 else 1.0


def wr_line(part: pd.DataFrame, label: str, quota: float, min_sample: int) -> str:
    wins = int((part["Outcome"] == "WIN").sum())
    losses = int((part["Outcome"] == "LOSS").sum())
    total = wins + losses
    if total == 0:
        return f"  {label}: nessun dato"
    wr = wins / total
    be = breakeven_wr(quota)
    flag = "?" if total < min_sample else ("OK" if wr >= be else "NO")
    return (
        f"  {label}: {wins}W-{losses}L | WR {wr * 100:.1f}% "
        f"(breakeven {be * 100:.1f}% a quota {quota:.2f}) | n={total} [{flag}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=LIVE_TRAINING_DATA_PATH)
    parser.add_argument("--min-sample", type=int, default=30, help="campione minimo per un verdetto affidabile")
    args = parser.parse_args()

    try:
        df = pd.read_csv(args.csv)
    except Exception as exc:
        print(f"Impossibile leggere {args.csv}: {exc}")
        return 1

    settled = df[df["Outcome"].isin(["WIN", "LOSS"])].copy()
    if settled.empty:
        print("Nessun segnale chiuso nel dataset: servono piu' giorni di raccolta.")
        return 0

    settled["Minute"] = pd.to_numeric(settled["Minute"], errors="coerce").fillna(0).astype(int)
    for column in ["ShotsOnGoalAtOpen", "TotalShotsAtOpen", "CornersAtOpen", "TitanPressureScore", "TotalGoalsAtOpen"]:
        if column in settled.columns:
            settled[column] = pd.to_numeric(settled[column], errors="coerce").fillna(0.0)

    print(f"Dataset: {len(df)} righe, {len(settled)} chiuse (WIN/LOSS)\n")

    print("=== WR per market e tier ===")
    for market_name, market_part in settled.groupby("Market"):
        quota = MARKET_QUOTAS.get(market_name, QUOTA)
        print(f"{market_name}:")
        real = market_part[market_part["Tier"] != "LEARNING"]
        shadow = market_part[market_part["Tier"] == "LEARNING"]
        print(wr_line(real, "reali (pubblicati)", quota, args.min_sample))
        print(wr_line(shadow, "shadow (LEARNING)", quota, args.min_sample))
        for tier_name, tier_part in real.groupby("Tier"):
            print(wr_line(tier_part, f"tier {tier_name}", quota, args.min_sample))
        print()

    print("=== WR per fascia minuto di apertura ===")
    for market_name, market_part in settled.groupby("Market"):
        quota = MARKET_QUOTAS.get(market_name, QUOTA)
        print(f"{market_name}:")
        for bucket, bucket_part in market_part.groupby("MinuteBucket"):
            print(wr_line(bucket_part, f"bucket {bucket}", quota, args.min_sample))
        print()

    print("=== VERDETTO: finestra HT estesa 21-28' sotto pressione ===")
    ht = settled[
        (settled["Market"] == "OVER 0.5 HT")
        & (settled["Minute"].between(21, 28))
        & (settled["TotalGoalsAtOpen"] == 0)
    ]
    # Proxy pressione: il dataset non salva shots_insidebox/goalkeeper_saves,
    # quindi usiamo tiri totali/in porta e TitanPressureScore come approssimazione.
    pressured = ht[
        ((ht["TotalShotsAtOpen"] >= 6) & (ht["ShotsOnGoalAtOpen"] >= 2))
        | (ht["TitanPressureScore"] >= 2)
    ]
    quota = MARKET_QUOTAS.get("OVER 0.5 HT", QUOTA)
    print(wr_line(ht, "21-28' tutti", quota, args.min_sample))
    print(wr_line(pressured, "21-28' con pressione", quota, args.min_sample))
    wins = int((pressured["Outcome"] == "WIN").sum())
    total = int(len(pressured))
    if total >= args.min_sample and total and wins / total >= breakeven_wr(quota) + 0.03:
        print(">>> La finestra estesa sotto pressione batte il breakeven con margine:")
        print(">>> puoi attivare HT_PRESSURE_WINDOW_ENABLED=1 nel .env")
    elif total < args.min_sample:
        print(f">>> Campione insufficiente ({total}/{args.min_sample}): lascia la finestra spenta e continua a raccogliere shadow.")
    else:
        print(">>> WR sotto il breakeven: lascia HT_PRESSURE_WINDOW_ENABLED=0.")
    print()

    print("=== NEXT GOAL: WR per finestra minuto (verifica filtro contestuale) ===")
    ng = settled[settled["Market"] == "NEXT GOAL LIVE"]
    if ng.empty:
        print("  nessun dato NEXT GOAL")
    else:
        quota = MARKET_QUOTAS.get("NEXT GOAL LIVE", QUOTA)
        windows = [(1, 11), (12, 19), (20, 44), (45, 69), (70, 120)]
        for lo, hi in windows:
            part = ng[ng["Minute"].between(lo, hi)]
            print(wr_line(part, f"minuto {lo}-{hi}", quota, args.min_sample))
    return 0


if __name__ == "__main__":
    sys.exit(main())
