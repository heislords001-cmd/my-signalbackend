"""One full scanner pass must never crash, even when the market is quiet or has no data. No internet needed."""
import sys, logging
sys.path.insert(0, '.')
from datetime import datetime, timezone
import worker
from localstore import LocalStore
import scanner_core as sc
import test_scanner as T
from config import Rules
import tempfile, os
logging.disable(logging.CRITICAL)

class Store(LocalStore):
    """LocalStore plus the database-only methods the pass calls, so the Db code path runs too."""
    def load_live_signals(self): return []
    def save_market(self, rows): self.market = rows
    def save_summary(self, s): self.summary = s

def one_pass(now, feed):
    d = tempfile.mkdtemp(); os.chdir(d)
    st = Store(d)
    sc.market_open = lambda t: True
    s = sc.Scanner(feed)
    state = {}
    return worker.cycle(st, s, now, True, state)

# 1. a normal pass on the test market: runs, returns a wait
feed = T.FakeFeed(); feed.end = T.BASE.index[600]
wait = one_pass((feed.end + __import__('pandas').Timedelta(minutes=5)).to_pydatetime(), feed)
assert isinstance(wait, int) and wait > 0
print("ok a normal pass runs and returns its wait")

# 2. an empty feed (no candles at all): the pass must not crash
class Empty:
    def candles(self, sym, tf, n): 
        import pandas as pd
        return pd.DataFrame(columns=["open","high","low","close"])
    def spread(self, sym): return 0.0
wait = one_pass(datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc), Empty())
assert isinstance(wait, int)
print("ok a pass with no price data runs without crashing")

print("\ncycle checks passed")
