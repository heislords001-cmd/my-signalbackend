"""Tests for the bounded run loop. No internet, no real database."""
from datetime import datetime, timezone
import sys; sys.path.insert(0, '.')
import worker

WED = lambda: datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)          # forex open
SAT = lambda: datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)          # forex closed

class Store:
    def __init__(self, running_seq):
        self.seq = list(running_seq); self.paused_marks = []; self.errors = []
    def running(self):
        return self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
    def set_running(self, on): self.paused_marks.append(on)
    def error(self, msg): self.errors.append(msg)

def ok(n): print("ok", n)

# 1. Stop pressed before the first pass: no scan happens at all
calls = []
store = Store([False])
r = worker.run_loop(store, None, False, 9999, {}, clock=WED, sleep=lambda s: None,
                    cycle_fn=lambda *a: calls.append(1) or 15)
assert r == "stopped" and calls == []; ok("stop before start: zero scans")

# 2. Running, then Stop pressed after two passes: scans twice, then stops cleanly
calls = []
store = Store([True, True, False])
r = worker.run_loop(store, None, False, 9999, {}, clock=WED, sleep=lambda s: None,
                    cycle_fn=lambda *a: calls.append(1) or 0)
assert r == "stopped" and len(calls) == 2; ok("stop pressed mid-run: stops after current pass")

# 3. Time limit reached: stops and marks the site paused
calls = []
store = Store([True])
t = {"now": 0.0}
import time as _t
real = _t.time
_t.time = lambda: t["now"]
try:
    def fake_cycle(*a):
        calls.append(1); t["now"] += 100; return 15
    r = worker.run_loop(store, None, False, 250, {}, clock=WED,
                        sleep=lambda s: t.__setitem__("now", t["now"] + s), cycle_fn=fake_cycle)
finally:
    _t.time = real
assert r == "timeout" and store.paused_marks == [False]; ok("time limit: stops and marks paused")
assert len(calls) <= 4; ok("time limit: bounded number of scans")

# 4. Forex closed: exits immediately, no scans, no minutes wasted
calls = []
store = Store([True])
r = worker.run_loop(store, None, False, 9999, {}, clock=SAT, sleep=lambda s: None,
                    cycle_fn=lambda *a: calls.append(1) or 15)
assert r == "closed" and calls == []; ok("weekend: exits at once")

# 5. A failing pass is logged and the loop keeps its place (does not crash)
calls = []
store = Store([True, True, False])
def flaky(*a):
    calls.append(1)
    if len(calls) == 1: raise RuntimeError("feed down")
    return 0
r = worker.run_loop(store, None, False, 9999, {}, clock=WED, sleep=lambda s: None, cycle_fn=flaky)
assert r == "stopped" and len(calls) == 2 and store.errors == ["feed down"]; ok("error in a pass: logged, loop continues")

print("\nall run loop tests passed")
