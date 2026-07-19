import time
from datetime import timedelta

from telebot import types

from config import (
    RENEWAL_REMINDER_DAYS,
    VIP_CHANNEL_ID,
    VIP_DURATION_DAYS,
    VIP_PRICE_XTR,
)

from oracle_live import state
from oracle_live.constants import VIP_PLAN_CODE, VIP_PLAN_NAME, VIP_SYNC_INTERVAL_SECONDS
from oracle_live.messaging import is_private_chat
from oracle_live.state import (
    bot,
    increment_analytics,
    log_event,
    membership_store,
    now_utc,
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
    if not VIP_CHANNEL_ID:
        return
    current_ts = time.time()
    if not force and current_ts - state.last_vip_sync_ts < VIP_SYNC_INTERVAL_SECONDS:
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

    state.last_vip_sync_ts = current_ts


def vip_sync_loop() -> None:
    while not state.shutdown_requested:
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
