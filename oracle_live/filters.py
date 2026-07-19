import json
import os
import re
import subprocess
import sys
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from config import MISSING_TEAMS_QUEUE_PATH

from oracle_live import state
from oracle_live.constants import (
    BASE_DIR,
    COVERAGE_GUARD_ENABLED,
    COVERAGE_GUARD_HOURS,
    COVERAGE_GUARD_THRESHOLD,
    DEFAULT_FILTER_MODE,
    FILTER_PRESETS,
    MANUAL_TEAM_ALIASES,
    NON_LEAGUE_EXCLUDED,
    SERIE_AB_PATTERNS,
    TOP10_COUNTRIES,
    YOUTH_EXCLUDED,
)
from oracle_live.messaging import escape_html, send_html_message_safe
from oracle_live.state import (
    bot,
    log_event,
    logger,
    missing_team_queue_lock,
    now_utc,
    salva_dati_web,
    state_lock,
    stats,
)

def normalizza_testo(value: str) -> str:
    value = str(value or "").lower()
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", value).strip()


def normalizza_squadra(value: str) -> str:
    value = str(value or "").lower().replace("b team", "").replace("ii", "")
    value = "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", "", value).strip()


def get_filter_mode() -> str:
    mode = stats.get("filter_mode", DEFAULT_FILTER_MODE)
    return mode if mode in FILTER_PRESETS else DEFAULT_FILTER_MODE


def get_filter_label() -> str:
    return FILTER_PRESETS[get_filter_mode()]["label"]


def load_missing_team_queue() -> None:
    if not os.path.exists(MISSING_TEAMS_QUEUE_PATH):
        state.missing_team_queue = {}
        return

    try:
        with missing_team_queue_lock:
            with open(MISSING_TEAMS_QUEUE_PATH, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            state.missing_team_queue = loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        state.missing_team_queue = {}
        log_event("MISSING_QUEUE_LOAD_ERROR", str(exc))


def save_missing_team_queue() -> None:
    with missing_team_queue_lock:
        with open(MISSING_TEAMS_QUEUE_PATH, "w", encoding="utf-8") as handle:
            json.dump(state.missing_team_queue, handle, indent=2)


def queue_missing_team_lookup(nome_live: str, country: str = "", league_name: str = "") -> None:
    norm_live = normalizza_squadra(nome_live)
    if not norm_live:
        return

    key = f"{country.strip().lower()}|{league_name.strip().lower()}|{norm_live}"
    now_iso = now_utc().isoformat()
    with missing_team_queue_lock:
        item = state.missing_team_queue.get(key, {
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
        state.missing_team_queue[key] = item

    save_missing_team_queue()


def get_missing_team_queue_count() -> int:
    return len(state.missing_team_queue)


def get_missing_team_queue_status_counts() -> dict:
    with missing_team_queue_lock:
        queue = state.missing_team_queue if isinstance(state.missing_team_queue, dict) else {}
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
    if state.normalized_team_lookup or not state.nomi_unici_db:
        return

    lookup = {}
    for nome_db in state.nomi_unici_db:
        norm_db = normalizza_squadra(nome_db)
        if not norm_db:
            continue
        lookup.setdefault(norm_db, []).append(nome_db)
    state.normalized_team_lookup = lookup


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
    count = state.team_not_found_counts.get(norm_live, 0) + 1
    state.team_not_found_counts[norm_live] = count
    if count <= 3:
        log_event("TEAM_NOT_FOUND", f"live={nome_live} normalized={norm_live} count={count}")
    queue_missing_team_lookup(nome_live, country, league_name)
    register_team_not_found(country, league_name)


def get_top_team_not_found(limit: int = 5) -> str:
    if not state.team_not_found_counts:
        return "-"
    pairs = sorted(state.team_not_found_counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return ", ".join(f"{name} ({count})" for name, count in pairs)


def trova_squadra(nome_live: str, country: str = "", league_name: str = ""):
    if not state.nomi_unici_db:
        return None

    build_team_lookup()
    norm_live = normalizza_squadra(nome_live)
    if not norm_live:
        return None

    cached = state.team_match_cache.get(norm_live)
    if cached:
        return cached

    for alias in get_controlled_aliases(nome_live):
        alias_hits = state.normalized_team_lookup.get(alias)
        if alias_hits:
            match = alias_hits[0]
            state.team_match_cache[norm_live] = match
            return match

    direct_hits = state.normalized_team_lookup.get(norm_live)
    if direct_hits:
        match = direct_hits[0]
        state.team_match_cache[norm_live] = match
        return match

    simple_live = simplify_team_tokens(nome_live)
    if simple_live:
        simple_hits = state.normalized_team_lookup.get(simple_live)
        if simple_hits:
            match = simple_hits[0]
            state.team_match_cache[norm_live] = match
            return match

    best_match = None
    best_ratio = 0.0
    best_simple_match = None
    best_simple_ratio = 0.0

    live_tokens = set(norm_live.split())
    simple_live_tokens = set(simple_live.split()) if simple_live else set()

    for norm_db, original_names in state.normalized_team_lookup.items():
        db_tokens = set(norm_db.split())
        if live_tokens and db_tokens and live_tokens == db_tokens:
            match = original_names[0]
            state.team_match_cache[norm_live] = match
            return match

        ratio = SequenceMatcher(None, norm_live, norm_db).ratio()
        if ratio > 0.94:
            match = original_names[0]
            state.team_match_cache[norm_live] = match
            return match
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = original_names[0]

        simple_db = simplify_team_tokens(norm_db)
        simple_db_tokens = set(simple_db.split()) if simple_db else set()
        if simple_live and simple_db:
            if simple_live_tokens and simple_db_tokens and simple_live_tokens == simple_db_tokens:
                match = original_names[0]
                state.team_match_cache[norm_live] = match
                return match
            simple_ratio = SequenceMatcher(None, simple_live, simple_db).ratio()
            if simple_ratio > best_simple_ratio:
                best_simple_ratio = simple_ratio
                best_simple_match = original_names[0]

    if best_simple_match and best_simple_ratio >= 0.88:
        state.team_match_cache[norm_live] = best_simple_match
        return best_simple_match
    if best_match and best_ratio >= 0.86:
        state.team_match_cache[norm_live] = best_match
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


def start_missing_team_backfill_job(
    chat_id: int,
    starter_text: str = "Missing-team backfill started in background. I will send the result here as soon as it finishes.",
    limit: int = 25,
    timeout_seconds: int = 600,
    process_all: bool = False,
) -> str:

    with state_lock:
        if state.backfill_running:
            return "Missing-team backfill already running. Please wait for the final message."
        state.backfill_running = True

    def backfill_worker():
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
                state.backfill_running = False

    thread = threading.Thread(target=backfill_worker, daemon=True, name="oracle-backfill")
    thread.start()
    return starter_text
