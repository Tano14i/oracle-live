from oracle_live.api_client import fetch_fixture_stats
from oracle_live.constants import MARKET_OVER05_HT, MARKET_OVER15_HT
from oracle_live.state import (
    ensure_daily_analytics,
    get_rolling_bucket_stats,
    get_settled_bucket_stats,
    stats,
)

def check_negative_window(stats_bucket: dict, min_total: int, min_wr: float) -> bool:
    total = int(stats_bucket.get("WIN", 0)) + int(stats_bucket.get("LOSS", 0))
    if total < min_total:
        return False
    return (int(stats_bucket.get("WIN", 0)) / max(1, total)) < min_wr

def should_skip_by_live_performance(market: str, league_name: str, minute_bucket: str):
    ensure_daily_analytics()
    analytics = stats["daily_analytics"]

    market_stats = get_settled_bucket_stats(analytics.get("settled_by_market"), market)
    market_total = market_stats["WIN"] + market_stats["LOSS"]
    if market_total >= 5 and market_stats["WIN"] / max(1, market_total) < 0.40:
        return True, f"market {market} under 40% today"

    league_stats = get_settled_bucket_stats(analytics.get("settled_by_league"), league_name)
    league_total = league_stats["WIN"] + league_stats["LOSS"]
    if league_total >= 4 and league_stats["WIN"] / max(1, league_total) < 0.35:
        return True, f"league {league_name} cold today"

    minute_stats = get_settled_bucket_stats(analytics.get("settled_by_minute_bucket"), minute_bucket)
    minute_total = minute_stats["WIN"] + minute_stats["LOSS"]
    if minute_total >= 4 and minute_stats["WIN"] / max(1, minute_total) < 0.35:
        return True, f"minute zone {minute_bucket} cold today"

    market_last_20 = get_rolling_bucket_stats("market", market, 20)
    if check_negative_window(market_last_20, 8, 0.40):
        return True, f"market {market} weak on last 20"

    market_last_50 = get_rolling_bucket_stats("market", market, 50)
    if check_negative_window(market_last_50, 15, 0.42):
        return True, f"market {market} weak on last 50"

    league_last_20 = get_rolling_bucket_stats("league_name", league_name, 20)
    if check_negative_window(league_last_20, 6, 0.33):
        return True, f"league {league_name} weak on last 20"

    minute_last_20 = get_rolling_bucket_stats("minute_bucket", minute_bucket, 20)
    if check_negative_window(minute_last_20, 6, 0.33):
        return True, f"minute zone {minute_bucket} weak on last 20"

    return False, ""


def should_skip_next_goal_by_context(minute_value: int, total_goals: int, score: str) -> tuple:
    """
    Filtro cecchino per NEXT GOAL LIVE basato su dati storici reali.
    WR breakeven a quota 1.75 = 57.1%

    Score killer da bloccare (WR < 40%):
      - 1-2 (22%), 3-2 (5%), 2-2 (19%), 2-5 (18%)
    Score favorevoli da lasciare passare (WR > 55%):
      - 2-3 (83%), 1-4 (60%), 2-1 (55%), 4-0 (52%)

    Finestra temporale:
      - Minuto 1-11: WR 53-60% -> ok
      - Minuto 12-19: WR 46-53% -> solo score favorevoli
      - Minuto 20-44: WR 38-49% -> solo score molto favorevoli
      - Minuto 45-69: WR 32-42% -> blocca quasi tutto
      - Minuto 70+: WR < 33% -> blocca sempre

    Total goals:
      - 4+ gol in campo: WR 30% -> blocca sempre
    """
    # Blocca sempre dopo il minuto 69 (WR crolla sotto 33%)
    if minute_value >= 70:
        return True, f"next_goal minute {minute_value} WR<33% storico"

    # Blocca sempre con 4+ gol in campo (WR 30%)
    if total_goals >= 4:
        return True, f"next_goal total_goals={total_goals} WR<31% storico"

    # Analisi dello score
    parts = str(score or "0-0").split("-")
    try:
        home_goals = int(parts[0])
        away_goals = int(parts[1])
    except Exception:
        home_goals = 0
        away_goals = 0

    diff = abs(home_goals - away_goals)

    # Score killer assoluti - blocca sempre indipendentemente dal minuto
    # 1-2 (22%), 2-1 reversed -> no, 3-2 (5%), 2-2 (19%), 2-5 (18%)
    killer_scores = {(1, 2), (2, 1) if False else None, (3, 2), (2, 3) if False else None, (2, 2), (2, 5), (5, 2)}
    # Correggo: blocco asimmetrico basato su chi perde
    # Score dove la squadra che insegue ha bisogno di 2+ gol = killer
    if (home_goals == 1 and away_goals == 2) or (home_goals == 2 and away_goals == 1 and False):
        # 1-2: WR 22% -> blocca sempre
        return True, f"next_goal killer score {score} WR=22%"
    if (home_goals == 3 and away_goals == 2) or (home_goals == 2 and away_goals == 3 and False):
        # 3-2: WR 5% -> blocca sempre
        return True, f"next_goal killer score {score} WR=5%"
    if home_goals == away_goals == 2:
        # 2-2: WR 19% -> blocca sempre
        return True, f"next_goal killer score {score} WR=19%"

    # Score favorevoli - lascia passare anche in finestre difficili
    # 2-3 (83%), 1-4 (60%), 2-1 (55%), 4-0 (52%), 0-2 (48%)
    favorable = (
        (home_goals == 2 and away_goals == 3) or
        (home_goals == 3 and away_goals == 2 and False) or
        (home_goals == 1 and away_goals == 4) or
        (home_goals == 4 and away_goals == 1) or
        (home_goals == 2 and away_goals == 1) or
        (home_goals == 1 and away_goals == 2 and False) or
        (home_goals == 4 and away_goals == 0) or
        (home_goals == 0 and away_goals == 4)
    )

    # Finestre temporali con logica per score
    if 1 <= minute_value <= 11:
        # WR 53-60% -> ok per tutti gli score non killer
        return False, ""

    if 12 <= minute_value <= 19:
        # WR 46-53% -> solo score favorevoli o parità 0-0/1-1
        if favorable:
            return False, ""
        if home_goals == away_goals <= 1:
            return False, ""
        return True, f"next_goal minute {minute_value} score {score} WR<50% non favorevole"

    if 20 <= minute_value <= 44:
        # WR 38-49% -> solo score molto favorevoli
        if favorable:
            return False, ""
        return True, f"next_goal minute {minute_value} score {score} WR<49% zona grigia"

    if 45 <= minute_value <= 69:
        # WR 32-42% -> solo score eccezionalmente favorevoli (diff >= 2 con squadra sotto che insegue)
        if (home_goals == 2 and away_goals == 3) or (home_goals == 4 and away_goals == 1) or (home_goals == 1 and away_goals == 4):
            return False, ""
        return True, f"next_goal minute {minute_value} secondo tempo non favorevole WR<42%"

    return False, ""


def should_skip_by_live_stats(fixture_id: int, market: str, minute_value: int, total_goals: int, headers: dict, stats_payload=None):
    if stats_payload is None:
        stats_payload = fetch_fixture_stats(fixture_id, headers)
    if not isinstance(stats_payload, dict):
        return False, ""

    red_cards = stats_payload.get("red_cards", 0.0)
    shots_on_goal = stats_payload.get("shots_on_goal", 0.0)
    total_shots = stats_payload.get("total_shots", 0.0)
    corners = stats_payload.get("corners", 0.0)

    if red_cards > 0:
        return True, f"red card detected ({int(red_cards)})"

    if market == MARKET_OVER05_HT:
        shots_insidebox = float(stats_payload.get("shots_insidebox", 0.0) or 0.0)
        goalkeeper_saves = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0)
        if minute_value >= 10 and shots_insidebox < 2:
            return True, "shots insidebox < 2 after min 10 — partita bloccata"
        if minute_value >= 22 and shots_on_goal < 1:
            return True, "no shots on target pressure"
        if minute_value >= 24 and total_shots < 6:
            return True, "low total shots pressure"
        if minute_value >= 28 and total_shots < 8 and corners < 2:
            return True, "weak attacking pressure"

    if market == MARKET_OVER15_HT:
        if total_goals != 1:
            return False, ""
        if shots_on_goal < 2:
            return True, "insufficient shots on target for O1.5 HT"
        if total_shots < 8:
            return True, "insufficient total shots for O1.5 HT"
        if minute_value >= 26 and corners < 3:
            return True, "corners pressure too low for O1.5 HT"

    return False, ""
