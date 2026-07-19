import re
import time

import requests

from oracle_live.constants import LIVE_ODDS_BET_IDS
from oracle_live.state import fixture_stats_cache, log_event

def fetch_fixture_status(fixture_id: int, headers: dict):
    try:
        response = requests.get("https://v3.football.api-sports.io/fixtures", headers=headers, params={"id": fixture_id}, timeout=20)
        if response.status_code != 200:
            return None
        items = response.json().get("response", [])
        if not items:
            return None
        match = items[0]
        goals_home = match["goals"].get("home", 0) or 0
        goals_away = match["goals"].get("away", 0) or 0
        return {
            "score": f"{goals_home}-{goals_away}",
            "total_goals": goals_home + goals_away,
            "minute_value": match["fixture"]["status"].get("elapsed", 0) or 0,
            "status_short": match["fixture"]["status"].get("short", ""),
        }
    except Exception as exc:
        print(f"Fetch fixture status failed for {fixture_id}: {exc}")
        return None


def parse_stat_value(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    try:
        return float(text)
    except Exception:
        return 0.0


def normalize_stat_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def prune_fixture_stats_cache(max_items: int = 400, max_age_seconds: int = 900) -> None:
    now_ts = time.time()
    stale_keys = []
    for cache_key, payload in list(fixture_stats_cache.items()):
        if not isinstance(payload, dict) or now_ts - float(payload.get("ts", 0.0)) > max_age_seconds:
            stale_keys.append(cache_key)
    for cache_key in stale_keys:
        fixture_stats_cache.pop(cache_key, None)

    if len(fixture_stats_cache) <= max_items:
        return

    ordered = sorted(
        fixture_stats_cache.items(),
        key=lambda item: float((item[1] or {}).get("ts", 0.0)),
        reverse=True,
    )
    fixture_stats_cache.clear()
    for cache_key, payload in ordered[:max_items]:
        fixture_stats_cache[cache_key] = payload


def fetch_fixture_stats(fixture_id: int, headers: dict):
    prune_fixture_stats_cache()
    cache_key = str(fixture_id)
    now_ts = time.time()
    cached = fixture_stats_cache.get(cache_key)
    if isinstance(cached, dict) and now_ts - float(cached.get("ts", 0.0)) < 90:
        return cached.get("data")

    try:
        response = requests.get(
            "https://v3.football.api-sports.io/fixtures/statistics",
            headers=headers,
            params={"fixture": fixture_id},
            timeout=20,
        )
        if response.status_code != 200:
            return None
        items = response.json().get("response", [])
        if not items:
            return None

        totals = {
            "shots_on_goal": 0.0,
            "total_shots": 0.0,
            "corners": 0.0,
            "red_cards": 0.0,
            "red_cards_home": 0.0,
            "red_cards_away": 0.0,
            "dangerous_attacks": 0.0,
            "possession_diff": 0.0,
            "xg_home": 0.0,
            "xg_away": 0.0,
            "shots_insidebox": 0.0,
            "goalkeeper_saves": 0.0,
        }
        for team_index, team_stats in enumerate(items):
            team_possession = 0.0
            for stat in team_stats.get("statistics", []):
                stat_key = normalize_stat_key(stat.get("type", ""))
                stat_value = parse_stat_value(stat.get("value"))
                if stat_key == "shots on goal":
                    totals["shots_on_goal"] += stat_value
                elif stat_key == "total shots":
                    totals["total_shots"] += stat_value
                elif stat_key == "corner kicks":
                    totals["corners"] += stat_value
                elif stat_key == "red cards":
                    totals["red_cards"] += stat_value
                    if team_index == 0:
                        totals["red_cards_home"] += stat_value
                    else:
                        totals["red_cards_away"] += stat_value
                elif stat_key == "dangerous attacks":
                    totals["dangerous_attacks"] += stat_value
                elif stat_key == "expected goals":
                    if team_index == 0:
                        totals["xg_home"] = stat_value
                    else:
                        totals["xg_away"] = stat_value
                elif stat_key == "shots insidebox":
                    totals["shots_insidebox"] += stat_value
                elif stat_key == "goalkeeper saves":
                    totals["goalkeeper_saves"] += stat_value
                elif stat_key == "ball possession":
                    team_possession = stat_value
            if team_index == 0:
                totals["possession_diff"] += team_possession
            else:
                totals["possession_diff"] -= team_possession
        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": totals}
        prune_fixture_stats_cache()
        return totals
    except Exception as exc:
        print(f"Fetch fixture stats failed for {fixture_id}: {exc}")
        return None

def fetch_live_market_odds(fixture_id: int, market: str, headers: dict):
    """Quota live media per il market indicato, None se non mappato/disponibile."""
    bet_id = LIVE_ODDS_BET_IDS.get(market)
    if not bet_id:
        return None
    return fetch_live_odds_by_bet(fixture_id, bet_id, headers)


def fetch_next_goal_live_odds(fixture_id: int, headers: dict):
    return fetch_live_odds_by_bet(fixture_id, 5, headers)


def fetch_live_odds_by_bet(fixture_id: int, bet_id: int, headers: dict):
    cache_key = f"odds_{bet_id}_" + str(fixture_id)
    now_ts = time.time()
    cached = fixture_stats_cache.get(cache_key)
    if isinstance(cached, dict) and now_ts - float(cached.get("ts", 0.0)) < 60:
        return cached.get("data")
    try:
        response = requests.get(
            "https://v3.football.api-sports.io/odds/live",
            headers=headers, params={"fixture": fixture_id, "bet": bet_id}, timeout=10,
        )
        if response.status_code != 200:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None
        items = response.json().get("response", [])
        if not items:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None
        odds_values = []
        for item in items:
            for bm in item.get("bookmakers", []):
                for bet in bm.get("bets", []):
                    for v in bet.get("values", []):
                        try:
                            ov = float(v.get("odd", 0))
                            if ov > 1.0:
                                odds_values.append(ov)
                        except Exception:
                            pass
        if not odds_values:
            fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
            return None
        avg_odd = round(sum(odds_values) / len(odds_values), 2)
        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": avg_odd}
        return avg_odd
    except Exception as exc:
        log_event("LIVE_ODDS_ERROR", "fid=" + str(fixture_id) + " err=" + str(exc))
        fixture_stats_cache[cache_key] = {"ts": now_ts, "data": None}
        return None
