"""Scalper tests on the paper broker. No money, no MT5 needed."""
from datetime import datetime, timezone
import sys; sys.path.insert(0, '.')
from broker import PaperBroker
from scalper import Scalper, ScalpCfg

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
ATR = 0.0004

def setup(mid=1.1000):
    b = PaperBroker(balance=1000.0, spread=0.00001)
    b.set_quote("EURUSD", mid)
    return b

def ok(n): print("ok", n)

def cluster_positions(b, cid):
    return [p for p in b.positions() if p.tag == f"scalp:EURUSD:{cid}"]

# 1. a buy trend opens 3 positions at the base lot
b = setup(); s = Scalper(b, "EURUSD")
s.step("buy", ATR, NOW)
ps = cluster_positions(b, 1)
assert len(ps) == 3 and all(p.lot == 0.01 and p.side == "buy" for p in ps)
ok("buy trend opens 3 positions at 0.01 lots")

# 2. price rises: the cluster closes at target, lot doubles, half the profit goes to reserve
b.set_quote("EURUSD", 1.1010)
s.step("buy", ATR, NOW)
assert cluster_positions(b, 1) == [] and s.state["history"][-1]["result"] > 0
assert s.state["lot"] == 0.02
assert abs(s.state["reserve"] - s.state["history"][-1]["result"] * 0.5) < 1e-9
ok("winning cluster closes at target, lot doubles, half banked to reserve")

# 3. the next cluster uses the bigger lot
s.step("buy", ATR, NOW)
ps = cluster_positions(b, 2)
assert len(ps) == 3 and all(p.lot == 0.02 for p in ps)
ok("next cluster opens at the bigger lot")

# 4. a losing cluster resets the lot to base
b.set_quote("EURUSD", 1.0980)
s.step("buy", ATR, NOW)
assert cluster_positions(b, 2) == [] and s.state["history"][-1]["result"] < 0
assert s.state["lot"] == 0.01
ok("losing cluster closes and resets lot to base")

# 5. the trend flipping closes an open cluster straight away
b = setup(); s = Scalper(b, "EURUSD")
s.step("buy", ATR, NOW)
s.step("sell", ATR, NOW)
assert cluster_positions(b, 1) == [] and "trend changed" in s.state["history"][-1]["reason"]
ok("trend flip closes the open cluster")

# 6. no trend, no trade
b = setup(); s = Scalper(b, "EURUSD")
s.step("none", ATR, NOW)
assert b.positions() == []
ok("no trend means no trades")

# 7. the daily loss cap stops new clusters for the rest of the day
b = setup(); s = Scalper(b, "EURUSD", state={"day": NOW.date().isoformat(), "day_realized": -5.0})
s.step("buy", ATR, NOW)
assert b.positions() == [] and any("daily loss cap" in m for m in s.log)
ok("daily loss cap halts new clusters")

# 8. the cap resets on a new day
b = setup(); s = Scalper(b, "EURUSD", state={"day": "2026-11-10", "day_realized": -5.0})
s.step("buy", ATR, NOW)
assert len(b.positions()) == 3
ok("loss cap resets on a new day")

# 9. the open-position limit is respected
b = setup(); s = Scalper(b, "EURUSD", cfg=ScalpCfg(max_open=3))
s.step("buy", ATR, NOW)
b.set_quote("EURUSD", 1.1000)
s.step("buy", ATR, NOW)
assert len(b.positions()) == 3
ok("max open positions respected")

# 10. every position carries an emergency stop on the correct side
b = setup(); s = Scalper(b, "EURUSD")
s.step("buy", ATR, NOW)
assert all(p.sl < p.entry for p in b.positions())
b = setup(); s = Scalper(b, "EURUSD")
s.step("sell", ATR, NOW)
assert all(p.sl > p.entry for p in b.positions())
ok("emergency stops are on the correct side for buys and sells")

# 11. the cluster stop closes a cluster that goes against us
b = setup(); s = Scalper(b, "EURUSD")
s.step("buy", ATR, NOW)
b.set_quote("EURUSD", 1.0970)
s.step("buy", ATR, NOW)
assert cluster_positions(b, 1) == [] and s.state["history"][-1]["reason"] == "cluster stop"
ok("cluster stop closes a losing cluster")

# 12. the state survives a restart (it can be saved and loaded)
b = setup(); s = Scalper(b, "EURUSD")
s.step("buy", ATR, NOW); b.set_quote("EURUSD", 1.1010); s.step("buy", ATR, NOW)
saved = dict(s.state)
s2 = Scalper(b, "EURUSD", state=saved)
assert s2.state["lot"] == s.state["lot"] and s2.state["reserve"] == s.state["reserve"]
ok("state can be saved and reloaded")

print("\nall scalper tests passed")
