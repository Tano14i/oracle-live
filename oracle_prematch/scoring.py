from __future__ import annotations

from datetime import datetime, timezone

from oracle_prematch.models import FixtureInput
from oracle_prematch.settings import NICHE_KEYWORDS, REVIEW_THRESHOLD, TOP_LEAGUE_KEYWORDS, WATCH_LIVE_THRESHOLD


MARKET_FIELDS = ("home_odds", "draw_odds", "away_odds", "over25_odds", "under25_odds")
MARKET_LABELS = {
    "home_odds": "1",
    "draw_odds": "X",
    "away_odds": "2",
    "over25_odds": "O2.5",
    "under25_odds": "U2.5",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct_drop(old_value: float | None, new_value: float | None) -> float:
    if not old_value or not new_value or old_value <= 0 or new_value <= 0:
        return 0.0
    return ((old_value - new_value) / old_value) * 100.0


def extract_keywords(fixture: FixtureInput) -> tuple[bool, bool]:
    haystack = " ".join(
        [
            fixture.sport.lower(),
            fixture.country.lower(),
            fixture.league.lower(),
            " ".join(tag.lower() for tag in fixture.tags),
        ]
    )
    is_niche = any(keyword in haystack for keyword in NICHE_KEYWORDS)
    is_top = any(keyword in haystack for keyword in TOP_LEAGUE_KEYWORDS)
    return is_niche, is_top


def compute_market_movement(fixture: FixtureInput) -> tuple[str, float, float, dict[str, float]]:
    first = fixture.snapshots[0]
    last = fixture.snapshots[-1]
    overall_drops: dict[str, float] = {}
    biggest_step_drop = 0.0

    for field in MARKET_FIELDS:
        overall_drops[field] = pct_drop(getattr(first, field), getattr(last, field))
        for previous, current in zip(fixture.snapshots, fixture.snapshots[1:]):
            biggest_step_drop = max(biggest_step_drop, pct_drop(getattr(previous, field), getattr(current, field)))

    leading_market, largest_drop_pct = max(overall_drops.items(), key=lambda item: item[1])
    return leading_market, largest_drop_pct, biggest_step_drop, overall_drops


def compute_direction_consistency(fixture: FixtureInput, leading_market: str) -> float:
    deltas: list[float] = []
    for previous, current in zip(fixture.snapshots, fixture.snapshots[1:]):
        previous_value = getattr(previous, leading_market)
        current_value = getattr(current, leading_market)
        if previous_value is None or current_value is None:
            continue
        deltas.append(previous_value - current_value)
    meaningful = [delta for delta in deltas if abs(delta) > 1e-9]
    if not meaningful:
        return 0.0
    downward_moves = sum(1 for delta in meaningful if delta > 0)
    return downward_moves / len(meaningful)


def compute_bookmaker_average(fixture: FixtureInput) -> float:
    values = [snapshot.bookmaker_count for snapshot in fixture.snapshots if snapshot.bookmaker_count]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def compute_isolated_move_bonus(overall_drops: dict[str, float], leading_market: str) -> float:
    leading_value = overall_drops.get(leading_market, 0.0)
    if leading_value < 8.0:
        return 0.0
    other_moves = [value for key, value in overall_drops.items() if key != leading_market and value > 0]
    if not other_moves:
        return 8.0
    if max(other_moves) <= leading_value * 0.35:
        return 6.0
    if max(other_moves) <= leading_value * 0.55:
        return 3.0
    return 0.0


def decide_explainability(public_news_hits: int, is_top_league: bool, bookmaker_count_avg: float, largest_drop_pct: float) -> str:
    if public_news_hits > 0:
        return "PUBLIC_NEWS"
    if is_top_league and bookmaker_count_avg >= 10 and largest_drop_pct < 14:
        return "LIKELY_PRICED"
    return "NO_PUBLIC_NEWS"


def decide_status(score: int, explainability: str, largest_drop_pct: float) -> str:
    if score >= WATCH_LIVE_THRESHOLD and explainability == "NO_PUBLIC_NEWS" and largest_drop_pct >= 10:
        return "WATCH LIVE"
    if score >= REVIEW_THRESHOLD and largest_drop_pct >= 8:
        return "MANUAL REVIEW"
    if score >= 40:
        return "WATCHLIST"
    return "IGNORE"


def build_flags(
    fixture: FixtureInput,
    is_niche: bool,
    is_top_league: bool,
    largest_drop_pct: float,
    biggest_step_drop: float,
    bookmaker_count_avg: float,
    explainability: str,
) -> list[str]:
    flags: list[str] = []
    if largest_drop_pct >= 10:
        flags.append(f"odds drop {largest_drop_pct:.1f}%")
    if biggest_step_drop >= 6:
        flags.append(f"fast move {biggest_step_drop:.1f}%")
    if bookmaker_count_avg and bookmaker_count_avg <= 6:
        flags.append("thin market")
    if is_niche:
        flags.append("niche competition")
    if is_top_league:
        flags.append("top-league penalty")
    if explainability == "NO_PUBLIC_NEWS":
        flags.append("no public news")
    elif explainability == "PUBLIC_NEWS":
        flags.append("public news found")
    flags.extend(fixture.notes[:2])
    return flags


def score_fixture(fixture: FixtureInput, now_utc: datetime | None = None) -> dict:
    now = now_utc or datetime.now(timezone.utc)
    leading_market, largest_drop_pct, biggest_step_drop, overall_drops = compute_market_movement(fixture)
    direction_consistency = compute_direction_consistency(fixture, leading_market)
    bookmaker_count_avg = compute_bookmaker_average(fixture)
    is_niche, is_top_league = extract_keywords(fixture)

    raw_hours_to_kickoff = (fixture.kickoff_utc - now).total_seconds() / 3600.0
    hours_to_kickoff = round(raw_hours_to_kickoff, 2)
    movement_score = clamp(largest_drop_pct * 1.2, 0, 28)
    step_score = clamp(biggest_step_drop * 0.9, 0, 12)
    timing_score = 0.0
    if 0.0 < raw_hours_to_kickoff <= 6.0:
        timing_score = clamp((6.0 - raw_hours_to_kickoff) * 1.6, 0, 10)
    consistency_score = 7.0 * direction_consistency if largest_drop_pct >= 6 else 0.0
    isolated_score = compute_isolated_move_bonus(overall_drops, leading_market)
    isolated_score = min(isolated_score, 5.0)
    niche_score = 12.0 if is_niche and not is_top_league else 4.0 if is_niche else 0.0
    liquidity_score = 0.0
    if bookmaker_count_avg:
        if bookmaker_count_avg <= 4:
            liquidity_score = 8.0
        elif bookmaker_count_avg <= 7:
            liquidity_score = 5.0
        elif bookmaker_count_avg <= 10:
            liquidity_score = 2.0

    public_news_penalty = min(24.0, fixture.public_news_hits * 10.0)
    top_league_penalty = 15.0 if is_top_league else 0.0
    weak_signal_penalty = 8.0 if largest_drop_pct < 5.0 else 0.0
    stale_penalty = 20.0 if raw_hours_to_kickoff <= 0.0 else 0.0

    raw_score = (
        movement_score
        + step_score
        + timing_score
        + consistency_score
        + isolated_score
        + niche_score
        + liquidity_score
        - public_news_penalty
        - top_league_penalty
        - weak_signal_penalty
        - stale_penalty
    )
    risk_score = int(round(clamp(raw_score, 0, 100)))
    explainability = decide_explainability(fixture.public_news_hits, is_top_league, bookmaker_count_avg, largest_drop_pct)
    status = decide_status(risk_score, explainability, largest_drop_pct)
    if raw_hours_to_kickoff <= 0.0:
        explainability = "KICKOFF_PASSED"
        status = "IGNORE"
    flags = build_flags(
        fixture=fixture,
        is_niche=is_niche,
        is_top_league=is_top_league,
        largest_drop_pct=largest_drop_pct,
        biggest_step_drop=biggest_step_drop,
        bookmaker_count_avg=bookmaker_count_avg,
        explainability=explainability,
    )

    metrics = {
        "largest_drop_pct": round(largest_drop_pct, 2),
        "biggest_step_drop_pct": round(biggest_step_drop, 2),
        "direction_consistency": round(direction_consistency, 2),
        "hours_to_kickoff": round(hours_to_kickoff, 2),
        "bookmaker_count_avg": bookmaker_count_avg,
        "movement_score": round(movement_score, 2),
        "step_score": round(step_score, 2),
        "timing_score": round(timing_score, 2),
        "consistency_score": round(consistency_score, 2),
        "isolated_score": round(isolated_score, 2),
        "niche_score": round(niche_score, 2),
        "liquidity_score": round(liquidity_score, 2),
        "public_news_penalty": round(public_news_penalty, 2),
        "top_league_penalty": round(top_league_penalty, 2),
        "weak_signal_penalty": round(weak_signal_penalty, 2),
        "stale_penalty": round(stale_penalty, 2),
        "market_drops": {MARKET_LABELS[key]: round(value, 2) for key, value in overall_drops.items() if value},
        "leading_market": MARKET_LABELS.get(leading_market, leading_market),
        "is_niche": is_niche,
        "is_top_league": is_top_league,
    }
    return {
        "risk_score": risk_score,
        "status": status,
        "explainability": explainability,
        "leading_market": MARKET_LABELS.get(leading_market, leading_market),
        "largest_drop_pct": round(largest_drop_pct, 2),
        "bookmaker_count_avg": bookmaker_count_avg,
        "flags": flags,
        "metrics": metrics,
    }
