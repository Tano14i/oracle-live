import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(ENV_PATH)


def get_setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def resolve_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(BASE_DIR / path)


TOKEN_LIVE = get_setting("TOKEN_LIVE")
CHAT_ID = get_setting("CHAT_ID")
CHANNEL_ID = get_setting("CHANNEL_ID")
API_KEY = get_setting("API_KEY")
VIP_CHANNEL_ID = get_setting("VIP_CHANNEL_ID")
VIP_SUPPORT_CONTACT = get_setting("VIP_SUPPORT_CONTACT", "@your_support")

CSV_PATH = resolve_path(get_setting("CSV_PATH", "Matches.csv"))
MODEL_PATH = resolve_path(get_setting("MODEL_PATH", "oracle_brain.pkl"))
WEB_DATA_PATH = resolve_path(get_setting("WEB_DATA_PATH", "web_stats.json"))
MEMBERS_DB_PATH = resolve_path(get_setting("MEMBERS_DB_PATH", "vip_members.db"))
LOG_FILE_PATH = resolve_path(get_setting("LOG_FILE_PATH", "oracle_live.log"))

STAKE = float(get_setting("STAKE", "10.0") or "10.0")
QUOTA = float(get_setting("QUOTA", "1.75") or "1.75")
VIP_PRICE_XTR = int(get_setting("VIP_PRICE_XTR", "499") or "499")
VIP_DURATION_DAYS = int(get_setting("VIP_DURATION_DAYS", "30") or "30")
FREE_DELAY_SECONDS = int(get_setting("FREE_DELAY_SECONDS", "180") or "180")
FREE_EVERY_N_APPROVED = int(get_setting("FREE_EVERY_N_APPROVED", "3") or "3")
RECAP_HOUR_UTC = int(get_setting("RECAP_HOUR_UTC", "21") or "21")
RECAP_MINUTE_UTC = int(get_setting("RECAP_MINUTE_UTC", "0") or "0")
RENEWAL_REMINDER_DAYS = int(get_setting("RENEWAL_REMINDER_DAYS", "3") or "3")

REPORT_EVERY_N_SETTLED = int(get_setting("REPORT_EVERY_N_SETTLED", "10") or "10")
REPORT_MIN_SETTLED = int(get_setting("REPORT_MIN_SETTLED", "20") or "20")
PERFORMANCE_STAKE_EXAMPLE = float(get_setting("PERFORMANCE_STAKE_EXAMPLE", "100") or "100")
PERFORMANCE_STARTING_BANKROLL = float(get_setting("PERFORMANCE_STARTING_BANKROLL", "1000") or "1000")
AUTO_RETRAIN_EVERY_N_SETTLED = int(get_setting("AUTO_RETRAIN_EVERY_N_SETTLED", "50") or "50")
LIVE_TRAINING_DATA_PATH = resolve_path(get_setting("LIVE_TRAINING_DATA_PATH", "live_training_data.csv"))
MISSING_TEAMS_QUEUE_PATH = resolve_path(get_setting("MISSING_TEAMS_QUEUE_PATH", "missing_teams_queue.json"))






