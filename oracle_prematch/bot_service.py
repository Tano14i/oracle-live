"""Adattatore fra il bot Telegram e il radar prematch OVER 0.5 HT.

Sostituisce lo scanner di anomalie sulle quote che stava qui prima. Quello
cercava cali sospetti prima del fischio d'inizio, ma non registrava alcun esito:
il suo punteggio non e' mai stato verificato contro cosa fosse poi successo, si
era fermato il 30 marzo 2026 e aveva accumulato 30 GB di risposte API grezze che
nessuno leggeva.

Il radar attuale usa la stessa logica del market OVER 0.5 HT del bot live —
ritmo di primo tempo sulle ultime 50 partite note — applicata alle partite in
programma, e serve a sapere in anticipo quali calci d'inizio presidiare.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import prematch_radar


@dataclass(slots=True)
class RadarCandidate:
    fixture_id: str
    country: str
    league: str
    home_team: str
    away_team: str
    kickoff_utc: str
    tier: str
    pair_ht_pace: float
    worst_ht_pace: float
    pair_ft_pace: float
    known_matches: str
    prematch_odd: float | None


@dataclass(slots=True)
class RadarSummary:
    total_fixtures: int
    flagged_total: int
    approved_total: int
    caution_total: int
    outcomes: list[RadarCandidate] = field(default_factory=list)


@dataclass(slots=True)
class PrematchBotResult:
    summary: RadarSummary
    fixtures_seen: int
    date_value: str
    skipped_unknown_team: int
    skipped_no_ht_history: int


@dataclass(slots=True)
class PrematchCollectionResult:
    """Mantenuta per compatibilita': il radar non accumula snapshot."""
    odds_rows: int = 0
    snapshots_saved: int = 0
    fixtures_seen: int = 0
    source_name: str = "prematch-radar"
    date_value: str = ""
    fixture_ids: list[str] = field(default_factory=list)


def collect_prematch_snapshots(date_value: str | None = None, page_limit: int | None = None,
                               source_name: str = "prematch-radar") -> PrematchCollectionResult:
    """No-op: il radar calcola al momento e non ha bisogno di uno storico quote."""
    return PrematchCollectionResult(date_value=date_value or datetime.now().date().isoformat(),
                                    source_name=source_name)


def run_prematch_bot_scan(date_value: str | None = None, top: int = 15,
                          lookback_hours: int = 0, page_limit: int | None = None,
                          source_name: str = "prematch-radar",
                          with_odds: bool = False) -> PrematchBotResult:
    scan_date = date_value or datetime.now().date().isoformat()
    result = prematch_radar.scan(date_value=scan_date, min_tier="CAUTION",
                                 with_odds=with_odds, known_leagues=True)
    candidates = [
        RadarCandidate(
            fixture_id=str(c["fixture_id"]),
            country=c["country"],
            league=c["league"],
            home_team=c["home_team"],
            away_team=c["away_team"],
            kickoff_utc=c["kickoff_utc"],
            tier=c["tier"],
            pair_ht_pace=c["pair_ht_pace"],
            worst_ht_pace=c["worst_ht_pace"],
            pair_ft_pace=c["pair_ft_pace"],
            known_matches=c["known_matches"],
            prematch_odd=c["prematch_odd"],
        )
        for c in result["candidates"]
    ]
    summary = RadarSummary(
        total_fixtures=result["fixtures_total"],
        flagged_total=len(candidates),
        approved_total=sum(1 for c in candidates if c.tier == "APPROVED"),
        caution_total=sum(1 for c in candidates if c.tier == "CAUTION"),
        outcomes=candidates[:top],
    )
    return PrematchBotResult(
        summary=summary,
        fixtures_seen=result["fixtures_total"],
        date_value=scan_date,
        skipped_unknown_team=result["skipped_unknown_team"],
        skipped_no_ht_history=result["skipped_no_ht_history"],
    )
