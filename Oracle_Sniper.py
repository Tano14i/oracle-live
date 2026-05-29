import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import joblib
import pandas as pd
import requests

import oracle_live as core


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNIPER_STATE_PATH = os.path.join(BASE_DIR, "oracle_sniper_state.json")
SNIPER_LOCK_PATH = os.path.join(BASE_DIR, "oracle_sniper.lock")
SNIPER_LOG_PATH = os.path.join(BASE_DIR, "oracle_sniper.log")
SNIPER_JOURNAL_PATH = os.path.join(BASE_DIR, "oracle_sniper_journal.csv")
SNIPER_SIGNAL_LIMIT_PER_DAY = 3
SNIPER_MAX_CONSECUTIVE_LOSSES = 3
SNIPER_DAILY_STOP_LOSS_UNITS = -3.0
SNIPER_MIN_SCORE = 0.58
SNIPER_MINUTES_MIN = 4
SNIPER_MINUTES_MAX = 44
SNIPER_ALLOWED_MARKETS = {
    core.MARKET_OVER05_HT,
    core.MARKET_OVER15_HT,
    core.MARKET_NEXT_GOAL,
}
SNIPER_ALLOWED_LEAGUES = {
    "League One",
    "Segunda Division",
    "Segunda División",
    "Serie B",
    "La Liga",
    "Primeira Liga",
    "Ekstraklasa",
    "Liga Profesional Argentina",
    "2. Bundesliga",
    "Premier Division",
}
SNIPER_BLOCKED_LEAGUES = {
    "Serie A",
    "Eerste Divisie",
    "National Division",
    "Super League 1",
    "Liga II",
    "Bundesliga",
    "Championship",
    "Liga MX",
}
SNIPER_BLOCKED_COUNTRIES = {"Brazil", "Greece", "Romania"}


@dataclass
class SniperState:
    date_utc: str
    daily_signals: int = 0
    daily_units: float = 0.0
    consecutive_losses: int = 0
    open_positions: dict | None = None
    sent_keys: list | None = None

    def __post_init__(self):
        if self.open_positions is None:
            self.open_positions = {}
        if self.sent_keys is None:
            self.sent_keys = []


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def current_date_key() -> str:
    return now_utc().date().isoformat()


def log_sniper(message: str) -> None:
    timestamp = now_utc().strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"{timestamp} | {message}"
    print(line)
    try:
        with open(SNIPER_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def load_state() -> SniperState:
    if os.path.exists(SNIPER_STATE_PATH):
        try:
            with open(SNIPER_STATE_PATH, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            state = SniperState(**raw)
        except Exception:
            state = SniperState(date_utc=current_date_key())
    else:
        state = SniperState(date_utc=current_date_key())
    if state.date_utc != current_date_key():
        state = SniperState(date_utc=current_date_key())
    return state


def save_state(state: SniperState) -> None:
    with open(SNIPER_STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(asdict(state), handle, indent=2)


def acquire_lock() -> bool:
    if os.path.exists(SNIPER_LOCK_PATH):
        return False
    try:
        with open(SNIPER_LOCK_PATH, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except Exception:
        return False


def release_lock() -> None:
    try:
        if os.path.exists(SNIPER_LOCK_PATH):
            os.remove(SNIPER_LOCK_PATH)
    except Exception:
        pass


def ensure_core_loaded() -> None:
    if core.oracle_brain is None:
        try:
            core.oracle_brain = joblib.load(core.MODEL_PATH)
            log_sniper("Main oracle model loaded.")
        except Exception as exc:
            raise RuntimeError(f"Unable to load production model: {exc}") from exc
    if core.titan_pressure_brain is None and os.path.exists(core.TITAN_PRESSURE_MODEL_PATH):
        try:
            core.titan_pressure_brain = joblib.load(core.TITAN_PRESSURE_MODEL_PATH)
            log_sniper("Titan pressure model loaded.")
        except Exception:
            log_sniper("Titan pressure model unavailable; continuing without it.")
    if core.df_matches is None:
        core.df_matches = pd.read_csv(core.CSV_PATH, low_memory=False)
        core.nomi_unici_db = pd.concat([core.df_matches["HomeTeam"], core.df_matches["AwayTeam"]]).dropna().unique().tolist()
        core.team_match_cache = {}
        core.normalized_team_lookup = {}
        core.team_not_found_counts = {}
        core.build_team_lookup()
        log_sniper(f"Team database loaded: {len(core.nomi_unici_db)} teams.")


def safe_send(text: str) -> None:
    try:
        core.bot.send_message(core.CHAT_ID, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        log_sniper(f"Telegram send failed: {exc}")


def append_journal(row: dict) -> None:
    frame = pd.DataFrame([row])
    exists = os.path.exists(SNIPER_JOURNAL_PATH)
    frame.to_csv(SNIPER_JOURNAL_PATH, mode="a", index=False, header=not exists, encoding="utf-8")


def is_sniper_league_allowed(country: str, league_name: str) -> bool:
    if core.get_league_filter_reason(country, league_name) is not None:
        return False
    if league_name in SNIPER_BLOCKED_LEAGUES or country in SNIPER_BLOCKED_COUNTRIES:
        return False
    return league_name in SNIPER_ALLOWED_LEAGUES


def get_market_payout_factor(market: str, minute_value: int, total_goals: int) -> float:
    if market == core.MARKET_NEXT_GOAL:
        if minute_value <= 5:
            return 0.28
        if minute_value <= 10:
            return 0.48
        if minute_value <= 20:
            return 0.82
        if minute_value <= 35:
            return 1.00
        return 0.93
    if market == core.MARKET_OVER05_HT:
        if total_goals > 0:
            return 0.25
        if minute_value <= 8:
            return 0.92
        if minute_value <= 20:
            return 1.00
        if minute_value <= 32:
            return 0.88
        return 0.58
    if market == core.MARKET_OVER15_HT:
        if total_goals == 0:
            return 0.18
        if total_goals == 1 and 12 <= minute_value <= 34:
            return 1.00
        if total_goals == 1:
            return 0.78
        return 0.35
    return 0.0


def get_context_strength(
    market: str,
    minute_value: int,
    total_goals: int,
    combined_metrics: dict,
    titan_pressure_prob,
    titan_soft: dict,
    stats_payload: dict,
) -> float:
    score = 0.0
    score += min(0.24, max(0.0, (combined_metrics["avg_total_goals"] - 2.2) * 0.08))
    score += min(0.20, max(0.0, (combined_metrics["avg_ht_goals"] - 0.95) * 0.22))
    if market == core.MARKET_NEXT_GOAL and 20 <= minute_value <= 39:
        score += 0.10
    if market == core.MARKET_OVER05_HT and minute_value <= 24 and total_goals == 0:
        score += 0.08
    if market == core.MARKET_OVER15_HT and total_goals == 1 and 15 <= minute_value <= 34:
        score += 0.10
    if titan_pressure_prob is not None:
        score += min(0.18, max(0.0, titan_pressure_prob - 0.56))
    if titan_soft.get("score", 0) >= 2:
        score += 0.05
    if core.has_live_pressure_data(stats_payload):
        score += 0.05
    return max(0.70, min(1.35, 0.85 + score))


def get_tier_multiplier(tier: str) -> float:
    if tier == core.TIER_APPROVED:
        return 1.12
    if tier == core.TIER_CAUTION:
        return 1.00
    if tier == core.TIER_LEARNING:
        return 0.88
    return 0.70


def get_sniper_probability_floor(market: str, tier: str, minute_value: int) -> float:
    if market == core.MARKET_NEXT_GOAL:
        if minute_value <= 10:
            return 0.78
        if minute_value <= 20:
            return 0.72
        return 0.68 if tier == core.TIER_APPROVED else 0.72
    if market == core.MARKET_OVER05_HT:
        return 0.74 if tier == core.TIER_APPROVED else 0.78
    if market == core.MARKET_OVER15_HT:
        return 0.79 if tier == core.TIER_APPROVED else 0.83
    return 0.80


def build_sniper_message(candidate: dict) -> str:
    stake_label = candidate["stake_label"]
    return (
        "<b>ORACLE SNIPER</b>\n"
        f"{core.SEPARATOR}\n"
        f"<b>LEAGUE:</b> {core.escape_html(candidate['league_name'])}\n"
        f"<b>COUNTRY:</b> {core.escape_html(candidate['country'])}\n"
        f"<b>MATCH:</b> {core.escape_html(candidate['match_up'])}\n"
        f"<b>MARKET:</b> {core.escape_html(candidate['market'])}\n"
        f"<b>TIER:</b> {core.escape_html(candidate['tier'])}\n"
        f"<b>MINUTE:</b> {candidate['minute_value']} | <b>SCORE:</b> {core.escape_html(candidate['score'])}\n"
        f"<b>MODEL:</b> {candidate['prob']:.2f} | <b>SNIPER SCORE:</b> {candidate['sniper_score']:.2f}\n"
        f"<b>DNA:</b> {candidate['dna']:.2f} | <b>STAKE CLASS:</b> {stake_label}\n"
        f"<b>REASON:</b> {core.escape_html(candidate['reason'])}\n"
        f"<b>ANGLE:</b> {core.escape_html(candidate['angle'])}\n"
        f"{core.SEPARATOR}\n"
        "<i>Experimental speculative stream. High risk, low volume.</i>"
    )


def get_stake_label(sniper_score: float) -> str:
    if sniper_score >= 0.82:
        return "A+ 8u max"
    if sniper_score >= 0.72:
        return "A 5u max"
    return "B 3u max"


def evaluate_sniper_candidate(match: dict) -> dict | None:
    fixture_id = match["fixture"].get("id")
    if fixture_id is None:
        return None
    home_live = match["teams"]["home"]["name"]
    away_live = match["teams"]["away"]["name"]
    country = match["league"].get("country", "Unknown")
    league_name = match["league"].get("name", "Unknown")
    if not is_sniper_league_allowed(country, league_name):
        return None

    goals_home = match["goals"].get("home", 0) or 0
    goals_away = match["goals"].get("away", 0) or 0
    total_goals = goals_home + goals_away
    score = f"{goals_home}-{goals_away}"
    minute_value = match["fixture"]["status"].get("elapsed", 0) or 0
    if minute_value < SNIPER_MINUTES_MIN or minute_value > SNIPER_MINUTES_MAX:
        return None

    home_db = core.trova_squadra(home_live, country, league_name)
    away_db = core.trova_squadra(away_live, country, league_name)
    if not home_db or not away_db:
        return None
    home_metrics = core.get_team_metrics(home_db)
    away_metrics = core.get_team_metrics(away_db)
    combined_metrics = core.combine_team_metrics(home_metrics, away_metrics)
    if not combined_metrics or not combined_metrics.get("metrics_ok", True):
        return None

    stats_payload = core.fetch_fixture_stats(fixture_id, {"x-apisports-key": core.API_KEY})
    shots_on_goal = float(stats_payload.get("shots_on_goal", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    total_shots = float(stats_payload.get("total_shots", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    corners = float(stats_payload.get("corners", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    red_cards = float(stats_payload.get("red_cards", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    dna = combined_metrics["avg_total_goals"]

    best_candidate = None
    model_feature_columns = list(getattr(core.oracle_brain, "feature_names_in_", core.TRAINER_FEATURE_COLUMNS))

    for market in core.prioritize_markets(list(SNIPER_ALLOWED_MARKETS), minute_value, total_goals):
        if not core.is_market_window(market, minute_value, total_goals):
            continue

        titan_soft = core.evaluate_titan_soft_layer(stats_payload, market, minute_value, total_goals)
        titan_pressure_score = float(titan_soft.get("score", 0.0) or 0.0)
        feature_values = {
            "DNA": dna,
            "Minute": minute_value,
            "TotalGoalsAtOpen": total_goals,
            "AvgTotalGoals": combined_metrics["avg_total_goals"],
            "AvgHTGoals": combined_metrics["avg_ht_goals"],
            "HomeAvgTotalGoals": combined_metrics["home_avg_total_goals"],
            "AwayAvgTotalGoals": combined_metrics["away_avg_total_goals"],
            "HomeAvgHTGoals": combined_metrics["home_avg_ht_goals"],
            "AwayAvgHTGoals": combined_metrics["away_avg_ht_goals"],
            "ShotsOnGoalAtOpen": shots_on_goal,
            "TotalShotsAtOpen": total_shots,
            "CornersAtOpen": corners,
            "RedCardsAtOpen": red_cards,
            "TitanPressureScore": titan_pressure_score,
        }
        x_input = pd.DataFrame([[feature_values.get(column, 0.0) for column in model_feature_columns]], columns=model_feature_columns)
        prob = float(core.oracle_brain.predict_proba(x_input)[0][1])
        titan_pressure_prob = core.predict_titan_pressure_prob(dna, minute_value, goals_home - goals_away, total_goals, stats_payload)

        assessment = core.evaluate_signal_candidate(market, minute_value, total_goals, prob, combined_metrics)
        if not assessment and market == core.MARKET_NEXT_GOAL:
            assessment = core.evaluate_pending_next_goal_candidate(
                minute_value,
                total_goals,
                prob,
                combined_metrics,
                persistence_count=2,
                titan_pressure_prob=titan_pressure_prob,
                titan_soft=titan_soft,
            )
        if not assessment:
            continue

        tier = assessment["tier"]
        reason = assessment["reason"]
        if tier not in {core.TIER_APPROVED, core.TIER_CAUTION}:
            continue
        if "titan pressure alert" in str(reason).lower():
            continue
        if prob < get_sniper_probability_floor(market, tier, minute_value):
            continue

        performance_skip, _ = core.should_skip_by_live_performance(market, league_name, core.get_minute_bucket(minute_value))
        if performance_skip:
            continue
        live_skip, live_skip_reason = core.should_skip_by_live_stats(
            fixture_id,
            market,
            minute_value,
            total_goals,
            {"x-apisports-key": core.API_KEY},
            stats_payload=stats_payload,
        )
        if live_skip:
            reason = f"{reason} | live caution: {live_skip_reason}"

        context_strength = get_context_strength(market, minute_value, total_goals, combined_metrics, titan_pressure_prob, titan_soft, stats_payload)
        payout_factor = get_market_payout_factor(market, minute_value, total_goals)
        router_factor = max(0.60, min(1.18, core.get_market_router_score(market, minute_value, total_goals)))
        tier_factor = get_tier_multiplier(tier)
        sniper_score = prob * context_strength * payout_factor * router_factor * tier_factor

        if sniper_score < SNIPER_MIN_SCORE:
            continue

        angle = (
            f"context {context_strength:.2f} x payout {payout_factor:.2f} x router {router_factor:.2f} x tier {tier_factor:.2f}"
        )
        candidate = {
            "fixture_id": fixture_id,
            "signal_key": f"sniper::{fixture_id}::{market}",
            "country": country,
            "league_name": league_name,
            "match_up": f"{home_live.upper()} vs {away_live.upper()}",
            "market": market,
            "minute_value": minute_value,
            "score": score,
            "prob": prob,
            "dna": dna,
            "tier": tier,
            "reason": reason,
            "sniper_score": sniper_score,
            "stake_label": get_stake_label(sniper_score),
            "angle": angle,
            "total_goals_at_open": total_goals,
        }
        if best_candidate is None or candidate["sniper_score"] > best_candidate["sniper_score"]:
            best_candidate = candidate

    return best_candidate


def settle_open_positions(state: SniperState, live_matches: list[dict]) -> None:
    if not state.open_positions:
        return
    by_fixture = {item["fixture"].get("id"): item for item in live_matches if item["fixture"].get("id") is not None}
    completed_keys = []
    for signal_key, position in state.open_positions.items():
        fixture_id = position["fixture_id"]
        market = position["market"]
        live_match = by_fixture.get(fixture_id)
        if live_match is None:
            continue
        goals_home = live_match["goals"].get("home", 0) or 0
        goals_away = live_match["goals"].get("away", 0) or 0
        total_goals = goals_home + goals_away
        score = f"{goals_home}-{goals_away}"
        status_short = live_match["fixture"]["status"].get("short", "")
        minute_value = live_match["fixture"]["status"].get("elapsed", 0) or 0
        outcome = None
        if market == core.MARKET_NEXT_GOAL:
            if total_goals > int(position["total_goals_at_open"]):
                outcome = "WIN"
            elif status_short in {"FT", "AET", "PEN"}:
                outcome = "LOSS"
        else:
            if core.is_market_winner(market, total_goals):
                outcome = "WIN"
            elif core.is_first_half_closed(status_short, minute_value):
                outcome = "LOSS"
        if outcome is None:
            continue

        units = 1.0 if outcome == "WIN" else -1.0
        state.daily_units += units
        if outcome == "LOSS":
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0
        completed_keys.append(signal_key)
        append_journal(
            {
                "TimestampUTC": now_utc().isoformat(),
                "Event": "SETTLE",
                "SignalKey": signal_key,
                "FixtureId": fixture_id,
                "Market": market,
                "Outcome": outcome,
                "Units": units,
                "CloseScore": score,
            }
        )
        safe_send(
            "<b>ORACLE SNIPER RESULT</b>\n"
            f"{core.SEPARATOR}\n"
            f"<b>MARKET:</b> {core.escape_html(market)}\n"
            f"<b>RESULT:</b> {outcome}\n"
            f"<b>CLOSE SCORE:</b> {core.escape_html(score)}\n"
            f"<b>DAILY UNITS:</b> {state.daily_units:.1f}\n"
            f"<b>LOSSES STREAK:</b> {state.consecutive_losses}\n"
        )

    for signal_key in completed_keys:
        state.open_positions.pop(signal_key, None)


def kill_switch_active(state: SniperState) -> str | None:
    if state.daily_signals >= SNIPER_SIGNAL_LIMIT_PER_DAY:
        return "daily_cap"
    if state.consecutive_losses >= SNIPER_MAX_CONSECUTIVE_LOSSES:
        return "loss_streak"
    if state.daily_units <= SNIPER_DAILY_STOP_LOSS_UNITS:
        return "daily_stop"
    return None


def scan_once(state: SniperState) -> None:
    response = requests.get(
        "https://v3.football.api-sports.io/fixtures",
        headers={"x-apisports-key": core.API_KEY},
        params={"live": "all"},
        timeout=20,
    )
    if response.status_code != 200:
        log_sniper(f"API error {response.status_code}")
        return
    data = response.json().get("response", [])
    settle_open_positions(state, data)

    stop_reason = kill_switch_active(state)
    if stop_reason:
        log_sniper(f"Kill switch active: {stop_reason}")
        return

    candidates = []
    for match in data:
        candidate = evaluate_sniper_candidate(match)
        if candidate:
            if candidate["signal_key"] in state.sent_keys or candidate["signal_key"] in state.open_positions:
                continue
            candidates.append(candidate)

    if not candidates:
        log_sniper("No sniper candidates in current scan.")
        return

    candidates.sort(key=lambda item: item["sniper_score"], reverse=True)
    best = candidates[0]
    state.sent_keys.append(best["signal_key"])
    state.open_positions[best["signal_key"]] = best
    state.daily_signals += 1
    append_journal(
        {
            "TimestampUTC": now_utc().isoformat(),
            "Event": "OPEN",
            "SignalKey": best["signal_key"],
            "FixtureId": best["fixture_id"],
            "LeagueName": best["league_name"],
            "Country": best["country"],
            "Market": best["market"],
            "Minute": best["minute_value"],
            "StartScore": best["score"],
            "Prob": round(best["prob"], 4),
            "SniperScore": round(best["sniper_score"], 4),
            "Tier": best["tier"],
            "Reason": best["reason"],
            "StakeLabel": best["stake_label"],
        }
    )
    safe_send(build_sniper_message(best))
    log_sniper(
        f"SNIPER_OPEN key={best['signal_key']} market={best['market']} minute={best['minute_value']} "
        f"score={best['score']} sniper_score={best['sniper_score']:.3f}"
    )


def main() -> None:
    print("Starting Oracle Sniper...")
    if not acquire_lock():
        print("Another Oracle Sniper instance is already running.")
        return
    try:
        ensure_core_loaded()
        state = load_state()
        safe_send(
            "<b>ORACLE SNIPER ONLINE</b>\n"
            f"{core.SEPARATOR}\n"
            f"<b>Daily cap:</b> {SNIPER_SIGNAL_LIMIT_PER_DAY}\n"
            f"<b>Stop loss:</b> {SNIPER_DAILY_STOP_LOSS_UNITS:.1f}u\n"
            f"<b>Loss streak stop:</b> {SNIPER_MAX_CONSECUTIVE_LOSSES}\n"
            "<i>Separate speculative engine started.</i>"
        )
        while True:
            state = load_state()
            scan_once(state)
            save_state(state)
            time.sleep(30)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
