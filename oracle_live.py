import html
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import socket
import threading
import time
import unicodedata
import atexit
import sys as _sys
if _sys.platform == "win32":
    import msvcrt as _lock_mod
    _LOCK_PLATFORM = "win32"
else:
    import fcntl as _lock_mod
    _LOCK_PLATFORM = "posix"
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import joblib
import pandas as pd
import requests
import telebot
from telebot import types

from config import (
    API_KEY,
    AUTO_RETRAIN_EVERY_N_SETTLED,
    CHANNEL_ID,
    CHAT_ID,
    CSV_PATH,
    FREE_DELAY_SECONDS,
    FREE_EVERY_N_APPROVED,
    LOG_FILE_PATH,
    LIVE_TRAINING_DATA_PATH,
    MEMBERS_DB_PATH,
    MISSING_TEAMS_QUEUE_PATH,
    MODEL_PATH,
    QUOTA,
    PERFORMANCE_STAKE_EXAMPLE,
    PERFORMANCE_STARTING_BANKROLL,
    REPORT_EVERY_N_SETTLED,
    REPORT_MIN_SETTLED,
    RECAP_HOUR_UTC,
    RECAP_MINUTE_UTC,
    RENEWAL_REMINDER_DAYS,
    STAKE,
    TOKEN_LIVE,
    VIP_CHANNEL_ID,
    VIP_DURATION_DAYS,
    VIP_PRICE_XTR,
    VIP_SUPPORT_CONTACT,
    WEB_DATA_PATH,
)
from vip_membership import VipMembershipStore
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from oracle_prematch.bot_service import collect_prematch_snapshots, run_prematch_bot_scan
from oracle_prematch.settings import (
    PREMATCH_AUTO_COLLECT_ENABLED,
    PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS,
    PREMATCH_AUTO_COLLECT_PAGE_LIMIT,
)

from trainer import (
    CANDIDATE_MODEL_NAME,
    DATA_FILE as TRAINER_DATA_FILE,
    FEATURE_COLUMNS as TRAINER_FEATURE_COLUMNS,
    MIN_CANDIDATE_ROWS,
    MIN_PRODUCTION_ROWS,
    MODEL_NAME as TRAINER_MODEL_NAME,
    train_oracle,
)

required_settings = {
    "TOKEN_LIVE": TOKEN_LIVE,
    "CHAT_ID": CHAT_ID,
    "CHANNEL_ID": CHANNEL_ID,
    "API_KEY": API_KEY,
}
LIVE_TRAINING_COLUMNS = [
    "SignalKey",
    "OpenTimeUTC",
    "FixtureId",
    "Country",
    "LeagueName",
    "FilterMode",
    "MarketMode",
    "Market",
    "Minute",
    "MinuteBucket",
    "StartScore",
    "TotalGoalsAtOpen",
    "DNA",
    "Prob",
    "Tier",
    "Reason",
    "AvgTotalGoals",
    "AvgHTGoals",
    "HomeAvgTotalGoals",
    "AwayAvgTotalGoals",
    "HomeAvgHTGoals",
    "AwayAvgHTGoals",
    "ShotsOnGoalAtOpen",
    "TotalShotsAtOpen",
    "CornersAtOpen",
    "RedCardsAtOpen",
    "TitanPressureScore",
    "Status",
    "Outcome",
    "CloseScore",
    "SettledTimeUTC",
]
TITAN_PRESSURE_MODEL_PATH = os.path.join(BASE_DIR, "titan_pressure_model.pkl")

# --- Modello v2 con soglia ottimale ---
V2_MODEL_PATH = os.path.join(BASE_DIR, "oracle_brain_v2.pkl")
V2_THRESHOLD_PATH = os.path.join(BASE_DIR, "oracle_brain_v2_threshold.txt")
V2_DEFAULT_THRESHOLD = 0.71
TITAN_PRESSURE_FEATURE_COLUMNS = [
    "DNAxG",
    "Minute",
    "ScoreDiff",
    "TotalGoalsAtSignal",
    "TotalShots",
    "ShotsOnGoal",
    "DangerousAttacks",
    "Corners",
    "PossessionDiff",
    "RedCardsHome",
    "RedCardsAway",
]
TITAN_PROMOTION_THRESHOLD = 0.64
TITAN_PRESSURE_ALERT_THRESHOLD = 0.70
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
PROCESS_LOCK_PATH = os.path.join(BASE_DIR, 'oracle_live.lock')
process_lock_handle = None

TIER_APPROVED = "APPROVED"
TIER_CAUTION = "CAUTION"
TIER_LEARNING = "LEARNING"
TIER_GAMBLING = "GAMBLING"
MARKET_OVER05_HT = "OVER 0.5 HT"
MARKET_OVER15_HT = "OVER 1.5 HT"
MARKET_NEXT_GOAL = "NEXT GOAL LIVE"
SEPARATOR = "----------------------------"
VIP_PLAN_CODE = "vip_monthly"
VIP_PLAN_NAME = "Oracle VIP Monthly"
VIP_SYNC_INTERVAL_SECONDS = 600
FREE_ALLOWED_TIERS = {TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING}
AUTO_MARKET_SWITCH_ENABLED = True
PREMIUM_ALLOWED_MARKETS = {MARKET_NEXT_GOAL}
PREMIUM_ALLOWED_LEAGUES = {
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
PREMIUM_ALLOWED_COUNTRIES = {
    "England",
    "Germany",
    "Spain",
    "Portugal",
    "Italy",
    "Poland",
}
PREMIUM_BLOCKED_LEAGUES = {
    "Serie A",
    "Eerste Divisie",
    "National Division",
    "Super League 1",
    "Liga II",
    "Bundesliga",
    "Championship",
    "Liga MX",
}
PREMIUM_BLOCKED_COUNTRIES = {
    "Brazil",
    "Greece",
    "Romania",
}
LEGACY_TIER_KEYS = {
    TIER_APPROVED: "ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¡ APPROVED",
    TIER_CAUTION: "ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¹ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â  CAUTION",
    TIER_GAMBLING: "ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â°ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¦ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¸ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¥ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â° GAMBLING",
}
TIER_EMOJI = {
    TIER_APPROVED: "\U0001F947",
    TIER_CAUTION: "\u26A0",
    TIER_GAMBLING: "\U0001F3AF",
}

MARKET_PRESETS = {
    "HT_05": {"label": MARKET_OVER05_HT, "markets": [MARKET_OVER05_HT]},
    "HT_15": {"label": MARKET_OVER15_HT, "markets": [MARKET_OVER15_HT]},
    "HT_BOTH": {"label": "OVER 0.5 HT + OVER 1.5 HT", "markets": [MARKET_OVER05_HT, MARKET_OVER15_HT]},
    "NEXT_GOAL": {"label": MARKET_NEXT_GOAL, "markets": [MARKET_NEXT_GOAL]},
    "HT_NEXT": {"label": "HT + NEXT GOAL LIVE", "markets": [MARKET_OVER05_HT, MARKET_OVER15_HT, MARKET_NEXT_GOAL]},
}
DEFAULT_MARKET_MODE = "HT_BOTH"

TOP10_COUNTRIES = {
    "SPAIN",
    "ITALY",
    "NETHERLANDS",
    "FRANCE",
    "GERMANY",
    "ENGLAND",
    "BELGIUM",
    "POLAND",
    "PORTUGAL",
    "TURKEY",
}

FILTER_PRESETS = {
    "TOP10": {"label": "Top 10 Europe", "top10_only": True, "ab_only": False, "allow_youth": False},
    "SERIE_AB": {"label": "Serie A/B Top 10", "top10_only": True, "ab_only": True, "allow_youth": False},
    "GLOBAL_U23": {"label": "Global ALL-IN", "top10_only": False, "ab_only": False, "allow_youth": True},
}
DEFAULT_FILTER_MODE = "TOP10"
COVERAGE_GUARD_ENABLED = False
COVERAGE_GUARD_THRESHOLD = 14
COVERAGE_GUARD_HOURS = 1
MANUAL_TEAM_ALIASES = {
    "lokerentemse": ["sporting lokeren"],
    "vikingur ii": ["vikingur reykjavik"],
    "vikingur b": ["vikingur reykjavik"],
    "olympic el qanah": ["al qanah"],
    "pdrm": ["pdrm"],
    "highbury": ["highbury"],
    "cape town city": ["cape town city"],
    "hrvatski dragovoljac": ["hrvatski dragovoljac"],
    "gornik zabrze ii": ["gornik zabrze"],
}
YOUTH_EXCLUDED = ["U16", "U17", "U18", "U19", "U20", "U21", "U22", "U23"]
NON_LEAGUE_EXCLUDED = [
    "AMATEUR",
    "FRIENDLY",
    "CUP",
    "COPA",
    "COPPA",
    "COUPE",
    "POKAL",
    "TROPHY",
    "SUPER CUP",
    "SUPERCUP",
    "PLAY OFF",
    "PLAY-OFF",
    "PLAYOFF",
]
SERIE_AB_PATTERNS = {
    "SPAIN": ["la liga", "laliga", "segunda division"],
    "ITALY": ["serie a", "serie b"],
    "NETHERLANDS": ["eredivisie", "eerste divisie"],
    "FRANCE": ["ligue 1", "ligue 2"],
    "GERMANY": ["bundesliga", "2 bundesliga"],
    "ENGLAND": ["premier league", "championship"],
    "BELGIUM": ["jupiler pro league", "challenger pro league", "first division a", "first division b"],
    "POLAND": ["ekstraklasa", "i liga", "1 liga"],
    "PORTUGAL": ["primeira liga", "liga portugal", "liga portugal 2", "segunda liga"],
    "TURKEY": ["super lig", "1 lig", "tff 1 lig"],
}
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


def summarize_wr_bucket(bucket: dict) -> str:
    wins = int((bucket or {}).get("WIN", 0))
    losses = int((bucket or {}).get("LOSS", 0))
    total = wins + losses
    if total <= 0:
        return "n/a"
    win_rate = wins / total * 100
    return f"{wins}W-{losses}L ({win_rate:.0f}%)"


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


def format_rolling_overview() -> str:
    parts = []
    for window in (20, 50, 100):
        parts.append(f"L{window}: {summarize_wr_bucket(get_recent_rolling_stats(window))}")
    return " | ".join(parts)


def format_market_rolling_overview() -> str:
    parts = []
    for market_name in get_active_markets():
        parts.append(f"{market_name}: {summarize_wr_bucket(get_rolling_bucket_stats('market', market_name, 20))}")
    return " | ".join(parts) if parts else "n/a"
def get_minute_bucket(minute_value: int) -> str:
    if minute_value <= 20:
        return "15-20"
    if minute_value <= 25:
        return "21-25"
    if minute_value <= 30:
        return "26-30"
    if minute_value <= 35:
        return "31-35"
    return "36-44"


def format_top_counts(values: dict, limit: int = 3) -> str:
    if not isinstance(values, dict) or not values:
        return "n/a"
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return " | ".join(f"{key}: {value}" for key, value in ordered)


def format_market_results(values: dict, limit: int = 5) -> str:
    if not isinstance(values, dict) or not values:
        return "n/a"

    rows = []
    ordered = sorted(
        values.items(),
        key=lambda item: (-(item[1].get("WIN", 0) + item[1].get("LOSS", 0)), item[0]),
    )[:limit]
    for market, market_stats in ordered:
        wins = market_stats.get("WIN", 0)
        losses = market_stats.get("LOSS", 0)
        rows.append(f"{market}: {wins}W/{losses}L")
    return " | ".join(rows)


def send_html_message_safe(chat_id, text: str, max_len: int = 3500) -> None:
    text = str(text or "")
    try:
        if len(text) <= max_len:
            bot.send_message(chat_id, text, parse_mode="HTML")
            return

        chunks = []
        current = ""
        for line in text.splitlines(True):
            if len(current) + len(line) > max_len and current:
                chunks.append(current)
                current = line
            else:
                current += line
        if current:
            chunks.append(current)

        for chunk in chunks[:4]:
            bot.send_message(chat_id, chunk, parse_mode="HTML")
    except Exception as exc:
        log_event("SEND_SAFE_FAIL", f"chat_id={chat_id} error={exc}")
        fallback = escape_html(text[:1500])
        bot.send_message(chat_id, f"<b>Reduced message</b>\n\n<code>{fallback}</code>", parse_mode="HTML")

def normalizza_testo(value: str) -> str:
    value = str(value or "").lower()
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", value).strip()


def normalizza_squadra(value: str) -> str:
    value = str(value or "").lower().replace("b team", "").replace("ii", "")
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", "", value).strip()


def escape_html(value: str) -> str:
    return html.escape(str(value or ""))


def extract_requested_date(message_text: str) -> str | None:
    parts = str(message_text or "").strip().split()
    if len(parts) < 2:
        return None
    candidate = parts[1].strip()
    try:
        return datetime.fromisoformat(candidate).date().isoformat()
    except ValueError:
        return None


def format_prematch_reason(outcome) -> str:
    metrics = outcome.metrics or {}
    timing = metrics.get("hours_to_kickoff")
    timing_label = "kickoff soon"
    if isinstance(timing, (int, float)):
        if timing > 0:
            timing_label = f"kickoff in {timing:.1f}h"
        else:
            timing_label = "kickoff very close"
    parts = [
        f"drop {outcome.largest_drop_pct:.1f}% on {outcome.leading_market}",
        f"fastest step {metrics.get('biggest_step_drop_pct', 0.0):.1f}%",
        f"bookmakers avg {outcome.bookmaker_count_avg:.1f}",
        timing_label,
    ]
    context_flags = [flag for flag in (outcome.flags or []) if flag]
    if context_flags:
        parts.append("context: " + ", ".join(context_flags[:4]))
    return " | ".join(parts)


def format_prematch_market_move(outcome) -> str:
    market_label = str(outcome.leading_market or "").strip().upper()
    drop_label = f"-{outcome.largest_drop_pct:.1f}%"
    if market_label == "1":
        return f"quota casa in calo ({drop_label})"
    if market_label == "2":
        return f"quota ospite in calo ({drop_label})"
    if market_label == "X":
        return f"quota pareggio in calo ({drop_label})"
    if market_label == "O2.5":
        return f"Over 2.5 in calo ({drop_label})"
    if market_label == "U2.5":
        return f"Under 2.5 in calo ({drop_label})"
    return f"movimento su {market_label} ({drop_label})"


def format_prematch_action_label(outcome) -> str:
    hours_to_kickoff = (outcome.metrics or {}).get("hours_to_kickoff")
    if outcome.status == "WATCH LIVE":
        return "CHECK ORA"
    if outcome.status == "MANUAL REVIEW":
        if isinstance(hours_to_kickoff, (int, float)):
            if hours_to_kickoff <= 0.5:
                return "CHECK ORA"
            if hours_to_kickoff <= 2.0:
                return "CHECK fra 10-15 minuti"
        return "CHECK PIU TARDI"
    return "NO BET per ora"


def format_prematch_bet_type(outcome) -> str:
    market_label = str(outcome.leading_market or "").strip().upper()
    if market_label == "1":
        return "1X (segnale base: 1)"
    if market_label == "2":
        return "X2 (segnale base: 2)"
    if market_label == "X":
        return "Pareggio"
    if market_label == "O2.5":
        return "Over 2.5 gol"
    if market_label == "U2.5":
        return "Under 2.5 gol"
    return market_label or "-"


def format_prematch_today_report(result) -> str:
    summary = result.summary
    header = (
        "<b>PARTITE SOSPETTE PRE-MATCH</b>\n\n"
        f"<b>Data:</b> {escape_html(result.date_value)}\n"
        f"<b>Partite analizzabili:</b> {summary.total_fixtures}\n"
        f"<b>Partite sospette:</b> {summary.flagged_total}"
    )
    if result.fixtures_seen == 0:
        return header + "\n\nNessuna partita prematch trovata per questa data."
    if summary.total_fixtures == 0:
        return (
            header
            + "\n\nPrimo snapshot salvato. Richiedi di nuovo tra qualche minuto cosi posso confrontare i movimenti quota."
        )
    if not summary.outcomes:
        return header + "\n\nNessuna partita sopra soglia in questo momento."

    blocks = [header, ""]
    for index, outcome in enumerate(summary.outcomes, start=1):
        location_line = escape_html(outcome.country or "-")
        if outcome.league:
            location_line = f"{location_line} | {escape_html(outcome.league)}"
        blocks.append(
            f"<b>{index}. {escape_html(outcome.home_team)} vs {escape_html(outcome.away_team)}</b>\n"
            f"{location_line}\n"
            f"Movimento mercato: {escape_html(format_prematch_market_move(outcome))}\n"
            f"Azione: <b>{escape_html(format_prematch_action_label(outcome))}</b>\n"
            f"Tipo di bet: <b>{escape_html(format_prematch_bet_type(outcome))}</b>"
        )
        blocks.append("")
    return "\n".join(blocks).strip()


def format_prematch_watch_update(result, watched_fixture_ids: list[str]) -> str:
    watched = [outcome for outcome in result.summary.outcomes if outcome.fixture_id in set(watched_fixture_ids or [])]
    header = (
        "<b>UPDATE PRE-MATCH WATCH</b>\n\n"
        f"<b>Data:</b> {escape_html(result.date_value)}\n"
        f"<b>Match monitorati:</b> {len(watched_fixture_ids or [])}\n"
        f"<b>Ancora sopra soglia:</b> {len(watched)}"
    )
    if not watched:
        return header + "\n\nNessuno dei match monitorati e sopra soglia adesso."

    blocks = [header, ""]
    for index, outcome in enumerate(watched, start=1):
        blocks.append(
            f"<b>{index}. {escape_html(outcome.home_team)} vs {escape_html(outcome.away_team)}</b>\n"
            f"Movimento mercato: {escape_html(format_prematch_market_move(outcome))}\n"
            f"Azione: <b>{escape_html(format_prematch_action_label(outcome))}</b>\n"
            f"Tipo di bet: <b>{escape_html(format_prematch_bet_type(outcome))}</b>"
        )
        blocks.append("")
    return "\n".join(blocks).strip()


def build_prematch_watch_snapshot(result, watched_fixture_ids: list[str]) -> dict:
    watched_ids = set(watched_fixture_ids or [])
    snapshot = {}
    for outcome in result.summary.outcomes:
        if outcome.fixture_id not in watched_ids:
            continue
        snapshot[outcome.fixture_id] = {
            "fixture_id": outcome.fixture_id,
            "match": f"{outcome.home_team} vs {outcome.away_team}",
            "market_move": format_prematch_market_move(outcome),
            "action": format_prematch_action_label(outcome),
            "bet_type": format_prematch_bet_type(outcome),
            "status": outcome.status,
            "risk_score": int(outcome.risk_score),
            "largest_drop_pct": float(outcome.largest_drop_pct),
        }
    return snapshot


def format_prematch_watch_delta(date_value: str, previous_snapshot: dict, current_snapshot: dict, watched_fixture_ids: list[str]) -> str | None:
    watched_ids = list(dict.fromkeys(watched_fixture_ids or []))
    changes = []

    for fixture_id in watched_ids:
        previous = previous_snapshot.get(fixture_id)
        current = current_snapshot.get(fixture_id)
        if previous is None and current is None:
            continue
        if previous is not None and current is None:
            changes.append(
                f"<b>{escape_html(previous.get('match', fixture_id))}</b>\n"
                f"Variazione: uscita dalla watchlist sopra soglia.\n"
                f"Azione: <b>NO BET per ora</b>"
            )
            continue
        if previous is None and current is not None:
            changes.append(
                f"<b>{escape_html(current.get('match', fixture_id))}</b>\n"
                f"Variazione: rientrata sopra soglia.\n"
                f"Movimento mercato: {escape_html(current.get('market_move', '-'))}\n"
                f"Azione: <b>{escape_html(current.get('action', '-'))}</b>\n"
                f"Tipo di bet: <b>{escape_html(current.get('bet_type', '-'))}</b>"
            )
            continue

        changed_lines = []
        if previous.get("status") != current.get("status"):
            changed_lines.append(f"status {previous.get('status')} -> {current.get('status')}")
        if previous.get("action") != current.get("action"):
            changed_lines.append(f"azione {previous.get('action')} -> {current.get('action')}")
        if previous.get("bet_type") != current.get("bet_type"):
            changed_lines.append(f"bet {previous.get('bet_type')} -> {current.get('bet_type')}")
        if previous.get("market_move") != current.get("market_move"):
            changed_lines.append(f"movimento {current.get('market_move')}")
        try:
            if abs(float(previous.get("largest_drop_pct", 0.0)) - float(current.get("largest_drop_pct", 0.0))) >= 1.0:
                changed_lines.append(
                    f"drop {float(previous.get('largest_drop_pct', 0.0)):.1f}% -> {float(current.get('largest_drop_pct', 0.0)):.1f}%"
                )
        except Exception:
            pass
        try:
            if abs(int(previous.get("risk_score", 0)) - int(current.get("risk_score", 0))) >= 3:
                changed_lines.append(f"score {int(previous.get('risk_score', 0))} -> {int(current.get('risk_score', 0))}")
        except Exception:
            pass

        if changed_lines:
            changes.append(
                f"<b>{escape_html(current.get('match', fixture_id))}</b>\n"
                f"Variazione: {escape_html(' | '.join(changed_lines))}\n"
                f"Azione: <b>{escape_html(current.get('action', '-'))}</b>\n"
                f"Tipo di bet: <b>{escape_html(current.get('bet_type', '-'))}</b>"
            )

    if not changes:
        return None

    header = (
        "<b>UPDATE PRE-MATCH WATCH</b>\n\n"
        f"<b>Data:</b> {escape_html(date_value)}\n"
        f"<b>Variazioni trovate:</b> {len(changes)}"
    )
    return header + "\n\n" + "\n\n".join(changes[:10])


def activate_prematch_watch(chat_id: int) -> str:
    with state_lock:
        last_report = stats.get("prematch_last_report") or default_prematch_last_report()
        fixture_ids = list(dict.fromkeys(last_report.get("fixture_ids") or []))
        report_date = str(last_report.get("date") or "").strip()
        if not fixture_ids or not report_date:
            return "Run /prematch_today first so I know which suspicious matches to monitor."
        stats["prematch_watch"] = {
            "active": True,
            "date": report_date,
            "chat_id": str(chat_id),
            "fixture_ids": fixture_ids,
            "interval_seconds": 300,
            "last_sent_utc": "",
            "baseline_ready": False,
            "last_snapshot": {},
        }
        salva_dati_web()
    return f"Prematch watch started for {len(fixture_ids)} matches on {report_date}. I will send updates every 5 minutes."


def stop_prematch_watch() -> str:
    with state_lock:
        watch = stats.get("prematch_watch") or default_prematch_watch_state()
        if not watch.get("active"):
            return "Prematch watch is not active."
        stats["prematch_watch"] = default_prematch_watch_state()
        salva_dati_web()
    return "Prematch watch stopped."


def is_private_chat(message) -> bool:
    return getattr(message.chat, "type", "") == "private"


def is_admin_message(message) -> bool:
    user_id = str(getattr(getattr(message, "from_user", None), "id", ""))
    admin_target = str(CHAT_ID or "").strip()
    if not admin_target:
        return False
    return is_private_chat(message) and user_id == admin_target


def require_admin_access(message, notice: str = "Private bot: command available only to the owner in private chat.") -> bool:
    if is_admin_message(message):
        return True
    try:
        bot.send_message(message.chat.id, notice)
    except Exception:
        pass
    return False


def get_filter_mode() -> str:
    mode = stats.get("filter_mode", DEFAULT_FILTER_MODE)
    return mode if mode in FILTER_PRESETS else DEFAULT_FILTER_MODE


def get_filter_label() -> str:
    return FILTER_PRESETS[get_filter_mode()]["label"]


def get_market_mode() -> str:
    mode = stats.get("market_mode", DEFAULT_MARKET_MODE)
    return mode if mode in MARKET_PRESETS else DEFAULT_MARKET_MODE


def get_market_label() -> str:
    return MARKET_PRESETS[get_market_mode()]["label"]


def get_active_markets():
    return MARKET_PRESETS[get_market_mode()]["markets"]


def get_routed_active_markets():
    markets = list(dict.fromkeys(get_active_markets()))
    if not AUTO_MARKET_SWITCH_ENABLED:
        return markets
    mode = get_market_mode()
    if mode in {"NEXT_GOAL", "HT_NEXT"}:
        return [MARKET_OVER05_HT, MARKET_OVER15_HT, MARKET_NEXT_GOAL]
    return markets


def get_market_router_score(market: str, minute_value: int, total_goals: int) -> float:
    if market == MARKET_OVER05_HT:
        if total_goals != 0:
            return -1.0
        if minute_value <= 10:
            return 1.30
        if minute_value <= 25:
            return 1.10
        if minute_value <= 35:
            return 0.85
        return 0.35
    if market == MARKET_OVER15_HT:
        if total_goals > 1:
            return -1.0
        if total_goals == 1:
            if minute_value <= 10:
                return 0.60
            if minute_value <= 25:
                return 1.05
            if minute_value <= 35:
                return 1.20
            return 0.55
        if minute_value <= 10:
            return 0.35
        if minute_value <= 25:
            return 0.55
        if minute_value <= 35:
            return 0.70
        return 0.20
    if market == MARKET_NEXT_GOAL:
        if minute_value <= 5:
            return 0.30
        if minute_value <= 10:
            return 0.45
        if minute_value <= 25:
            return 0.90
        if minute_value <= 35:
            return 1.00
        return 1.20
    return 0.0


def prioritize_markets(markets, minute_value: int, total_goals: int):
    return sorted(
        list(dict.fromkeys(markets)),
        key=lambda market_name: (get_market_router_score(market_name, minute_value, total_goals), market_name == MARKET_NEXT_GOAL),
        reverse=True,
    )


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


def carica_memoria() -> None:
    global stats
    if not os.path.exists(WEB_DATA_PATH):
        return

    try:
        bootstrap_changed = False
        with state_lock:
            with open(WEB_DATA_PATH, "r", encoding="utf-8-sig") as handle:
                caricati = json.load(handle)

            for tier_key, legacy_key in LEGACY_TIER_KEYS.items():
                if legacy_key in caricati and tier_key not in caricati:
                    caricati[tier_key] = caricati[legacy_key]

            for key in stats.keys():
                if key in caricati:
                    stats[key] = caricati[key]

            stats["filter_mode"] = get_filter_mode()
            stats["market_mode"] = get_market_mode()
            if not isinstance(stats.get("monitor_risultati"), dict):
                stats["monitor_risultati"] = {}
            if not isinstance(stats.get("pending_signal_tracker"), dict):
                stats["pending_signal_tracker"] = {}
            if not isinstance(stats.get("segnali_inviati"), list):
                stats["segnali_inviati"] = []
            if not isinstance(stats.get("rolling_settled"), list):
                stats["rolling_settled"] = []
            if not isinstance(stats.get("daily_analytics"), dict):
                stats["daily_analytics"] = default_analytics(current_date_key())
            if not isinstance(stats.get("recap_delivery"), dict):
                stats["recap_delivery"] = default_recap_delivery(current_date_key())
            if not isinstance(stats.get("coverage_guard"), dict):
                stats["coverage_guard"] = {"miss_counts": {}, "blocked_until": {}}
            if not isinstance(stats.get("prematch_last_report"), dict):
                stats["prematch_last_report"] = default_prematch_last_report()
            if not isinstance(stats.get("prematch_watch"), dict):
                stats["prematch_watch"] = default_prematch_watch_state()
            ensure_daily_analytics()
            migrate_monitor_entries()
            prune_settled_signals()
            clean_sent_signals()
            if not isinstance(stats.get("last_auto_retrain_total"), int):
                stats["last_auto_retrain_total"] = get_total_settled_count()
                bootstrap_changed = True

        if bootstrap_changed:
            salva_dati_web()
        print(
            f"Memoria caricata. Current bankroll: {stats['total_profit']} EUR | filter: {get_filter_label()} | market: {get_market_label()}"
        )
    except Exception as exc:
        print(f"Errore caricamento memoria: {exc}")

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



def load_missing_team_queue() -> None:
    global missing_team_queue
    if not os.path.exists(MISSING_TEAMS_QUEUE_PATH):
        missing_team_queue = {}
        return

    try:
        with missing_team_queue_lock:
            with open(MISSING_TEAMS_QUEUE_PATH, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            missing_team_queue = loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        missing_team_queue = {}
        log_event("MISSING_QUEUE_LOAD_ERROR", str(exc))


def save_missing_team_queue() -> None:
    with missing_team_queue_lock:
        with open(MISSING_TEAMS_QUEUE_PATH, "w", encoding="utf-8") as handle:
            json.dump(missing_team_queue, handle, indent=2)


def queue_missing_team_lookup(nome_live: str, country: str = "", league_name: str = "") -> None:
    norm_live = normalizza_squadra(nome_live)
    if not norm_live:
        return

    key = f"{country.strip().lower()}|{league_name.strip().lower()}|{norm_live}"
    now_iso = now_utc().isoformat()
    with missing_team_queue_lock:
        item = missing_team_queue.get(key, {
            "team_name": nome_live,
            "normalized": norm_live,
            "country": country,
            "league_name": league_name,
            "count": 0,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "status": "pending",
        })
        item["count"] = int(item.get("count", 0)) + 1
        item["last_seen"] = now_iso
        if not item.get("first_seen"):
            item["first_seen"] = now_iso
        if country and not item.get("country"):
            item["country"] = country
        if league_name and not item.get("league_name"):
            item["league_name"] = league_name
        missing_team_queue[key] = item

    save_missing_team_queue()


def get_missing_team_queue_count() -> int:
    return len(missing_team_queue)


def get_missing_team_queue_status_counts() -> dict:
    with missing_team_queue_lock:
        queue = missing_team_queue if isinstance(missing_team_queue, dict) else {}
        counts = {"total": len(queue), "pending": 0, "resolved": 0, "other": 0}
        for item in queue.values():
            if not isinstance(item, dict):
                counts["other"] += 1
                continue
            status = str(item.get("status", "pending") or "pending").strip().lower()
            if status == "pending":
                counts["pending"] += 1
            elif status == "resolved":
                counts["resolved"] += 1
            else:
                counts["other"] += 1
        return counts


def read_missing_team_queue_status_counts_from_disk() -> dict:
    if not os.path.exists(MISSING_TEAMS_QUEUE_PATH):
        return {"total": 0, "pending": 0, "resolved": 0, "other": 0}
    try:
        with open(MISSING_TEAMS_QUEUE_PATH, "r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
    except Exception as exc:
        log_event("MISSING_QUEUE_READ_DIRECT_ERROR", str(exc))
        return get_missing_team_queue_status_counts()

    queue = loaded if isinstance(loaded, dict) else {}
    counts = {"total": len(queue), "pending": 0, "resolved": 0, "other": 0}
    for item in queue.values():
        if not isinstance(item, dict):
            counts["other"] += 1
            continue
        status = str(item.get("status", "pending") or "pending").strip().lower()
        if status == "pending":
            counts["pending"] += 1
        elif status == "resolved":
            counts["resolved"] += 1
        else:
            counts["other"] += 1
    return counts

def build_team_lookup() -> None:
    global normalized_team_lookup
    if normalized_team_lookup or not nomi_unici_db:
        return

    lookup = {}
    for nome_db in nomi_unici_db:
        norm_db = normalizza_squadra(nome_db)
        if not norm_db:
            continue
        lookup.setdefault(norm_db, []).append(nome_db)
    normalized_team_lookup = lookup


def simplify_team_tokens(value: str) -> str:
    text = f" {normalizza_squadra(value)} "
    removable = [
        " fc ", " cf ", " sc ", " afc ", " athletic ", " club ", " calcio ",
        " futbol ", " football ", " sporting ", " sport ", " association ",
        " team ", " reserve ", " reserves ", " youth ", " women ", " wfc ",
    ]
    for token in removable:
        text = text.replace(token, " ")
    text = re.sub(r"\b\d{2,4}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_controlled_aliases(nome_live: str) -> list[str]:
    normalized = normalizza_squadra(nome_live)
    aliases = []

    manual_aliases = MANUAL_TEAM_ALIASES.get(normalized, [])
    for alias in manual_aliases:
        alias_norm = normalizza_squadra(alias)
        if alias_norm and alias_norm not in aliases and alias_norm != normalized:
            aliases.append(alias_norm)

    patterns = [
        r"^jong\s+",
        r"\su21$",
        r"\su23$",
        r"\sii$",
        r"\sb$",
        r"\sreserves?$",
    ]

    alias = normalized
    for pattern in patterns:
        alias = re.sub(pattern, " ", alias).strip()
    alias = re.sub(r"\s+", " ", alias).strip()
    if alias and alias != normalized:
        aliases.append(alias)

    simple_alias = simplify_team_tokens(nome_live)
    if simple_alias and simple_alias not in aliases and simple_alias != normalized:
        aliases.append(simple_alias)

    return aliases

def ensure_coverage_guard() -> dict:
    guard = stats.get("coverage_guard")
    if not isinstance(guard, dict):
        guard = {"miss_counts": {}, "blocked_until": {}}
        stats["coverage_guard"] = guard
    if not isinstance(guard.get("miss_counts"), dict):
        guard["miss_counts"] = {}
    if not isinstance(guard.get("blocked_until"), dict):
        guard["blocked_until"] = {}
    return guard


def get_coverage_key(country: str, league_name: str) -> str:
    country_value = str(country or "").strip().upper()
    league_value = normalizza_testo(league_name).upper()
    if not country_value and not league_value:
        return ""
    return f"{country_value}::{league_value}"


def is_coverage_blocked(country: str, league_name: str) -> bool:
    if not COVERAGE_GUARD_ENABLED:
        return False
    key = get_coverage_key(country, league_name)
    if not key:
        return False
    with state_lock:
        guard = ensure_coverage_guard()
        blocked_until = guard["blocked_until"]
        expires_at = blocked_until.get(key)
        if not expires_at:
            return False
        try:
            expires_dt = datetime.fromisoformat(expires_at)
        except Exception:
            blocked_until.pop(key, None)
            guard["miss_counts"].pop(key, None)
            return False
        if expires_dt <= now_utc():
            blocked_until.pop(key, None)
            guard["miss_counts"].pop(key, None)
            return False
        return True


def register_team_not_found(country: str, league_name: str) -> None:
    if not COVERAGE_GUARD_ENABLED:
        return
    key = get_coverage_key(country, league_name)
    if not key:
        return

    should_log = False
    expires_value = ""
    with state_lock:
        guard = ensure_coverage_guard()
        miss_counts = guard["miss_counts"]
        blocked_until = guard["blocked_until"]
        expires_at = blocked_until.get(key)
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) > now_utc():
                    return
            except Exception:
                pass
            blocked_until.pop(key, None)
        new_count = int(miss_counts.get(key, 0)) + 1
        miss_counts[key] = new_count
        if new_count >= COVERAGE_GUARD_THRESHOLD:
            expires_dt = now_utc() + timedelta(hours=COVERAGE_GUARD_HOURS)
            expires_value = expires_dt.isoformat()
            blocked_until[key] = expires_value
            miss_counts.pop(key, None)
            should_log = True

    if should_log:
        log_event("COVERAGE_BLOCK", f"country={country or '-'} league={league_name or '-'} hours={COVERAGE_GUARD_HOURS} until={expires_value}")
        salva_dati_web()


def log_team_not_found(nome_live: str, country: str = "", league_name: str = "") -> None:
    norm_live = normalizza_squadra(nome_live)
    if not norm_live:
        return
    count = team_not_found_counts.get(norm_live, 0) + 1
    team_not_found_counts[norm_live] = count
    if count <= 3:
        log_event("TEAM_NOT_FOUND", f"live={nome_live} normalized={norm_live} count={count}")
    queue_missing_team_lookup(nome_live, country, league_name)
    register_team_not_found(country, league_name)


def get_top_team_not_found(limit: int = 5) -> str:
    if not team_not_found_counts:
        return "-"
    pairs = sorted(team_not_found_counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return ", ".join(f"{name} ({count})" for name, count in pairs)
def trova_squadra(nome_live: str, country: str = "", league_name: str = ""):
    if not nomi_unici_db:
        return None

    build_team_lookup()
    norm_live = normalizza_squadra(nome_live)
    if not norm_live:
        return None

    cached = team_match_cache.get(norm_live)
    if cached:
        return cached

    for alias in get_controlled_aliases(nome_live):
        alias_hits = normalized_team_lookup.get(alias)
        if alias_hits:
            match = alias_hits[0]
            team_match_cache[norm_live] = match
            return match

    direct_hits = normalized_team_lookup.get(norm_live)
    if direct_hits:
        match = direct_hits[0]
        team_match_cache[norm_live] = match
        return match

    simple_live = simplify_team_tokens(nome_live)
    if simple_live:
        simple_hits = normalized_team_lookup.get(simple_live)
        if simple_hits:
            match = simple_hits[0]
            team_match_cache[norm_live] = match
            return match

    best_match = None
    best_ratio = 0.0
    best_simple_match = None
    best_simple_ratio = 0.0

    live_tokens = set(norm_live.split())
    simple_live_tokens = set(simple_live.split()) if simple_live else set()

    for norm_db, original_names in normalized_team_lookup.items():
        db_tokens = set(norm_db.split())
        if live_tokens and db_tokens and live_tokens == db_tokens:
            match = original_names[0]
            team_match_cache[norm_live] = match
            return match

        ratio = SequenceMatcher(None, norm_live, norm_db).ratio()
        if ratio > 0.94:
            match = original_names[0]
            team_match_cache[norm_live] = match
            return match
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = original_names[0]

        simple_db = simplify_team_tokens(norm_db)
        simple_db_tokens = set(simple_db.split()) if simple_db else set()
        if simple_live and simple_db:
            if simple_live_tokens and simple_db_tokens and simple_live_tokens == simple_db_tokens:
                match = original_names[0]
                team_match_cache[norm_live] = match
                return match
            simple_ratio = SequenceMatcher(None, simple_live, simple_db).ratio()
            if simple_ratio > best_simple_ratio:
                best_simple_ratio = simple_ratio
                best_simple_match = original_names[0]

    if best_simple_match and best_simple_ratio >= 0.88:
        team_match_cache[norm_live] = best_simple_match
        return best_simple_match
    if best_match and best_ratio >= 0.86:
        team_match_cache[norm_live] = best_match
        return best_match

    log_team_not_found(nome_live, country, league_name)
    return None

def is_non_league_competition(league_name: str) -> bool:
    text = normalizza_testo(league_name).upper()
    return any(token in text for token in NON_LEAGUE_EXCLUDED)


def is_youth_competition(league_name: str) -> bool:
    text = f" {str(league_name or '').upper()} "
    return any(f" {token} " in text for token in YOUTH_EXCLUDED)


def is_allowed_serie_ab(country: str, league_name: str) -> bool:
    patterns = SERIE_AB_PATTERNS.get(str(country or "").upper(), [])
    normalized_league = normalizza_testo(league_name)
    return any(pattern in normalized_league for pattern in patterns)


def get_league_filter_reason(country: str, league_name: str) -> str | None:
    preset = FILTER_PRESETS[get_filter_mode()]
    country_upper = str(country or "").upper()
    if is_coverage_blocked(country_upper, league_name):
        return "coverage"

    if preset["top10_only"] and country_upper not in TOP10_COUNTRIES:
        return "base"
    if is_non_league_competition(league_name):
        return "base"
    if not preset["allow_youth"] and is_youth_competition(league_name):
        return "base"
    if preset["ab_only"] and not is_allowed_serie_ab(country_upper, league_name):
        return "base"
    return None

def is_league_allowed(country: str, league_name: str) -> bool:
    return get_league_filter_reason(country, league_name) is None
def set_filter_mode(mode: str) -> str:
    if mode not in FILTER_PRESETS:
        return get_filter_label()
    with state_lock:
        stats["filter_mode"] = mode
    salva_dati_web()
    return FILTER_PRESETS[mode]["label"]


def set_market_mode(mode: str) -> str:
    if mode not in MARKET_PRESETS:
        return get_market_label()
    with state_lock:
        stats["market_mode"] = mode
    salva_dati_web()
    return MARKET_PRESETS[mode]["label"]



def acquire_process_lock() -> bool:
    global process_lock_handle
    try:
        handle = open(PROCESS_LOCK_PATH, "a+")
        handle.seek(0)
        try:
            if _LOCK_PLATFORM == "win32":
                _lock_mod.locking(handle.fileno(), _lock_mod.LK_NBLCK, 1)
            else:
                _lock_mod.flock(handle.fileno(), _lock_mod.LOCK_EX | _lock_mod.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.truncate(0)
        handle.write(str(os.getpid()))
        handle.flush()
        process_lock_handle = handle
        return True
    except Exception:
        return False


def release_process_lock() -> None:
    global process_lock_handle
    if process_lock_handle is None:
        return
    try:
        if _LOCK_PLATFORM == "win32":
            process_lock_handle.seek(0)
            _lock_mod.locking(process_lock_handle.fileno(), _lock_mod.LK_UNLCK, 1)
        else:
            _lock_mod.flock(process_lock_handle.fileno(), _lock_mod.LOCK_UN)
    except Exception:
        pass
    try:
        process_lock_handle.close()
    except Exception:
        pass
    process_lock_handle = None
    try:
        if os.path.exists(PROCESS_LOCK_PATH):
            os.remove(PROCESS_LOCK_PATH)
    except Exception:
        pass


atexit.register(release_process_lock)
def is_market_window(market: str, minute_value: int, total_goals: int) -> bool:
    if market == MARKET_NEXT_GOAL:
        return 1 <= minute_value <= 85
    if market == MARKET_OVER15_HT:
        # Disabilitato: WR storico 28.3% — market strutturalmente in perdita
        return False
    if not 1 <= minute_value <= 44:
        return False
    if market == MARKET_OVER05_HT:
        # Limitato al minuto <= 20: WR crolla a 6-20% dopo
        return total_goals == 0 and minute_value <= 20
    return False



def get_team_metrics(team_name: str):
    if not team_name or df_matches is None:
        return None

    storico = df_matches[(df_matches["HomeTeam"] == team_name) | (df_matches["AwayTeam"] == team_name)].tail(12)
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


def is_market_winner(market: str, total_goals: int) -> bool:
    if market == MARKET_OVER05_HT:
        return total_goals >= 1
    if market == MARKET_OVER15_HT:
        return total_goals >= 2
    if market == MARKET_NEXT_GOAL:
        return False
    return False


def is_first_half_closed(status_short: str, minute_value: int) -> bool:
    status_short = str(status_short or "").upper()
    return status_short in {"HT", "BT", "FT", "AET", "PEN"} or minute_value >= 45


def get_profile_label(tier: str) -> str:
    return "HIGH PRECISION" if tier == TIER_APPROVED else "CONTROLLED RISK" if tier == TIER_CAUTION else "AGGRESSIVE VALUE"


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

def format_edge_text(reason: str, market: str = "") -> str:
    if not reason:
        return ""
    parts = [part.strip() for part in str(reason).split("|") if part.strip()]
    if not parts:
        return escape_html(str(reason))
    if market == MARKET_NEXT_GOAL:
        labels = ['PERSISTENCE', 'MODEL', 'WHY']
    else:
        labels = ['HT AVG', 'FT AVG', 'WHY']
    formatted_parts = []
    for idx, part in enumerate(parts):
        label = labels[idx] if idx < len(labels) else f"EDGE {idx + 1}"
        formatted_parts.append(f"<b>{label}:</b> {escape_html(part)}")
    return " | ".join(formatted_parts)

def format_signal_message(
    tier: str, country: str, match_up: str, dna: float, prob: float, minute_value: int, score: str, market: str, reason: str = "", live_odd=None
) -> str:
    tier_icons = {TIER_APPROVED: "\U0001F947", TIER_CAUTION: "\u26A0", TIER_GAMBLING: "\U0001F3AF"}
    emoji = tier_icons.get(tier, "\U0001F916")
    tier_profiles = {
        TIER_APPROVED: "Segnale selezionato — alta precisione",
        TIER_CAUTION: "Setup giocabile — rischio controllato",
        TIER_GAMBLING: "Setup aggressivo — rischio elevato",
    }
    profile_label = tier_profiles.get(tier, "Segnale automatico")
    if dna >= 3.5:
        pace_label = "Partita ad altissimo scoring (media " + str(dna) + " gol)"
    elif dna >= 2.8:
        pace_label = "Partita ad alto scoring (media " + str(dna) + " gol)"
    elif dna >= 2.2:
        pace_label = "Partita a medio scoring (media " + str(dna) + " gol)"
    else:
        pace_label = "Partita a basso scoring (media " + str(dna) + " gol)"
    import re as _re
    parts = [p.strip() for p in str(reason or "").split("|") if p.strip()]
    confirm_line = ""
    if market == MARKET_NEXT_GOAL and parts:
        m_cycles = _re.search(r"x(\d+)", parts[0])
        if m_cycles:
            cycles = int(m_cycles.group(1))
            if cycles >= 4:
                confirm_line = "\U0001F504 Confermato su " + str(cycles) + " rilevamenti\n"
            elif cycles >= 2:
                confirm_line = "\U0001F504 Rilevato su " + str(cycles) + " scansioni\n"
    min_quota = get_min_quota_for_tier(tier)
    if live_odd is not None:
        if live_odd >= min_quota:
            quota_line = "\U0001F4B0 Quota live: <b>" + str(live_odd) + "</b> \u2705 (min " + str(min_quota) + ")\n"
        else:
            quota_line = "\U0001F4B0 Quota live: <b>" + str(live_odd) + "</b> \u26A0 sotto soglia, attendi " + str(min_quota) + "+\n"
    else:
        quota_line = "\U0001F4B0 Entra solo sopra quota <b>" + str(min_quota) + "</b>\n"
    if market == MARKET_NEXT_GOAL:
        mkt_header = emoji + " <b>NEXT GOAL</b> — <b>" + escape_html(tier) + "</b>"
    else:
        mkt_header = emoji + " <b>" + escape_html(market) + "</b> — <b>" + escape_html(tier) + "</b>"
    min_str = str(minute_value) + "' | " + escape_html(score)
    return (
        mkt_header + "\n"
        + SEPARATOR + "\n"
        + "\U0001F30D " + escape_html(country) + " — " + escape_html(match_up) + "\n"
        + "\u23F1 " + min_str + "\n\n"
        + "\U0001F525 " + escape_html(pace_label) + "\n"
        + confirm_line + quota_line
        + SEPARATOR + "\n"
        + "\U0001F4CC " + escape_html(profile_label)
    )


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


def format_premium_signal_message(
    tier: str,
    country: str,
    league_name: str,
    match_up: str,
    dna: float,
    prob: float,
    minute_value: int,
    score: str,
    market: str,
    reason: str = "",
    live_odd=None,
) -> str:
    base_message = format_signal_message(tier, country, match_up, dna, prob, minute_value, score, market, reason, live_odd=live_odd)
    return (
        "<b>PREMIUM PRIVATE</b>\n"
        f"{SEPARATOR}\n"
        f"<b>LEAGUE:</b> {escape_html(league_name)}\n"
        f"{base_message}"
    )


def format_signal_legend() -> str:
    return (
        "<b>Signal Legend</b>\n"
        f"{SEPARATOR}\n"
        "<b>DNA:</b> historical goal profile of the matchup. Higher usually means a more goal-friendly game.\n"
        "<b>CONF / MODEL:</b> the model probability used by the bot. Higher means the setup looks stronger to the engine.\n"
        "<b>MINUTE | SCORE:</b> live minute and score when the signal was opened.\n"
        "<b>APPROVED:</b> strongest public setup.\n"
        "<b>CAUTION:</b> playable setup, but less clean.\n"
        "<b>GAMBLING:</b> aggressive and higher-risk setup.\n"
        f"{SEPARATOR}\n"
        "<b>HT markets</b>\n"
        "<b>HT AVG:</b> combined first-half goal average from the teams' recent history.\n"
        "<b>FT AVG:</b> combined full-match goal average from the teams' recent history.\n"
        "<b>WHY:</b> short explanation of why the bot considered the setup playable.\n"
        f"{SEPARATOR}\n"
        "<b>NEXT GOAL LIVE</b>\n"
        "<b>PERSISTENCE:</b> how many radar cycles the game stayed live and interesting before the alert.\n"
        "<b>MODEL:</b> next-goal probability used by the live engine.\n"
        "<b>WHY:</b> short explanation, usually based on goal profile or live pressure.\n"
        "<b>PENDING:</b> the match is still alive in the radar but not strong enough yet to become a public signal.\n"
    )
def format_free_teaser_message(tier: str, country: str, match_up: str, minute_value: int, score: str, market: str) -> str:
    return (
        f"<b>VIP TEASER {TIER_EMOJI.get(tier, '\U0001F916')} {escape_html(tier)}</b>\n"
        f"{SEPARATOR}\n"
        f"<b>MARKET:</b> {escape_html(market)}\n"
        f"<b>COUNTRY:</b> {escape_html(country)}\n"
        f"<b>MATCH:</b> {escape_html(match_up)}\n"
        f"<b>MINUTE:</b> {minute_value}' | {escape_html(score)}\n"
        f"{SEPARATOR}\n"
        f"<b>FREE VIEW:</b> premium signal detected by the Oracle radar\n"
        f"<b>VIP:</b> confidence, edge, edited updates and full settlement inside the premium channel\n"
        f"<b>ACCESS:</b> open the bot and use /vip"
    )


def format_settlement_message(original_text: str, market: str, outcome: str, score_finale: str, audience: str) -> str:
    outcome_label = "WIN" if outcome == "WIN" else "LOSS"
    outcome_icon = "\u2705" if outcome == "WIN" else "\u274C"
    if audience == "free":
        return (
            f"<b>{outcome_icon} {outcome_label}</b>\n"
            f"{SEPARATOR}\n"
            f"{original_text}\n"
            f"{SEPARATOR}\n"
            f"<b>RESULT:</b> {outcome_label}\n"
            f"<b>FINAL SCORE:</b> {escape_html(score_finale)}\n"
            f"<b>VIP:</b> use /vip for the full live feed"
        )
    return (
        f"{original_text}\n"
        f"{SEPARATOR}\n"
        f"<b>SETTLEMENT:</b> {escape_html(market)}\n"
        f"<b>{outcome_icon} RESULT:</b> {outcome_label}\n"
        f"<b>FINAL SCORE:</b> {escape_html(score_finale)}"
    )


def format_analytics_text() -> str:
    ensure_daily_analytics()
    analytics = stats["daily_analytics"]
    return (
        f"Analytics UTC {analytics['date_utc']}\n"
        f"Signals: {analytics['signals_total']}\n"
        f"Approved: {analytics['signals_by_tier'].get(TIER_APPROVED, 0)} | Caution: {analytics['signals_by_tier'].get(TIER_CAUTION, 0)} | Gambling: {analytics['signals_by_tier'].get(TIER_GAMBLING, 0)}\n"
        f"Settled WIN: {analytics['settled_win']} | LOSS: {analytics['settled_loss']}\n"
        f"Rolling overall: {format_rolling_overview()}\n"
        f"Rolling active markets: {format_market_rolling_overview()}\n"
        f"By market: {format_top_counts(analytics.get('signals_by_market', {}), 5)}\n"
        f"By league: {format_top_counts(analytics.get('signals_by_league', {}), 5)}\n"
        f"By minute: {format_top_counts(analytics.get('signals_by_minute_bucket', {}), 5)}\n"
        f"Market results: {format_market_results(analytics.get('settled_by_market', {}))}\n"
        f"Free teasers scheduled: {analytics['free_teasers_scheduled']} | sent: {analytics['free_teasers_sent']}\n"
        f"VIP payments: {analytics['vip_payments_count']} | revenue XTR: {analytics['vip_revenue_xtr']}\n"
        f"Renewal reminders: {analytics['renewal_reminders_sent']}\n"
        f"Active VIP members: {membership_store.get_active_member_count()}"
    )


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
    if oracle_brain is None:
        return f"{market}: NO_MODEL"

    dna = combined_metrics["avg_total_goals"]
    stats_payload = fetch_fixture_stats(fixture_id, headers)
    titan_soft = evaluate_titan_soft_layer(stats_payload, market, minute_value, total_goals)
    shots_on_goal_at_open = float(stats_payload.get("shots_on_goal", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    total_shots_at_open = float(stats_payload.get("total_shots", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    corners_at_open = float(stats_payload.get("corners", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    red_cards_at_open = float(stats_payload.get("red_cards", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
    titan_pressure_score = float(titan_soft.get("score", 0.0) or 0.0)
    titan_pressure_prob = predict_titan_pressure_prob(dna, minute_value, 0, total_goals, stats_payload)

    model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))
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
    }
    x_input = pd.DataFrame(
        [[model_feature_values.get(column, 0.0) for column in model_feature_columns]],
        columns=model_feature_columns,
    )
    prob = oracle_brain.predict_proba(x_input)[0][1]

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

def format_admin_panel() -> str:
    ensure_daily_analytics()
    analytics = stats["daily_analytics"]
    active_members = membership_store.get_active_member_count()
    total_members = membership_store.get_total_member_count()
    expired_members = membership_store.get_expired_member_count()
    pending_invoices = membership_store.get_pending_invoices_count()
    paid_invoices = membership_store.get_paid_invoices_count()
    revenue_xtr = membership_store.get_paid_invoices_total()
    expiring_soon = membership_store.get_members_expiring_within(max(1, RENEWAL_REMINDER_DAYS))
    recent_members = membership_store.get_recent_members(5)
    settled_total = analytics["settled_win"] + analytics["settled_loss"]
    hit_rate = (analytics["settled_win"] / settled_total * 100) if settled_total else 0.0
    conversion = (active_members / max(1, analytics["free_teasers_sent"]) * 100) if analytics["free_teasers_sent"] else 0.0
    market_results = analytics.get("settled_by_market", {})
    league_results = analytics.get("settled_by_league", {})
    minute_results = analytics.get("settled_by_minute_bucket", {})

    recent_block = "No VIP members registered yet."
    if recent_members:
        rows = []
        for member in recent_members:
            label = member.get("username") or member.get("first_name") or str(member.get("user_id"))
            rows.append(f"- {escape_html(label)} | {escape_html(member.get('status', '-'))} | exp {escape_html(member.get('expires_at', '-') or '-')}")
        recent_block = "\n".join(rows)

    return (
        f"<b>ADMIN PANEL</b>\n"
        f"{SEPARATOR}\n"
        f"<b>Filter:</b> {escape_html(get_filter_label())}\n"
        f"<b>Market:</b> {escape_html(get_market_label())}\n"
        f"<b>Live bankroll:</b> {stats['total_profit']} EUR\n"
        f"<b>Matches analyzed:</b> {stats['matches_analyzed']}\n"
        f"{SEPARATOR}\n"
        f"<b>Today UTC:</b> {analytics['date_utc']}\n"
        f"<b>Signals:</b> {analytics['signals_total']}\n"
        f"<b>Approved:</b> {analytics['signals_by_tier'].get(TIER_APPROVED, 0)} | <b>Caution:</b> {analytics['signals_by_tier'].get(TIER_CAUTION, 0)}\n"
        f"<b>WIN:</b> {analytics['settled_win']} | <b>LOSS:</b> {analytics['settled_loss']} | <b>Hit rate:</b> {hit_rate:.1f}%\n"
        f"<b>Rolling overall:</b> {escape_html(format_rolling_overview())}\n"
        f"<b>Rolling active markets:</b> {escape_html(format_market_rolling_overview())}\n"
        f"<b>Top market:</b> {escape_html(format_top_counts(analytics.get('signals_by_market', {}), 3))}\n"
        f"<b>Top league:</b> {escape_html(format_top_counts(analytics.get('signals_by_league', {}), 3))}\n"
        f"<b>Best minute zones:</b> {escape_html(format_top_counts(analytics.get('signals_by_minute_bucket', {}), 3))}\n"
        f"<b>Market results:</b> {escape_html(format_market_results(market_results, 5))}\n"
        f"<b>League results:</b> {escape_html(format_market_results(league_results, 4))}\n"
        f"<b>Minute results:</b> {escape_html(format_market_results(minute_results, 4))}\n"
        f"<b>Auto filter:</b> penalizes cold markets, leagues and minute zones using daily + rolling data\n"
        f"<b>Free teasers:</b> {analytics['free_teasers_sent']} sent | <b>scheduled:</b> {analytics['free_teasers_scheduled']}\n"
        f"{SEPARATOR}\n"
        f"<b>VIP active:</b> {active_members}\n"
        f"<b>VIP total:</b> {total_members} | <b>expired:</b> {expired_members}\n"
        f"<b>Expiring soon ({max(1, RENEWAL_REMINDER_DAYS)}d):</b> {len(expiring_soon)}\n"
        f"<b>Paid invoices:</b> {paid_invoices} | <b>pending:</b> {pending_invoices}\n"
        f"<b>Total revenue:</b> {revenue_xtr} XTR\n"
        f"<b>Teaser -> VIP conversion:</b> {conversion:.1f}%\n"
        f"{SEPARATOR}\n"
        f"<b>Recent members:</b>\n{recent_block}"
    )


def format_admin_recap() -> str:
    analytics = stats["daily_analytics"]
    return (
        f"<b>DAILY ADMIN RECAP</b>\n"
        f"{SEPARATOR}\n"
        f"<b>Date UTC:</b> {analytics['date_utc']}\n"
        f"<b>Signals:</b> {analytics['signals_total']}\n"
        f"<b>Approved:</b> {analytics['signals_by_tier'].get(TIER_APPROVED, 0)} | <b>Caution:</b> {analytics['signals_by_tier'].get(TIER_CAUTION, 0)} | <b>Gambling:</b> {analytics['signals_by_tier'].get(TIER_GAMBLING, 0)}\n"
        f"<b>WIN:</b> {analytics['settled_win']} | <b>LOSS:</b> {analytics['settled_loss']}\n"
        f"<b>Rolling overall:</b> {escape_html(format_rolling_overview())}\n"
        f"<b>Free teasers:</b> {analytics['free_teasers_sent']} sent\n"
        f"<b>VIP payments:</b> {analytics['vip_payments_count']} | <b>Revenue XTR:</b> {analytics['vip_revenue_xtr']}\n"
        f"<b>VIP active:</b> {membership_store.get_active_member_count()}"
    )


def format_vip_recap() -> str:
    analytics = stats["daily_analytics"]
    return (
        f"<b>VIP DAILY RECAP</b>\n"
        f"{SEPARATOR}\n"
        f"<b>Premium signals:</b> {analytics['signals_total']}\n"
        f"<b>WIN:</b> {analytics['settled_win']} | <b>LOSS:</b> {analytics['settled_loss']}\n"
        f"<b>Approved:</b> {analytics['signals_by_tier'].get(TIER_APPROVED, 0)}\n"
        f"<b>Caution:</b> {analytics['signals_by_tier'].get(TIER_CAUTION, 0)}\n"
        f"<b>Gambling:</b> {analytics['signals_by_tier'].get(TIER_GAMBLING, 0)}\n"
        f"<b>Rolling overall:</b> {escape_html(format_rolling_overview())}\n"
        f"<b>Live tracker bankroll:</b> {stats['total_profit']} EUR"
    )


def format_free_recap() -> str:
    analytics = stats["daily_analytics"]
    return (
        f"<b>DAILY FREE RECAP</b>\n"
        f"{SEPARATOR}\n"
        f"<b>Public teasers today:</b> {analytics['free_teasers_sent']}\n"
        f"<b>WIN:</b> {analytics['settled_win']} | <b>LOSS:</b> {analytics['settled_loss']}\n"
        f"<b>Rolling overall:</b> {escape_html(format_rolling_overview())}\n"
        f"<b>Want every full live signal in real time?</b>\n"
        f"Open the bot and use <b>/vip</b>"
    )


def compute_performance_snapshot() -> dict:
    total_wins = sum(int(stats.get(tier, {}).get("v", 0)) for tier in [TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING])
    total_losses = sum(int(stats.get(tier, {}).get("p", 0)) for tier in [TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING])
    settled_total = total_wins + total_losses
    tracked_stake = float(STAKE or 0.0)
    total_profit = float(stats.get("total_profit", 0.0))
    win_rate = (total_wins / settled_total * 100) if settled_total else 0.0
    roi = (total_profit / (settled_total * tracked_stake) * 100) if settled_total and tracked_stake else 0.0
    units = (total_profit / tracked_stake) if tracked_stake else 0.0
    sample_stake = float(PERFORMANCE_STAKE_EXAMPLE or 0.0)
    sample_profit = units * sample_stake
    sample_bankroll = PERFORMANCE_STARTING_BANKROLL + sample_profit
    by_market = []
    try:
        with live_training_lock:
            df_perf = pd.read_csv(TRAINER_DATA_FILE)
        if not df_perf.empty and all(column in df_perf.columns for column in ["SignalKey", "Market", "Tier", "Outcome"]):
            public_tiers = {TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING}
            settled_mask = df_perf["Outcome"].isin(["WIN", "LOSS"]) & df_perf["Tier"].isin(public_tiers)
            df_perf = df_perf.loc[settled_mask, ["SignalKey", "Market", "Outcome"]].copy()
            if not df_perf.empty:
                df_perf["SignalKey"] = df_perf["SignalKey"].astype(str)
                df_perf["Market"] = df_perf["Market"].fillna("UNKNOWN").astype(str)
                df_perf = df_perf.drop_duplicates(subset=["SignalKey"], keep="last")
                for market_name, df_market in df_perf.groupby("Market"):
                    wins = int((df_market["Outcome"] == "WIN").sum())
                    losses = int((df_market["Outcome"] == "LOSS").sum())
                    market_settled = wins + losses
                    market_profit = ((wins * (QUOTA - 1)) - losses) * tracked_stake if tracked_stake else 0.0
                    market_roi = (market_profit / (market_settled * tracked_stake) * 100) if market_settled and tracked_stake else 0.0
                    by_market.append({
                        "market": market_name,
                        "wins": wins,
                        "losses": losses,
                        "settled_total": market_settled,
                        "profit": market_profit,
                        "roi": market_roi,
                        "win_rate": (wins / market_settled * 100) if market_settled else 0.0,
                    })
                by_market.sort(key=lambda item: (-item["settled_total"], item["market"]))
    except Exception:
        by_market = []
    return {
        "wins": total_wins,
        "losses": total_losses,
        "settled_total": settled_total,
        "profit": total_profit,
        "win_rate": win_rate,
        "roi": roi,
        "units": units,
        "tracked_stake": tracked_stake,
        "sample_stake": sample_stake,
        "sample_profit": sample_profit,
        "sample_bankroll": sample_bankroll,
        "by_market": by_market,
    }


def format_performance_by_market(snapshot: dict, max_items: int = 6) -> str:
    market_rows = snapshot.get("by_market") or []
    if not market_rows:
        return "n/a"
    lines = []
    for row in market_rows[:max_items]:
        lines.append(
            f"{row['market']}: {row['wins']}W-{row['losses']}L | WR {row['win_rate']:.1f}% | ROI {row['roi']:+.1f}% | P/L {row['profit']:+.2f} EUR"
        )
    return "\n".join(lines)


def format_performance_report(audience: str = "vip") -> str:
    snapshot = compute_performance_snapshot()
    by_market_text = escape_html(format_performance_by_market(snapshot))
    if audience == "free":
        return (
            f"<b>PERFORMANCE REPORT</b>\n"
            f"{SEPARATOR}\n"
            f"<b>Settled signals:</b> {snapshot['settled_total']}\n"
            f"<b>Win Rate:</b> {snapshot['win_rate']:.1f}%\n"
            f"<b>ROI:</b> {snapshot['roi']:.1f}%\n"
            f"<b>Units:</b> {snapshot['units']:+.2f}u (1u = {snapshot['tracked_stake']:.0f} EUR)\n"
            f"<b>{snapshot['sample_stake']:.0f} EUR flat equivalent:</b> bankroll {snapshot['sample_bankroll']:.0f} EUR\n"
            f"{SEPARATOR}\n"
            f"<b>Want every full live signal in real time?</b>\n"
            f"Open the bot and use <b>/vip</b>"
        )
    if audience == "admin":
        return (
            f"<b>PERFORMANCE REPORT ADMIN</b>\n"
            f"{SEPARATOR}\n"
            f"<b>Settled signals:</b> {snapshot['settled_total']}\n"
            f"<b>WIN:</b> {snapshot['wins']} | <b>LOSS:</b> {snapshot['losses']}\n"
            f"<b>Win Rate:</b> {snapshot['win_rate']:.1f}%\n"
            f"<b>ROI:</b> {snapshot['roi']:.1f}%\n"
            f"<b>Units:</b> {snapshot['units']:+.2f}u (1u = {snapshot['tracked_stake']:.0f} EUR)\n"
            f"<b>Live profit (tracked @ {snapshot['tracked_stake']:.0f} EUR flat):</b> {snapshot['profit']:+.2f} EUR\n"
            f"<b>{snapshot['sample_stake']:.0f} EUR flat equivalent:</b> bankroll {snapshot['sample_bankroll']:.0f} EUR\n"
            f"{SEPARATOR}\n"
            f"<b>BY MARKET</b>\n"
            f"{by_market_text}\n"
            f"{SEPARATOR}\n"
            f"<b>Formula:</b> tracker uses {snapshot['tracked_stake']:.0f} EUR flat stakes; the bankroll example rescales the same units to {snapshot['sample_stake']:.0f} EUR flat."
        )
    return (
        f"<b>VIP PERFORMANCE REPORT</b>\n"
        f"{SEPARATOR}\n"
        f"<b>Settled signals:</b> {snapshot['settled_total']}\n"
        f"<b>WIN:</b> {snapshot['wins']} | <b>LOSS:</b> {snapshot['losses']}\n"
        f"<b>Win Rate:</b> {snapshot['win_rate']:.1f}%\n"
        f"<b>ROI:</b> {snapshot['roi']:.1f}%\n"
        f"<b>Units:</b> {snapshot['units']:+.2f}u (1u = {snapshot['tracked_stake']:.0f} EUR)\n"
        f"<b>Live profit (tracked @ {snapshot['tracked_stake']:.0f} EUR flat):</b> {snapshot['profit']:+.2f} EUR\n"
        f"<b>{snapshot['sample_stake']:.0f} EUR flat equivalent:</b> bankroll {snapshot['sample_bankroll']:.0f} EUR\n"
        f"{SEPARATOR}\n"
        f"<b>BY MARKET</b>\n"
        f"{by_market_text}\n"
        f"{SEPARATOR}\n"
        f"<b>Momentum:</b> the premium tracker keeps updating signal after signal"
    )
def format_x_post_copy() -> str:
    snapshot = compute_performance_snapshot()
    return (
        f"Oracle Performance Update\n\n"
        f"{snapshot['settled_total']} settled bets\n"
        f"Win Rate: {snapshot['win_rate']:.1f}%\n"
        f"ROI: {snapshot['roi']:+.1f}%\n"
        f"Units: {snapshot['units']:+.2f}u\n\n"
        f"Tracked stake: {snapshot['tracked_stake']:.0f} EUR flat (1u = {snapshot['tracked_stake']:.0f} EUR)\n"
        f"{snapshot['sample_stake']:.0f} EUR flat equivalent: {PERFORMANCE_STARTING_BANKROLL:.0f} -> {snapshot['sample_bankroll']:.0f} EUR\n\n"
        f"Telegram VIP for live signals.\n"
        f"#BettingTips #FootballBets #SportsBetting #TelegramVIP #ROI"
    )


def format_x_copy_message() -> str:
    x_post = escape_html(format_x_post_copy())
    return f"<b>X COPY READY</b>\n{SEPARATOR}\n<code>{x_post}</code>"


def format_x_promo_copy() -> str:
    snapshot = compute_performance_snapshot()
    market_label = get_market_label()
    filter_label = get_filter_label()
    variants = [
        (
            f"Oracle is a Telegram betting channel focused on live first-half football markets.\n\n"
            f"We track Over 0.5 HT and Over 1.5 HT with selective filters, live editing and performance tracking.\n"
            f"Current focus: {market_label} | {filter_label}.\n\n"
            f"Win Rate: {snapshot['win_rate']:.1f}% | ROI: {snapshot['roi']:+.1f}% | Units: {snapshot['units']:+.2f}u\n\n"
            f"Join the Telegram VIP for live signals.\n"
            f"#BettingTips #FootballBets #LiveBetting #TelegramVIP #SportsBetting"
        ),
        (
            f"What does Oracle do?\n\n"
            f"It scans live football, filters leagues, selects HT markets and updates every signal live inside Telegram.\n"
            f"No blind spam. Only structured setups with tracking, ROI and performance reports.\n\n"
            f"{snapshot['settled_total']} settled bets | Win Rate {snapshot['win_rate']:.1f}% | ROI {snapshot['roi']:+.1f}%\n\n"
            f"Telegram VIP available now.\n"
            f"#FootballTrading #BettingCommunity #TelegramChannel #ROI #SoccerBets"
        ),
        (
            f"Looking for a Telegram betting channel focused on live football?\n\n"
            f"Oracle works on filtered first-half opportunities, tracks results, edits outcomes live and keeps the feed clean.\n"
            f"Market focus: {market_label}.\n\n"
            f"Tracked on {snapshot['tracked_stake']:.0f} EUR flat stakes | {snapshot['sample_stake']:.0f} EUR flat equivalent bankroll: {snapshot['sample_bankroll']:.0f} EUR.\n\n"
            f"DM / join Telegram for VIP access.\n"
            f"#BettingX #FootballTips #LiveFootball #TelegramVIP #ProfitTracking"
        ),
    ]
    return random.choice(variants)


def format_x_promo_message() -> str:
    promo_text = escape_html(format_x_promo_copy())
    return f"<b>X PROMO COPY</b>\n{SEPARATOR}\n<code>{promo_text}</code>"


def maybe_send_performance_report() -> None:
    settled_total = sum(int(stats.get(tier, {}).get("v", 0)) + int(stats.get(tier, {}).get("p", 0)) for tier in [TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING])
    step = max(1, REPORT_EVERY_N_SETTLED)
    minimum = max(step, REPORT_MIN_SETTLED)
    if settled_total < minimum or settled_total % step != 0:
        return
    with state_lock:
        last_report_total = int(stats.get("last_performance_report_total", 0) or 0)
        if settled_total <= last_report_total:
            return
        stats["last_performance_report_total"] = settled_total
    delivery_plan = [
        (CHAT_ID, "admin"),
        (VIP_CHANNEL_ID, "vip"),
        (CHANNEL_ID, "free"),
    ]
    for chat_target, audience in delivery_plan:
        if not chat_target:
            continue
        try:
            report_text = format_performance_report(audience)
            bot.send_message(chat_target, report_text, parse_mode="HTML")
            if audience == "admin":
                bot.send_message(chat_target, format_x_copy_message(), parse_mode="HTML")
        except Exception as exc:
            print(f"Performance report delivery failed for {chat_target}: {exc}")
            log_event("PERFORMANCE_REPORT_FAIL", f"chat_target={chat_target} audience={audience} error={exc}")
    log_event("PERFORMANCE_REPORT", f"settled_total={settled_total} step={step} minimum={minimum}")

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

def format_ml_status() -> str:
    ensure_live_training_dataset()
    if not os.path.exists(TRAINER_DATA_FILE):
        return (
            "<b>ML STATUS</b>\n\n"
            f"Dataset not found: <code>{html.escape(TRAINER_DATA_FILE)}</code>"
        )

    try:
        with live_training_lock:
            df = pd.read_csv(TRAINER_DATA_FILE)
    except Exception as exc:
        return (
            "<b>ML STATUS</b>\n\n"
            f"Dataset read error: <code>{html.escape(str(exc))}</code>"
        )

    total_rows = len(df)
    settled_rows = int(df["Outcome"].isin(["WIN", "LOSS"]).sum()) if "Outcome" in df.columns else 0

    missing_features = [column for column in TRAINER_FEATURE_COLUMNS if column not in df.columns]
    if missing_features:
        full_feature_rows = 0
        full_feature_settled_rows = 0
        live_format_rows = 0
        live_format_settled_rows = 0
    else:
        full_feature_mask = df[TRAINER_FEATURE_COLUMNS].notna().all(axis=1)
        full_feature_rows = int(full_feature_mask.sum())
        settled_mask = df["Outcome"].isin(["WIN", "LOSS"]) if "Outcome" in df.columns else pd.Series([False] * len(df))
        full_feature_settled_rows = int((full_feature_mask & settled_mask).sum())
        live_format_mask = df[["AvgTotalGoals", "AvgHTGoals", "HomeAvgTotalGoals", "AwayAvgTotalGoals", "HomeAvgHTGoals", "AwayAvgHTGoals"]].notna().any(axis=1)
        live_format_rows = int(live_format_mask.sum())
        live_format_settled_rows = int((live_format_mask & settled_mask).sum())

    migrated_rows = max(0, total_rows - live_format_rows)
    migrated_settled_rows = max(0, settled_rows - live_format_settled_rows)

    candidate_exists = os.path.exists(CANDIDATE_MODEL_NAME)
    production_exists = os.path.exists(MODEL_PATH)
    active_model = MODEL_PATH if production_exists else (CANDIDATE_MODEL_NAME if candidate_exists else "none")

    last_retrain_total_rows = int(stats.get("last_retrain_total_rows", 0) or 0)
    last_retrain_settled_rows = int(stats.get("last_retrain_settled_rows", 0) or 0)
    last_retrain_full_feature_settled = int(stats.get("last_retrain_full_feature_settled", 0) or 0)

    new_rows_since_retrain = max(0, total_rows - last_retrain_total_rows)
    new_settled_since_retrain = max(0, settled_rows - last_retrain_settled_rows)
    new_full_feature_settled_since_retrain = max(0, full_feature_settled_rows - last_retrain_full_feature_settled)

    lines = [
        "<b>ML STATUS</b>",
        "",
        f"Dataset: <code>{html.escape(TRAINER_DATA_FILE)}</code>",
        f"Total rows: <b>{total_rows}</b>",
        f"Settled WIN/LOSS rows: <b>{settled_rows}</b>",
        f"Full-feature rows: <b>{full_feature_rows}</b>",
        f"Full-feature settled rows: <b>{full_feature_settled_rows}</b>",
        f"Candidate threshold: <b>{MIN_CANDIDATE_ROWS}</b>",
        f"Production threshold: <b>{MIN_PRODUCTION_ROWS}</b>",
        f"Candidate model present: <b>{'YES' if candidate_exists else 'NO'}</b>",
        f"Production model present: <b>{'YES' if production_exists else 'NO'}</b>",
        f"Active runtime model: <code>{html.escape(active_model)}</code>",
        f"Retrain running: <b>{'YES' if retrain_running else 'NO'}</b>",
        "",
        "<b>Dataset mix</b>",
        f"Migrated historical rows: <b>{migrated_rows}</b> | settled: <b>{migrated_settled_rows}</b>",
        f"New live-format rows: <b>{live_format_rows}</b> | settled: <b>{live_format_settled_rows}</b>",
        "",
        "<b>Since last retrain</b>",
        f"New rows: <b>{new_rows_since_retrain}</b>",
        f"New settled rows: <b>{new_settled_since_retrain}</b>",
        f"New full-feature settled rows: <b>{new_full_feature_settled_since_retrain}</b>",
    ]

    if missing_features:
        lines.extend([
            "",
            "Missing dataset features:",
            ", ".join(missing_features),
        ])
    elif total_rows:
        coverage_parts = []
        for column in TRAINER_FEATURE_COLUMNS:
            non_null = int(df[column].notna().sum())
            coverage = (non_null / total_rows) * 100 if total_rows else 0.0
            coverage_parts.append(f"{column} {coverage:.0f}%")
        lines.extend([
            "",
            "Feature coverage:",
            " | ".join(coverage_parts),
        ])

    if last_retrain_result:
        lines.extend([
            "",
            "Last retrain:",
            html.escape(last_retrain_result),
        ])

    return "\n".join(lines)

def run_retrain_from_bot() -> str:
    global oracle_brain
    global titan_pressure_brain
    global last_retrain_result

    try:
        with live_training_lock:
            result = train_oracle()
    except Exception as exc:
        logger.exception("RETRAIN_ERROR | error=%s", exc)
        last_retrain_result = f"Error: {exc}"
        return (
            "<b>RETRAIN</b>\n\n"
            f"Retrain failed: <code>{html.escape(str(exc))}</code>"
        )

    status = result.get("status", "error")
    if status != "ok":
        last_retrain_result = result.get("message", "Retrain failed.")
        return (
            "<b>RETRAIN</b>\n\n"
            f"{html.escape(result.get('message', 'Retrain failed.'))}\n"
            f"Settled rows available: <b>{int(result.get('rows', 0))}</b>"
        )

    mode = result.get("mode", "none")
    model_path = result.get("model_path", "")
    rows = int(result.get("rows", 0))
    validation = result.get("validation", {}) or {}

    try:
        with live_training_lock:
            df_metrics = pd.read_csv(TRAINER_DATA_FILE)
        retrain_total_rows = len(df_metrics)
        retrain_settled_rows = int(df_metrics["Outcome"].isin(["WIN", "LOSS"]).sum()) if "Outcome" in df_metrics.columns else 0
        retrain_full_feature_settled = 0
        if all(column in df_metrics.columns for column in TRAINER_FEATURE_COLUMNS) and "Outcome" in df_metrics.columns:
            retrain_full_feature_settled = int((df_metrics[TRAINER_FEATURE_COLUMNS].notna().all(axis=1) & df_metrics["Outcome"].isin(["WIN", "LOSS"])).sum())
    except Exception:
        retrain_total_rows = rows
        retrain_settled_rows = rows
        retrain_full_feature_settled = 0

    if mode == "production":
        try:
            oracle_brain = joblib.load(MODEL_PATH)
        except Exception as exc:
            logger.exception("RETRAIN_RELOAD_ERROR | error=%s", exc)
            last_retrain_result = f"Production saved but reload failed: {exc}"
            return (
                "<b>RETRAIN</b>\n\n"
                f"Production retrain completed, but reload failed: <code>{html.escape(str(exc))}</code>\n"
                f"Saved model: <code>{html.escape(model_path)}</code>"
            )

    sorted_features = sorted(
        result.get("feature_importances", {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    top_features = ", ".join(f"{name} {value:.2f}" for name, value in sorted_features[:4]) or "n/a"
    validation_line = ""
    if validation:
        validation_line = (
            f" | val acc {validation.get('accuracy', 0.0):.2f}"
            f" | val logloss {validation.get('log_loss', 0.0):.2f}"
        )
    last_retrain_result = f"{mode.upper()} | {rows} rows | {top_features}{validation_line}"
    with state_lock:
        stats["last_retrain_total_rows"] = retrain_total_rows
        stats["last_retrain_settled_rows"] = retrain_settled_rows
        stats["last_retrain_full_feature_settled"] = retrain_full_feature_settled
    salva_dati_web()
    logger.info(
        "RETRAIN_OK | mode=%s rows=%s model=%s top_features=%s validation=%s",
        mode,
        rows,
        model_path,
        top_features,
        validation,
    )

    validation_block = ""
    if validation:
        validation_block = (
            f"\n<b>Validation:</b> accuracy {validation.get('accuracy', 0.0):.3f}"
            f" | log loss {validation.get('log_loss', 0.0):.3f}"
            f" | rows {validation.get('rows', 0)}"
        )

    return (
        "<b>RETRAIN COMPLETED</b>\n\n"
        f"Mode: <b>{html.escape(mode.upper())}</b>\n"
        f"Settled rows used: <b>{rows}</b>\n"
        f"Saved model: <code>{html.escape(model_path)}</code>\n"
        f"{html.escape(result.get('message', ''))}\n"
        f"<b>Top features:</b> {html.escape(top_features)}"
        f"{validation_block}"
    )

def start_retrain_job(chat_id: int, starter_text: str = "ML retrain started in background. I will send the result here as soon as it finishes.") -> str:
    global retrain_running

    with state_lock:
        if retrain_running:
            return "Retrain already running. Please wait for the final message."
        retrain_running = True

    def retrain_worker():
        global retrain_running
        try:
            outcome_message = run_retrain_from_bot()
            bot.send_message(chat_id, outcome_message, parse_mode="HTML")
        except Exception as exc:
            logger.exception("RETRAIN_THREAD_ERROR | error=%s", exc)
            bot.send_message(chat_id, f"Retrain thread error: {exc}")
        finally:
            with state_lock:
                retrain_running = False

    thread = threading.Thread(target=retrain_worker, daemon=True, name="oracle-retrain")
    thread.start()
    return starter_text


def start_missing_team_backfill_job(
    chat_id: int,
    starter_text: str = "Missing-team backfill started in background. I will send the result here as soon as it finishes.",
    limit: int = 25,
    timeout_seconds: int = 600,
    process_all: bool = False,
) -> str:
    global backfill_running

    with state_lock:
        if backfill_running:
            return "Missing-team backfill already running. Please wait for the final message."
        backfill_running = True

    def backfill_worker():
        global backfill_running
        try:
            script_path = os.path.join(BASE_DIR, "api_football_missing_team_backfill.py")
            python_executable = sys.executable or os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
            current_year = datetime.now(timezone.utc).year
            batch_limit = max(1, min(int(limit), 100 if process_all else int(limit)))
            max_batches = 500 if process_all else 1
            per_batch_timeout = max(300, int(timeout_seconds))
            summaries = []
            overall_before = None
            last_pending = None

            for batch_index in range(1, max_batches + 1):
                before_counts = read_missing_team_queue_status_counts_from_disk()
                pending_before = int(before_counts.get("pending", 0) or 0)
                if overall_before is None:
                    overall_before = pending_before
                if pending_before <= 0:
                    summaries.append("Queue already clean. No pending missing-team items left.")
                    break

                command = [
                    python_executable,
                    script_path,
                    "--limit",
                    str(batch_limit),
                    "--season",
                    str(current_year - 1),
                    "--season",
                    str(current_year),
                ]

                try:
                    completed = subprocess.run(
                        command,
                        cwd=BASE_DIR,
                        capture_output=True,
                        text=True,
                        timeout=per_batch_timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    stdout = (exc.stdout or "").strip() if exc.stdout else ""
                    stderr = (exc.stderr or "").strip() if exc.stderr else ""
                    parts = [f"Batch {batch_index} timed out after {per_batch_timeout}s."]
                    if stdout:
                        parts.append(stdout[-1800:])
                    if stderr:
                        parts.append("STDERR:\n" + stderr[-1200:])
                    summaries.append("\n\n".join(parts))
                    break

                stdout = (completed.stdout or "").strip()
                stderr = (completed.stderr or "").strip()
                load_missing_team_queue()
                after_counts = read_missing_team_queue_status_counts_from_disk()
                pending_after = int(after_counts.get("pending", 0) or 0)
                resolved_delta = max(0, pending_before - pending_after)
                last_pending = pending_after

                batch_lines = [
                    f"Batch {batch_index}: rc={completed.returncode}",
                    f"Pending before: {pending_before}",
                    f"Pending after: {pending_after}",
                    f"Resolved this batch: {resolved_delta}",
                ]
                if stdout:
                    batch_lines.append(stdout[-1500:])
                if stderr:
                    batch_lines.append("STDERR:\n" + stderr[-1000:])
                summaries.append("\n\n".join(batch_lines))

                if not process_all:
                    break
                if completed.returncode != 0:
                    break
                if "No eligible missing-team items to process." in stdout:
                    break
                if pending_after <= 0:
                    break
                if pending_after >= pending_before:
                    summaries.append(
                        f"Stopping after batch {batch_index}: no queue progress detected."
                    )
                    break

            total_pending_before = overall_before if overall_before is not None else 0
            total_pending_after = last_pending if last_pending is not None else total_pending_before
            resolved_total = max(0, total_pending_before - total_pending_after)
            title = "MISSING-TEAM BACKFILL COMPLETED"
            if process_all:
                title = "MISSING-TEAM BACKFILL ALL COMPLETED"
            final_body = [
                f"Initial pending queue items: {total_pending_before}",
                f"Pending queue items now: {total_pending_after}",
                f"Resolved in this run: {resolved_total}",
            ]
            if summaries:
                final_body.append("\n\n".join(summaries[-4:]))
            send_html_message_safe(chat_id, f"<b>{title}</b>\n\n<code>{escape_html(chr(10).join(final_body)[-3500:])}</code>")
        except Exception as exc:
            logger.exception("BACKFILL_THREAD_ERROR | error=%s", exc)
            bot.send_message(chat_id, f"Missing-team backfill thread error: {exc}")
        finally:
            with state_lock:
                backfill_running = False

    thread = threading.Thread(target=backfill_worker, daemon=True, name="oracle-backfill")
    thread.start()
    return starter_text


def start_prematch_today_job(
    chat_id: int,
    requested_date: str | None = None,
    starter_text: str = "Pre-match scan started in background. I will send the suspicious matches of the day here as soon as the backend finishes.",
) -> str:
    global prematch_running

    with state_lock:
        if prematch_running:
            return "Pre-match suspicious scan already running. Please wait for the final message."
        prematch_running = True

    def prematch_worker():
        global prematch_running
        try:
            with prematch_backend_lock:
                result = run_prematch_bot_scan(date_value=requested_date)
            with state_lock:
                stats["prematch_last_report"] = {
                    "date": result.date_value,
                    "chat_id": str(chat_id),
                    "fixture_ids": [outcome.fixture_id for outcome in result.summary.outcomes],
                }
                salva_dati_web()
            send_html_message_safe(chat_id, format_prematch_today_report(result))
        except Exception as exc:
            logger.exception("PREMATCH_THREAD_ERROR | error=%s", exc)
            bot.send_message(chat_id, f"Prematch thread error: {exc}")
        finally:
            with state_lock:
                prematch_running = False

    thread = threading.Thread(target=prematch_worker, daemon=True, name="oracle-prematch")
    thread.start()
    return starter_text


def prematch_auto_collect_loop() -> None:
    if not PREMATCH_AUTO_COLLECT_ENABLED:
        logger.info("PREMATCH_AUTO_COLLECT_DISABLED")
        return

    interval_seconds = max(120, int(PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS or 600))
    page_limit = max(1, int(PREMATCH_AUTO_COLLECT_PAGE_LIMIT or 3))

    while not shutdown_requested:
        try:
            acquired = prematch_backend_lock.acquire(blocking=False)
            if acquired:
                try:
                    result = collect_prematch_snapshots(page_limit=page_limit)
                    logger.info(
                        "PREMATCH_AUTO_COLLECT_OK | date=%s odds_rows=%s snapshots_saved=%s fixtures_seen=%s page_limit=%s",
                        result.date_value,
                        result.odds_rows,
                        result.snapshots_saved,
                        result.fixtures_seen,
                        page_limit,
                    )
                finally:
                    prematch_backend_lock.release()
            else:
                logger.info("PREMATCH_AUTO_COLLECT_SKIPPED | reason=backend_busy")
        except Exception as exc:
            logger.exception("PREMATCH_AUTO_COLLECT_ERROR | error=%s", exc)
        time.sleep(interval_seconds)


def prematch_watch_loop() -> None:
    while not shutdown_requested:
        try:
            with state_lock:
                watch = dict(stats.get("prematch_watch") or default_prematch_watch_state())
            if not watch.get("active"):
                time.sleep(60)
                continue

            chat_id = watch.get("chat_id")
            watch_date = watch.get("date") or current_date_key()
            fixture_ids = list(dict.fromkeys(watch.get("fixture_ids") or []))
            interval_seconds = max(300, int(watch.get("interval_seconds") or 300))
            last_sent_utc = str(watch.get("last_sent_utc") or "").strip()
            baseline_ready = bool(watch.get("baseline_ready"))
            previous_snapshot = watch.get("last_snapshot") or {}
            if last_sent_utc:
                try:
                    last_sent_dt = datetime.fromisoformat(last_sent_utc)
                    elapsed = (now_utc() - last_sent_dt).total_seconds()
                    if elapsed < interval_seconds:
                        time.sleep(60)
                        continue
                except ValueError:
                    pass

            if not chat_id or not fixture_ids:
                with state_lock:
                    stats["prematch_watch"] = default_prematch_watch_state()
                    salva_dati_web()
                time.sleep(60)
                continue

            with prematch_backend_lock:
                result = run_prematch_bot_scan(date_value=watch_date, top=50)
            current_snapshot = build_prematch_watch_snapshot(result, fixture_ids)
            message_text = None
            if baseline_ready:
                message_text = format_prematch_watch_delta(
                    date_value=result.date_value,
                    previous_snapshot=previous_snapshot,
                    current_snapshot=current_snapshot,
                    watched_fixture_ids=fixture_ids,
                )
            with state_lock:
                current_watch = stats.get("prematch_watch") or default_prematch_watch_state()
                if current_watch.get("active"):
                    current_watch["last_snapshot"] = current_snapshot
                    current_watch["baseline_ready"] = True
                    current_watch["last_sent_utc"] = now_utc().isoformat()
                    stats["prematch_watch"] = current_watch
                    salva_dati_web()
            if message_text:
                send_html_message_safe(chat_id, message_text)
        except Exception as exc:
            logger.exception("PREMATCH_WATCH_LOOP_ERROR | error=%s", exc)
        time.sleep(60)


def get_local_dashboard_url(port: int = 8501) -> str:
    host = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0] or host
    except Exception:
        try:
            fallback = socket.gethostbyname(socket.gethostname())
            if fallback and not fallback.startswith("127."):
                host = fallback
        except Exception:
            pass
    return f"http://{host}:{port}"


def find_ngrok_executable() -> str | None:
    candidates = [
        os.path.join(BASE_DIR, "ngrok.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "ngrok.exe"),
        r"C:\Tools\ngrok\ngrok.exe",
        r"C:\Program Files\ngrok\ngrok.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("ngrok")


def extract_ngrok_public_url(api_url: str = "http://127.0.0.1:4040/api/tunnels") -> str | None:
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    tunnels = payload.get("tunnels", []) if isinstance(payload, dict) else []
    for tunnel in tunnels:
        public_url = str(tunnel.get("public_url", ""))
        if public_url.startswith("https://"):
            return public_url
    for tunnel in tunnels:
        public_url = str(tunnel.get("public_url", ""))
        if public_url.startswith("http://"):
            return public_url
    return None


def start_dashboard_web_job(chat_id: int, port: int = 8501) -> str:
    global dashboard_process
    with state_lock:
        running_process = dashboard_process if dashboard_process and dashboard_process.poll() is None else None
        if running_process is not None:
            return f"Dashboard already running: {get_local_dashboard_url(port)}"
    try:
        python_executable = sys.executable or os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
        dashboard_script = os.path.join(BASE_DIR, "dashboard.py")
        command = [
            python_executable,
            "-m",
            "streamlit",
            "run",
            dashboard_script,
            "--server.address",
            "0.0.0.0",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ]
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with state_lock:
            dashboard_process = process
        dashboard_url = get_local_dashboard_url(port)
        return (
            f"Dashboard web started.\n\n"
            f"Open this link on your phone: {dashboard_url}\n\n"
            f"Phone and PC must be on the same Wi-Fi network."
        )
    except Exception as exc:
        logger.exception("DASHBOARD_WEB_START_ERROR | error=%s", exc)
        return f"Dashboard web start failed: {exc}"


def start_dashboard_public_job(chat_id: int, port: int = 8501) -> str:
    global ngrok_process
    local_message = start_dashboard_web_job(chat_id, port)
    ngrok_path = find_ngrok_executable()
    if not ngrok_path:
        return (
            f"{local_message}\n\n"
            "ngrok not found. Install it or place ngrok.exe in Downloads or C:\\Tools\\ngrok, then retry /dashboard_public."
        )

    with state_lock:
        running_ngrok = ngrok_process if ngrok_process and ngrok_process.poll() is None else None
        if running_ngrok is not None:
            public_url = extract_ngrok_public_url()
            if public_url:
                return f"Public dashboard already running.\n\nOpen this link: {public_url}"
            return "Public dashboard tunnel already running, but the URL is not available yet. Retry in a few seconds."

    try:
        process = subprocess.Popen(
            [ngrok_path, "http", str(port), "--log", "stdout"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with state_lock:
            ngrok_process = process
        for _ in range(10):
            time.sleep(1)
            public_url = extract_ngrok_public_url()
            if public_url:
                return (
                    "Public dashboard started.\n\n"
                    f"Open this link anywhere: {public_url}\n\n"
                    f"Local link: {get_local_dashboard_url(port)}"
                )
        return (
            "ngrok started, but the public URL is not ready yet.\n\n"
            "Open the local dashboard first, then retry /dashboard_public in 5-10 seconds."
        )
    except Exception as exc:
        logger.exception("DASHBOARD_PUBLIC_START_ERROR | error=%s", exc)
        return f"Public dashboard start failed: {exc}"


def restart_dashboard_job(chat_id: int, public: bool = False, port: int = 8501) -> str:
    global dashboard_process, ngrok_process

    stopped = []
    with state_lock:
        current_dashboard = dashboard_process
        dashboard_process = None
        current_ngrok = ngrok_process
        ngrok_process = None

    for name, process in (("dashboard", current_dashboard), ("ngrok", current_ngrok)):
        if process is None:
            continue
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except Exception:
                    process.kill()
            stopped.append(name)
        except Exception as exc:
            logger.exception("DASHBOARD_RESTART_STOP_ERROR | target=%s error=%s", name, exc)

    base_message = "Dashboard restarted from scratch."
    if stopped:
        base_message = f"Dashboard restarted from scratch. Stopped: {', '.join(stopped)}."

    if public:
        started_message = start_dashboard_public_job(chat_id, port)
    else:
        started_message = start_dashboard_web_job(chat_id, port)
    return f"{base_message}\n\n{started_message}"

def get_total_settled_count() -> int:
    return sum(
        int(stats.get(tier, {}).get("v", 0)) + int(stats.get(tier, {}).get("p", 0))
        for tier in [TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING]
    )


def maybe_trigger_auto_retrain() -> None:
    step = max(0, AUTO_RETRAIN_EVERY_N_SETTLED)
    if step <= 0:
        return

    settled_total = get_total_settled_count()
    if settled_total < step:
        return

    with state_lock:
        last_auto_total = int(stats.get("last_auto_retrain_total", 0) or 0)
    if settled_total - last_auto_total < step:
        return

    started_message = start_retrain_job(
        CHAT_ID,
        f"Auto ML retrain started after {settled_total} settled signals.",
    )
    if started_message.startswith("Retrain already running"):
        return

    with state_lock:
        stats["last_auto_retrain_total"] = settled_total
    salva_dati_web()
    log_event("AUTO_RETRAIN_START", f"settled_total={settled_total} step={step}")
    if CHAT_ID:
        bot.send_message(CHAT_ID, started_message)

def send_daily_recap_if_due() -> None:
    ensure_daily_analytics()
    now = now_utc()
    date_key = current_date_key()
    if (now.hour, now.minute) < (RECAP_HOUR_UTC, RECAP_MINUTE_UTC):
        return

    with state_lock:
        recap_delivery = stats.get("recap_delivery") or default_recap_delivery(date_key)
        if recap_delivery.get("date_utc") != date_key:
            recap_delivery = default_recap_delivery(date_key)
            stats["recap_delivery"] = recap_delivery
            stats["last_recap_date_utc"] = ""

    delivery_plan = [
        ("admin", CHAT_ID, format_admin_recap),
        ("vip", VIP_CHANNEL_ID, format_vip_recap),
        ("free", CHANNEL_ID, format_free_recap),
    ]

    changed = False
    for audience, chat_target, formatter in delivery_plan:
        if not chat_target:
            with state_lock:
                recap_delivery = stats.get("recap_delivery") or default_recap_delivery(date_key)
                recap_delivery[audience] = True
                stats["recap_delivery"] = recap_delivery
                changed = True
            continue

        with state_lock:
            recap_delivery = stats.get("recap_delivery") or default_recap_delivery(date_key)
            already_sent = recap_delivery.get(audience, False)
        if already_sent:
            continue

        bot.send_message(chat_target, formatter(), parse_mode="HTML")
        with state_lock:
            recap_delivery = stats.get("recap_delivery") or default_recap_delivery(date_key)
            recap_delivery[audience] = True
            stats["recap_delivery"] = recap_delivery
            changed = True

    with state_lock:
        recap_delivery = stats.get("recap_delivery") or default_recap_delivery(date_key)
        required_done = recap_delivery.get("admin", False) and recap_delivery.get("vip", False) and recap_delivery.get("free", False)
        if required_done:
            stats["last_recap_date_utc"] = date_key
            changed = True
    if changed:
        salva_dati_web()


def recap_loop() -> None:
    while not shutdown_requested:
        try:
            send_daily_recap_if_due()
        except Exception as exc:
            print(f"recap_loop error: {exc}")
        time.sleep(60)

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

def fetch_next_goal_live_odds(fixture_id: int, headers: dict):
    cache_key = "ng_odds_" + str(fixture_id)
    now_ts = time.time()
    cached = fixture_stats_cache.get(cache_key)
    if isinstance(cached, dict) and now_ts - float(cached.get("ts", 0.0)) < 60:
        return cached.get("data")
    try:
        response = requests.get(
            "https://v3.football.api-sports.io/odds/live",
            headers=headers, params={"fixture": fixture_id, "bet": 5}, timeout=10,
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


def get_min_quota_for_tier(tier: str) -> float:
    return {"APPROVED": 1.90, "CAUTION": 1.70, "GAMBLING": 1.75, "LEARNING": 1.75}.get(tier, 1.75)


def predict_titan_pressure_prob(dna: float, minute_value: int, score_diff: int, total_goals: int, stats_payload: dict):
    if titan_pressure_brain is None or not isinstance(stats_payload, dict):
        return None
    try:
        model_feature_columns = list(getattr(titan_pressure_brain, "feature_names_in_", TITAN_PRESSURE_FEATURE_COLUMNS))
        feature_values = {
            "DNAxG": dna,
            "Minute": minute_value,
            "ScoreDiff": score_diff,
            "TotalGoalsAtSignal": total_goals,
            "TotalShots": float(stats_payload.get("total_shots", 0.0) or 0.0),
            "ShotsOnGoal": float(stats_payload.get("shots_on_goal", 0.0) or 0.0),
            "DangerousAttacks": float(stats_payload.get("dangerous_attacks", 0.0) or 0.0),
            "Corners": float(stats_payload.get("corners", 0.0) or 0.0),
            "PossessionDiff": float(stats_payload.get("possession_diff", 0.0) or 0.0),
            "RedCardsHome": float(stats_payload.get("red_cards_home", 0.0) or 0.0),
            "RedCardsAway": float(stats_payload.get("red_cards_away", 0.0) or 0.0),
        }
        x_input = pd.DataFrame([[feature_values.get(column, 0.0) for column in model_feature_columns]], columns=model_feature_columns)
        return float(titan_pressure_brain.predict_proba(x_input)[0][1])
    except Exception as exc:
        logger.exception("TITAN_PRESSURE_PREDICT_ERROR | error=%s", exc)
        return None

def evaluate_titan_soft_layer(stats_payload: dict, market: str, minute_value: int, total_goals: int) -> dict:
    if not isinstance(stats_payload, dict):
        return {"promote": False, "label": "", "score": 0}

    red_cards = float(stats_payload.get("red_cards", 0.0) or 0.0)
    shots_on_goal = float(stats_payload.get("shots_on_goal", 0.0) or 0.0)
    total_shots = float(stats_payload.get("total_shots", 0.0) or 0.0)
    corners = float(stats_payload.get("corners", 0.0) or 0.0)

    score = 0
    promote = False
    if market == MARKET_OVER05_HT:
        if shots_on_goal >= 2:
            score += 1
        if total_shots >= 7:
            score += 1
        if corners >= 2:
            score += 1
        if minute_value <= 20 and total_shots >= 5:
            score += 1
        promote = red_cards == 0 and score >= 3
    elif market == MARKET_OVER15_HT:
        if total_goals != 1:
            return {"promote": False, "label": "", "score": 0}
        if shots_on_goal >= 3:
            score += 1
        if total_shots >= 9:
            score += 1
        if corners >= 3:
            score += 1
        if minute_value <= 25 and shots_on_goal >= 2:
            score += 1
        promote = red_cards == 0 and score >= 3

    label = f"titan pressure {int(score)}/4 | sog {int(shots_on_goal)} | shots {int(total_shots)} | corners {int(corners)}"
    return {"promote": promote, "label": label, "score": score}


def has_live_pressure_data(stats_payload: dict) -> bool:
    if not isinstance(stats_payload, dict):
        return False
    return any(float(stats_payload.get(key, 0.0) or 0.0) > 0 for key in ["shots_on_goal", "total_shots", "corners", "dangerous_attacks"])

def get_xg_rate(stats_payload: dict, minute_value: int) -> float:
    if not isinstance(stats_payload, dict) or minute_value <= 0:
        return 0.0
    xg_h = float(stats_payload.get("xg_home", 0.0) or 0.0)
    xg_a = float(stats_payload.get("xg_away", 0.0) or 0.0)
    return round((xg_h + xg_a) / max(1, minute_value), 4)


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

def stop_radar() -> None:
    global running
    running = False
    log_event('RADAR_STOP', 'Radar paused by admin')


def request_shutdown() -> None:
    global running, shutdown_requested
    running = False
    shutdown_requested = True
    log_event('BOT_SHUTDOWN', 'Shutdown requested by admin')
    try:
        bot.stop_polling()
    except Exception as exc:
        print(f"stop_polling fallito: {exc}")


def build_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("AVVIA AI RADAR", "STOP")
    kb.add("DASHBOARD", "ADMIN PANEL")
    kb.add("ML STATUS", "PREMATCH OGGI")
    kb.add("PREMATCH WATCH ON", "PREMATCH WATCH OFF")
    kb.add("MENU FILTRI", "MENU MARKET")
    kb.add('MENU VIP', 'COMANDI')
    kb.add('LEGEND')
    return kb


def build_filter_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("FILTRO TOP 10", "FILTRO SERIE A/B")
    kb.add("FILTRO GLOBAL ALL-IN", "FILTRO ATTUALE")
    kb.add("INDIETRO")
    return kb


def build_market_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("MARKET O0.5 HT", "MARKET O1.5 HT")
    kb.add("MARKET BOTH HT", "MARKET NEXT GOAL")
    kb.add("MARKET HT + NEXT", "MARKET ATTUALE")
    kb.add("INDIETRO")
    return kb


def build_vip_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("VIP ACCESS", "VIP STATUS")
    kb.add("X COPY", "X PROMO")
    kb.add("INDIETRO")
    return kb

def format_commands_help() -> str:
    return (
        "<b>Oracle Bot - Command Guide</b>\n\n"
        "<b>Home</b>\n"
        "AVVIA AI RADAR: start live scanning.\n"
        "STOP: pause the radar only.\n"
        "DASHBOARD: show bankroll, active filter and active market.\n"
        "ADMIN PANEL: opens KPIs, payments and member stats.\n"
        "ML STATUS: shows ML dataset and model status.\n"
        "PREMATCH OGGI or /prematch_today: fetch suspicious pre-match fixtures for the day with explanations.\n"
        "/prematch_watch_start: monitor the latest prematch shortlist every 5 minutes.\n"
        "/prematch_watch_stop: stop prematch updates.\n"
        "PREMATCH WATCH ON: start 5-minute prematch monitoring from the latest shortlist.\n"
        "PREMATCH WATCH OFF: stop prematch monitoring.\n"
        "RADARCHECK or /radarcheck: show live matches and why they are skipped or accepted.\n/backfill_missing: run a standard missing-team API backfill in background.\n/backfill_missing_all: process the whole eligible missing-team queue in background.\n\n"
        "<b>Menus</b>\n"
        "MENU FILTRI: open league filter presets.\n"
        "MENU MARKET: open available HT and next-goal markets.\n"
        "MENU VIP: open quick VIP actions.\n"
        "INDIETRO: return to the bot home.\n\n"
        "<b>League filters</b>\n"
        "FILTRO TOP 10: top 10 European leagues only.\n"
        "FILTRO SERIE A/B: top-10 first and second divisions only.\n"
        "FILTRO GLOBAL ALL-IN: global scan with U23 leagues included.\n"
        "FILTRO ATTUALE: show the active filter.\n\n"
        "<b>Markets</b>\n"
        "MARKET O0.5 HT: Over 0.5 first half only.\n"
        "MARKET O1.5 HT: Over 1.5 first half only.\n"
        "MARKET BOTH HT: monitor both HT markets.\n"
        "MARKET NEXT GOAL: monitor the next-goal live engine.\n"
        "MARKET HT + NEXT: monitor both HT markets plus Next Goal Live.\n"
        "MARKET ATTUALE: show the active market.\n\n"
        "<b>VIP and admin</b>\n"
        "VIP ACCESS: start the VIP purchase flow.\n"
        "VIP STATUS: show VIP status and expiry.\n"
        "X COPY or /xcopy: copy-ready text for X.\n"
        "X PROMO or /xpromo: random promo copy for X.\n"
        "/analytics: daily analytics summary.\n"
        "/admin: full admin panel.\n"
        "/ml_status: dataset and ML model status.\n"
        "/dashboard_web: start the mobile dashboard and send the local link.\n"
        "/dashboard_public: start the public dashboard and send the ngrok link.\n"
        "/dashboard_restart: restart Streamlit and relaunch the dashboard link.\n"
        "/retrain: trigger model retraining from the bot.\n"
        "/shutdown: turn the bot off completely.\n\n"
        "<b>Support</b>\n"
        "COMANDI or /help: show this guide.\n"
        "LEGEND or /legend: explain signal labels and values.\n"
        "/paysupport: show the payment support contact."
    )

def create_vip_invite_link(user_id: int):
    if not VIP_CHANNEL_ID:
        return None
    expire_at = int((now_utc() + timedelta(days=2)).timestamp())
    try:
        invite = bot.create_chat_invite_link(
            VIP_CHANNEL_ID,
            name=f"vip-{user_id}",
            expire_date=expire_at,
            member_limit=1,
            creates_join_request=False,
        )
        return getattr(invite, "invite_link", None)
    except Exception as exc:
        print(f"Errore creazione invite link VIP: {exc}")
        return None


def sync_vip_memberships(force: bool = False) -> None:
    global last_vip_sync_ts
    if not VIP_CHANNEL_ID:
        return
    current_ts = time.time()
    if not force and current_ts - last_vip_sync_ts < VIP_SYNC_INTERVAL_SECONDS:
        return

    for member in membership_store.get_members_expiring_within(max(1, RENEWAL_REMINDER_DAYS)):
        user_id = member["user_id"]
        try:
            bot.send_message(user_id, f"Il tuo accesso VIP scade presto ({member.get('expires_at')}). Usa /vip per rinnovare ora.")
            membership_store.mark_reminder_sent(user_id)
            increment_analytics("renewal_reminders_sent")
            log_event('VIP_RENEWAL_REMINDER', f"user_id={user_id} expires_at={member.get('expires_at')}")
        except Exception as exc:
            print(f"Reminder rinnovo fallito per {user_id}: {exc}")

    expired_members = membership_store.get_expired_active_members()
    for member in expired_members:
        user_id = member["user_id"]
        try:
            chat_member = bot.get_chat_member(VIP_CHANNEL_ID, user_id)
            status = getattr(chat_member, "status", "")
            if status not in {"left", "kicked"}:
                bot.ban_chat_member(VIP_CHANNEL_ID, user_id, revoke_messages=False)
                bot.unban_chat_member(VIP_CHANNEL_ID, user_id, only_if_banned=True)
        except Exception as exc:
            print(f"Sync VIP fallita per {user_id}: {exc}")
        membership_store.mark_revoked(user_id)
        log_event('VIP_REVOKED', f"user_id={user_id} expires_at={member.get('expires_at')}")
        try:
            bot.send_message(user_id, "Il tuo accesso VIP e scaduto. Usa /vip per rinnovare.")
        except Exception:
            pass

    last_vip_sync_ts = current_ts


def vip_sync_loop() -> None:
    while not shutdown_requested:
        try:
            sync_vip_memberships(force=True)
        except Exception as exc:
            print(f"Errore vip_sync_loop: {exc}")
        time.sleep(VIP_SYNC_INTERVAL_SECONDS)


def send_vip_invoice(message) -> None:
    if not is_private_chat(message):
        bot.reply_to(message, "Per acquistare il VIP scrivimi in privato e usa /vip")
        return
    if not VIP_CHANNEL_ID:
        bot.reply_to(message, "VIP non configurato. Imposta VIP_CHANNEL_ID e riprova.")
        return

    payload = f"vip:{message.from_user.id}:{int(time.time())}"
    membership_store.create_invoice(payload, message.from_user.id, VIP_PLAN_CODE, VIP_PLAN_NAME, VIP_PRICE_XTR, "XTR")
    prices = [types.LabeledPrice(VIP_PLAN_NAME, VIP_PRICE_XTR)]
    bot.send_invoice(
        message.chat.id,
        title="Oracle VIP Access",
        description=f"Accesso VIP per {VIP_DURATION_DAYS} giorni al canale premium Oracle.",
        invoice_payload=payload,
        provider_token=None,
        currency="XTR",
        prices=prices,
        start_parameter="oracle-vip",
    )


def format_member_status(member) -> str:
    if not member:
        return "Nessun abbonamento VIP attivo. Usa /vip per iniziare."
    return (
        f"Plan: {member.get('plan_name', VIP_PLAN_NAME)}\n"
        f"Stato: {member.get('status', 'unknown')}\n"
        f"Expires UTC: {member.get('expires_at', '-') }"
    )


def handle_vip_status(message) -> None:
    if not is_private_chat(message):
        bot.reply_to(message, "Apri il bot in privato e usa /vip_status")
        return
    member = membership_store.get_member(message.from_user.id)
    bot.send_message(message.chat.id, format_member_status(member))


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
    global running
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_KEY}

    while running and not shutdown_requested:
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


                if oracle_brain is None:
                    scan_debug["no_model"] += len(prioritized_markets)
                    continue

                stats_payload = fetch_fixture_stats(fixture_id, headers)
                shots_on_goal_at_open = float(stats_payload.get("shots_on_goal", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                total_shots_at_open = float(stats_payload.get("total_shots", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                corners_at_open = float(stats_payload.get("corners", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                red_cards_at_open = float(stats_payload.get("red_cards", 0.0) or 0.0) if isinstance(stats_payload, dict) else 0.0
                dna = combined_metrics["avg_total_goals"]
                model_feature_columns = list(getattr(oracle_brain, "feature_names_in_", TRAINER_FEATURE_COLUMNS))
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
                    }
                    x_input = pd.DataFrame([[model_feature_values.get(column, 0.0) for column in model_feature_columns]], columns=model_feature_columns)
                    prob = oracle_brain.predict_proba(x_input)[0][1]
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
                    effective_threshold = oracle_v2_threshold + (xg_threshold_bonus if market == MARKET_NEXT_GOAL else ht_threshold_bonus)
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

                        with state_lock:
                            stats["segnali_inviati"].append(signal_key)
                        increment_analytics("signals_total")
                        increment_analytics("signals_by_tier", tier=tier)
                        increment_breakdown_counter("signals_by_market", market)
                        increment_breakdown_counter("signals_by_league", league_name)
                        increment_breakdown_counter("signals_by_minute_bucket", minute_bucket)
                        live_odd = None
                        if market == MARKET_NEXT_GOAL:
                            live_odd = fetch_next_goal_live_odds(fixture_id, headers)
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


@bot.message_handler(commands=["shutdown"])
def shutdown_cmd(message):
    if not require_admin_access(message):
        return
    request_shutdown()
    bot.send_message(message.chat.id, "Shutdown completed. The process will now close.")

@bot.message_handler(commands=["start"])
def start_cmd(message):
    if not is_admin_message(message):
        return
    bot.send_message(
        message.chat.id,
        f"Oracle Sniper online. Filter: {get_filter_label()} | Market: {get_market_label()}",
        reply_markup=build_main_keyboard(),
    )

@bot.message_handler(commands=["dashboard_web"])
def dashboard_web_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, start_dashboard_web_job(message.chat.id))

@bot.message_handler(commands=["dashboard_public"])
def dashboard_public_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, start_dashboard_public_job(message.chat.id))

@bot.message_handler(commands=["dashboard_restart"])
def dashboard_restart_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, restart_dashboard_job(message.chat.id, public=True))

@bot.message_handler(commands=["vip"])
def vip_cmd(message):
    if not require_admin_access(message):
        return
    send_vip_invoice(message)


@bot.message_handler(commands=["vip_status"])
def vip_status_cmd(message):
    if not require_admin_access(message):
        return
    handle_vip_status(message)


@bot.message_handler(commands=["paysupport"])
def paysupport_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, f"Payment support: {VIP_SUPPORT_CONTACT}")


@bot.message_handler(commands=["analytics"])
def analytics_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_analytics_text())


@bot.message_handler(commands=["admin"])
def admin_cmd(message):
    if not require_admin_access(message, "Admin panel is not available in this chat."):
        return
    send_html_message_safe(message.chat.id, format_admin_panel())
@bot.message_handler(commands=["radarcheck"])
def radarcheck_cmd(message):
    if not require_admin_access(message):
        return
    send_html_message_safe(message.chat.id, format_radar_check_text())

@bot.message_handler(commands=["prematch_today"])
def prematch_today_cmd(message):
    if not require_admin_access(message):
        return
    requested_date = extract_requested_date(getattr(message, "text", ""))
    if getattr(message, "text", "") and len(str(message.text).strip().split()) >= 2 and requested_date is None:
        bot.send_message(message.chat.id, "Use /prematch_today or /prematch_today YYYY-MM-DD")
        return
    bot.send_message(message.chat.id, start_prematch_today_job(message.chat.id, requested_date=requested_date))


@bot.message_handler(commands=["prematch_watch_start"])
def prematch_watch_start_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, activate_prematch_watch(message.chat.id))


@bot.message_handler(commands=["prematch_watch_stop"])
def prematch_watch_stop_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, stop_prematch_watch())

@bot.message_handler(commands=["ml_status"])
def ml_status_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_ml_status(), parse_mode="HTML")

@bot.message_handler(commands=["retrain"])
def retrain_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, start_retrain_job(message.chat.id))

@bot.message_handler(commands=["backfill_missing"])
def backfill_missing_cmd(message):
    if not require_admin_access(message):
        return
    reply = start_missing_team_backfill_job(message.chat.id) or "Missing-team backfill started in background."
    bot.send_message(message.chat.id, reply)

@bot.message_handler(commands=["backfill_missing_all"])
def backfill_missing_all_cmd(message):
    if not require_admin_access(message):
        return
    reply = start_missing_team_backfill_job(
        message.chat.id,
        starter_text="Full missing-team backfill started in background in multiple batches. I will send the final result here when the queue run stops.",
        limit=100,
        timeout_seconds=1200,
        process_all=True,
    ) or "Full missing-team backfill started in background."
    bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=["xcopy"])
def xcopy_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_x_copy_message(), parse_mode="HTML")


@bot.message_handler(commands=["xpromo"])
def xpromo_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_x_promo_message(), parse_mode="HTML")


@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_handler(pre_checkout_query):
    invoice = membership_store.get_invoice(pre_checkout_query.invoice_payload)
    if not invoice or invoice.get("user_id") != pre_checkout_query.from_user.id:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Invalid payment. Please retry from /vip")
        return
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=["successful_payment"])
def successful_payment_handler(message):
    if not is_admin_message(message):
        return
    payment = message.successful_payment
    payload = payment.invoice_payload
    invoice = membership_store.get_invoice(payload)
    if not invoice:
        bot.send_message(message.chat.id, "Payment received, but the order was not found. Please contact support.")
        return

    charge_id = getattr(payment, "telegram_payment_charge_id", "")
    membership_store.mark_invoice_paid(payload, charge_id)
    expires_at = (now_utc() + timedelta(days=VIP_DURATION_DAYS)).isoformat()
    invite_link = create_vip_invite_link(message.from_user.id)
    increment_analytics("vip_payments_count")
    increment_analytics("vip_revenue_xtr", VIP_PRICE_XTR)
    log_event("VIP_PAYMENT_OK", f"user_id={message.from_user.id} payload={payload} xtr={VIP_PRICE_XTR} expires_at={expires_at}")
    membership_store.activate_membership(
        user_id=message.from_user.id,
        username=getattr(message.from_user, "username", None),
        first_name=getattr(message.from_user, "first_name", None),
        plan_code=VIP_PLAN_CODE,
        plan_name=VIP_PLAN_NAME,
        expires_at=expires_at,
        payload=payload,
        charge_id=charge_id,
        invite_link=invite_link,
    )

    reply = (
        f"Payment confirmed.\n"
        f"Plan: {VIP_PLAN_NAME}\n"
        f"Expires UTC: {expires_at}\n"
    )
    if invite_link:
        reply += f"Link VIP: {invite_link}\n"
    else:
        reply += "Invite link unavailable. Please contact support.\n"
    reply += f"Support: {VIP_SUPPORT_CONTACT}"
    bot.send_message(message.chat.id, reply)


@bot.message_handler(func=lambda message: message.text == "AVVIA AI RADAR")
def go_cmd(message):
    global running
    if not require_admin_access(message):
        return
    if not running:
        running = True
        threading.Thread(target=radar_loop, daemon=True).start()
        bot.send_message(message.chat.id, f"Radar online. Filter: {get_filter_label()} | Market: {get_market_label()}")
    else:
        bot.send_message(message.chat.id, f"Radar already running. Filter: {get_filter_label()} | Market: {get_market_label()}")


@bot.message_handler(func=lambda message: message.text == "DASHBOARD")
def dash_cmd(message):
    if not require_admin_access(message):
        return
    testo = (
        f"Current bankroll: {stats['total_profit']} EUR\n"
        f"Current filter: {get_filter_label()}\n"
        f"Active market: {get_market_label()}\n"
        f"Matches analyzed: {stats['matches_analyzed']}\n"
        f"Top missing teams: {get_top_team_not_found()}\n"
        f"Missing-team queue: {get_missing_team_queue_count()}\n"
        f"Free channel: all public tiers with delay {max(0, FREE_DELAY_SECONDS)}s"
    )
    bot.send_message(message.chat.id, testo)


@bot.message_handler(func=lambda message: message.text == "STOP")
def stop_cmd(message):
    if not require_admin_access(message):
        return
    stop_radar()
    bot.send_message(message.chat.id, "Radar paused. Use /shutdown to turn the bot off completely.")


@bot.message_handler(func=lambda message: message.text == "MENU FILTRI")
def filter_menu_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, "Filter menu opened.", reply_markup=build_filter_keyboard())


@bot.message_handler(func=lambda message: message.text == "MENU MARKET")
def market_menu_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, "Market menu opened.", reply_markup=build_market_keyboard())


@bot.message_handler(func=lambda message: message.text == "MENU VIP")
def vip_menu_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, "VIP menu opened.", reply_markup=build_vip_keyboard())


@bot.message_handler(func=lambda message: message.text == "INDIETRO")
def back_to_home_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, "Main command menu restored.", reply_markup=build_main_keyboard())


@bot.message_handler(func=lambda message: message.text == "FILTRO ATTUALE")
def current_filter_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, f"Current filter: {get_filter_label()} | Market: {get_market_label()}")


@bot.message_handler(func=lambda message: message.text == "MARKET ATTUALE")
def current_market_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, f"Active market: {get_market_label()}")


@bot.message_handler(func=lambda message: message.text == "VIP ACCESS")
def vip_access_button_cmd(message):
    if not require_admin_access(message):
        return
    send_vip_invoice(message)


@bot.message_handler(func=lambda message: message.text == "X COPY")
def xcopy_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_x_copy_message(), parse_mode="HTML")


@bot.message_handler(func=lambda message: message.text == "X PROMO")
def xpromo_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_x_promo_message(), parse_mode="HTML")

@bot.message_handler(func=lambda message: message.text == "VIP STATUS")
def vip_status_button_cmd(message):
    if not require_admin_access(message):
        return
    handle_vip_status(message)

@bot.message_handler(commands=["help"])
def help_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_commands_help(), parse_mode="HTML")


@bot.message_handler(commands=["legend"])
def legend_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_signal_legend(), parse_mode="HTML")


@bot.message_handler(func=lambda message: message.text == "COMANDI")
def commands_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_commands_help(), parse_mode="HTML")


@bot.message_handler(func=lambda message: message.text == "LEGEND")
def legend_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_signal_legend(), parse_mode="HTML")

@bot.message_handler(func=lambda message: message.text == "ADMIN PANEL")
def admin_panel_button_cmd(message):
    if not require_admin_access(message, "Admin panel is not available in this chat."):
        return
    send_html_message_safe(message.chat.id, format_admin_panel())


@bot.message_handler(func=lambda message: message.text == "ML STATUS")
def ml_status_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, format_ml_status(), parse_mode="HTML")


@bot.message_handler(func=lambda message: message.text == "PREMATCH OGGI")
def prematch_today_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, start_prematch_today_job(message.chat.id))


@bot.message_handler(func=lambda message: message.text == "PREMATCH WATCH ON")
def prematch_watch_on_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, activate_prematch_watch(message.chat.id))


@bot.message_handler(func=lambda message: message.text == "PREMATCH WATCH OFF")
def prematch_watch_off_button_cmd(message):
    if not require_admin_access(message):
        return
    bot.send_message(message.chat.id, stop_prematch_watch())

@bot.message_handler(func=lambda message: message.text == "FILTRO TOP 10")
def filter_top10_cmd(message):
    if not require_admin_access(message):
        return
    label = set_filter_mode("TOP10")
    bot.send_message(message.chat.id, f"Filter updated: {label}")


@bot.message_handler(func=lambda message: message.text == "FILTRO SERIE A/B")
def filter_serie_ab_cmd(message):
    if not require_admin_access(message):
        return
    label = set_filter_mode("SERIE_AB")
    bot.send_message(message.chat.id, f"Filter updated: {label}")


@bot.message_handler(func=lambda message: message.text == "FILTRO GLOBAL ALL-IN")
def filter_global_cmd(message):
    if not require_admin_access(message):
        return
    label = set_filter_mode("GLOBAL_U23")
    bot.send_message(message.chat.id, f"Filter updated: {label}")


@bot.message_handler(func=lambda message: message.text == "MARKET O0.5 HT")
def market_over05_cmd(message):
    if not require_admin_access(message):
        return
    label = set_market_mode("HT_05")
    bot.send_message(message.chat.id, f"Market updated: {label}")


@bot.message_handler(func=lambda message: message.text == "MARKET O1.5 HT")
def market_over15_cmd(message):
    if not require_admin_access(message):
        return
    label = set_market_mode("HT_15")
    bot.send_message(message.chat.id, f"Market updated: {label}")


@bot.message_handler(func=lambda message: message.text == "MARKET BOTH HT")
def market_both_cmd(message):
    if not require_admin_access(message):
        return
    label = set_market_mode("HT_BOTH")
    bot.send_message(message.chat.id, f"Market updated: {label}")



@bot.message_handler(func=lambda message: message.text == "MARKET NEXT GOAL")
def market_next_goal_cmd(message):
    if not require_admin_access(message):
        return
    label = set_market_mode("NEXT_GOAL")
    bot.send_message(message.chat.id, f"Market updated: {label}")


@bot.message_handler(func=lambda message: message.text == "MARKET HT + NEXT")
def market_ht_next_cmd(message):
    if not require_admin_access(message):
        return
    label = set_market_mode("HT_NEXT")
    bot.send_message(message.chat.id, f"Market updated: {label}")
if __name__ == "__main__":
    print("Starting Oracle system...")
    if not acquire_process_lock():
        print("Another Oracle instance is already running. Exiting before Telegram polling.")
        log_event("BOOT_ABORT", "Another instance is already running")
        raise SystemExit(0)
    try:
        oracle_brain = joblib.load(V2_MODEL_PATH)
        print("AI model v2 loaded.")
        log_event("BOOT", "Model v2 loaded successfully")
        try:
            with open(V2_THRESHOLD_PATH, "r") as _f:
                oracle_v2_threshold = float(_f.read().strip())
            print(f"Soglia ottimale v2: {oracle_v2_threshold}")
            log_event("BOOT", f"V2 threshold loaded: {oracle_v2_threshold}")
        except Exception:
            oracle_v2_threshold = V2_DEFAULT_THRESHOLD
            print(f"Threshold file non trovato, uso default: {oracle_v2_threshold}")
    except Exception:
        try:
            oracle_brain = joblib.load(MODEL_PATH)
            oracle_v2_threshold = 0.5
            print("AI model v2 non trovato, caricato modello originale.")
            log_event("BOOT", "Fallback to original model")
        except Exception:
            oracle_brain = None
            oracle_v2_threshold = V2_DEFAULT_THRESHOLD
            print("AI model non trovato.")
            log_event("BOOT", "Model not found; running without ML model")

    try:
        titan_pressure_brain = joblib.load(TITAN_PRESSURE_MODEL_PATH)
        print("Titan pressure model loaded.")
        log_event("BOOT", "Titan pressure model loaded successfully")
    except Exception:
        titan_pressure_brain = None
        print("Titan pressure model not found.")
        log_event("BOOT", "Titan pressure model not found; soft booster disabled")

    carica_memoria()
    load_missing_team_queue()
    ensure_live_training_dataset()
    threading.Thread(target=vip_sync_loop, daemon=True).start()
    threading.Thread(target=recap_loop, daemon=True).start()
    threading.Thread(target=prematch_auto_collect_loop, daemon=True).start()
    threading.Thread(target=prematch_watch_loop, daemon=True).start()

    if os.path.exists(CSV_PATH):
        df_matches = pd.read_csv(CSV_PATH, low_memory=False)
        nomi_unici_db = pd.concat([df_matches["HomeTeam"], df_matches["AwayTeam"]]).dropna().unique().tolist()
        team_match_cache = {}
        normalized_team_lookup = {}
        team_not_found_counts = {}
        build_team_lookup()
        print(f"Database ready: {len(nomi_unici_db)} squadre.")
        print("Bot is listening on Telegram...")
        log_event("BOOT", f"Bot listening with {len(nomi_unici_db)} teams loaded")

        while not shutdown_requested:
            try:
                bot.polling(none_stop=False, interval=0, timeout=30, skip_pending=True)
            except Exception as exc:
                if shutdown_requested:
                    break
                print(f"Auto-restart polling: {exc}")
                log_event("POLLING_RESTART", str(exc))
                time.sleep(5)
    else:
        print(f"Error: {CSV_PATH} mancante!")






































































































































































































