from __future__ import annotations

from oracle_prematch.models import ScanOutcome


def build_alert_text(outcome: ScanOutcome) -> str:
    news_line = "No public news detected" if outcome.public_news_hits == 0 else f"Public news hits: {outcome.public_news_hits}"
    flags_line = ", ".join(outcome.flags[:4]) if outcome.flags else "none"
    return (
        "PRE-MATCH ALERT\n\n"
        f"Match: {outcome.home_team} vs {outcome.away_team}\n"
        f"League: {outcome.country} | {outcome.league}\n"
        f"Kickoff UTC: {outcome.kickoff_utc.strftime('%Y-%m-%d %H:%M')}\n"
        f"Leading market: {outcome.leading_market}\n"
        f"Odds drop: -{outcome.largest_drop_pct:.1f}%\n"
        f"{news_line}\n"
        f"Explainability: {outcome.explainability}\n"
        f"Risk score: {outcome.risk_score}/100\n"
        f"Status: {outcome.status}\n"
        f"Flags: {flags_line}"
    )
