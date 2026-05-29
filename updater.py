import io
import os
from datetime import datetime

import pandas as pd
import requests


CSV_ORIGINALE = "Matches.csv"
SEASONS = [
    "1819",
    "1920",
    "2021",
    "2122",
    "2223",
    "2324",
    "2425",
    "2526",
]
LEAGUES = [
    "E0", "E1", "E2", "E3", "EC",
    "SP1", "SP2",
    "D1", "D2",
    "I1", "I2",
    "F1", "F2",
    "N1", "B1", "P1", "T1", "G1",
    "SC0", "SC1",
    "AUT", "SWZ", "POL", "CZE", "RUS",
    "IRL", "NOR", "SWE", "FIN", "DNK",
]
COLUMN_MAP = {
    "HomeTeam": "HomeTeam",
    "AwayTeam": "AwayTeam",
    "FTHG": "FTHome",
    "FTAG": "FTAway",
    "HTHG": "HTHome",
    "HTAG": "HTAway",
    "Date": "MatchDate",
}
REQUIRED_BASE = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway"]
OUTPUT_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]


def backup_file(path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(path)
    backup_path = f"{base}_updater_backup_{timestamp}{ext}"
    with open(path, "rb") as src, open(backup_path, "wb") as dst:
        dst.write(src.read())
    return backup_path


def normalize_matches_frame(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    missing = [col for col in REQUIRED_BASE if col not in working.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if "HTHome" not in working.columns:
        working["HTHome"] = 0
    if "HTAway" not in working.columns:
        working["HTAway"] = 0

    working = working[OUTPUT_COLUMNS].copy()
    date_series = working["MatchDate"].astype(str)
    iso_mask = date_series.str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)
    working.loc[iso_mask, "MatchDate"] = pd.to_datetime(date_series[iso_mask], format="%Y-%m-%d", errors="coerce")
    working.loc[~iso_mask, "MatchDate"] = pd.to_datetime(date_series[~iso_mask], dayfirst=True, errors="coerce")
    working = working.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam"])

    working["HomeTeam"] = working["HomeTeam"].astype(str).str.strip().str.upper()
    working["AwayTeam"] = working["AwayTeam"].astype(str).str.strip().str.upper()

    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        working[col] = pd.to_numeric(working[col], errors="coerce").fillna(0).astype(int)

    return working

def fetch_league_season(session: requests.Session, season: str, league: str) -> pd.DataFrame | None:
    url = f"https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
    try:
        response = session.get(url, timeout=15)
    except requests.RequestException:
        return None

    if response.status_code != 200 or not response.text.strip():
        return None

    try:
        df_temp = pd.read_csv(io.StringIO(response.text))
    except Exception:
        return None

    present_map = {source: target for source, target in COLUMN_MAP.items() if source in df_temp.columns}
    if not all(col in present_map for col in ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"]):
        return None

    df_filtered = df_temp[list(present_map.keys())].rename(columns=present_map)
    if "HTHome" not in df_filtered.columns:
        df_filtered["HTHome"] = 0
    if "HTAway" not in df_filtered.columns:
        df_filtered["HTAway"] = 0

    try:
        return normalize_matches_frame(df_filtered)
    except Exception:
        return None


def super_updater_massivo() -> None:
    cartella_script = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cartella_script)

    if not os.path.exists(CSV_ORIGINALE):
        print(f"ERROR: '{CSV_ORIGINALE}' not found.")
        return

    print("Reading current matches database...")
    try:
        df_vecchio = pd.read_csv(CSV_ORIGINALE, low_memory=False)
        df_vecchio = normalize_matches_frame(df_vecchio)
    except Exception as exc:
        print(f"ERROR: unable to read existing database: {exc}")
        return

    nuovi_match_list = []
    success_count = 0
    attempted = 0

    print("Starting extended football-data.co.uk update with HT scores...")
    session = requests.Session()
    session.headers.update({"User-Agent": "OracleLiveUpdater/1.0"})

    for season in SEASONS:
        for league in LEAGUES:
            attempted += 1
            df_new = fetch_league_season(session, season, league)
            if df_new is None or df_new.empty:
                continue
            nuovi_match_list.append(df_new)
            success_count += 1
            print(f"OK {league} {season}: {len(df_new)} rows")

    if not nuovi_match_list:
        print("No new compatible data found from football-data.co.uk.")
        return

    df_nuovi = pd.concat(nuovi_match_list, ignore_index=True)
    df_totale = pd.concat([df_vecchio, df_nuovi], ignore_index=True)
    before_dedup = len(df_totale)
    df_totale["MatchDate"] = pd.to_datetime(df_totale["MatchDate"], errors="coerce")
    df_totale = df_totale.dropna(subset=["MatchDate"])
    df_totale = df_totale.sort_values("MatchDate")
    df_totale = df_totale.drop_duplicates(subset=["MatchDate", "HomeTeam", "AwayTeam"], keep="last")
    df_totale["MatchDate"] = df_totale["MatchDate"].dt.strftime("%Y-%m-%d")

    backup_path = backup_file(CSV_ORIGINALE)
    df_totale.to_csv(CSV_ORIGINALE, index=False)

    print("\n" + "=" * 40)
    print("FOOTBALL-DATA UPDATE COMPLETED")
    print(f"Attempted league/season files: {attempted}")
    print(f"Downloaded successfully: {success_count}")
    print(f"Backup created: {backup_path}")
    print(f"Rows before update: {len(df_vecchio)}")
    print(f"Rows after update: {len(df_totale)}")
    print(f"Duplicates removed: {before_dedup - len(df_totale)}")
    print("=" * 40)


if __name__ == "__main__":
    super_updater_massivo()

