"""Tests for signal_monitor.py — no API key needed."""
import json, os, sys, unittest.mock as m
sys.path.insert(0, '.')
from signal_monitor import check_signal_validity, build_alert_message, _math_check
from datetime import datetime, timezone

NOW = datetime(2026, 11, 5, 1, 56, 10, tzinfo=timezone.utc)
BUY_SIG = {"id": 1, "symbol": "EURUSD", "side": "buy", "entry": 1.1000, "sl": 1.0980, "tp1": 1.1030, "tp2": 1.1060, "timeframe": "M15", "strategy": "trend_pullback"}
SELL_SIG = {"id": 2, "symbol": "GBPUSD", "side": "sell", "entry": 1.3484, "sl": 1.3510, "tp1": 1.3450, "tp2": 1.3420, "timeframe": "M15", "strategy": "structure_retest"}

def ok(n): print("ok", n)

# math fallback
r = _math_check(BUY_SIG, {"price": 1.1010}); assert r["status"] == "ACTIVE"; ok("buy active")
r = _math_check(BUY_SIG, {"price": 1.0975}); assert r["status"] == "INVALIDATED"; assert "broke below" in r["reasoning"]; ok("buy invalidated")
r = _math_check(BUY_SIG, {"price": 1.1035}); assert r["status"] == "WIN"; ok("buy win")
r = _math_check(SELL_SIG, {"price": 1.3515}); assert r["status"] == "INVALIDATED"; assert "broke above" in r["reasoning"]; ok("sell invalidated")
r = _math_check(SELL_SIG, {"price": 1.3445}); assert r["status"] == "WIN"; ok("sell win")
r = _math_check(SELL_SIG, {"price": 1.3470}); assert r["status"] == "ACTIVE"; ok("sell active")
r = _math_check(BUY_SIG, {}); assert r["status"] == "ACTIVE"; ok("empty snapshot safe")

# AI path
os.environ["NVIDIA_API_KEY"] = "fake-key"
fake = {"choices": [{"message": {"content": '{"status":"INVALIDATED","reasoning":"Price broke stop loss.","recommended_action":"Cancel/Exit NOW"}'}}]}
with m.patch("signal_monitor.requests.post") as mp:
    mp.return_value.raise_for_status = lambda: None
    mp.return_value.json = lambda: fake
    r = check_signal_validity(BUY_SIG, {"price": 1.0975, "symbol": "EURUSD"})
assert r["status"] == "INVALIDATED"; ok("AI invalidated path")

# AI failure falls back to maths
with m.patch("signal_monitor.requests.post", side_effect=Exception("timeout")):
    r = check_signal_validity(BUY_SIG, {"price": 1.0975, "symbol": "EURUSD"})
assert r["status"] == "INVALIDATED"; ok("AI failure falls back to maths")

# alert message format matches your friend's bot style
r = {"status": "INVALIDATED", "reasoning": "Setup Invalidated Monitored Outgoing Trade Protection.", "recommended_action": "Cancel/Exit NOW"}
msg = build_alert_message(SELL_SIG, r, NOW)
assert "[INVALIDATED]" in msg; assert "GBPUSD" in msg; assert "Cancel/Exit NOW" in msg; assert "M15" in msg; assert "2026" in msg; ok("alert message format")
r2 = {"status": "WIN", "reasoning": "TP1 hit.", "recommended_action": "Take profit"}
msg2 = build_alert_message(BUY_SIG, r2, NOW); assert "WIN" in msg2 and "Take profit" in msg2; ok("win message format")

print("\nall signal_monitor tests passed")
