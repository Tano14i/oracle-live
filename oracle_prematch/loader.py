from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from oracle_prematch.models import FixtureInput, OddsSnapshot


MARKET_FIELDS = ("home_odds", "draw_odds", "away_odds", "over25_odds", "under25_odds")


def parse_datetime(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("Missing datetime value.")
    text = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _normalize_snapshots(raw_snapshots: list[dict]) -> list[OddsSnapshot]:
    snapshots: list[OddsSnapshot] = []
    for raw in raw_snapshots:
        snapshot = OddsSnapshot(
            captured_at_utc=parse_datetime(raw["captured_at_utc"]),
            home_odds=_to_float(raw.get("home_odds")),
            draw_odds=_to_float(raw.get("draw_odds")),
            away_odds=_to_float(raw.get("away_odds")),
            over25_odds=_to_float(raw.get("over25_odds")),
            under25_odds=_to_float(raw.get("under25_odds")),
            bookmaker_count=_to_int(raw.get("bookmaker_count")),
        )
        snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item.captured_at_utc)
    if len(snapshots) < 2:
        raise ValueError("Each fixture needs at least two odds snapshots.")
    return snapshots


def load_fixtures(input_path: str | Path) -> list[FixtureInput]:
    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_fixtures = payload["fixtures"] if isinstance(payload, dict) else payload
    fixtures: list[FixtureInput] = []

    for raw in raw_fixtures:
        snapshots = _normalize_snapshots(raw["snapshots"])
        tags = [str(tag).strip() for tag in raw.get("tags", []) if str(tag).strip()]
        notes = [str(note).strip() for note in raw.get("notes", []) if str(note).strip()]
        fixture = FixtureInput(
            fixture_id=str(raw["fixture_id"]),
            sport=str(raw.get("sport", "football")).strip().lower(),
            country=str(raw.get("country", "")).strip(),
            league=str(raw["league"]).strip(),
            home_team=str(raw["home_team"]).strip(),
            away_team=str(raw["away_team"]).strip(),
            kickoff_utc=parse_datetime(raw["kickoff_utc"]),
            public_news_hits=int(raw.get("public_news_hits", 0) or 0),
            tags=tags,
            notes=notes,
            snapshots=snapshots,
        )
        if not any(getattr(snapshot, field) is not None for snapshot in snapshots for field in MARKET_FIELDS):
            raise ValueError(f"Fixture {fixture.fixture_id} has no odds values.")
        fixtures.append(fixture)
    return fixtures

