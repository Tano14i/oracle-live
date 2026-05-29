from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class OddsSnapshot:
    captured_at_utc: datetime
    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None
    over25_odds: float | None = None
    under25_odds: float | None = None
    bookmaker_count: int | None = None


@dataclass(slots=True)
class FixtureInput:
    fixture_id: str
    sport: str
    country: str
    league: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    public_news_hits: int = 0
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    snapshots: list[OddsSnapshot] = field(default_factory=list)


@dataclass(slots=True)
class ScanOutcome:
    fixture_id: str
    sport: str
    country: str
    league: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    risk_score: int
    status: str
    explainability: str
    leading_market: str
    largest_drop_pct: float
    bookmaker_count_avg: float
    public_news_hits: int
    flags: list[str]
    metrics: dict[str, Any]
    alert_text: str
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kickoff_utc"] = self.kickoff_utc.isoformat()
        return payload
