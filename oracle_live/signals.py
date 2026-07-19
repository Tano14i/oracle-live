import threading
import time
from datetime import datetime

import pandas as pd
import requests

from config import (
    API_KEY,
    CHANNEL_ID,
    CHAT_ID,
    EV_GATE_ENABLED,
    EV_MIN_EDGE,
    FREE_DELAY_SECONDS,
    QUOTA,
    STAKE,
    VIP_CHANNEL_ID,
)
from trainer import FEATURE_COLUMNS as TRAINER_FEATURE_COLUMNS

from oracle_live import state
from oracle_live.api_client import (
    fetch_fixture_stats,
    fetch_fixture_status,
    fetch_live_market_odds,
)
from oracle_live.constants import (
    FREE_ALLOWED_TIERS,
    MARKET_NEXT_GOAL,
    MARKET_OVER05_HT,
    MARKET_OVER15_HT,
    PREMIUM_ALLOWED_COUNTRIES,
    PREMIUM_ALLOWED_LEAGUES,
    PREMIUM_ALLOWED_MARKETS,
    PREMIUM_BLOCKED_COUNTRIES,
    PREMIUM_BLOCKED_LEAGUES,
    SEPARATOR,
    TIER_APPROVED,
    TIER_CAUTION,
    TIER_GAMBLING,
    TIER_LEARNING,
    TITAN_PRESSURE_ALERT_THRESHOLD,
    TITAN_PROMOTION_THRESHOLD,
)
from oracle_live.filters import (
    get_filter_label,
    get_league_filter_reason,
    trova_squadra,
)
from oracle_live.guards import (
    should_skip_by_live_performance,
    should_skip_by_live_stats,
    should_skip_next_goal_by_context,
)
from oracle_live.markets import (
    get_active_markets,
    get_market_label,
    get_minute_bucket,
    get_routed_active_markets,
    is_first_half_closed,
    is_market_window,
    is_market_winner,
    prioritize_markets,
)
from oracle_live.messaging import (
    escape_html,
    format_free_teaser_message,
    format_premium_signal_message,
    format_settlement_message,
    format_signal_message,
)
from oracle_live.models import (
    evaluate_titan_soft_layer,
    get_xg_rate,
    has_live_pressure_data,
    maybe_trigger_auto_retrain,
    predict_titan_pressure_prob,
)
from oracle_live.reporting import maybe_send_performance_report
from oracle_live.state import (
    append_live_training_row,
    append_rolling_settled,
    bot,
    ensure_daily_analytics,
    increment_analytics,
    increment_breakdown_counter,
    increment_market_settlement,
    increment_settled_breakdown,
    log_event,
    now_utc,
    pending_free_timers,
    salva_dati_web,
    state_lock,
    stats,
    update_live_training_outcome,
)
from oracle_live.vip import sync_vip_memberships

def get_signal_key(fixture_id: int, market: str) -> str:
    return f"{fixture_id}:{market}"


def should_send_free_teaser(tier: str) -> bool:
    if not CHANNEL_ID or tier not in FREE_ALLOWED_TIERS:
        return False
    with state_lock:
        stats["free_teaser_counter"] = int(stats.get("free_teaser_counter", 0)) + 1
    return True


def build_delivery_targets_from_legacy(info: dict):
    deliveries = list(info.get("delivery_targets") or [])
    if deliveries:
        return deliveries

    chat_msg_id = info.get("chat_msg_id") or info.get("msg_id_chat")
    channel_msg_id = info.get("channel_msg_id")

    if chat_msg_id and CHAT_ID:
        deliveries.append(
            {
                "chat_id": CHAT_ID,
                "message_id": chat_msg_id,
                "audience": "admin",
                "original_text": info.get("original_text", ""),
            }
        )
    if channel_msg_id and CHANNEL_ID:
        deliveries.append(
            {
                "chat_id": CHANNEL_ID,
                "message_id": channel_msg_id,
                "audience": "free",
                "original_text": info.get("original_text", ""),
            }
        )
    if deliveries:
        info["delivery_targets"] = deliveries
    return deliveries


def migrate_monitor_entries() -> None:
    changed = False
    monitor = stats.get("monitor_risultati") or {}
    for info in monitor.values():
        if isinstance(info, dict) and not info.get("delivery_targets"):
            if build_delivery_targets_from_legacy(info):
                changed = True
    if changed:
        salva_dati_web()


def prune_settled_signals(max_settled: int = 200) -> None:
    with state_lock:
        monitor = stats.get("monitor_risultati") or {}
        pending_items = {k: v for k, v in monitor.items() if isinstance(v, dict) and v.get("status") == "pending"}
        settled_items = [(k, v) for k, v in monitor.items() if isinstance(v, dict) and v.get("status") == "settled"]
        if len(settled_items) > max_settled:
            settled_items = settled_items[-max_settled:]
        rebuilt = dict(settled_items)
        rebuilt.update(pending_items)
        stats["monitor_risultati"] = rebuilt


def clean_sent_signals() -> None:
    with state_lock:
        active_keys = {key for key, value in stats["monitor_risultati"].items() if isinstance(value, dict) and value.get("status") == "pending"}
        stats["segnali_inviati"] = [key for key in stats.get("segnali_inviati", []) if key in active_keys]


def get_team_metrics(team_name: str):
    if not team_name or state.df_matches is None:
        return None

    storico = state.df_matches[(state.df_matches["HomeTeam"] == team_name) | (state.df_matches["AwayTeam"] == team_name)].tail(12)
    if len(storico) < 6:
        return {
            "team": team_name,
            "metrics_ok": False,
            "reason": f"insufficient history ({len(storico)}/6)",
            "matches": int(len(storico)),
        }

    total_goals = (storico["FTHome"].fillna(0) + storico["FTAway"].fillna(0)).astype(float)
    ht_goals = (storico["HTHome"].fillna(0) + storico["HTAway"].fillna(0)).astype(float)

    avg_total_goals = round(total_goals.mean(), 2)
    avg_ht_goals = round(ht_goals.mean(), 2)

    suspicious_ht_zero_mask = (ht_goals == 0) & (total_goals >= 2)
    suspicious_ratio = float(suspicious_ht_zero_mask.mean()) if len(storico) else 0.0
    positive_ht_count = int((ht_goals > 0).sum())
    ht_fallback_used = False

    if avg_total_goals >= 2.2 and avg_ht_goals <= 0.35 and suspicious_ratio >= 0.6 and positive_ht_count <= 2:
        avg_ht_goals = round(min(max(avg_total_goals * 0.38, 0.8), 1.35), 2)
        ht_fallback_used = True

    reason = "ok"
    if ht_fallback_used:
        reason = f"ht fallback used (suspicious_zero_ratio={suspicious_ratio:.2f})"

    return {
        "team": team_name,
        "metrics_ok": True,
        "reason": reason,
        "matches": int(len(storico)),
        "avg_total_goals": avg_total_goals,
        "avg_ht_goals": avg_ht_goals,
    }

def combine_team_metrics(home_metrics: dict, away_metrics: dict):
    if not home_metrics or not away_metrics:
        return None

    if not home_metrics.get("metrics_ok", True) or not away_metrics.get("metrics_ok", True):
        return {
            "metrics_ok": False,
            "reason": f"home={home_metrics.get('reason', 'unknown')} | away={away_metrics.get('reason', 'unknown')}",
            "matches": min(home_metrics.get("matches", 0), away_metrics.get("matches", 0)),
            "home_avg_total_goals": home_metrics.get("avg_total_goals", 0.0),
            "away_avg_total_goals": away_metrics.get("avg_total_goals", 0.0),
            "home_avg_ht_goals": home_metrics.get("avg_ht_goals", 0.0),
            "away_avg_ht_goals": away_metrics.get("avg_ht_goals", 0.0),
            "avg_total_goals": 0.0,
            "avg_ht_goals": 0.0,
        }

    return {
        "metrics_ok": True,
        "reason": f"home={home_metrics.get('reason', 'ok')} | away={away_metrics.get('reason', 'ok')}",
        "matches": min(home_metrics["matches"], away_metrics["matches"]),
        "home_avg_total_goals": home_metrics["avg_total_goals"],
        "away_avg_total_goals": away_metrics["avg_total_goals"],
        "home_avg_ht_goals": home_metrics["avg_ht_goals"],
        "away_avg_ht_goals": away_metrics["avg_ht_goals"],
        "avg_total_goals": round((home_metrics["avg_total_goals"] + away_metrics["avg_total_goals"]) / 2, 2),
        "avg_ht_goals": round((home_metrics["avg_ht_goals"] + away_metrics["avg_ht_goals"]) / 2, 2),
    }


def evaluate_signal_candidate(market: str, minute_value: int, total_goals: int, prob: float, metrics: dict):
    if not metrics or metrics["matches"] < 6:
        return None

    avg_total_goals = metrics["avg_total_goals"]
    avg_ht_goals = metrics["avg_ht_goals"]
    home_ht = metrics["home_avg_ht_goals"]
    away_ht = metrics["away_avg_ht_goals"]

    if market == MARKET_OVER05_HT:
        if total_goals != 0 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 2.10 or avg_ht_goals < 0.80:
            return None
        if min(home_ht, away_ht) < 0.56:
            return None
        if prob >= 0.88 and avg_total_goals >= 2.35 and avg_ht_goals >= 1.00:
            return {
                "tier": TIER_APPROVED,
                "reason": f"HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f} | 0-0 with time window still strong",
            }
        if prob >= 0.80 and avg_total_goals >= 2.20 and avg_ht_goals >= 0.86:
            return {
                "tier": TIER_CAUTION,
                "reason": f"HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f} | setup still tradable",
            }
        if prob >= 0.72 and avg_total_goals >= 2.08 and avg_ht_goals >= 0.78 and min(home_ht, away_ht) >= 0.52:
            return {
                "tier": TIER_GAMBLING,
                "reason": f"HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f} | aggressive early HT value setup",
            }
        return None

    if market == MARKET_OVER15_HT:
        if total_goals != 1 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 2.30 or avg_ht_goals < 0.98:
            return None
        if min(home_ht, away_ht) < 0.72:
            return None
        if prob >= 0.90 and avg_total_goals >= 2.65 and avg_ht_goals >= 1.25:
            return {
                "tier": TIER_APPROVED,
                "reason": f"Strong first-half pace {avg_ht_goals:.2f} | one goal already landed | high continuation setup",
            }
        if prob >= 0.84 and avg_total_goals >= 2.48 and avg_ht_goals >= 1.14:
            return {
                "tier": TIER_CAUTION,
                "reason": f"One-goal HT setup with solid pace {avg_ht_goals:.2f} and total profile {avg_total_goals:.2f}",
            }
        if prob >= 0.76 and avg_total_goals >= 2.34 and avg_ht_goals >= 1.04 and min(home_ht, away_ht) >= 0.66:
            return {
                "tier": TIER_GAMBLING,
                "reason": f"One-goal HT setup with aggressive continuation value and pace {avg_ht_goals:.2f}",
            }
        return None

    if market == MARKET_NEXT_GOAL:
        if not 1 <= minute_value <= 85:
            return None
        if avg_total_goals < 2.20:
            return None
        if prob >= 0.82 and avg_total_goals >= 2.70:
            return {
                "tier": TIER_APPROVED,
                "reason": f"Live next-goal pressure | model {prob:.2f} | total pace {avg_total_goals:.2f}",
            }
        if prob >= 0.72 and avg_total_goals >= 2.45:
            return {
                "tier": TIER_CAUTION,
                "reason": f"Next-goal live setup | model {prob:.2f} | total pace {avg_total_goals:.2f}",
            }
        if prob >= 0.64 and avg_total_goals >= 2.25:
            return {
                "tier": TIER_GAMBLING,
                "reason": f"Aggressive next-goal value | model {prob:.2f} | total pace {avg_total_goals:.2f}",
            }
        return None

    return None


def evaluate_learning_candidate(market: str, minute_value: int, total_goals: int, prob: float, metrics: dict):
    if not metrics or metrics.get("matches", 0) < 6:
        return None

    avg_total_goals = metrics["avg_total_goals"]
    avg_ht_goals = metrics["avg_ht_goals"]
    home_ht = metrics["home_avg_ht_goals"]
    away_ht = metrics["away_avg_ht_goals"]

    if market == MARKET_OVER05_HT:
        if total_goals != 0 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 2.10 or avg_ht_goals < 0.78:
            return None
        if min(home_ht, away_ht) < 0.55:
            return None
        if prob >= 0.78:
            return {
                "tier": TIER_LEARNING,
                "reason": f"HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f} | learning shadow candidate",
            }
        return None

    if market == MARKET_OVER15_HT:
        if total_goals != 1 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 2.30 or avg_ht_goals < 0.98:
            return None
        if min(home_ht, away_ht) < 0.68:
            return None
        if prob >= 0.82:
            return {
                "tier": TIER_LEARNING,
                "reason": f"HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f} | learning one-goal shadow",
            }
        return None

    if market == MARKET_NEXT_GOAL:
        if not 1 <= minute_value <= 85:
            return None
        if avg_total_goals < 2.10:
            return None
        if prob >= 0.58:
            return {
                "tier": TIER_LEARNING,
                "reason": f"Next-goal shadow | model {prob:.2f} | total pace {avg_total_goals:.2f}",
            }
        return None

    return None


def clear_pending_signal_tracker(signal_key: str) -> None:
    with state_lock:
        tracker = stats.setdefault("pending_signal_tracker", {})
        tracker.pop(signal_key, None)

def register_pending_signal_tracker(signal_key: str, minute_value: int, total_goals: int, prob: float) -> int:
    with state_lock:
        tracker = stats.setdefault("pending_signal_tracker", {})
        item = tracker.get(signal_key)
        if not isinstance(item, dict):
            item = {}
        previous_score = item.get("last_score")
        previous_minute = int(item.get("last_minute", -1) or -1)
        if previous_score == total_goals and minute_value >= previous_minute:
            count = int(item.get("count", 0) or 0) + 1
        else:
            count = 1
        tracker[signal_key] = {
            "count": count,
            "last_score": total_goals,
            "last_minute": minute_value,
            "last_prob": round(float(prob or 0.0), 4),
            "last_seen": now_utc().isoformat(),
        }
        return count


def evaluate_pending_next_goal_candidate(minute_value: int, total_goals: int, prob: float, metrics: dict, persistence_count: int, titan_pressure_prob, titan_soft: dict):
    if total_goals >= 6 or not metrics:
        return None

    avg_total_goals = metrics.get("avg_total_goals", 0.0)
    if not 1 <= minute_value <= 80 or avg_total_goals < 2.15:
        return None

    titan_score = int((titan_soft or {}).get("score", 0) or 0)
    titan_prob_value = float(titan_pressure_prob) if titan_pressure_prob is not None else -1.0

    if persistence_count >= 4 and prob >= 0.52 and (titan_prob_value >= 0.60 or titan_score >= 2 or avg_total_goals >= 2.60):
        return {
            "tier": TIER_CAUTION,
            "reason": f"next-goal pending persistence x{persistence_count} | model {prob:.2f} | total pace {avg_total_goals:.2f}",
        }
    if persistence_count >= 3 and prob >= 0.44:
        return {
            "tier": TIER_GAMBLING,
            "reason": f"risky next-goal persistence x{persistence_count} | model {prob:.2f} | total pace {avg_total_goals:.2f}",
        }
    return None

def evaluate_snapshot_candidate(market: str, minute_value: int, total_goals: int, prob: float, metrics: dict):
    if not metrics or metrics.get("matches", 0) < 6:
        return None

    avg_total_goals = metrics["avg_total_goals"]
    avg_ht_goals = metrics["avg_ht_goals"]
    home_ht = metrics["home_avg_ht_goals"]
    away_ht = metrics["away_avg_ht_goals"]

    if market == MARKET_OVER05_HT:
        if total_goals != 0 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 1.95 or avg_ht_goals < 0.70:
            return None
        if min(home_ht, away_ht) < 0.48:
            return None
        if prob >= 0.72:
            return {
                "tier": TIER_LEARNING,
                "reason": f"wide shadow candidate | HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f}",
            }
        return None

    if market == MARKET_OVER15_HT:
        if total_goals != 1 or not 1 <= minute_value <= 44:
            return None
        if avg_total_goals < 2.25 or avg_ht_goals < 0.95:
            return None
        if min(home_ht, away_ht) < 0.60:
            return None
        if prob >= 0.76:
            return {
                "tier": TIER_LEARNING,
                "reason": f"wide one-goal shadow | HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f}",
            }
        return None

    return None


def evaluate_prewindow_snapshot_candidate(market: str, minute_value: int, total_goals: int, prob: float, metrics: dict):
    if not metrics or metrics.get("matches", 0) < 6:
        return None
    avg_total_goals = metrics["avg_total_goals"]
    avg_ht_goals = metrics["avg_ht_goals"]
    home_ht = metrics["home_avg_ht_goals"]
    away_ht = metrics["away_avg_ht_goals"]
    if not 1 <= minute_value <= 44:
        return None
    if market == MARKET_OVER05_HT:
        if total_goals != 0 or prob < 0.70 or avg_total_goals < 2.00 or avg_ht_goals < 0.72 or min(home_ht, away_ht) < 0.50:
            return None
        return {"tier": TIER_LEARNING, "reason": f"pre-window shadow | model {prob:.2f} | HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f}"}
    if market == MARKET_OVER15_HT:
        if total_goals not in (0, 1) or prob < 0.72 or avg_total_goals < 2.20 or avg_ht_goals < 0.92 or min(home_ht, away_ht) < 0.58:
            return None
        return {"tier": TIER_LEARNING, "reason": f"pre-window one-goal shadow | model {prob:.2f} | HT pace {avg_ht_goals:.2f} | total pace {avg_total_goals:.2f}"}
    return None


def is_premium_private_signal(
    tier: str,
    country: str,
    league_name: str,
    market: str,
    minute_value: int,
    dna: float,
    prob: float,
    reason: str = "",
):
    normalized_reason = (reason or "").lower()
    if market not in PREMIUM_ALLOWED_MARKETS:
        return False, "market"
    if minute_value < 15 or minute_value > 35:
        return False, "minute"
    if league_name in PREMIUM_BLOCKED_LEAGUES:
        return False, "league_blocked"
    if country in PREMIUM_BLOCKED_COUNTRIES:
        return False, "country_blocked"
    if "titan pressure alert" in normalized_reason:
        return False, "pressure_alert"
    if dna < 1.8 or dna > 3.3:
        return False, "dna_band"
    if tier == TIER_APPROVED:
        min_prob = 0.66
    elif tier == TIER_CAUTION:
        min_prob = 0.70
    elif tier == TIER_LEARNING:
        min_prob = 0.74
    else:
        return False, "tier"
    if prob < min_prob:
        return False, "prob"
    if league_name in PREMIUM_ALLOWED_LEAGUES:
        return True, "league_allow"
    if country in PREMIUM_ALLOWED_COUNTRIES and prob >= max(0.72, min_prob):
        return True, "country_allow"
    return False, "not_whitelisted"


def get_market_debug_status(
    fixture_id: int,
    market: str,
    minute_value: int,
    total_goals: int,
    score: str,
    league_name: str,
    headers: dict,
    combined_metrics: dict,
) -> str:
    signal_key = get_signal_key(fixture_id, market)
    pending_signal = stats["monitor_risultati"].get(signal_key)
    if pending_signal and pending_signal.get("status") == "pending":
        return f"{market}: PENDING"
    if signal_key in stats["segnali_inviati"]:
        return f"{market}: ALREADY_SENT"
    if state.oracle_brain is None:
        return f"{market}: NO_MODEL"

    dna = combined_metrics["avg_total_goals"]
    stats_payload = fetch_fixture_stats(fixture_id, headers)
    titan_soft = evaluate_titan_soft_layer(stats_payload, market, minute_value, total_goals)
    shots_on_goal_at_open = float(stats_payload.get("shots_on_goal", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    total_shots_at_open = float(stats_payload.get("total_shots", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    corners_at_open = float(stats_payload.get("corners", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    red_cards_at_open = float(stats_payload.get("red_cards", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    shots_insidebox_at_open = float(stats_payload.get("shots_insidebox", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    goalkeeper_saves_at_open = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    xg_rate_at_open = get_xg_rate(stats_payload, minute_value)
    titan_pressure_score = float(titan_soft.get("score", 0.0) or 0.0)
    titan_pressure_prob = predict_titan_pressure_prob(dna, minute_value, 0, total_goals, stats_payload)

    model_feature_columns = list(getattr(state.oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))
    model_feature_values = {
        "DNA": dna,
        "Minute": minute_value,
        "TotalGoalsAtOpen": total_goals,
        "AvgTotalGoals": combined_metrics["avg_total_goals"],
        "AvgHTGoals": combined_metrics["avg_ht_goals"],
        "HomeAvgTotalGoals": combined_metrics["home_avg_total_goals"],
        "AwayAvgTotalGoals": combined_metrics["away_avg_total_goals"],
        "HomeAvgHTGoals": combined_metrics["home_avg_ht_goals"],
        "AwayAvgHTGoals": combined_metrics["away_avg_ht_goals"],
        "ShotsOnGoalAtOpen": shots_on_goal_at_open,
        "TotalShotsAtOpen": total_shots_at_open,
        "CornersAtOpen": corners_at_open,
        "RedCardsAtOpen": red_cards_at_open,
        "TitanPressureScore": titan_pressure_score,
        "MarketOver05HT": 1.0 if market == MARKET_OVER05_HT else 0.0,
        "MarketOver15HT": 1.0 if market == MARKET_OVER15_HT else 0.0,
        "MarketNextGoal": 1.0 if market == MARKET_NEXT_GOAL else 0.0,
        "ShotsInsideBoxAtOpen": shots_insidebox_at_open,
        "GoalkeeperSavesAtOpen": goalkeeper_saves_at_open,
        "XgRateAtOpen": xg_rate_at_open,
    }
    x_input = pd.DataFrame(
        [[model_feature_values.get(column, 0.0) for column in model_feature_columns]],
        columns=model_feature_columns,
    )
    prob = state.oracle_brain.predict_proba(x_input)[0][1]

    if not is_market_window(market, minute_value, total_goals):
        assessment = evaluate_prewindow_snapshot_candidate(market, minute_value, total_goals, prob, combined_metrics)
        if assessment:
            return f"{market}: SHADOW_PRE ({assessment['tier']})"
        return f"{market}: MARKET_WINDOW score {score} min {minute_value}' prob {prob:.2f}"

    assessment = evaluate_signal_candidate(market, minute_value, total_goals, prob, combined_metrics)
    if assessment:
        return f"{market}: SIGNAL {assessment['tier']} prob {prob:.2f}"

    live_pressure_available = has_live_pressure_data(stats_payload)
    if not live_pressure_available:
        pressure_alert_reason = None
        if market == MARKET_OVER05_HT and total_goals == 0 and prob >= 0.78 and combined_metrics["avg_ht_goals"] >= 0.92 and min(combined_metrics["home_avg_ht_goals"], combined_metrics["away_avg_ht_goals"]) >= 0.62:
            pressure_alert_reason = "EARLY_PRESSURE_ALERT"
        elif market == MARKET_OVER15_HT and total_goals == 1 and prob >= 0.80 and combined_metrics["avg_ht_goals"] >= 1.08 and min(combined_metrics["home_avg_ht_goals"], combined_metrics["away_avg_ht_goals"]) >= 0.72:
            pressure_alert_reason = "EARLY_PRESSURE_ALERT"
        if pressure_alert_reason:
            return f"{market}: PRESSURE_ALERT no-stats prob {prob:.2f}"
    if titan_pressure_prob is not None and titan_pressure_prob >= TITAN_PRESSURE_ALERT_THRESHOLD:
        return f"{market}: PRESSURE_ALERT titan {titan_pressure_prob:.2f}"
    if titan_soft.get("score", 0) >= 3:
        return f"{market}: PRESSURE_ALERT soft {titan_soft.get('score', 0)}"

    assessment = evaluate_learning_candidate(market, minute_value, total_goals, prob, combined_metrics)
    if assessment:
        return f"{market}: SHADOW ({assessment['tier']}) prob {prob:.2f}"
    assessment = evaluate_snapshot_candidate(market, minute_value, total_goals, prob, combined_metrics)
    if assessment:
        return f"{market}: SHADOW_WIDE ({assessment['tier']}) prob {prob:.2f}"

    skip_signal, skip_reason = should_skip_by_live_performance(market, league_name, get_minute_bucket(minute_value))
    if skip_signal:
        return f"{market}: PERFORMANCE_SKIP {skip_reason}"
    stats_skip, stats_skip_reason = should_skip_by_live_stats(
        fixture_id,
        market,
        minute_value,
        total_goals,
        headers,
        stats_payload=stats_payload,
    )
    if stats_skip:
        return f"{market}: LIVE_STATS_SKIP {stats_skip_reason}"
    return f"{market}: CANDIDATE_FAILED prob {prob:.2f}"


def format_radar_check_text(limit: int = 10) -> str:
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_KEY}
    response = requests.get(url, headers=headers, params={"live": "all"}, timeout=20)
    if response.status_code != 200:
        return f"Radar check failed: API {response.status_code}"

    data = response.json().get("response", [])
    if not data:
        return "<b>RADAR CHECK</b>\n----------------------------\nNo live fixtures right now."

    rows = []
    for match in data[:limit]:
        fixture_id = match["fixture"].get("id")
        if fixture_id is None:
            continue
        home_live = match["teams"]["home"]["name"]
        away_live = match["teams"]["away"]["name"]
        country = match["league"].get("country", "Unknown")
        league_name = match["league"].get("name", "Unknown")
        goals_home = match["goals"].get("home", 0) or 0
        goals_away = match["goals"].get("away", 0) or 0
        score = f"{goals_home}-{goals_away}"
        total_goals = goals_home + goals_away
        minute_value = match["fixture"]["status"].get("elapsed", 0) or 0
        match_up = f"{home_live} vs {away_live}"

        league_filter_reason = get_league_filter_reason(country, league_name)
        if league_filter_reason is not None:
            rows.append(f"{minute_value}' {match_up}\n{country} | {league_name}\nLEAGUE_FILTERED: {league_filter_reason}")
            continue

        home_db = trova_squadra(home_live, country, league_name)
        away_db = trova_squadra(away_live, country, league_name)
        if not home_db or not away_db:
            rows.append(f"{minute_value}' {match_up}\n{country} | {league_name}\nTEAM_NOT_FOUND: home={home_db or '-'} away={away_db or '-'}")
            continue

        home_metrics = get_team_metrics(home_db)
        away_metrics = get_team_metrics(away_db)
        combined_metrics = combine_team_metrics(home_metrics, away_metrics)
        if not combined_metrics or not combined_metrics.get("metrics_ok", True):
            reason = combined_metrics.get("reason", "unknown") if isinstance(combined_metrics, dict) else "unknown"
            rows.append(f"{minute_value}' {match_up}\n{country} | {league_name}\nNO_METRICS: {reason}")
            continue

        market_statuses = []
        for market in get_active_markets():
            market_statuses.append(get_market_debug_status(fixture_id, market, minute_value, total_goals, score, league_name, headers, combined_metrics))
        rows.append(
            f"{minute_value}' {match_up}\n"
            f"{country} | {league_name} | score {score}\n"
            + "\n".join(market_statuses)
        )

    body = "\n\n".join(rows[:limit])
    return f"<b>RADAR CHECK</b>\n{SEPARATOR}\n<pre>{escape_html(body)}</pre>"


def update_recent_signal(signal_key: str, outcome: str) -> None:
    for signal in stats["recent_signals"]:
        if signal.get("SignalKey") == signal_key:
            signal["Esito"] = outcome
            return


def edit_signal_message(delivery_targets, market: str, outcome: str, score_finale: str) -> None:
    for delivery in delivery_targets or []:
        chat_target = delivery.get("chat_id")
        message_id = delivery.get("message_id")
        original_text = delivery.get("original_text", "")
        audience = delivery.get("audience", "vip")
        if not chat_target or not message_id:
            continue
        updated_text = format_settlement_message(original_text, market, outcome, score_finale, audience)
        try:
            bot.edit_message_text(text=updated_text, chat_id=chat_target, message_id=message_id, parse_mode="HTML")
            log_event('EDIT_OK', f"chat_id={chat_target} message_id={message_id} outcome={outcome} market={market}")
        except Exception as exc:
            log_event('EDIT_FAIL', f"chat_id={chat_target} message_id={message_id} outcome={outcome} market={market} error={exc}")
            print(f"Edit failed for {chat_target}:{message_id} -> {exc}")
            try:
                bot.send_message(chat_target, updated_text, parse_mode="HTML")
            except Exception as send_exc:
                print(f"Fallback send failed for {chat_target}:{message_id} -> {send_exc}")
                if CHAT_ID and str(chat_target) != str(CHAT_ID):
                    try:
                        bot.send_message(CHAT_ID, f"Edit failed on {chat_target}:{message_id} | {exc}")
                    except Exception:
                        pass


def settle_missing_live_signals(seen_fixture_ids, headers: dict) -> None:
    pending_items = list((stats.get("monitor_risultati") or {}).items())
    for signal_key, info in pending_items:
        if not isinstance(info, dict) or info.get("status") != "pending":
            continue
        fixture_id = info.get("fixture_id")
        market = info.get("market")
        if not fixture_id or fixture_id in seen_fixture_ids or not market:
            continue

        fixture_state = fetch_fixture_status(fixture_id, headers)
        if not fixture_state:
            continue

        total_goals = fixture_state["total_goals"]
        minute_value = fixture_state["minute_value"]
        status_short = fixture_state["status_short"]
        score = fixture_state["score"]

        if market == MARKET_NEXT_GOAL:
            start_total_goals = int(info.get("total_goals_at_open", 0) or 0)
            if total_goals > start_total_goals:
                chiudi_scommessa(signal_key, True, score)
            elif status_short in {"FT", "AET", "PEN"}:
                chiudi_scommessa(signal_key, False, score)
        elif is_market_winner(market, total_goals):
            chiudi_scommessa(signal_key, True, score)
        elif is_first_half_closed(status_short, minute_value):
            chiudi_scommessa(signal_key, False, score)


def chiudi_scommessa(signal_key: str, vinta: bool, score_finale: str) -> None:
    with state_lock:
        info = stats["monitor_risultati"].get(signal_key)
        if not info or info.get("status") == "settled":
            return

        timer = pending_free_timers.pop(signal_key, None)
        if timer:
            timer.cancel()

        shadow_only = bool(info.get("shadow_only", False))
        tier = info["tier"]
        cambio = (STAKE * QUOTA - STAKE) if vinta else -STAKE
        outcome = "WIN" if vinta else "LOSS"

        if not shadow_only:
            stats[tier]["v" if vinta else "p"] += 1
            increment_analytics("settled_win" if vinta else "settled_loss")
            increment_market_settlement(info.get("market", signal_key), outcome)
            increment_settled_breakdown("settled_by_league", info.get("league_name", ""), outcome)
            increment_settled_breakdown("settled_by_minute_bucket", info.get("minute_bucket", ""), outcome)
            append_rolling_settled(
                info.get("market", signal_key),
                info.get("league_name", ""),
                info.get("minute_bucket", ""),
                outcome,
            )
            update_recent_signal(signal_key, outcome)

        info["status"] = "settled"
        info["edited_outcome"] = outcome
        delivery_targets = info.get("delivery_targets") or build_delivery_targets_from_legacy(info)
        market_name = info.get("market", signal_key)
    log_event("SHADOW_SETTLED" if shadow_only else "SIGNAL_SETTLED", f"key={signal_key} outcome={outcome} score={score_finale} market={market_name}")
    prune_settled_signals()
    update_live_training_outcome(signal_key, outcome, score_finale)
    if shadow_only:
        salva_dati_web()
        maybe_trigger_auto_retrain()
        return
    salva_dati_web(nuovo_profitto=cambio)
    edit_signal_message(delivery_targets, market_name, outcome, score_finale)
    maybe_send_performance_report()
    maybe_trigger_auto_retrain()


def schedule_free_delivery(signal_key: str, chat_id, message_text: str) -> None:
    def _send():
        pending_free_timers.pop(signal_key, None)
        with state_lock:
            info = stats["monitor_risultati"].get(signal_key)
        if not info or info.get("status") != "pending":
            return
        try:
            sent = bot.send_message(chat_id, message_text, parse_mode="HTML")
            increment_analytics("free_teasers_sent")
            with state_lock:
                info.setdefault("delivery_targets", []).append(
                    {
                        "chat_id": chat_id,
                        "message_id": getattr(sent, "message_id", None),
                        "audience": "free",
                        "original_text": message_text,
                    }
                )
            salva_dati_web()
        except Exception as exc:
            print(f"Invio teaser free fallito per {chat_id}: {exc}")

    delay = max(0, FREE_DELAY_SECONDS)
    timer = threading.Timer(delay, _send)
    timer.daemon = True
    pending_free_timers[signal_key] = timer
    timer.start()
    increment_analytics("free_teasers_scheduled")


def record_signal_delivery(signal_key: str, tier: str, full_message: str, free_message: str, private_premium_message: str = ""):
    deliveries = []

    for chat_target, audience, message_text in [
        (CHAT_ID, "admin", full_message),
        (VIP_CHANNEL_ID, "vip", full_message),
    ]:
        if not chat_target:
            continue
        if not message_text:
            continue
        try:
            sent = bot.send_message(chat_target, message_text, parse_mode="HTML")
            deliveries.append(
                {
                    "chat_id": chat_target,
                    "message_id": getattr(sent, "message_id", None),
                    "audience": audience,
                    "original_text": message_text,
                }
            )
        except Exception as exc:
            print(f"Invio fallito per {chat_target}: {exc}")

    if CHAT_ID and private_premium_message:
        try:
            sent = bot.send_message(CHAT_ID, private_premium_message, parse_mode="HTML")
            deliveries.append(
                {
                    "chat_id": CHAT_ID,
                    "message_id": getattr(sent, "message_id", None),
                    "audience": "admin_premium",
                    "original_text": private_premium_message,
                }
            )
        except Exception as exc:
            print(f"Invio premium privato fallito per {CHAT_ID}: {exc}")

    if should_send_free_teaser(tier):
        schedule_free_delivery(signal_key, CHANNEL_ID, free_message)

    return deliveries


def radar_loop() -> None:
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_KEY}

    while state.running and not state.shutdown_requested:
        try:
            sync_vip_memberships()
            ensure_daily_analytics()
            seen_fixture_ids = set()
            print(
                f"Scansione: {datetime.now().strftime('%H:%M:%S')} | filter: {get_filter_label()} | market: {get_market_label()}"
            )
            response = requests.get(url, headers=headers, params={"live": "all"}, timeout=20)
            if response.status_code != 200:
                print(f"API error: {response.status_code}")
                time.sleep(30)
                continue

            data = response.json().get("response", [])
            scan_debug = {
                "fixtures_total": len(data),
                "league_filtered": 0,
                "league_filtered_base": 0,
                "league_filtered_coverage": 0,
                "team_not_found": 0,
                "no_metrics": 0,
                "pending_or_sent": 0,
                "market_window": 0,
                "no_model": 0,
                "candidate_failed": 0,
                "performance_skip": 0,
                "live_stats_skip": 0,
                "signals_opened": 0,
                "shadow_opened": 0,
                "ev_gate_skip": 0,
            }
            for match in data:
                fixture_id = match["fixture"].get("id")
                if fixture_id is None:
                    continue
                seen_fixture_ids.add(fixture_id)

                home_live = match["teams"]["home"]["name"]
                away_live = match["teams"]["away"]["name"]
                country = match["league"].get("country", "Unknown")
                league_name = match["league"].get("name", "Unknown")
                goals_home = match["goals"].get("home", 0) or 0
                goals_away = match["goals"].get("away", 0) or 0
                score = f"{goals_home}-{goals_away}"
                total_goals = goals_home + goals_away
                minute_value = match["fixture"]["status"].get("elapsed", 0) or 0
                status_short = match["fixture"]["status"].get("short", "")
                match_up = f"{home_live.upper()} vs {away_live.upper()}"

                league_filter_reason = get_league_filter_reason(country, league_name)
                if league_filter_reason is not None:
                    scan_debug["league_filtered"] += 1
                    if league_filter_reason == "coverage":
                        scan_debug["league_filtered_coverage"] += 1
                    else:
                        scan_debug["league_filtered_base"] += 1
                    continue

                home_db = trova_squadra(home_live, country, league_name)
                away_db = trova_squadra(away_live, country, league_name)
                if not home_db or not away_db:
                    scan_debug["team_not_found"] += 1
                    continue

                home_metrics = get_team_metrics(home_db)
                away_metrics = get_team_metrics(away_db)
                combined_metrics = combine_team_metrics(home_metrics, away_metrics)
                if not combined_metrics or not combined_metrics.get("metrics_ok", True):
                    scan_debug["no_metrics"] += 1
                    log_event("NO_METRICS", f"match={match_up} home_db={home_db or '-'} away_db={away_db or '-'} reason={combined_metrics.get('reason', 'unknown') if isinstance(combined_metrics, dict) else 'unknown'}")
                    continue

                with state_lock:
                    stats["matches_analyzed"] += 1

                active_markets = get_routed_active_markets()
                prioritized_markets = prioritize_markets(active_markets, minute_value, total_goals)
                opened_primary_signal = False

                for market in active_markets:
                    signal_key = get_signal_key(fixture_id, market)
                    pending_signal = stats["monitor_risultati"].get(signal_key)
                    if pending_signal and pending_signal.get("status") == "pending":
                        if market == MARKET_NEXT_GOAL:
                            start_total_goals = int(pending_signal.get("total_goals_at_open", 0) or 0)
                            if total_goals > start_total_goals:
                                chiudi_scommessa(signal_key, True, score)
                            elif status_short in {"FT", "AET", "PEN"}:
                                chiudi_scommessa(signal_key, False, score)
                        else:
                            if is_market_winner(market, total_goals):
                                chiudi_scommessa(signal_key, True, score)
                            elif is_first_half_closed(status_short, minute_value):
                                chiudi_scommessa(signal_key, False, score)
                        continue


                if state.oracle_brain is None:
                    scan_debug["no_model"] += len(prioritized_markets)
                    continue

                stats_payload = fetch_fixture_stats(fixture_id, headers)
                shots_on_goal_at_open = float(stats_payload.get("shots_on_goal", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                total_shots_at_open = float(stats_payload.get("total_shots", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                corners_at_open = float(stats_payload.get("corners", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                red_cards_at_open = float(stats_payload.get("red_cards", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                shots_insidebox_at_open = float(stats_payload.get("shots_insidebox", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                goalkeeper_saves_at_open = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                xg_rate_at_open = get_xg_rate(stats_payload, minute_value)
                dna = combined_metrics["avg_total_goals"]
                model_feature_columns = list(getattr(state.oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))
                xg_threshold_bonus = 0.0

                for market in prioritized_markets:
                    signal_key = get_signal_key(fixture_id, market)
                    if signal_key in stats["segnali_inviati"]:
                        scan_debug["pending_or_sent"] += 1
                        continue
                    if opened_primary_signal:
                        log_event("MARKET_ROUTER_SKIP", f"fixture_id={fixture_id} market={market} routed_to_primary=1 minute={minute_value} score={score}")
                        continue

                    titan_soft = evaluate_titan_soft_layer(stats_payload, market, minute_value, total_goals)
                    titan_pressure_score = float(titan_soft.get("score", 0.0) or 0.0)
                    titan_pressure_prob = predict_titan_pressure_prob(dna, minute_value, goals_home - goals_away, total_goals, stats_payload)
                    model_feature_values = {
                        "DNA": dna,
                        "Minute": minute_value,
                        "TotalGoalsAtOpen": total_goals,
                        "AvgTotalGoals": combined_metrics["avg_total_goals"],
                        "AvgHTGoals": combined_metrics["avg_ht_goals"],
                        "HomeAvgTotalGoals": combined_metrics["home_avg_total_goals"],
                        "AwayAvgTotalGoals": combined_metrics["away_avg_total_goals"],
                        "HomeAvgHTGoals": combined_metrics["home_avg_ht_goals"],
                        "AwayAvgHTGoals": combined_metrics["away_avg_ht_goals"],
                        "ShotsOnGoalAtOpen": shots_on_goal_at_open,
                        "TotalShotsAtOpen": total_shots_at_open,
                        "CornersAtOpen": corners_at_open,
                        "RedCardsAtOpen": red_cards_at_open,
                        "TitanPressureScore": titan_pressure_score,
                        "MarketOver05HT": 1.0 if market == MARKET_OVER05_HT else 0.0,
                        "MarketOver15HT": 1.0 if market == MARKET_OVER15_HT else 0.0,
                        "MarketNextGoal": 1.0 if market == MARKET_NEXT_GOAL else 0.0,
                        "ShotsInsideBoxAtOpen": shots_insidebox_at_open,
                        "GoalkeeperSavesAtOpen": goalkeeper_saves_at_open,
                        "XgRateAtOpen": xg_rate_at_open,
                    }
                    x_input = pd.DataFrame([[model_feature_values.get(column, 0.0) for column in model_feature_columns]], columns=model_feature_columns)
                    prob = state.oracle_brain.predict_proba(x_input)[0][1]
                    market_in_window = is_market_window(market, minute_value, total_goals)
                    ht_threshold_bonus = 0.0
                    if market == MARKET_OVER05_HT and isinstance(stats_payload, dict):
                        sib = float(stats_payload.get("shots_insidebox", 0.0) or 0.0)
                        gks = float(stats_payload.get("goalkeeper_saves", 0.0) or 0.0)
                        xgr = get_xg_rate(stats_payload, minute_value)
                        if sib >= 6 and gks >= 3:
                            ht_threshold_bonus = -0.06
                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " gks=" + str(gks) + " b=-0.06")
                        elif sib >= 4 and gks >= 2:
                            ht_threshold_bonus = -0.04
                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " gks=" + str(gks) + " b=-0.04")
                        elif sib >= 3 and xgr >= 0.025:
                            ht_threshold_bonus = -0.02
                            log_event("HT_PRESSURE_BONUS", "fid=" + str(fixture_id) + " sib=" + str(sib) + " xgr=" + str(xgr) + " b=-0.02")
                    effective_threshold = state.oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else ht_threshold_bonus)
                    if market_in_window and prob < effective_threshold:
                        scan_debug["candidate_failed"] += 1
                        clear_pending_signal_tracker(signal_key)
                        log_event("V2_THRESHOLD_SKIP", "fid=" + str(fixture_id) + " mkt=" + str(market) + " prob=" + str(round(prob,3)) + " thr=" + str(round(effective_threshold,2)))
                        continue
                    if not market_in_window:
                        clear_pending_signal_tracker(signal_key)
                        assessment = evaluate_prewindow_snapshot_candidate(market, minute_value, total_goals, prob, combined_metrics)
                        if not assessment:
                            scan_debug["market_window"] += 1
                            continue
                        shadow_only = True
                        log_event("PREWINDOW_CHECK", f"fixture_id={fixture_id} market={market} minute={minute_value} score={score} prob={prob:.2f} avg_ht={combined_metrics['avg_ht_goals']:.2f} avg_total={combined_metrics['avg_total_goals']:.2f} home_ht={combined_metrics['home_avg_ht_goals']:.2f} away_ht={combined_metrics['away_avg_ht_goals']:.2f}")
                    else:
                        shadow_only = False
                        assessment = evaluate_signal_candidate(market, minute_value, total_goals, prob, combined_metrics)
                        log_event("PRESSURE_CHECK", f"fixture_id={fixture_id} market={market} minute={minute_value} score={score} titan_prob={(titan_pressure_prob if titan_pressure_prob is not None else -1):.2f} titan_score={titan_soft.get('score', 0)} shots={shots_on_goal_at_open}/{total_shots_at_open} corners={corners_at_open}")
                        pressure_alert_reason = None
                        live_pressure_available = has_live_pressure_data(stats_payload)
                        if not live_pressure_available:
                            if market == MARKET_OVER05_HT and total_goals == 0 and prob >= 0.78 and combined_metrics["avg_ht_goals"] >= 0.92 and min(combined_metrics["home_avg_ht_goals"], combined_metrics["away_avg_ht_goals"]) >= 0.62:
                                pressure_alert_reason = f"risky early HT pressure alert | model {prob:.2f} | HT pace {combined_metrics['avg_ht_goals']:.2f} | high-risk profile"
                            elif market == MARKET_OVER15_HT and total_goals == 1 and prob >= 0.80 and combined_metrics["avg_ht_goals"] >= 1.08 and min(combined_metrics["home_avg_ht_goals"], combined_metrics["away_avg_ht_goals"]) >= 0.72:
                                pressure_alert_reason = f"risky early HT continuation alert | model {prob:.2f} | HT pace {combined_metrics['avg_ht_goals']:.2f} | high-risk profile"
                        if pressure_alert_reason is None and titan_pressure_prob is not None and titan_pressure_prob >= TITAN_PRESSURE_ALERT_THRESHOLD:
                            pressure_alert_reason = f"titan pressure alert {titan_pressure_prob:.2f}"
                        elif pressure_alert_reason is None and titan_soft.get("score", 0) >= 3:
                            pressure_alert_reason = titan_soft.get("label", "titan pressure alert")
                        if pressure_alert_reason:
                            assessment = {"tier": TIER_CAUTION, "reason": pressure_alert_reason}
                            log_event("SIGNAL_PRESSURE_ALERT", f"fixture_id={fixture_id} market={market} reason={pressure_alert_reason}")
                        else:
                            if market == MARKET_NEXT_GOAL:
                                # Filtro cecchino: score, minuto, total goals
                                ng_skip, ng_reason = should_skip_next_goal_by_context(minute_value, total_goals, score)
                                if ng_skip:
                                    scan_debug["candidate_failed"] += 1
                                    clear_pending_signal_tracker(signal_key)
                                    log_event("NG_CONTEXT_SKIP", f"fixture_id={fixture_id} minute={minute_value} score={score} reason={ng_reason}")
                                    continue
                                xg_rate = get_xg_rate(stats_payload, minute_value)
                                if xg_rate > 0.0 and xg_rate < 0.010 and minute_value >= 15:
                                    scan_debug["candidate_failed"] += 1
                                    clear_pending_signal_tracker(signal_key)
                                    log_event("NG_XG_SKIP", "fid=" + str(fixture_id) + " min=" + str(minute_value) + " xgr=" + str(xg_rate))
                                    continue
                                if xg_rate >= 0.030:
                                    xg_threshold_bonus = -0.05
                                    log_event("NG_XG_BONUS", "fid=" + str(fixture_id) + " xgr=" + str(xg_rate) + " b=-0.05")
                                elif xg_rate >= 0.025:
                                    xg_threshold_bonus = -0.03
                                    log_event("NG_XG_BONUS", "fid=" + str(fixture_id) + " xgr=" + str(xg_rate) + " b=-0.03")
                                pending_cycles = register_pending_signal_tracker(signal_key, minute_value, total_goals, prob)
                                assessment = evaluate_pending_next_goal_candidate(minute_value, total_goals, prob, combined_metrics, pending_cycles, titan_pressure_prob, titan_soft)
                                if assessment:
                                    log_event("SIGNAL_PENDING_PROMOTED", f"fixture_id={fixture_id} market={market} cycles={pending_cycles} tier={assessment['tier']} prob={prob:.2f}")
                            if not assessment:
                                assessment = evaluate_learning_candidate(market, minute_value, total_goals, prob, combined_metrics)
                            if not assessment:
                                assessment = evaluate_snapshot_candidate(market, minute_value, total_goals, prob, combined_metrics)
                            if not assessment:
                                scan_debug["candidate_failed"] += 1
                                continue
                            shadow_only = assessment.get("tier") == TIER_LEARNING
                    clear_pending_signal_tracker(signal_key)
                    tier = assessment["tier"]
                    reason = assessment["reason"]
                    minute_bucket = get_minute_bucket(minute_value)
                    live_odd = None
                    ev_at_open = None

                    if not shadow_only:
                        skip_signal, skip_reason = should_skip_by_live_performance(market, league_name, minute_bucket)
                        if skip_signal:
                            scan_debug["performance_skip"] += 1
                            log_event("SIGNAL_SKIPPED", f"market={market} league={league_name} minute_bucket={minute_bucket} reason={skip_reason}")
                            continue
                        stats_skip, stats_skip_reason = should_skip_by_live_stats(
                            fixture_id, market, minute_value, total_goals, headers, stats_payload=stats_payload
                        )
                        if stats_skip:
                            scan_debug["live_stats_skip"] += 1
                            if tier != TIER_CAUTION:
                                tier = TIER_CAUTION
                            reason = f"{reason} | live context caution: {stats_skip_reason}" if reason else f"live context caution: {stats_skip_reason}"
                            log_event("SIGNAL_DOWNGRADED", f"fixture_id={fixture_id} market={market} downgraded_to={tier} reason={stats_skip_reason}")
                        if titan_pressure_prob is not None and titan_pressure_prob >= TITAN_PROMOTION_THRESHOLD:
                            original_tier = tier
                            if tier == TIER_GAMBLING:
                                tier = TIER_CAUTION
                            elif tier == TIER_CAUTION:
                                tier = TIER_APPROVED
                            if tier != original_tier:
                                titan_reason = f"titan model prob {titan_pressure_prob:.2f}"
                                reason = f"{reason} | {titan_reason}" if reason else titan_reason
                                log_event("SIGNAL_PROMOTED", f"fixture_id={fixture_id} market={market} from={original_tier} to={tier} reason={titan_reason}")
                        if titan_soft.get("promote"):
                            original_tier = tier
                            if tier == TIER_GAMBLING:
                                tier = TIER_CAUTION
                            elif tier == TIER_CAUTION:
                                tier = TIER_APPROVED
                            if tier != original_tier:
                                titan_reason = titan_soft.get("label", "")
                                reason = f"{reason} | {titan_reason}" if reason and titan_reason else (titan_reason or reason)
                                log_event("SIGNAL_PROMOTED", f"fixture_id={fixture_id} market={market} from={original_tier} to={tier} reason={titan_reason}")

                        # EV gate: con la quota live disponibile si apre solo se il valore
                        # atteso supera il margine minimo. Senza quota, comportamento storico.
                        live_odd = fetch_live_market_odds(fixture_id, market, headers)
                        if live_odd is not None:
                            ev_at_open = round(prob * live_odd - 1.0, 4)
                            if EV_GATE_ENABLED and ev_at_open < EV_MIN_EDGE:
                                scan_debug["ev_gate_skip"] += 1
                                log_event("EV_GATE_SKIP", f"key={signal_key} market={market} prob={prob:.3f} odd={live_odd} ev={ev_at_open:+.3f} min={EV_MIN_EDGE}")
                                continue

                        with state_lock:
                            stats["segnali_inviati"].append(signal_key)
                        increment_analytics("signals_total")
                        increment_analytics("signals_by_tier", tier=tier)
                        increment_breakdown_counter("signals_by_market", market)
                        increment_breakdown_counter("signals_by_league", league_name)
                        increment_breakdown_counter("signals_by_minute_bucket", minute_bucket)
                        full_msg = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)
                        free_msg = format_free_teaser_message(tier, country, match_up, minute_value, score, market)
                        is_private_premium, private_premium_reason = is_premium_private_signal(
                            tier,
                            country,
                            league_name,
                            market,
                            minute_value,
                            dna,
                            prob,
                            reason,
                        )
                        private_premium_msg = ""
                        if is_private_premium:
                            private_premium_msg = format_premium_signal_message(
                                tier,
                                country,
                                league_name,
                                match_up,
                                dna,
                                prob,
                                minute_value,
                                score,
                                market,
                                reason,
                                live_odd=live_odd,
                            )
                        deliveries = record_signal_delivery(signal_key, tier, full_msg, free_msg, private_premium_msg)
                        log_event(
                            "PRIVATE_PREMIUM_SIGNAL" if is_private_premium else "PRIVATE_PREMIUM_SKIP",
                            f"key={signal_key} market={market} league={league_name} country={country} minute={minute_value} reason={private_premium_reason}",
                        )
                        scan_debug["signals_opened"] += 1
                        opened_primary_signal = True
                    else:
                        deliveries = []
                        full_msg = ""
                        scan_debug["shadow_opened"] += 1
                        log_event("SHADOW_OPEN", f"key={signal_key} market={market} match={match_up} minute={minute_value} score={score} prob={prob:.3f}")

                    with state_lock:
                        stats["monitor_risultati"][signal_key] = {
                            "status": "pending",
                            "start_score": score,
                            "tier": tier,
                            "market": market,
                            "league_name": league_name,
                            "minute_bucket": minute_bucket,
                            "match_up": match_up,
                            "fixture_id": fixture_id,
                            "team_ref": home_db,
                            "original_text": full_msg,
                            "delivery_targets": deliveries,
                            "shadow_only": shadow_only,
                            "total_goals_at_open": total_goals,
                        }
                    append_live_training_row({
                        "SignalKey": signal_key,
                        "OpenTimeUTC": now_utc().isoformat(),
                        "FixtureId": fixture_id,
                        "Country": country,
                        "LeagueName": league_name,
                        "FilterMode": get_filter_label(),
                        "MarketMode": get_market_label(),
                        "Market": market,
                        "Minute": minute_value,
                        "MinuteBucket": minute_bucket,
                        "StartScore": score,
                        "TotalGoalsAtOpen": total_goals,
                        "DNA": dna,
                        "Prob": round(prob, 4),
                        "Tier": tier,
                        "Reason": reason,
                        "AvgTotalGoals": combined_metrics["avg_total_goals"],
                        "AvgHTGoals": combined_metrics["avg_ht_goals"],
                        "HomeAvgTotalGoals": combined_metrics["home_avg_total_goals"],
                        "AwayAvgTotalGoals": combined_metrics["away_avg_total_goals"],
                        "HomeAvgHTGoals": combined_metrics["home_avg_ht_goals"],
                        "AwayAvgHTGoals": combined_metrics["away_avg_ht_goals"],
                        "ShotsOnGoalAtOpen": shots_on_goal_at_open,
                        "TotalShotsAtOpen": total_shots_at_open,
                        "CornersAtOpen": corners_at_open,
                        "RedCardsAtOpen": red_cards_at_open,
                        "TitanPressureScore": titan_pressure_score,
                        "ShotsInsideBoxAtOpen": shots_insidebox_at_open,
                        "GoalkeeperSavesAtOpen": goalkeeper_saves_at_open,
                        "XgRateAtOpen": xg_rate_at_open,
                        "OddsAtOpen": live_odd if live_odd is not None else "",
                        "EVAtOpen": ev_at_open if ev_at_open is not None else "",
                        "Status": "pending",
                        "Outcome": "",
                        "CloseScore": "",
                        "SettledTimeUTC": "",
                    })
                    if not shadow_only:
                        log_event("SIGNAL_OPEN", f"key={signal_key} tier={tier} market={market} match={match_up} minute={minute_value} score={score}")
                        salva_dati_web(
                            {
                                "SignalKey": signal_key,
                                "Ora": datetime.now().strftime("%H:%M"),
                                "Match": match_up,
                                "Campionato": league_name,
                                "Filtro": get_filter_label(),
                                "Mode": get_market_label(),
                                "Market": market,
                                "DNA": dna,
                                "Tier": tier,
                                "Prob": f"{prob * 100:.1f}%",
                                "Esito": "PENDING",
                            }
                        )
            log_event("RADAR_SUMMARY", (
                f"fixtures={scan_debug['fixtures_total']} "
                f"league_filtered={scan_debug['league_filtered']} "
                f"league_filtered_base={scan_debug['league_filtered_base']} "
                f"league_filtered_coverage={scan_debug['league_filtered_coverage']} "
                f"team_not_found={scan_debug['team_not_found']} "
                f"no_metrics={scan_debug['no_metrics']} "
                f"pending_or_sent={scan_debug['pending_or_sent']} "
                f"market_window={scan_debug['market_window']} "
                f"no_model={scan_debug['no_model']} "
                f"candidate_failed={scan_debug['candidate_failed']} "
                f"performance_skip={scan_debug['performance_skip']} "
                f"live_stats_skip={scan_debug['live_stats_skip']} "
                f"signals_opened={scan_debug['signals_opened']} "
                f"shadow_opened={scan_debug['shadow_opened']} "
                f"ev_gate_skip={scan_debug['ev_gate_skip']} "
            ))
            settle_missing_live_signals(seen_fixture_ids, headers)
            prune_settled_signals()
            clean_sent_signals()
            salva_dati_web()
            time.sleep(40)
        except Exception as exc:
            print(f"Loop error: {exc}")
            log_event("RADAR_ERROR", str(exc))
            time.sleep(15)
