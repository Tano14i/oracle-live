import html

from config import CHAT_ID

from oracle_live.constants import (
    MARKET_NEXT_GOAL,
    SEPARATOR,
    TIER_APPROVED,
    TIER_CAUTION,
    TIER_EMOJI,
    TIER_GAMBLING,
)
from oracle_live.markets import get_min_quota_for_tier
from oracle_live.state import bot, log_event

def escape_html(value: str) -> str:
    return html.escape(str(value or ""))


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


def is_private_chat(message) -> bool:
    return getattr(message.chat, "type", "") == "private"


def is_admin_message(message) -> bool:
    user_id = str(getattr(getattr(message, "from_user", None), "id", ""))
    admin_target = str(CHAT_ID or "").strip()
    if not admin_target:
        return False
    return is_private_chat(message) and user_id == admin_target


def get_profile_label(tier: str) -> str:
    return "HIGH PRECISION" if tier == TIER_APPROVED else "CONTROLLED RISK" if tier == TIER_CAUTION else "AGGRESSIVE VALUE"


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
        f"<b>VIP TEASER {TIER_EMOJI.get(tier, chr(0x1F916))} {escape_html(tier)}</b>\n"
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
        "ANALISI or /analisi: WR/ROI/calibration report from the live dataset.\n"
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
