"""Tests for nvidia_brain.py — no real API key needed."""
import json, os, sys, unittest.mock as m
sys.path.insert(0, '.')

from nvidia_brain import get_signal, configured

SNAP = {"symbol": "EURUSD", "trend": "buy", "price": 1.1004, "ema50": 1.1000, "atr": 0.0004}
RULES = [{"Entry_Rules": ["RSI < 30 AND price above 200 EMA"], "Confirmation_Triggers": ["H4 candle close above EMA50"], "Risk_Notes": ["Risk 1% per trade"], "Exit_Rules": []}]

def ok(n): print("ok", n)

assert not configured(); ok("not configured without key")
os.environ["NVIDIA_API_KEY"] = "fake-key"; assert configured(); ok("configured with key")

# happy path: BUY signal
fake_resp = {"choices": [{"message": {"content": '{"signal":"BUY","confidence":0.82,"reasoning":"Price above EMA50, trend confirmed."}'}}]}
with m.patch("nvidia_brain.requests.post") as mp:
    mp.return_value.raise_for_status = lambda: None
    mp.return_value.json = lambda: fake_resp
    r = get_signal(SNAP, RULES)
assert r["signal"] == "BUY" and abs(r["confidence"] - 0.82) < 0.01; ok("buy signal parsed")

# SKIP signal
fake_resp["choices"][0]["message"]["content"] = '{"signal":"SKIP","confidence":0.3,"reasoning":"Not enough confirmation."}'
with m.patch("nvidia_brain.requests.post") as mp:
    mp.return_value.raise_for_status = lambda: None
    mp.return_value.json = lambda: fake_resp
    r = get_signal(SNAP, RULES)
assert r["signal"] == "SKIP"; ok("skip signal parsed")

# API error → None, never crashes
with m.patch("nvidia_brain.requests.post", side_effect=Exception("timeout")):
    r = get_signal(SNAP, RULES)
assert r is None; ok("api error returns None")

# bad JSON → None
fake_resp["choices"][0]["message"]["content"] = "Sorry, I cannot help with that."
with m.patch("nvidia_brain.requests.post") as mp:
    mp.return_value.raise_for_status = lambda: None; mp.return_value.json = lambda: fake_resp
    r = get_signal(SNAP, RULES)
assert r is None; ok("bad json returns None")

# no rules loaded → still works
with m.patch("nvidia_brain.requests.post") as mp:
    mp.return_value.raise_for_status = lambda: None
    mp.return_value.json = lambda: {"choices": [{"message": {"content": '{"signal":"SELL","confidence":0.7,"reasoning":"Downtrend."}'}}]}
    r = get_signal(SNAP, [])
assert r["signal"] == "SELL"; ok("no rules still works")

print("\nall nvidia_brain tests passed")
