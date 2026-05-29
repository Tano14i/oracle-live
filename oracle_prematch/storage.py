from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oracle_prematch.loader import parse_datetime
from oracle_prematch.models import FixtureInput, OddsSnapshot, ScanOutcome


SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_utc TEXT NOT NULL,
    source_name TEXT NOT NULL,
    total_fixtures INTEGER NOT NULL,
    flagged_total INTEGER NOT NULL,
    watch_live_total INTEGER NOT NULL,
    manual_review_total INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    country TEXT,
    league TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff_utc TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    fixture_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    status TEXT NOT NULL,
    explainability TEXT NOT NULL,
    leading_market TEXT NOT NULL,
    largest_drop_pct REAL NOT NULL,
    bookmaker_count_avg REAL NOT NULL,
    public_news_hits INTEGER NOT NULL,
    flags_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    alert_text TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES scan_runs(id),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    bookmaker_count INTEGER NOT NULL,
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    over25_odds REAL,
    under25_odds REAL,
    raw_json TEXT NOT NULL,
    UNIQUE (fixture_id, source_name, captured_at_utc),
    FOREIGN KEY (fixture_id) REFERENCES fixtures(fixture_id)
);
"""


class PrematchStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def upsert_fixture(
        self,
        fixture_id: str,
        sport: str,
        country: str,
        league: str,
        home_team: str,
        away_team: str,
        kickoff_utc: str,
        tags: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        tags_json = json.dumps(tags or [], ensure_ascii=True)
        notes_json = json.dumps(notes or [], ensure_ascii=True)
        seen_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO fixtures (
                    fixture_id, sport, country, league, home_team, away_team, kickoff_utc, tags_json, notes_json, last_seen_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fixture_id) DO UPDATE SET
                    sport = excluded.sport,
                    country = excluded.country,
                    league = excluded.league,
                    home_team = excluded.home_team,
                    away_team = excluded.away_team,
                    kickoff_utc = excluded.kickoff_utc,
                    tags_json = excluded.tags_json,
                    notes_json = excluded.notes_json,
                    last_seen_utc = excluded.last_seen_utc
                """,
                (fixture_id, sport, country, league, home_team, away_team, kickoff_utc, tags_json, notes_json, seen_at),
            )
            conn.commit()

    def save_odds_snapshot(
        self,
        fixture_id: str,
        source_name: str,
        captured_at_utc: str,
        bookmaker_count: int,
        home_odds: float | None,
        draw_odds: float | None,
        away_odds: float | None,
        over25_odds: float | None,
        under25_odds: float | None,
        raw_payload: dict,
    ) -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO odds_snapshots (
                    fixture_id, source_name, captured_at_utc, bookmaker_count, home_odds, draw_odds, away_odds,
                    over25_odds, under25_odds, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fixture_id,
                    source_name,
                    captured_at_utc,
                    bookmaker_count,
                    home_odds,
                    draw_odds,
                    away_odds,
                    over25_odds,
                    under25_odds,
                    json.dumps(raw_payload, ensure_ascii=True),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def save_run(self, source_name: str, total_fixtures: int, outcomes: list[ScanOutcome]) -> int:
        started_at = datetime.now(timezone.utc).isoformat()
        flagged_total = sum(1 for outcome in outcomes if outcome.status != "IGNORE")
        watch_live_total = sum(1 for outcome in outcomes if outcome.status == "WATCH LIVE")
        manual_review_total = sum(1 for outcome in outcomes if outcome.status == "MANUAL REVIEW")
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scan_runs (
                    started_at_utc, source_name, total_fixtures, flagged_total, watch_live_total, manual_review_total
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (started_at, source_name, total_fixtures, flagged_total, watch_live_total, manual_review_total),
            )
            run_id = int(cursor.lastrowid)
            for outcome in outcomes:
                conn.execute(
                    """
                    INSERT INTO fixtures (
                        fixture_id, sport, country, league, home_team, away_team, kickoff_utc, tags_json, notes_json, last_seen_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fixture_id) DO UPDATE SET
                        sport = excluded.sport,
                        country = excluded.country,
                        league = excluded.league,
                        home_team = excluded.home_team,
                        away_team = excluded.away_team,
                        kickoff_utc = excluded.kickoff_utc,
                        tags_json = excluded.tags_json,
                        notes_json = excluded.notes_json,
                        last_seen_utc = excluded.last_seen_utc
                    """,
                    (
                        outcome.fixture_id,
                        outcome.sport,
                        outcome.country,
                        outcome.league,
                        outcome.home_team,
                        outcome.away_team,
                        outcome.kickoff_utc.isoformat(),
                        json.dumps(outcome.tags, ensure_ascii=True),
                        json.dumps(outcome.notes, ensure_ascii=True),
                        started_at,
                    ),
                )
                if outcome.status == "IGNORE":
                    continue
                conn.execute(
                    """
                    INSERT INTO alerts (
                        run_id, fixture_id, created_at_utc, risk_score, status, explainability, leading_market,
                        largest_drop_pct, bookmaker_count_avg, public_news_hits, flags_json, metrics_json, alert_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        outcome.fixture_id,
                        started_at,
                        outcome.risk_score,
                        outcome.status,
                        outcome.explainability,
                        outcome.leading_market,
                        outcome.largest_drop_pct,
                        outcome.bookmaker_count_avg,
                        outcome.public_news_hits,
                        json.dumps(outcome.flags, ensure_ascii=True),
                        json.dumps(outcome.metrics, ensure_ascii=True),
                        outcome.alert_text,
                    ),
                )
            conn.commit()
        return run_id

    def fetch_latest_alerts(self, limit: int = 10) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT
                    alerts.created_at_utc,
                    alerts.fixture_id,
                    fixtures.country,
                    fixtures.league,
                    fixtures.home_team,
                    fixtures.away_team,
                    alerts.risk_score,
                    alerts.status,
                    alerts.explainability,
                    alerts.largest_drop_pct
                FROM alerts
                INNER JOIN fixtures ON fixtures.fixture_id = alerts.fixture_id
                ORDER BY alerts.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def fetch_latest_fixture_ids_for_source(self, source_name: str, limit: int = 1000) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT fixture_id, MAX(captured_at_utc) AS last_seen
                FROM odds_snapshots
                WHERE source_name = ?
                GROUP BY fixture_id
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (source_name, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def build_fixture_inputs(
        self,
        fixture_ids: list[str],
        lookback_hours: int,
        source_name: str,
        min_snapshots: int = 2,
    ) -> list[FixtureInput]:
        if not fixture_ids:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
        placeholders = ",".join("?" for _ in fixture_ids)
        params = [source_name, cutoff, *fixture_ids]
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    fixtures.fixture_id,
                    fixtures.sport,
                    fixtures.country,
                    fixtures.league,
                    fixtures.home_team,
                    fixtures.away_team,
                    fixtures.kickoff_utc,
                    fixtures.tags_json,
                    fixtures.notes_json,
                    odds_snapshots.captured_at_utc,
                    odds_snapshots.bookmaker_count,
                    odds_snapshots.home_odds,
                    odds_snapshots.draw_odds,
                    odds_snapshots.away_odds,
                    odds_snapshots.over25_odds,
                    odds_snapshots.under25_odds
                FROM fixtures
                INNER JOIN odds_snapshots ON odds_snapshots.fixture_id = fixtures.fixture_id
                WHERE odds_snapshots.source_name = ?
                  AND odds_snapshots.captured_at_utc >= ?
                  AND fixtures.fixture_id IN ({placeholders})
                ORDER BY fixtures.fixture_id, odds_snapshots.captured_at_utc ASC
                """,
                params,
            ).fetchall()

        grouped: dict[str, dict] = {}
        for row in rows:
            payload = grouped.setdefault(
                row["fixture_id"],
                {
                    "fixture_id": row["fixture_id"],
                    "sport": row["sport"],
                    "country": row["country"] or "",
                    "league": row["league"],
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                    "kickoff_utc": parse_datetime(row["kickoff_utc"]),
                    "tags": json.loads(row["tags_json"] or "[]"),
                    "notes": json.loads(row["notes_json"] or "[]"),
                    "snapshots": [],
                },
            )
            payload["snapshots"].append(
                OddsSnapshot(
                    captured_at_utc=parse_datetime(row["captured_at_utc"]),
                    home_odds=row["home_odds"],
                    draw_odds=row["draw_odds"],
                    away_odds=row["away_odds"],
                    over25_odds=row["over25_odds"],
                    under25_odds=row["under25_odds"],
                    bookmaker_count=row["bookmaker_count"],
                )
            )

        fixtures: list[FixtureInput] = []
        for payload in grouped.values():
            if len(payload["snapshots"]) < min_snapshots:
                continue
            fixtures.append(FixtureInput(**payload))
        return fixtures
