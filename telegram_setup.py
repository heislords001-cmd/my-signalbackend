"""Sets up Telegram alerts. Run: python telegram_setup.py
It asks for your bot token, finds your chat by itself, saves both in .env, and sends a test message."""
from __future__ import annotations

import os
import re
import time

import requests


def api(token: str, method: str, **params) -> dict:
    return requests.get(f"https://api.telegram.org/bot{token}/{method}", params=params, timeout=30).json()


def find_chat(token: str, tries: int = 40, wait: float = 3.0):
    for _ in range(tries):
        for u in reversed(api(token, "getUpdates").get("result", [])):
            msg = u.get("message") or u.get("channel_post")
            if msg:
                return msg["chat"]["id"]
        time.sleep(wait)
    return None


def write_env(values: dict, path: str = ".env") -> None:
    if os.path.exists(path):
        lines = open(path, encoding="utf-8").read().splitlines()
    elif os.path.exists(".env.example"):
        lines = open(".env.example", encoding="utf-8").read().splitlines()
    else:
        lines = []
    for k, v in values.items():
        pat = re.compile(rf"^{k}=.*$")
        if any(pat.match(x) for x in lines):
            lines = [f"{k}={v}" if pat.match(x) else x for x in lines]
        else:
            lines.append(f"{k}={v}")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main() -> None:
    token = input("Paste your bot token from BotFather and press Enter: ").strip()
    me = api(token, "getMe")
    if not me.get("ok"):
        print("That token does not work. Copy it again from BotFather (it looks like 123456789:ABC...).")
        return
    print(f"Found your bot: @{me['result']['username']}")
    print("Now open Telegram, find that bot, press Start and send it the word: hi")
    print("Waiting for your message (up to 2 minutes)...")
    chat = find_chat(token)
    if chat is None:
        print("I did not see a message. Send 'hi' to your bot, then run this again.")
        return
    write_env({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat})
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": "FX Desk alerts are connected. Signals will appear here."}, timeout=15)
    print("Done. Check Telegram: you should have a message from your bot. Settings saved in .env")


if __name__ == "__main__":
    main()
