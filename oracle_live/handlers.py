import threading
from datetime import timedelta

from config import (
    FREE_DELAY_SECONDS,
    VIP_DURATION_DAYS,
    VIP_PRICE_XTR,
    VIP_SUPPORT_CONTACT,
)
from telebot import types

from oracle_live import state
from oracle_live.constants import VIP_PLAN_CODE, VIP_PLAN_NAME
from oracle_live.filters import (
    get_filter_label,
    get_missing_team_queue_count,
    get_top_team_not_found,
    set_filter_mode,
    start_missing_team_backfill_job,
)
from oracle_live.markets import get_market_label, set_market_mode
from oracle_live.messaging import (
    format_commands_help,
    format_signal_legend,
    is_admin_message,
    send_html_message_safe,
)
from oracle_live.models import format_ml_status, start_retrain_job
from oracle_live.prematch import (
    activate_prematch_watch,
    extract_requested_date,
    start_prematch_today_job,
    stop_prematch_watch,
)
from oracle_live.reporting import (
    format_admin_panel,
    format_analytics_text,
    format_x_copy_message,
    format_x_promo_message,
)
from oracle_live.runtime import (
    request_shutdown,
    restart_dashboard_job,
    start_dashboard_public_job,
    start_dashboard_web_job,
    stop_radar,
)
from oracle_live.signals import format_radar_check_text, radar_loop
from oracle_live.state import (
    bot,
    increment_analytics,
    log_event,
    membership_store,
    now_utc,
    stats,
)
from oracle_live.vip import create_vip_invite_link, handle_vip_status, send_vip_invoice

def require_admin_access(message, notice: str = "Private bot: command available only to the owner in private chat.") -> bool:
    if is_admin_message(message):
        return True
    try:
        bot.send_message(message.chat.id, notice)
    except Exception:
        pass
    return False


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
    if not require_admin_access(message):
        return
    if not state.running:
        state.running = True
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
