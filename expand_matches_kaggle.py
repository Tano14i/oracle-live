import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


MATCHES_PATH = "Matches.csv"
REQUIRED_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]
COLUMN_MAPPING = {
    "Date": "MatchDate",
    "date": "MatchDate",
    "fecha": "MatchDate",
    "match_date": "MatchDate",
    "HomeTeam": "HomeTeam",
    "home_team": "HomeTeam",
    "home": "HomeTeam",
    "team_home": "HomeTeam",
    "home_name": "HomeTeam",
    "AwayTeam": "AwayTeam",
    "away_team": "AwayTeam",
    "away": "AwayTeam",
    "team_away": "AwayTeam",
    "away_name": "AwayTeam",
    "FTHG": "FTHome",
    "home_score": "FTHome",
    "home_goals": "FTHome",
    "HG": "FTHome",
    "gh": "FTHome",
    "FTAG": "FTAway",
    "away_score": "FTAway",
    "away_goals": "FTAway",
    "AG": "FTAway",
    "ga": "FTAway",
    "HTHG": "HTHome",
    "ht_home_goals": "HTHome",
    "HTAG": "HTAway",
    "ht_away_goals": "HTAway",
}


def discover_csv_files(source: str) -> list[Path]:
    source_path = Path(source)
    if source_path.is_file():
        return [source_path]
    if source_path.is_dir():
        return sorted(source_path.rglob("*.csv"))
    raise FileNotFoundError(f"Source not found: {source}")


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    if df.empty:
        return None

    working = df.rename(columns=COLUMN_MAPPING).copy()

    if {"venue", "opponent", "team", "gf", "ga"}.issubset(working.columns):
        venue_mask = working["venue"].astype(str).str.lower().eq("home")
        working = working.loc[venue_mask].copy()
        working = working.rename(
            columns={
                "team": "HomeTeam",
                "opponent": "AwayTeam",
                "gf": "FTHome",
                "ga": "FTAway",
            }
        )

    core = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway"]
    if not all(column in working.columns for column in core):
        return None

    if "HTHome" not in working.columns:
        working["HTHome"] = 0
    if "HTAway" not in working.columns:
        working["HTAway"] = 0

    working = working[REQUIRED_COLUMNS].copy()
    working["MatchDate"] = pd.to_datetime(working["MatchDate"], errors="coerce")
    working = working.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam"])

    for column in ["HomeTeam", "AwayTeam"]:
        working[column] = working[column].astype(str).str.strip().str.upper()

    for column in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0).astype(int)

    return working


def load_source_frames(source: str) -> tuple[list[pd.DataFrame], list[str]]:
    frames = []
    imported_files = []
    for csv_file in discover_csv_files(source):
        try:
            df = pd.read_csv(csv_file, low_memory=False)
        except Exception:
            continue
        normalized = normalize_frame(df)
        if normalized is None or normalized.empty:
            continue
        frames.append(normalized)
        imported_files.append(str(csv_file))
    return frames, imported_files


def backup_matches_file(matches_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = matches_path.with_name(f"{matches_path.stem}_backup_{timestamp}{matches_path.suffix}")
    backup_path.write_bytes(matches_path.read_bytes())
    return backup_path


def merge_into_matches(source: str, matches_path: str = MATCHES_PATH) -> None:
    matches_file = Path(matches_path)
    if not matches_file.exists():
        raise FileNotFoundError(f"Matches file not found: {matches_path}")

    existing = pd.read_csv(matches_file, low_memory=False)
    existing = normalize_frame(existing)
    if existing is None:
        raise RuntimeError("Existing Matches.csv does not contain the required schema.")

    source_frames, imported_files = load_source_frames(source)
    if not source_frames:
        print("No compatible CSV files found in the source.")
        return

    merged_source = pd.concat(source_frames, ignore_index=True)
    merged = pd.concat([existing, merged_source], ignore_index=True)
    merged = merged.sort_values("MatchDate")
    before_dedup = len(merged)
    merged = merged.drop_duplicates(subset=["MatchDate", "HomeTeam", "AwayTeam"], keep="last")
    merged["MatchDate"] = merged["MatchDate"].dt.strftime("%Y-%m-%d")

    backup_path = backup_matches_file(matches_file)
    merged.to_csv(matches_file, index=False)

    unique_teams = pd.concat([merged["HomeTeam"], merged["AwayTeam"]]).nunique()
    print("Kaggle merge completed.")
    print(f"- Imported CSV files: {len(imported_files)}")
    print(f"- Backup created: {backup_path}")
    print(f"- Rows before merge: {len(existing)}")
    print(f"- Rows after merge: {len(merged)}")
    print(f"- Duplicates removed: {before_dedup - len(merged)}")
    print(f"- Unique teams available: {unique_teams}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge one Kaggle dataset (CSV or folder) into Matches.csv.")
    parser.add_argument("source", help="CSV file or folder extracted from Kaggle")
    parser.add_argument("--matches", default=MATCHES_PATH, help="Target Matches.csv path")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    merge_into_matches(args.source, args.matches)
