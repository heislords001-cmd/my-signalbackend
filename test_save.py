"""Signals still save when a newer column is missing from the database. No internet needed."""
import sys, logging
sys.path.insert(0, '.')
import unittest.mock as m
import worker
logging.disable(logging.CRITICAL)

class R:
    def __init__(self, code, body, text=""):
        self.status_code = code; self._b = body; self.text = text
    def json(self): return self._b
    def raise_for_status(self):
        if self.status_code >= 300: raise RuntimeError(f"HTTP {self.status_code}")

row = {"symbol": "EURUSD", "side": "buy", "timeframe": "M5", "strategy": "trend_pullback", "bar_time": "t", "entry": 1.1,
       "sl": 1.098, "tp1": 1.103, "tp2": 1.106, "agreement": "H1 agrees", "approved": True}
db = worker.Db("https://x.supabase.co", "k")
sent = []

# 1. the agreement column is missing: the signal still saves, without that field
def fake_missing(url, headers=None, json=None, timeout=None):
    sent.append(dict(json))
    if "agreement" in json:
        return R(400, None, '{"message":"Could not find the \'agreement\' column of \'signals\' in the schema cache"}')
    return R(201, [{"id": 1}])
with m.patch("worker.requests.post", side_effect=fake_missing):
    assert db.new_signal(row) is True
assert "agreement" not in sent[-1] and sent[-1]["symbol"] == "EURUSD"
print("ok a missing optional column is dropped and the signal still saves")

# 2. a missing ESSENTIAL column still fails loudly (we never silently drop the price levels)
def fake_essential(url, headers=None, json=None, timeout=None):
    return R(400, None, '{"message":"column signals.entry does not exist"}')
with m.patch("worker.requests.post", side_effect=fake_essential):
    try:
        db.new_signal(row); raise AssertionError("should have failed")
    except RuntimeError:
        pass
print("ok a missing essential column is still reported, not hidden")

# 3. a normal save is unchanged
with m.patch("worker.requests.post", return_value=R(201, [{"id": 2}])):
    assert db.new_signal(row) is True
print("ok a normal save works as before")
print("\nsave checks passed")
