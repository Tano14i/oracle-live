from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from oracle_prematch.alerts import build_alert_text
from oracle_prematch.loader import load_fixtures
from oracle_prematch.models import ScanOutcome
from oracle_prematch.scoring import score_fixture
from oracle_prematch.storage import PrematchStore


@dataclass(slots=True)
class ScanSummary:
    run_id: int
    source_name: str
    total_fixtures: int
    flagged_total: int
    watch_live_total: int
    manual_review_total: int
    outcomes: list[ScanOutcome]


def build_outcomes(input_path: str) -> list[ScanOutcome]:
    fixtures = load_fixtures(input_path)
    return build_outcomes_from_fixtures(fixtures)


def build_outcomes_from_fixtures(fixtures) -> list[ScanOutcome]:
    outcomes: list[ScanOutcome] = []
    now_utc = datetime.now(timezone.utc)

    for fixture in fixtures:
        scored = score_fixture(fixture, now_utc=now_utc)
        outcome = ScanOutcome(
            fixture_id=fixture.fixture_id,
            sport=fixture.sport,
            country=fixture.country,
            league=fixture.league,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            kickoff_utc=fixture.kickoff_utc,
            risk_score=scored["risk_score"],
            status=scored["status"],
            explainability=scored["explainability"],
            leading_market=scored["leading_market"],
            largest_drop_pct=scored["largest_drop_pct"],
            bookmaker_count_avg=scored["bookmaker_count_avg"],
            public_news_hits=fixture.public_news_hits,
            flags=scored["flags"],
            metrics=scored["metrics"],
            alert_text="",
            tags=fixture.tags,
            notes=fixture.notes,
        )
        outcome.alert_text = build_alert_text(outcome)
        outcomes.append(outcome)

    outcomes.sort(
        key=lambda item: (
            item.risk_score,
            item.status == "WATCH LIVE",
            item.largest_drop_pct,
        ),
        reverse=True,
    )
    return outcomes


def run_scan(
    input_path: str,
    db_path: str,
    source_name: str,
    top: int,
    output_json_path: str,
    output_text_path: str,
) -> ScanSummary:
    outcomes = build_outcomes(input_path)
    store = PrematchStore(db_path)
    run_id = store.save_run(source_name=source_name, total_fixtures=len(outcomes), outcomes=outcomes)

    flagged = [outcome for outcome in outcomes if outcome.status != "IGNORE"][:top]
    summary = ScanSummary(
        run_id=run_id,
        source_name=source_name,
        total_fixtures=len(outcomes),
        flagged_total=sum(1 for outcome in outcomes if outcome.status != "IGNORE"),
        watch_live_total=sum(1 for outcome in outcomes if outcome.status == "WATCH LIVE"),
        manual_review_total=sum(1 for outcome in outcomes if outcome.status == "MANUAL REVIEW"),
        outcomes=flagged,
    )
    write_outputs(summary, output_json_path=output_json_path, output_text_path=output_text_path)
    return summary


def write_outputs(summary: ScanSummary, output_json_path: str, output_text_path: str) -> None:
    json_path = Path(output_json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "run_id": summary.run_id,
                "source_name": summary.source_name,
                "total_fixtures": summary.total_fixtures,
                "flagged_total": summary.flagged_total,
                "watch_live_total": summary.watch_live_total,
                "manual_review_total": summary.manual_review_total,
                "watchlist": [outcome.to_dict() for outcome in summary.outcomes],
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    lines = [
        f"Run #{summary.run_id} | source={summary.source_name}",
        f"Fixtures={summary.total_fixtures} | flagged={summary.flagged_total} | watch_live={summary.watch_live_total} | manual_review={summary.manual_review_total}",
        "",
    ]
    for index, outcome in enumerate(summary.outcomes, start=1):
        lines.extend(
            [
                f"{index}. {outcome.home_team} vs {outcome.away_team}",
                f"   {outcome.country} | {outcome.league}",
                f"   score={outcome.risk_score} | status={outcome.status} | drop=-{outcome.largest_drop_pct:.1f}% | explainability={outcome.explainability}",
                f"   flags={', '.join(outcome.flags[:4]) if outcome.flags else 'none'}",
                "",
            ]
        )

    text_path = Path(output_text_path)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
