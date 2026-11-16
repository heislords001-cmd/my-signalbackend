"""The scanner runs only while someone is receiving. No internet needed."""
import sys, logging
sys.path.insert(0, '.')
import worker
logging.disable(logging.CRITICAL)

class Store:
    def __init__(self, receivers, running=True): self.receivers = receivers; self._running = running
    def running(self): return self._running
    def any_receivers(self): return self.receivers > 0
    def beat(self, now): pass
    def error(self, msg): pass
from datetime import datetime, timezone
WED = lambda: datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
calls = []
def cyc(*a): calls.append(1); return 0

r = worker.run_loop(Store(0), None, False, 9999, {}, clock=WED, sleep=lambda s: None, cycle_fn=cyc)
assert r == "nobody receiving" and calls == []
print("ok nobody receiving: the scanner stops without scanning")
calls.clear()
class Busy(Store):
    passes = 0
    def running(self):
        return self.passes < 3            # the test ends the loop after three passes, as a Stop would
def busy_cycle(*a):
    Busy.passes += 1; calls.append(1); return 0
r = worker.run_loop(Busy(2), None, False, 9999, {}, clock=WED, sleep=lambda s: None, cycle_fn=busy_cycle)
assert len(calls) == 3
print("ok someone receiving: the scanner keeps scanning")
class Fake:
    def get(self, *a, **k): pass
import unittest.mock as m
db = worker.Db("https://x.supabase.co", "k")
resp = type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: []})()
with m.patch("worker.requests.get", return_value=resp):
    assert db.any_receivers() is False
resp2 = type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: [{"user_id": "x"}]})()
with m.patch("worker.requests.get", return_value=resp2):
    assert db.any_receivers() is True
print("ok the database check finds receivers by their switch")
print("\nreceiver checks passed")
