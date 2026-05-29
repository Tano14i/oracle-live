import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from config import API_KEY, CSV_PATH, MISSING_TEAMS_QUEUE_PATH

API_BASE = "https://v3.football.api-sports.io"
FINAL_STATUSES = {"FT", "AET", "PEN"}
OUTPUT_COLUMNS = ["MatchDate", "HomeTeam", "AwayTeam", "FTHome", "FTAway", "HTHome", "HTAway"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def backup_file(path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(path)
    backup_path = f"{base}_missing_team_backfill_{timestamp}{ext}"
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
    response = session.get(f"{API_BASE}{endpoint}", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("response", [])


def fixture_to_row(fixture: dict) -> dict | None:
    fixture_info = fixture.get("fixture", {}) or {}
    teams = fixture.get("teams", {}) or {}
    goals = fixture.get("goals", {}) or {}
    score = fixture.get("score", {}) or {}
    status = ((fixture_info.get("status", {}) or {}).get("short") or "").upper()
    if status not in FINAL_STATUSES:
        return None

    home_name = ((teams.get("home", {}) or {}).get("name") or "").strip()
    away_name = ((teams.get("away", {}) or {}).get("name") or "").strip()
    date_value = fixture_info.get("date")
    if not home_name or not away_name or not date_value:
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


def choose_team_candidate(rows: list[dict], team_name: str) -> dict | None:
    if not rows:
        return None
    target = normalize_name(team_name)
    best_row = None
    best_score = -1
    for row in rows:
        team = row.get("team", {}) or {}
        candidate_name = str(team.get("name", "")).strip()
        candidate_norm = normalize_name(candidate_name)
        score = 0
        if candidate_norm == target:
            score = 100
        elif target and target in candidate_norm:
            score = 80
        elif candidate_norm and candidate_norm in target:
            score = 70
        if score > best_score:
            best_score = score
            best_row = row
    return best_row if best_score >= 70 else None


def fetch_team_candidate(session: requests.Session, team_name: str, country: str) -> dict | None:
    params = {"search": team_name}
    if country:
        params["country"] = country
    rows = api_get(session, "/teams", params)
    candidate = choose_team_candidate(rows, team_name)
    if candidate or not country:
        return candidate
    rows = api_get(session, "/teams", {"search": team_name})
    return choose_team_candidate(rows, team_name)


def fetch_team_history(session: requests.Session, team_id: int, seasons: list[int]) -> pd.DataFrame:
    rows = []
    for season in seasons:
        fixtures = api_get(session, "/fixtures", {"team": team_id, "season": season})
        for fixture in fixtures:
            normalized = fixture_to_row(fixture)
            if normalized is not None:
                rows.append(normalized)
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return normalize_matches_frame(pd.DataFrame(rows))


def load_queue() -> dict:
    if not os.path.exists(MISSING_TEAMS_QUEUE_PATH):
        return {}
    with open(MISSING_TEAMS_QUEUE_PATH, "r", encoding="utf-8-sig") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def save_queue(queue: dict) -> None:
    with open(MISSING_TEAMS_QUEUE_PATH, "w", encoding="utf-8") as handle:
        json.dump(queue, handle, indent=2)


def merge_rows(csv_path: str, imported_frames: list[pd.DataFrame]) -> tuple[str, int, int, int]:
    df_old = pd.read_csv(csv_path, low_memory=False)
    df_old = normalize_matches_frame(df_old)
    df_new = pd.concat(imported_frames, ignore_index=True) if imported_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
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
    parser = argparse.ArgumentParser(description="Backfill missing teams queue using API-FOOTBALL team search.")
    parser.add_argument("--limit", type=int, default=25, help="Max pending queue items to process.")
    parser.add_argument("--retry-hours", type=int, default=12, help="Hours to wait before retrying a failed team.")
    parser.add_argument("--season", action="append", type=int, default=[], help="Season year to import. Repeatable.")
    args = parser.parse_args()
    if not args.season:
        args.season = [current_year - 1, current_year]
    args.season = list(dict.fromkeys(args.season))
    return args

def parse_attempt_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def is_retry_due(item: dict, reference_time: datetime) -> bool:
    retry_at = item.get("next_retry_at")
    if not retry_at:
        return True
    return parse_attempt_timestamp(retry_at) <= reference_time


def main() -> None:
    args = parse_args()
    if not API_KEY:
        print("ERROR: API_KEY missing in .env / config.")
        return
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: Matches database not found: {CSV_PATH}")
        return

    queue = load_queue()
    now_utc = datetime.now(timezone.utc)
    pending_total = len([1 for _, value in queue.items() if str(value.get("status", "pending")) == "pending"])
    pending_items = [
        (key, value)
        for key, value in queue.items()
        if str(value.get("status", "pending")) == "pending" and is_retry_due(value, now_utc)
    ]
    pending_items = sorted(
        pending_items,
        key=lambda item: (
            parse_attempt_timestamp(item[1].get("last_attempt")),
            -int(item[1].get("count", 0)),
            str(item[1].get("team_name", "")).lower(),
        ),
    )[: args.limit]

    print("Starting API-FOOTBALL missing-team backfill...")
    print(f"Queue path: {MISSING_TEAMS_QUEUE_PATH}")
    print(f"Pending queue items: {pending_total}")
    print(f"Eligible queue items: {len(pending_items)}")
    print(f"Processing limit: {min(args.limit, len(pending_items))}")
    print(f"Seasons: {', '.join(str(x) for x in args.season)}")

    if not pending_items:
        print("No eligible missing-team items to process.")
        return

    session = requests.Session()
    session.headers.update({"x-apisports-key": API_KEY})

    imported_frames = []
    resolved = 0
    unresolved = 0
    imported_rows_total = 0

    for key, item in pending_items:
        team_name = str(item.get("team_name", "")).strip()
        country = str(item.get("country", "")).strip()
        if not team_name:
            continue
        next_retry_at = (datetime.now(timezone.utc) + timedelta(hours=max(1, int(args.retry_hours)))).isoformat()

        try:
            candidate = fetch_team_candidate(session, team_name, country)
        except Exception as exc:
            item["last_error"] = str(exc)
            item["last_attempt"] = now_iso()
            item["next_retry_at"] = next_retry_at
            unresolved += 1
            print(f"SEARCH_FAIL team={team_name} country={country or '-'} error={exc}")
            continue

        if not candidate:
            item["last_error"] = "team search returned no confident match"
            item["last_attempt"] = now_iso()
            item["next_retry_at"] = next_retry_at
            unresolved += 1
            print(f"NO_MATCH team={team_name} country={country or '-'}")
            continue

        team = candidate.get("team", {}) or {}
        team_id = team.get("id")
        resolved_name = str(team.get("name", team_name))
        if not team_id:
            item["last_error"] = "team search returned match without id"
            item["last_attempt"] = now_iso()
            item["next_retry_at"] = next_retry_at
            unresolved += 1
            print(f"NO_ID team={team_name} resolved={resolved_name}")
            continue

        try:
            df_team = fetch_team_history(session, int(team_id), args.season)
        except Exception as exc:
            item["last_error"] = str(exc)
            item["last_attempt"] = now_iso()
            item["next_retry_at"] = next_retry_at
            unresolved += 1
            print(f"FIXTURE_FAIL team={team_name} resolved={resolved_name} id={team_id} error={exc}")
            continue

        item["last_attempt"] = now_iso()
        item["resolved_team_name"] = resolved_name
        item["resolved_team_id"] = int(team_id)
        if df_team.empty:
            item["last_error"] = "no finished fixtures imported"
            unresolved += 1
            print(f"EMPTY team={team_name} resolved={resolved_name} id={team_id}")
            continue

        imported_frames.append(df_team)
        item["status"] = "resolved"
        item["resolved_at"] = now_iso()
        item["imported_rows"] = int(len(df_team))
        item.pop("next_retry_at", None)
        item.pop("last_error", None)
        resolved += 1
        imported_rows_total += int(len(df_team))
        print(f"OK team={team_name} resolved={resolved_name} id={team_id} rows={len(df_team)}")

    save_queue(queue)
    pending_after = len([1 for _, value in queue.items() if str(value.get("status", "pending")) == "pending"])

    if not imported_frames:
        print("No fixtures imported from missing-team queue.")
        print(f"Resolved items: {resolved}")
        print(f"Unresolved items: {unresolved}")
        print(f"Pending queue items remaining: {pending_after}")
        return

    backup_path, before_rows, after_rows, duplicates_removed = merge_rows(CSV_PATH, imported_frames)
    print("\n" + "=" * 40)
    print("MISSING-TEAM BACKFILL COMPLETED")
    print(f"Resolved queue items: {resolved}")
    print(f"Unresolved queue items: {unresolved}")
    print(f"Pending queue items remaining: {pending_after}")
    print(f"Rows imported total: {imported_rows_total}")
    print(f"Backup created: {backup_path}")
    print(f"Rows before update: {before_rows}")
    print(f"Rows after update: {after_rows}")
    print(f"Duplicates removed: {duplicates_removed}")
    print("=" * 40)


if __name__ == "__main__":
    main()





