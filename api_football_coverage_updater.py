import argparse
import os
import time
from datetime import datetime

import pandas as pd
import requests

from config import API_KEY, CSV_PATH

API_BASE = "https://v3.football.api-sports.io"
FINAL_STATUSES = {"FT", "AET", "PEN"}
OUTPUT_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]


def backup_file(path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(path)
    backup_path = f"{base}_api_football_backup_{timestamp}{ext}"
    with open(path, "rb") as src, open(backup_path, "wb") as dst:
        dst.write(src.read())
    return backup_path


def normalize_matches_frame(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for col in OUTPUT_COLUMNS:
        if col not in working.columns:
            if col in {"HTHome", "HTAway"}:
                working[col] = 0
            else:
                raise ValueError(f"Missing required column: {col}")

    working = working[OUTPUT_COLUMNS].copy()
    working["MatchDate"] = pd.to_datetime(working["MatchDate"], errors="coerce")
    working = working.dropna(subset=["MatchDate", "HomeTeam", "AwayTeam"])
    working["HomeTeam"] = working["HomeTeam"].astype(str).str.strip().str.upper()
    working["AwayTeam"] = working["AwayTeam"].astype(str).str.strip().str.upper()
    for col in ["FTHome", "FTAway", "HTHome", "HTAway"]:
        working[col] = pd.to_numeric(working[col], errors="coerce").fillna(0).astype(int)
    return working


def api_get(session: requests.Session, endpoint: str, params: dict) -> list:
    page = 1
    rows = []
    while True:
        payload = dict(params)
        payload["page"] = page
        response = session.get(f"{API_BASE}{endpoint}", params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        rows.extend(data.get("response", []))
        paging = data.get("paging", {}) or {}
        current = int(paging.get("current", page) or page)
        total = int(paging.get("total", current) or current)
        if current >= total:
            break
        page += 1
        time.sleep(0.25)
    return rows


def _rows_to_leagues(rows: list[dict], fallback_country: str, season: int | None) -> list[dict]:
    leagues = []
    seen = set()
    for row in rows:
        league = row.get("league", {}) or {}
        country_info = row.get("country", {}) or {}
        league_id = league.get("id")
        league_type = str(league.get("type", "")).strip().lower()
        if not league_id or league_type != "league":
            continue

        resolved_season = season
        if resolved_season is None:
            seasons = row.get("seasons", []) or []
            preferred = None
            for season_info in seasons:
                year = season_info.get("year")
                if year is None:
                    continue
                if season_info.get("current") is True:
                    preferred = int(year)
                    break
                if preferred is None:
                    preferred = int(year)
            if preferred is None:
                continue
            resolved_season = preferred

        key = (int(league_id), int(resolved_season))
        if key in seen:
            continue
        seen.add(key)
        leagues.append(
            {
                "league_id": int(league_id),
                "league_name": str(league.get("name", "Unknown")),
                "country": str(country_info.get("name", fallback_country)),
                "season": int(resolved_season),
            }
        )
    return leagues


def get_country_leagues(session: requests.Session, country: str, season: int) -> list[dict]:
    rows = api_get(session, "/leagues", {"country": country, "season": season, "current": "true"})
    leagues = _rows_to_leagues(rows, country, season)
    if leagues:
        return leagues

    rows = api_get(session, "/leagues", {"country": country, "season": season})
    leagues = _rows_to_leagues(rows, country, season)
    if leagues:
        return leagues

    rows = api_get(session, "/leagues", {"country": country})
    leagues = []
    seen = set()
    for row in rows:
        league = row.get("league", {}) or {}
        league_id = league.get("id")
        league_type = str(league.get("type", "")).strip().lower()
        if not league_id or league_type != "league":
            continue

        seasons = row.get("seasons", []) or []
        available_years = {int(item.get("year")) for item in seasons if item.get("year") is not None}
        if season not in available_years:
            continue

        items = _rows_to_leagues([row], country, season)
        if not items:
            continue

        key = (items[0]["league_id"], items[0]["season"] )
        if key in seen:
            continue
        seen.add(key)
        leagues.extend(items)
    return leagues



def fixture_to_row(fixture: dict) -> dict | None:
    fixture_info = fixture.get("fixture", {}) or {}
    teams = fixture.get("teams", {}) or {}
    goals = fixture.get("goals", {}) or {}
    score = fixture.get("score", {}) or {}
    status = ((fixture_info.get("status", {}) or {}).get("short") or "").upper()
    if status not in FINAL_STATUSES:
        return None

    date_value = fixture_info.get("date")
    if not date_value:
        return None

    home_name = ((teams.get("home", {}) or {}).get("name") or "").strip()
    away_name = ((teams.get("away", {}) or {}).get("name") or "").strip()
    if not home_name or not away_name:
        return None

    halftime = score.get("halftime", {}) or {}
    return {
        "MatchDate": pd.to_datetime(date_value, errors="coerce"),
        "HomeTeam": home_name,
        "AwayTeam": away_name,
        "FTHome": goals.get("home", 0) or 0,
        "FTAway": goals.get("away", 0) or 0,
        "HTHome": halftime.get("home", 0) or 0,
        "HTAway": halftime.get("away", 0) or 0,
    }


def fetch_league_fixtures(session: requests.Session, league_id: int, season: int) -> pd.DataFrame:
    rows = api_get(session, "/fixtures", {"league": league_id, "season": season})
    normalized_rows = []
    for row in rows:
        normalized = fixture_to_row(row)
        if normalized is not None:
            normalized_rows.append(normalized)
    if not normalized_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return normalize_matches_frame(pd.DataFrame(normalized_rows))


def build_targets(session: requests.Session, countries: list[str], league_ids: list[int], seasons: list[int]) -> list[dict]:
    targets = []
    seen = set()

    for league_id in league_ids:
        for season in seasons:
            key = (league_id, season)
            if key in seen:
                continue
            seen.add(key)
            targets.append({"league_id": league_id, "league_name": f"League {league_id}", "country": "custom", "season": season})

    for country in countries:
        for season in seasons:
            for item in get_country_leagues(session, country, season):
                key = (item["league_id"], item["season"])
                if key in seen:
                    continue
                seen.add(key)
                targets.append(item)

    return targets


def merge_into_matches(csv_path: str, new_frames: list[pd.DataFrame]) -> tuple[str, int, int, int]:
    df_old = pd.read_csv(csv_path, low_memory=False)
    df_old = normalize_matches_frame(df_old)
    df_new = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    if df_new.empty:
        return "", len(df_old), len(df_old), 0

    df_total = pd.concat([df_old, df_new], ignore_index=True)
    before_dedup = len(df_total)
    df_total["MatchDate"] = pd.to_datetime(df_total["MatchDate"], errors="coerce")
    df_total = df_total.dropna(subset=["MatchDate"])
    df_total = df_total.sort_values("MatchDate")
    df_total = df_total.drop_duplicates(subset=["MatchDate", "HomeTeam", "AwayTeam"], keep="last")
    df_total["MatchDate"] = df_total["MatchDate"].dt.strftime("%Y-%m-%d")

    backup_path = backup_file(csv_path)
    df_total.to_csv(csv_path, index=False)
    return backup_path, len(df_old), len(df_total), before_dedup - len(df_total)


def parse_args() -> argparse.Namespace:
    current_year = datetime.now().year
    parser = argparse.ArgumentParser(description="Expand Matches.csv using API-FOOTBALL historical fixtures.")
    parser.add_argument("--country", action="append", default=[], help="Country to import current leagues for. Repeatable.")
    parser.add_argument("--league-id", action="append", type=int, default=[], help="Specific league id to import. Repeatable.")
    parser.add_argument("--season", action="append", type=int, default=[], help="Season year used by API-FOOTBALL, e.g. 2025. Repeatable.")
    parser.add_argument("--max-leagues", type=int, default=0, help="Optional cap on number of league/season targets.")
    parser.add_argument("--sleep-ms", type=int, default=250, help="Delay between paginated API pages in milliseconds.")
    args = parser.parse_args()
    if not args.season:
        args.season = [current_year - 1, current_year]

    deduped_seasons = []
    seen_seasons = set()
    for season in args.season:
        if season in seen_seasons:
            continue
        seen_seasons.add(season)
        deduped_seasons.append(season)
    args.season = deduped_seasons
    return args


def main() -> None:
    args = parse_args()
    if not API_KEY:
        print("ERROR: API_KEY missing in .env / config.")
        return
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: Matches database not found: {CSV_PATH}")
        return
    if not args.country and not args.league_id:
        print("ERROR: specify at least one --country or one --league-id.")
        return

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})
    global_sleep_seconds = max(0, args.sleep_ms) / 1000.0

    print("Starting API-FOOTBALL coverage update...")
    print(f"Matches DB: {CSV_PATH}")
    print(f"Countries: {', '.join(args.country) if args.country else '-'}")
    print(f"League IDs: {', '.join(str(x) for x in args.league_id) if args.league_id else '-'}")
    print(f"Seasons: {', '.join(str(x) for x in args.season)}")

    targets = build_targets(session, args.country, args.league_id, args.season)
    if args.max_leagues > 0:
        targets = targets[: args.max_leagues]

    print(f"League/season targets: {len(targets)}")
    if not targets:
        print("No league targets resolved.")
        return

    imported_frames = []
    success = 0
    for target in targets:
        try:
            df_league = fetch_league_fixtures(session, target["league_id"], target["season"])
        except Exception as exc:
            print(f"SKIP league={target['league_id']} season={target['season']} country={target['country']} name={target['league_name']} error={exc}")
            time.sleep(global_sleep_seconds)
            continue

        if df_league.empty:
            print(f"EMPTY league={target['league_id']} season={target['season']} country={target['country']} name={target['league_name']}")
        else:
            imported_frames.append(df_league)
            success += 1
            print(f"OK league={target['league_id']} season={target['season']} country={target['country']} name={target['league_name']} rows={len(df_league)}")
        time.sleep(global_sleep_seconds)

    if not imported_frames:
        print("No finished fixtures imported from API-FOOTBALL.")
        return

    backup_path, before_rows, after_rows, duplicates_removed = merge_into_matches(CSV_PATH, imported_frames)
    print("\n" + "=" * 40)
    print("API-FOOTBALL COVERAGE UPDATE COMPLETED")
    print(f"League/season targets: {len(targets)}")
    print(f"Successful imports: {success}")
    print(f"Backup created: {backup_path}")
    print(f"Rows before update: {before_rows}")
    print(f"Rows after update: {after_rows}")
    print(f"Duplicates removed: {duplicates_removed}")
    print("=" * 40)


if __name__ == "__main__":
    main()



