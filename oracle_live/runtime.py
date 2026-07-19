import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import sys as _sys
if _sys.platform == "win32":
    import msvcrt as _lock_mod
    _LOCK_PLATFORM = "win32"
else:
    import fcntl as _lock_mod
    _LOCK_PLATFORM = "posix"

import pandas as pd
import requests

from config import CSV_PATH, WEB_DATA_PATH

from oracle_live import state
from oracle_live.constants import BASE_DIR, LEGACY_TIER_KEYS, PROCESS_LOCK_PATH
from oracle_live.filters import (
    build_team_lookup,
    get_filter_label,
    get_filter_mode,
    load_missing_team_queue,
)
from oracle_live.markets import get_market_label, get_market_mode
from oracle_live.models import load_models
from oracle_live.prematch import prematch_auto_collect_loop, prematch_watch_loop
from oracle_live.reporting import recap_loop
from oracle_live.signals import (
    clean_sent_signals,
    migrate_monitor_entries,
    prune_settled_signals,
)
from oracle_live.state import (
    bot,
    current_date_key,
    default_analytics,
    default_prematch_last_report,
    default_prematch_watch_state,
    default_recap_delivery,
    ensure_daily_analytics,
    ensure_live_training_dataset,
    get_total_settled_count,
    log_event,
    logger,
    salva_dati_web,
    state_lock,
    stats,
)
from oracle_live.vip import vip_sync_loop

process_lock_handle = None


def carica_memoria() -> None:
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
    with state_lock:
        running_process = state.dashboard_process if state.dashboard_process and state.dashboard_process.poll() is None else None
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
            state.dashboard_process = process
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
    local_message = start_dashboard_web_job(chat_id, port)
    ngrok_path = find_ngrok_executable()
    if not ngrok_path:
        return (
            f"{local_message}\n\n"
            "ngrok not found. Install it or place ngrok.exe in Downloads or C:\\Tools\\ngrok, then retry /dashboard_public."
        )

    with state_lock:
        running_ngrok = state.ngrok_process if state.ngrok_process and state.ngrok_process.poll() is None else None
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
            state.ngrok_process = process
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

    stopped = []
    with state_lock:
        current_dashboard = state.dashboard_process
        state.dashboard_process = None
        current_ngrok = state.ngrok_process
        state.ngrok_process = None

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


def stop_radar() -> None:
    state.running = False
    log_event('RADAR_STOP', 'Radar paused by admin')


def request_shutdown() -> None:
    state.running = False
    state.shutdown_requested = True
    log_event('BOT_SHUTDOWN', 'Shutdown requested by admin')
    try:
        bot.stop_polling()
    except Exception as exc:
        print(f"stop_polling fallito: {exc}")


def main() -> None:
    from oracle_live import handlers  # noqa: F401  (registra gli handler telebot prima del polling)

    print("Starting Oracle system...")
    if not acquire_process_lock():
        print("Another Oracle instance is already running. Exiting before Telegram polling.")
        log_event("BOOT_ABORT", "Another instance is already running")
        raise SystemExit(0)

    load_models()

    carica_memoria()
    load_missing_team_queue()
    ensure_live_training_dataset()
    threading.Thread(target=vip_sync_loop, daemon=True).start()
    threading.Thread(target=recap_loop, daemon=True).start()
    threading.Thread(target=prematch_auto_collect_loop, daemon=True).start()
    threading.Thread(target=prematch_watch_loop, daemon=True).start()

    if os.path.exists(CSV_PATH):
        state.df_matches = pd.read_csv(CSV_PATH, low_memory=False)
        state.nomi_unici_db = pd.concat([state.df_matches["HomeTeam"], state.df_matches["AwayTeam"]]).dropna().unique().tolist()
        state.team_match_cache = {}
        state.normalized_team_lookup = {}
        state.team_not_found_counts = {}
        build_team_lookup()
        print(f"Database ready: {len(state.nomi_unici_db)} squadre.")
        print("Bot is listening on Telegram...")
        log_event("BOOT", f"Bot listening with {len(state.nomi_unici_db)} teams loaded")

        while not state.shutdown_requested:
            try:
                bot.polling(none_stop=False, interval=0, timeout=30, skip_pending=True)
            except Exception as exc:
                if state.shutdown_requested:
                    break
                print(f"Auto-restart polling: {exc}")
                log_event("POLLING_RESTART", str(exc))
                time.sleep(5)
    else:
        print(f"Error: {CSV_PATH} mancante!")
