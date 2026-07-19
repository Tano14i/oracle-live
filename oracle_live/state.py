import json
import logging
import os
import threading
from datetime import datetime, timezone

import pandas as pd
import telebot

from config import (
    API_KEY,
    CHANNEL_ID,
    CHAT_ID,
    LIVE_TRAINING_DATA_PATH,
    LOG_FILE_PATH,
    MEMBERS_DB_PATH,
    TOKEN_LIVE,
    WEB_DATA_PATH,
)
from vip_membership import VipMembershipStore

from oracle_live.constants import (
    DEFAULT_FILTER_MODE,
    DEFAULT_MARKET_MODE,
    LIVE_TRAINING_COLUMNS,
    TIER_APPROVED,
    TIER_CAUTION,
    TIER_GAMBLING,
    V2_DEFAULT_THRESHOLD,
)

required_settings = {
    "TOKEN_LIVE": TOKEN_LIVE,
    "CHAT_ID": CHAT_ID,
    "CHANNEL_ID": CHANNEL_ID,
    "API_KEY": API_KEY,
}


missing_settings = [name for name, value in required_settings.items() if not value]
if missing_settings:
    raise RuntimeError(
        f"Configurazione mancante: {', '.join(missing_settings)}. Crea il file .env partendo da .env.example"
    )

bot = telebot.TeleBot(TOKEN_LIVE)
running = False
shutdown_requested = False
df_matches = None
nomi_unici_db = []
oracle_brain = None
titan_pressure_brain = None
oracle_v2_threshold = V2_DEFAULT_THRESHOLD
membership_store = VipMembershipStore(MEMBERS_DB_PATH)
last_vip_sync_ts = 0.0
pending_free_timers = {}
state_lock = threading.RLock()
analytics_lock = state_lock
live_training_lock = threading.RLock()
missing_team_queue_lock = threading.RLock()
prematch_backend_lock = threading.Lock()
retrain_running = False
backfill_running = False
prematch_running = False
dashboard_process = None
ngrok_process = None
last_retrain_result = "Nessun retrain eseguito in questa sessione."
fixture_stats_cache = {}
missing_team_queue = {}
logger = logging.getLogger("oracle_live")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)sZ | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(file_handler)
logger.propagate = False


team_match_cache = {}
normalized_team_lookup = {}
team_not_found_counts = {}


def log_event(event: str, message: str) -> None:
    try:
        logger.info(f"{event} | {message}")
    except Exception:
        pass


def default_analytics(date_key: str):
    return {
        "date_utc": date_key,
        "signals_total": 0,
        "signals_by_tier": {TIER_APPROVED: 0, TIER_CAUTION: 0, TIER_GAMBLING: 0},
        "signals_by_market": {},
        "signals_by_league": {},
        "signals_by_minute_bucket": {},
        "settled_win": 0,
        "settled_loss": 0,
        "settled_by_market": {},
        "settled_by_league": {},
        "settled_by_minute_bucket": {},
        "free_teasers_scheduled": 0,
        "free_teasers_sent": 0,
        "vip_payments_count": 0,
        "vip_revenue_xtr": 0,
        "renewal_reminders_sent": 0,
    }


def default_prematch_last_report() -> dict:
    return {"date": "", "chat_id": "", "fixture_ids": []}


def default_prematch_watch_state() -> dict:
    return {
        "active": False,
        "date": "",
        "chat_id": "",
        "fixture_ids": [],
        "interval_seconds": 300,
        "last_sent_utc": "",
        "baseline_ready": False,
        "last_snapshot": {},
    }


stats = {
    TIER_APPROVED: {"v": 0, "p": 0},
    TIER_CAUTION: {"v": 0, "p": 0},
    TIER_GAMBLING: {"v": 0, "p": 0},
    "matches_analyzed": 0,
    "ai_scartati": 0,
    "total_profit": 0.0,
    "profit_history": [{"time": datetime.now().strftime("%H:%M"), "profit": 0.0}],
    "recent_signals": [],
    "rolling_settled": [],
    "monitor_risultati": {},
    "pending_signal_tracker": {},
    "segnali_inviati": [],
    "filter_mode": DEFAULT_FILTER_MODE,
    "market_mode": DEFAULT_MARKET_MODE,
    "free_teaser_counter": 0,
    "daily_analytics": default_analytics(datetime.now(timezone.utc).date().isoformat()),
    "last_recap_date_utc": "",
    "last_performance_report_total": 0,
    "last_retrain_total_rows": 0,
    "last_retrain_settled_rows": 0,
    "last_retrain_full_feature_settled": 0,
    "recap_delivery": {"date_utc": "", "admin": False, "vip": False, "free": False},
    "coverage_guard": {"miss_counts": {}, "blocked_until": {}},
    "prematch_last_report": default_prematch_last_report(),
    "prematch_watch": default_prematch_watch_state(),
}

def now_utc() -> datetime:
    return datetime.now(timezone.utc)



def current_date_key() -> str:
    return now_utc().date().isoformat()


def default_recap_delivery(date_key: str):
    return {"date_utc": date_key, "admin": False, "vip": False, "free": False}


def ensure_daily_analytics() -> None:
    current_key = current_date_key()
    analytics = stats.get("daily_analytics") or default_analytics(current_key)
    recap_delivery = stats.get("recap_delivery") or default_recap_delivery(current_key)
    changed = False
    if analytics.get("date_utc") != current_key:
        stats["daily_analytics"] = default_analytics(current_key)
        changed = True
    if recap_delivery.get("date_utc") != current_key:
        stats["recap_delivery"] = default_recap_delivery(current_key)
        stats["last_recap_date_utc"] = ""
        changed = True
    if changed:
        salva_dati_web()


def increment_analytics(field: str, amount: int = 1, tier: str = None) -> None:
    with analytics_lock:
        ensure_daily_analytics()
        analytics = stats["daily_analytics"]
        if field == "signals_by_tier" and tier:
            analytics["signals_by_tier"][tier] = analytics["signals_by_tier"].get(tier, 0) + amount
        else:
            analytics[field] = analytics.get(field, 0) + amount
def increment_breakdown_counter(field: str, key: str, amount: int = 1) -> None:
    if not key:
        return
    with analytics_lock:
        ensure_daily_analytics()
        analytics = stats["daily_analytics"]
        bucket = analytics.get(field)
        if not isinstance(bucket, dict):
            bucket = {}
            analytics[field] = bucket
        bucket[key] = bucket.get(key, 0) + amount


def increment_market_settlement(market: str, outcome: str) -> None:
    if not market or outcome not in {"WIN", "LOSS"}:
        return
    with analytics_lock:
        ensure_daily_analytics()
        analytics = stats["daily_analytics"]
        settled = analytics.get("settled_by_market")
        if not isinstance(settled, dict):
            settled = {}
            analytics["settled_by_market"] = settled
        market_stats = settled.get(market)
        if not isinstance(market_stats, dict):
            market_stats = {"WIN": 0, "LOSS": 0}
            settled[market] = market_stats
        market_stats[outcome] = market_stats.get(outcome, 0) + 1


def increment_settled_breakdown(field: str, key: str, outcome: str) -> None:
    if not key or outcome not in {"WIN", "LOSS"}:
        return
    with analytics_lock:
        ensure_daily_analytics()
        analytics = stats["daily_analytics"]
        settled = analytics.get(field)
        if not isinstance(settled, dict):
            settled = {}
            analytics[field] = settled
        item_stats = settled.get(key)
        if not isinstance(item_stats, dict):
            item_stats = {"WIN": 0, "LOSS": 0}
            settled[key] = item_stats
        item_stats[outcome] = item_stats.get(outcome, 0) + 1


def get_settled_bucket_stats(values: dict, key: str):
    if not isinstance(values, dict):
        return {"WIN": 0, "LOSS": 0}
    item = values.get(key)
    if not isinstance(item, dict):
        return {"WIN": 0, "LOSS": 0}
    return {"WIN": int(item.get("WIN", 0)), "LOSS": int(item.get("LOSS", 0))}


def append_rolling_settled(market: str, league_name: str, minute_bucket: str, outcome: str) -> None:
    if outcome not in {"WIN", "LOSS"}:
        return
    with state_lock:
        rolling = stats.get("rolling_settled")
        if not isinstance(rolling, list):
            rolling = []
            stats["rolling_settled"] = rolling
        rolling.append(
            {
                "market": market or "",
                "league_name": league_name or "",
                "minute_bucket": minute_bucket or "",
                "outcome": outcome,
                "time": now_utc().isoformat(),
            }
        )
        if len(rolling) > 300:
            stats["rolling_settled"] = rolling[-300:]


def get_rolling_bucket_stats(field: str, key: str, window: int) -> dict:
    rolling = stats.get("rolling_settled")
    if not key or not isinstance(rolling, list) or not rolling:
        return {"WIN": 0, "LOSS": 0}

    wins = 0
    losses = 0
    checked = 0
    for item in reversed(rolling):
        if not isinstance(item, dict):
            continue
        if item.get(field) != key:
            continue
        outcome = item.get("outcome")
        if outcome == "WIN":
            wins += 1
        elif outcome == "LOSS":
            losses += 1
        checked += 1
        if checked >= window:
            break
    return {"WIN": wins, "LOSS": losses}


def get_recent_rolling_stats(window: int) -> dict:
    rolling = stats.get("rolling_settled")
    if not isinstance(rolling, list) or not rolling:
        return {"WIN": 0, "LOSS": 0}
    selected = []
    for item in reversed(rolling):
        if not isinstance(item, dict):
            continue
        outcome = item.get("outcome")
        if outcome not in {"WIN", "LOSS"}:
            continue
        selected.append(outcome)
        if len(selected) >= window:
            break
    wins = sum(1 for item in selected if item == "WIN")
    losses = sum(1 for item in selected if item == "LOSS")
    return {"WIN": wins, "LOSS": losses}


def salva_dati_web(nuovo_segnale=None, nuovo_profitto=None) -> None:
    with state_lock:
        if nuovo_segnale:
            stats["recent_signals"].insert(0, nuovo_segnale)
            stats["recent_signals"] = stats["recent_signals"][:20]
        if nuovo_profitto is not None:
            stats["total_profit"] = round(stats["total_profit"] + nuovo_profitto, 2)
            stats["profit_history"].append({"time": datetime.now().strftime("%H:%M"), "profit": stats["total_profit"]})

        with open(WEB_DATA_PATH, "w", encoding="utf-8") as handle:
            json.dump(stats, handle, indent=4)


def ensure_live_training_dataset() -> None:
    with live_training_lock:
        if os.path.exists(LIVE_TRAINING_DATA_PATH):
            try:
                df = pd.read_csv(LIVE_TRAINING_DATA_PATH)
            except Exception:
                df = pd.DataFrame()
            missing_columns = [col for col in LIVE_TRAINING_COLUMNS if col not in df.columns]
            if missing_columns:
                for column in missing_columns:
                    df[column] = pd.NA
                df = df[LIVE_TRAINING_COLUMNS]
                df.to_csv(LIVE_TRAINING_DATA_PATH, index=False)
            return
        df = pd.DataFrame(columns=LIVE_TRAINING_COLUMNS)
        df.to_csv(LIVE_TRAINING_DATA_PATH, index=False)


def append_live_training_row(row: dict) -> None:
    with live_training_lock:
        ensure_live_training_dataset()
        frame = pd.DataFrame([[row.get(col, "") for col in LIVE_TRAINING_COLUMNS]], columns=LIVE_TRAINING_COLUMNS)
        frame.to_csv(LIVE_TRAINING_DATA_PATH, mode="a", header=False, index=False)


def update_live_training_outcome(signal_key: str, outcome: str, close_score: str) -> None:
    with live_training_lock:
        ensure_live_training_dataset()
        try:
            df = pd.read_csv(
                LIVE_TRAINING_DATA_PATH,
                dtype={"CloseScore": "string", "SettledTimeUTC": "string"},
            )
        except Exception as exc:
            print(f"Live training dataset read error: {exc}")
            return
        if "SignalKey" not in df.columns or df.empty:
            return
        mask = df["SignalKey"].astype(str) == str(signal_key)
        if not mask.any():
            return
        if "CloseScore" in df.columns:
            df["CloseScore"] = df["CloseScore"].astype("string")
        if "SettledTimeUTC" in df.columns:
            df["SettledTimeUTC"] = df["SettledTimeUTC"].astype("string")
        df.loc[mask, "Status"] = "settled"
        df.loc[mask, "Outcome"] = outcome
        df.loc[mask, "CloseScore"] = close_score
        df.loc[mask, "SettledTimeUTC"] = now_utc().isoformat()
        df.to_csv(LIVE_TRAINING_DATA_PATH, index=False)


def get_total_settled_count() -> int:
    return sum(
        int(stats.get(tier, {}).get("v", 0)) + int(stats.get(tier, {}).get("p", 0))
        for tier in [TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING]
    )
