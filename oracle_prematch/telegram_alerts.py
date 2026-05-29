from __future__ import annotations

import requests


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token or not chat_id:
        raise ValueError("Telegram bot token and chat id are required.")
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()
