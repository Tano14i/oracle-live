from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from oracle_prematch.api_football_odds import ApiFootballOddsClient
from oracle_prematch.pipeline import ScanSummary, build_outcomes_from_fixtures, write_outputs
from oracle_prematch.settings import (
    API_FOOTBALL_HOST,
    API_FOOTBALL_KEY,
    API_FOOTBALL_LOOKBACK_HOURS,
    API_FOOTBALL_TIMEOUT,
    DEFAULT_TOP,
    LATEST_JSON_PATH,
    LATEST_TEXT_PATH,
    PREMATCH_DB_PATH,
)
from oracle_prematch.storage import PrematchStore


@dataclass(slots=True)
class PrematchBotResult:
    summary: ScanSummary
    odds_rows: int
    snapshots_saved: int
    fixtures_seen: int
    source_name: str
    date_value: str


@dataclass(slots=True)
class PrematchCollectionResult:
    odds_rows: int
    snapshots_saved: int
    fixtures_seen: int
    source_name: str
    date_value: str
    fixture_ids: list[str]


def _build_client() -> ApiFootballOddsClient:
    return ApiFootballOddsClient(
        api_key=API_FOOTBALL_KEY,
        base_url=API_FOOTBALL_HOST,
        timeout_seconds=API_FOOTBALL_TIMEOUT,
    )


def _fetch_and_store_snapshots(
    scan_date: str,
    source_name: str,
    page_limit: int | None = None,
) -> PrematchCollectionResult:
    store = PrematchStore(PREMATCH_DB_PATH)
    client = _build_client()

    odds_rows = client.fetch_odds(date_value=scan_date, page_limit=page_limit)
    fixture_ids = [str(((row.get("fixture") or {}).get("id")) or "").strip() for row in odds_rows]
    fixture_ids = [fixture_id for fixture_id in fixture_ids if fixture_id]
    fixtures_by_id = client.fetch_fixtures_for_date(
        date_value=scan_date,
        fixture_ids=list(dict.fromkeys(fixture_ids)),
        page_limit=page_limit,
    )
    events = client.normalize_events(odds_rows, fixtures_by_id)

    snapshots_saved = 0
    touched_fixture_ids: list[str] = []
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
            source_name=source_name,
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
            snapshots_saved += 1
        touched_fixture_ids.append(event.fixture_id)

    return PrematchCollectionResult(
        odds_rows=len(odds_rows),
        snapshots_saved=snapshots_saved,
        fixtures_seen=len(list(dict.fromkeys(touched_fixture_ids))),
        source_name=source_name,
        date_value=scan_date,
        fixture_ids=list(dict.fromkeys(touched_fixture_ids)),
    )


def collect_prematch_snapshots(
    date_value: str | None = None,
    page_limit: int | None = None,
    source_name: str = "api-football-odds",
) -> PrematchCollectionResult:
    scan_date = date_value or datetime.now().date().isoformat()
    return _fetch_and_store_snapshots(scan_date=scan_date, source_name=source_name, page_limit=page_limit)


def run_prematch_bot_scan(
    date_value: str | None = None,
    top: int = DEFAULT_TOP,
    lookback_hours: int = API_FOOTBALL_LOOKBACK_HOURS,
    page_limit: int | None = None,
    source_name: str = "api-football-odds",
) -> PrematchBotResult:
    scan_date = date_value or datetime.now().date().isoformat()
    collection = _fetch_and_store_snapshots(scan_date=scan_date, source_name=source_name, page_limit=page_limit)
    store = PrematchStore(PREMATCH_DB_PATH)
    unique_fixture_ids = collection.fixture_ids
    fixtures = store.build_fixture_inputs(
        fixture_ids=unique_fixture_ids,
        lookback_hours=lookback_hours,
        source_name=source_name,
        min_snapshots=2,
    )
    outcomes = build_outcomes_from_fixtures(fixtures)
    run_id = store.save_run(source_name=source_name, total_fixtures=len(fixtures), outcomes=outcomes)

    summary = ScanSummary(
        run_id=run_id,
        source_name=source_name,
        total_fixtures=len(fixtures),
        flagged_total=sum(1 for outcome in outcomes if outcome.status != "IGNORE"),
        watch_live_total=sum(1 for outcome in outcomes if outcome.status == "WATCH LIVE"),
        manual_review_total=sum(1 for outcome in outcomes if outcome.status == "MANUAL REVIEW"),
        outcomes=[outcome for outcome in outcomes if outcome.status != "IGNORE"][:top],
    )
    write_outputs(summary, output_json_path=LATEST_JSON_PATH, output_text_path=LATEST_TEXT_PATH)
    return PrematchBotResult(
        summary=summary,
        odds_rows=collection.odds_rows,
        snapshots_saved=collection.snapshots_saved,
        fixtures_seen=collection.fixtures_seen,
        source_name=source_name,
        date_value=scan_date,
    )
