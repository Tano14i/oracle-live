import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(r"C:\Users\Gebruiker\Desktop\Oracle Titan v5.0 - Full API Script\oracle_titan_v24_simple.db")
OUTPUT_PATH = Path(r"C:\Users\Gebruiker\Desktop\Oracle Live\titan_raw_snapshots_export.csv")

QUERY = """
SELECT
    snapshot_id,
    fixture_id,
    timestamp,
    odds_timestamp,
    league,
    dna_xg,
    shots,
    sot,
    da,
    corners,
    possession_diff,
    rc_home,
    rc_away,
    minute,
    score_diff,
    total_goals_at_signal,
    market_type,
    odds_live,
    target_outcome
FROM raw_snapshots
WHERE target_outcome IN (0, 1)
ORDER BY timestamp
"""

RENAME_MAP = {
    "snapshot_id": "SnapshotId",
    "fixture_id": "FixtureId",
    "timestamp": "SnapshotTimeUTC",
    "odds_timestamp": "OddsTimeUTC",
    "league": "LeagueName",
    "dna_xg": "DNAxG",
    "shots": "TotalShots",
    "sot": "ShotsOnGoal",
    "da": "DangerousAttacks",
    "corners": "Corners",
    "possession_diff": "PossessionDiff",
    "rc_home": "RedCardsHome",
    "rc_away": "RedCardsAway",
    "minute": "Minute",
    "score_diff": "ScoreDiff",
    "total_goals_at_signal": "TotalGoalsAtSignal",
    "market_type": "MarketType",
    "odds_live": "OddsLive",
    "target_outcome": "TargetOutcome",
}


def main():
    print("Titan snapshot export starting...")
    print(f"Source DB: {DB_PATH}")
    print(f"Output CSV: {OUTPUT_PATH}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Titan DB not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(QUERY, conn)

    if df.empty:
        print("No settled Titan snapshots found.")
        return

    df = df.rename(columns=RENAME_MAP)
    df["TargetLabel"] = df["TargetOutcome"].map({1: "WIN", 0: "LOSS"}).fillna("")
    df.to_csv(OUTPUT_PATH, index=False)

    print("Export completed.")
    print(f"Rows exported: {len(df)}")
    print(f"Distinct fixtures: {df['FixtureId'].nunique()}")
    print(f"Distinct leagues: {df['LeagueName'].nunique()}")
    print(f"Market types: {', '.join(sorted(df['MarketType'].dropna().astype(str).unique()))}")
    print("Top missing odds rows:", int(df['OddsLive'].isna().sum()))


if __name__ == "__main__":
    main()
