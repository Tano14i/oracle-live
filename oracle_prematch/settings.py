from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ROOT_ENV_PATH = BASE_DIR.parent / ".env"
ENV_PATH = BASE_DIR / ".env.prematch"
OUTPUT_DIR = BASE_DIR / "output"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_bool_setting(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_project_path(value: str, default_name: str) -> str:
    raw_value = value or default_name
    path = Path(raw_value)
    if path.is_absolute():
        return str(path)
    return str(BASE_DIR / path)


_load_env_file(ROOT_ENV_PATH)
_load_env_file(ENV_PATH)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREMATCH_DB_PATH = resolve_project_path(get_setting("PREMATCH_DB_PATH"), "prematch_watchlist.db")
DEFAULT_INPUT_PATH = resolve_project_path(get_setting("PREMATCH_INPUT_PATH"), "sample_feed.json")
LATEST_JSON_PATH = resolve_project_path(get_setting("PREMATCH_OUTPUT_JSON"), "output/latest_watchlist.json")
LATEST_TEXT_PATH = resolve_project_path(get_setting("PREMATCH_OUTPUT_TEXT"), "output/latest_watchlist.txt")

TELEGRAM_BOT_TOKEN = get_setting("PREMATCH_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_setting("PREMATCH_TELEGRAM_CHAT_ID")
DEFAULT_TOP = int(get_setting("PREMATCH_TOP", "10") or "10")
WATCH_LIVE_THRESHOLD = int(get_setting("PREMATCH_WATCH_LIVE_THRESHOLD", "70") or "70")
REVIEW_THRESHOLD = int(get_setting("PREMATCH_REVIEW_THRESHOLD", "55") or "55")
SOURCE_NAME = get_setting("PREMATCH_SOURCE_NAME", "manual-feed")
API_FOOTBALL_HOST = get_setting("PREMATCH_API_FOOTBALL_HOST", "https://v3.football.api-sports.io")
API_FOOTBALL_KEY = get_setting("PREMATCH_API_FOOTBALL_KEY", get_setting("API_KEY"))
API_FOOTBALL_LOOKBACK_HOURS = int(get_setting("PREMATCH_API_FOOTBALL_LOOKBACK_HOURS", "48") or "48")
API_FOOTBALL_TIMEOUT = int(get_setting("PREMATCH_API_FOOTBALL_TIMEOUT", "30") or "30")
PREMATCH_AUTO_COLLECT_ENABLED = get_bool_setting("PREMATCH_AUTO_COLLECT_ENABLED", True)
PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS = int(get_setting("PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS", "600") or "600")
PREMATCH_AUTO_COLLECT_PAGE_LIMIT = int(get_setting("PREMATCH_AUTO_COLLECT_PAGE_LIMIT", "3") or "3")

NICHE_KEYWORDS = [
    "u19",
    "u20",
    "u21",
    "u23",
    "youth",
    "reserves",
    "reserve",
    "women cup",
    "cup",
    "regional",
    "state league",
    "itf",
    "challenger",
    "future",
    "qualifying",
    "2nd division",
    "serie c",
    "liga iii",
]

TOP_LEAGUE_KEYWORDS = [
    "premier league",
    "serie a",
    "la liga",
    "bundesliga",
    "ligue 1",
    "champions league",
    "europa league",
    "primeira liga",
]
