"""Turns a signal into a message, and sends it to Telegram if Telegram is set up."""
from __future__ import annotations

import os

import requests

from strategies import NAMES


def format_signal(s: dict) -> str:
    lines = [f"{s['side'].upper()} {s['symbol']} · {s['timeframe']} · {NAMES.get(s['strategy'], s['strategy'])}"]
    if s.get("approved") is False:
        lines.append("WARNING: UNTESTED. This strategy has not passed the backtest. Demo account only.")
    lines += [f"Entry about {s['entry']}", f"Stop {s['sl']}", f"TP1 {s['tp1']}   TP2 {s['tp2']}",
              f"Valid until {s['expires_at'][11:16]} UTC. Hold up to {s['max_hold_min'] // 60}h.", f"{s['htf']} trend agrees."]
    if s.get("pf"):
        lines.append(f"Backtest: {round(s['win_rate'] * 100)}% wins, profit factor {s['pf']}, {s['bt_trades']} trades.")
    lines.append("Prices come from a free feed. Your broker's price can differ a little, so use the distances to the stop and targets.")
    return "\n".join(lines)


def telegram(text: str) -> bool:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False
    try:
        return requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15).ok
    except requests.RequestException:
        return False
