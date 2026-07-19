import threading
import time
from datetime import datetime

from oracle_prematch.bot_service import collect_prematch_snapshots, run_prematch_bot_scan
from oracle_prematch.settings import (
    PREMATCH_AUTO_COLLECT_ENABLED,
    PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS,
    PREMATCH_AUTO_COLLECT_PAGE_LIMIT,
)

from oracle_live import state
from oracle_live.messaging import escape_html, send_html_message_safe
from oracle_live.state import (
    bot,
    current_date_key,
    default_prematch_last_report,
    default_prematch_watch_state,
    logger,
    now_utc,
    prematch_backend_lock,
    salva_dati_web,
    state_lock,
    stats,
)

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


def start_prematch_today_job(
    chat_id: int,
    requested_date: str | None = None,
    starter_text: str = "Pre-match scan started in background. I will send the suspicious matches of the day here as soon as the backend finishes.",
) -> str:

    with state_lock:
        if state.prematch_running:
            return "Pre-match suspicious scan already running. Please wait for the final message."
        state.prematch_running = True

    def prematch_worker():
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
                state.prematch_running = False

    thread = threading.Thread(target=prematch_worker, daemon=True, name="oracle-prematch")
    thread.start()
    return starter_text


def prematch_auto_collect_loop() -> None:
    if not PREMATCH_AUTO_COLLECT_ENABLED:
        logger.info("PREMATCH_AUTO_COLLECT_DISABLED")
        return

    interval_seconds = max(120, int(PREMATCH_AUTO_COLLECT_INTERVAL_SECONDS or 600))
    page_limit = max(1, int(PREMATCH_AUTO_COLLECT_PAGE_LIMIT or 3))

    while not state.shutdown_requested:
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
    while not state.shutdown_requested:
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
