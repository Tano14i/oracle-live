import random
import time

import pandas as pd

from config import (
    CHANNEL_ID,
    CHAT_ID,
    PERFORMANCE_STAKE_EXAMPLE,
    PERFORMANCE_STARTING_BANKROLL,
    QUOTA,
    RECAP_HOUR_UTC,
    RECAP_MINUTE_UTC,
    RENEWAL_REMINDER_DAYS,
    REPORT_EVERY_N_SETTLED,
    REPORT_MIN_SETTLED,
    STAKE,
    VIP_CHANNEL_ID,
)
from trainer import DATA_FILE as TRAINER_DATA_FILE

from oracle_live import state
from oracle_live.constants import SEPARATOR, TIER_APPROVED, TIER_CAUTION, TIER_GAMBLING
from oracle_live.filters import get_filter_label
from oracle_live.markets import get_active_markets, get_market_label
from oracle_live.messaging import escape_html
from oracle_live.state import (
    bot,
    current_date_key,
    default_recap_delivery,
    ensure_daily_analytics,
    get_recent_rolling_stats,
    get_rolling_bucket_stats,
    live_training_lock,
    log_event,
    membership_store,
    now_utc,
    salva_dati_web,
    state_lock,
    stats,
)

def summarize_wr_bucket(bucket: dict) -> str:
    wins = int((bucket or {}).get("WIN", 0))
    losses = int((bucket or {}).get("LOSS", 0))
    total = wins + losses
    if total <= 0:
        return "n/a"
    win_rate = wins / total * 100
    return f"{wins}W-{losses}L ({win_rate:.0f}%)"


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
    while not state.shutdown_requested:
        try:
            send_daily_recap_if_due()
        except Exception as exc:
            print(f"recap_loop error: {exc}")
        time.sleep(60)
