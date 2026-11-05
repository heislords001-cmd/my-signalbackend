"""
Signal monitor: after the scanner saves a signal, this checks every 5 minutes
whether the signal is still valid or has been invalidated (price broke the
structure before the target was hit). If invalidated, it fires an alert.

This is what your friend's bot does. It is pure maths against live price data,
no screenshots needed. The AI reads the numbers and writes the message.

Called from worker.py on every cycle for any LIVE signal.
"""
from __future__ import annotations
import logging, os, json
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger("signal_monitor")

MONITOR_PROMPT = """\
You are a professional forex trade monitor.

A signal was placed with these parameters:
{signal}

Current market snapshot:
{snapshot}

Rules for invalidation:
- BUY signal: if the current price closes BELOW the stop loss level, the setup is invalidated.
- SELL signal: if the current price closes ABOVE the stop loss level, the setup is invalidated.
- If price has already hit TP1, the signal is a WIN.
- If still within range, the signal is ACTIVE.

Respond with ONLY this JSON (no extra text):
{{
  "status": "ACTIVE" or "WIN" or "INVALIDATED",
  "reasoning": "one sentence max",
  "recommended_action": "Hold" or "Cancel/Exit NOW" or "Take profit"
}}
"""

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"


def _nvidia_key() -> str:
    return os.environ.get("NVIDIA_API_KEY", "")


def _model() -> str:
    return os.environ.get("NVIDIA_MODEL", "mistralai/mistral-7b-instruct")


def check_signal_validity(signal: dict, snapshot: dict) -> Optional[dict]:
    """
    Ask the AI whether a live signal is still valid given the current market snapshot.
    Returns dict with status, reasoning, recommended_action — or None if AI unavailable.
    """
    if not _nvidia_key():
        # fallback: pure maths, no AI
        return _math_check(signal, snapshot)

    prompt = MONITOR_PROMPT.format(
        signal=json.dumps({k: v for k, v in signal.items() if k in
                          ('symbol', 'side', 'entry', 'sl', 'tp1', 'tp2', 'timeframe', 'strategy')}, indent=2),
        snapshot=json.dumps({k: v for k, v in snapshot.items() if k != 'updated_at'}, indent=2),
    )
    try:
        r = requests.post(
            f"{NVIDIA_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {_nvidia_key()}", "Content-Type": "application/json"},
            json={"model": _model(),
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 150, "temperature": 0.1},
            timeout=30,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        start, end = text.find("{"), text.rfind("}") + 1
        result = json.loads(text[start:end])
        assert result.get("status") in ("ACTIVE", "WIN", "INVALIDATED")
        log.info("monitor %s %s → %s: %s", signal.get("symbol"), signal.get("side"),
                 result["status"], result["reasoning"])
        return result
    except Exception as exc:
        log.warning("monitor AI call failed for %s: %s — using maths fallback", signal.get("symbol"), exc)
        return _math_check(signal, snapshot)


def _math_check(signal: dict, snapshot: dict) -> dict:
    """Pure maths fallback: no API key needed."""
    price = float(snapshot.get("price") or 0)
    sl = float(signal.get("sl") or 0)
    tp1 = float(signal.get("tp1") or 0)
    side = str(signal.get("side", "")).lower()
    if not price or not sl or not tp1:
        return {"status": "ACTIVE", "reasoning": "Insufficient data to check.", "recommended_action": "Hold"}
    if side == "buy":
        if price <= sl:
            return {"status": "INVALIDATED", "reasoning": f"Price {price} broke below stop loss {sl}.", "recommended_action": "Cancel/Exit NOW"}
        if price >= tp1:
            return {"status": "WIN", "reasoning": f"Price {price} reached TP1 {tp1}.", "recommended_action": "Take profit"}
    elif side == "sell":
        if price >= sl:
            return {"status": "INVALIDATED", "reasoning": f"Price {price} broke above stop loss {sl}.", "recommended_action": "Cancel/Exit NOW"}
        if price <= tp1:
            return {"status": "WIN", "reasoning": f"Price {price} reached TP1 {tp1}.", "recommended_action": "Take profit"}
    return {"status": "ACTIVE", "reasoning": f"Price {price} within range.", "recommended_action": "Hold"}


def build_alert_message(signal: dict, result: dict, now: datetime) -> str:
    """Build the alert message in the same style as your friend's bot."""
    emoji = {"ACTIVE": "✅", "WIN": "🏆", "INVALIDATED": "🚨"}.get(result["status"], "ℹ️")
    action = result.get("recommended_action", "")
    reasoning = result.get("reasoning", "")
    ts = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    sym = signal.get("symbol", "")
    side = str(signal.get("side", "")).upper()
    entry = signal.get("entry", "")
    tf = signal.get("timeframe", "")
    status = result["status"]
    lines = [
        f"{emoji} [{status}] {side} {sym} @ {entry}",
        f"{emoji} SIGNAL {status}" + (" — CANCEL / EXIT NOW" if status == "INVALIDATED" else ""),
        f"{side} {sym} — {reasoning}",
        f"Timeframe: {tf} · {ts}",
        f"Recommended Action: {action}",
    ]
    return "\n".join(lines)
