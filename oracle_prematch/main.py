from __future__ import annotations

import argparse
from datetime import datetime

from oracle_prematch.api_football_odds import ApiFootballOddsClient
from oracle_prematch.pipeline import build_outcomes_from_fixtures, run_scan, write_outputs, ScanSummary
from oracle_prematch.settings import (
    API_FOOTBALL_HOST,
    API_FOOTBALL_KEY,
    API_FOOTBALL_LOOKBACK_HOURS,
    API_FOOTBALL_TIMEOUT,
    DEFAULT_INPUT_PATH,
    DEFAULT_TOP,
    LATEST_JSON_PATH,
    LATEST_TEXT_PATH,
    PREMATCH_DB_PATH,
    SOURCE_NAME,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from oracle_prematch.storage import PrematchStore
from oracle_prematch.telegram_alerts import send_telegram_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oracle PreMatch anomaly scanner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Create or update the SQLite schema")
    init_db.add_argument("--db-path", default=PREMATCH_DB_PATH)

    scan = subparsers.add_parser("scan", help="Run a prematch scan from a JSON feed")
    scan.add_argument("--input", default=DEFAULT_INPUT_PATH)
    scan.add_argument("--db-path", default=PREMATCH_DB_PATH)
    scan.add_argument("--top", type=int, default=DEFAULT_TOP)
    scan.add_argument("--source-name", default=SOURCE_NAME)
    scan.add_argument("--output-json", default=LATEST_JSON_PATH)
    scan.add_argument("--output-text", default=LATEST_TEXT_PATH)
    scan.add_argument("--send-telegram", action="store_true")

    report = subparsers.add_parser("report", help="Show the latest saved alerts")
    report.add_argument("--db-path", default=PREMATCH_DB_PATH)
    report.add_argument("--limit", type=int, default=10)

    list_bookmakers = subparsers.add_parser("list-bookmakers", help="List available bookmakers from API-FOOTBALL odds")

    fetch = subparsers.add_parser("fetch-odds", help="Fetch current odds from API-FOOTBALL and score fixtures with history")
    fetch.add_argument("--db-path", default=PREMATCH_DB_PATH)
    fetch.add_argument("--date", default=datetime.now().date().isoformat())
    fetch.add_argument("--league-id", action="append", dest="league_ids", type=int, default=[])
    fetch.add_argument("--season", type=int, default=None)
    fetch.add_argument("--page-limit", type=int, default=None)
    fetch.add_argument("--lookback-hours", type=int, default=API_FOOTBALL_LOOKBACK_HOURS)
    fetch.add_argument("--top", type=int, default=DEFAULT_TOP)
    fetch.add_argument("--source-name", default="api-football-odds")
    fetch.add_argument("--output-json", default=LATEST_JSON_PATH)
    fetch.add_argument("--output-text", default=LATEST_TEXT_PATH)
    fetch.add_argument("--send-telegram", action="store_true")
    return parser


def command_init_db(db_path: str) -> int:
    PrematchStore(db_path)
    print(f"Prematch database ready: {db_path}")
    return 0


def command_scan(args) -> int:
    summary = run_scan(
        input_path=args.input,
        db_path=args.db_path,
        source_name=args.source_name,
        top=args.top,
        output_json_path=args.output_json,
        output_text_path=args.output_text,
    )
    print(
        f"Scan completed | run={summary.run_id} | fixtures={summary.total_fixtures} | "
        f"flagged={summary.flagged_total} | watch_live={summary.watch_live_total} | "
        f"manual_review={summary.manual_review_total}"
    )
    for outcome in summary.outcomes:
        print(
            f"- {outcome.home_team} vs {outcome.away_team} | {outcome.risk_score}/100 | "
            f"{outcome.status} | drop -{outcome.largest_drop_pct:.1f}% | {outcome.explainability}"
        )

    if args.send_telegram and summary.outcomes:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError("Missing PREMATCH_TELEGRAM_BOT_TOKEN or PREMATCH_TELEGRAM_CHAT_ID.")
        for outcome in summary.outcomes:
            send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, outcome.alert_text)
        print(f"Telegram alerts sent: {len(summary.outcomes)}")
    return 0


def command_report(db_path: str, limit: int) -> int:
    store = PrematchStore(db_path)
    rows = store.fetch_latest_alerts(limit=limit)
    if not rows:
        print("No prematch alerts saved yet.")
        return 0
    for row in rows:
        print(
            f"{row['created_at_utc']} | {row['home_team']} vs {row['away_team']} | "
            f"{row['country']} | {row['league']} | score={row['risk_score']} | "
            f"{row['status']} | drop=-{row['largest_drop_pct']:.1f}% | {row['explainability']}"
        )
    return 0


def build_client() -> ApiFootballOddsClient:
    return ApiFootballOddsClient(
        api_key=API_FOOTBALL_KEY,
        base_url=API_FOOTBALL_HOST,
        timeout_seconds=API_FOOTBALL_TIMEOUT,
    )


def command_list_bookmakers() -> int:
    client = build_client()
    rows = client.list_bookmakers()
    for row in rows:
        print(f"{row.get('id')} | {row.get('name')}")
    return 0


def command_fetch_odds(args) -> int:
    store = PrematchStore(args.db_path)
    client = build_client()
    saved_snapshots = 0
    touched_fixture_ids: list[str] = []

    odds_rows = client.fetch_odds(
        date_value=args.date,
        league_ids=args.league_ids,
        season=args.season,
        page_limit=args.page_limit,
    )
    fixture_ids = [str(((row.get("fixture") or {}).get("id")) or "").strip() for row in odds_rows]
    fixture_ids = [fixture_id for fixture_id in fixture_ids if fixture_id]
    fixtures_by_id = client.fetch_fixtures_for_date(
        date_value=args.date,
        fixture_ids=list(dict.fromkeys(fixture_ids)),
        league_ids=args.league_ids,
        season=args.season,
        page_limit=args.page_limit,
    )
    events = client.normalize_events(odds_rows, fixtures_by_id)

    for event in events:
        store.upsert_fixture(
            fixture_id=event.fixture_id,
            sport=event.sport,
            country=event.country,
            league=event.league,
            home_team=event.home_team,
            away_team=event.away_team,
            kickoff_utc=event.kickoff_utc.isoformat(),
            tags=event.tags,
            notes=event.notes,
        )
        saved = store.save_odds_snapshot(
            fixture_id=event.fixture_id,
            source_name=args.source_name,
            captured_at_utc=event.captured_at_utc.isoformat(),
            bookmaker_count=event.bookmaker_count,
            home_odds=event.home_odds,
            draw_odds=event.draw_odds,
            away_odds=event.away_odds,
            over25_odds=event.over25_odds,
            under25_odds=event.under25_odds,
            raw_payload=event.raw_payload,
        )
        if saved:
            saved_snapshots += 1
        touched_fixture_ids.append(event.fixture_id)

    unique_fixture_ids = list(dict.fromkeys(touched_fixture_ids))
    fixtures = store.build_fixture_inputs(
        fixture_ids=unique_fixture_ids,
        lookback_hours=args.lookback_hours,
        source_name=args.source_name,
        min_snapshots=2,
    )
    outcomes = build_outcomes_from_fixtures(fixtures)
    run_id = store.save_run(source_name=args.source_name, total_fixtures=len(fixtures), outcomes=outcomes)

    flagged = [outcome for outcome in outcomes if outcome.status != "IGNORE"][: args.top]
    summary = ScanSummary(
        run_id=run_id,
        source_name=args.source_name,
        total_fixtures=len(fixtures),
        flagged_total=sum(1 for outcome in outcomes if outcome.status != "IGNORE"),
        watch_live_total=sum(1 for outcome in outcomes if outcome.status == "WATCH LIVE"),
        manual_review_total=sum(1 for outcome in outcomes if outcome.status == "MANUAL REVIEW"),
        outcomes=flagged,
    )
    write_outputs(summary, output_json_path=args.output_json, output_text_path=args.output_text)

    print(
        f"Odds fetch completed | date={args.date} | odds_rows={len(odds_rows)} | snapshots_saved={saved_snapshots} | "
        f"fixtures_seen={len(unique_fixture_ids)} | scorable_fixtures={len(fixtures)} | "
        f"flagged={summary.flagged_total}"
    )
    if not fixtures:
        print("Not enough historical snapshots yet. Run fetch-odds again later to compare price movements.")
        return 0

    for outcome in summary.outcomes:
        print(
            f"- {outcome.home_team} vs {outcome.away_team} | {outcome.risk_score}/100 | "
            f"{outcome.status} | drop -{outcome.largest_drop_pct:.1f}% | {outcome.explainability}"
        )

    if args.send_telegram and summary.outcomes:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError("Missing PREMATCH_TELEGRAM_BOT_TOKEN or PREMATCH_TELEGRAM_CHAT_ID.")
        for outcome in summary.outcomes:
            send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, outcome.alert_text)
        print(f"Telegram alerts sent: {len(summary.outcomes)}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "init-db":
        return command_init_db(args.db_path)
    if args.command == "scan":
        return command_scan(args)
    if args.command == "report":
        return command_report(args.db_path, args.limit)
    if args.command == "list-bookmakers":
        return command_list_bookmakers()
    if args.command == "fetch-odds":
        return command_fetch_odds(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
