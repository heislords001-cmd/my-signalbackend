"""Scanner plumbing with a fake feed. Run: python test_scanner.py"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

import scanner_core as sc
import strategies as S
from config import PAIRS, Rules
from test_strategies import market, to_h1

BASE = market()


class FakeFeed:
    """Serves the synthetic market, cut off at `end` so we can step through time."""
    def __init__(self):
        self.end = BASE.index[-1]

    def candles(self, sym, tf, n):
        d = BASE[BASE.index <= self.end]
        if tf != "M5":
            d = d.resample({"M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D"}[tf]).agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            d = d[d.index + pd.Timedelta(minutes=S.TF_MIN[tf]) <= self.end + pd.Timedelta(minutes=5)]   # closed candles only
        return d.tail(n)

    def spread(self, sym):
        return 0.0


def setup(monkey=True):
    sc.PAIRS = {"EURUSD": PAIRS["EURUSD"]}
    sc.TIMEFRAMES = {"M5": S.TIMEFRAMES["M5"]}
    return sc.Scanner(FakeFeed())


def test_rate_then_scan_then_dedupe():
    r = Rules()
    s = setup()
    rows = s.rate_all(r)
    assert {x["strategy"] for x in rows} == set(S.SIGNAL_FUNCS) and all({"symbol", "timeframe", "enabled", "pf", "win_rate", "trades"} <= set(x) for x in rows)
    for k in s.ratings:
        s.ratings[k]["ok"] = True                       # approve everything for this plumbing test
    sg = S.trend_pullback(BASE, S.htf_trend(to_h1(BASE), BASE.index, 60, 5))
    t = [x for x in sg.index[len(sg) // 3:] if x.weekday() < 5][0]      # a weekday candle that has a signal
    s.feed.end = t + pd.Timedelta(minutes=4)            # that candle has just closed
    at = (t + pd.Timedelta(minutes=5, seconds=2)).to_pydatetime()
    out = [x for x in s.scan(at, r) if x["strategy"] == "trend_pullback"]
    assert len(out) == 1, out
    x = out[0]
    assert x["timeframe"] == "M5" and x["htf"] == "H1" and x["symbol"] == "EURUSD"
    assert x["side"] in ("buy", "sell") and x["tp2"] != x["tp1"] and x["max_hold_min"] == 240
    assert pd.Timestamp(x["expires_at"]) == t + pd.Timedelta(minutes=5 + 15)             # valid for 3 more candles
    assert [y for y in s.scan(at + timedelta(seconds=30), r) if y["strategy"] == "trend_pullback"] == []   # same candle: no duplicate


def test_weekend_and_unapproved_are_silent():
    r = Rules()
    s = setup()
    s.rate_all(r)
    sat = pd.Timestamp("2026-03-07 12:00", tz="UTC").to_pydatetime()
    assert s.scan(sat, r) == []
    for k in s.ratings:
        s.ratings[k]["ok"] = False
    s.feed.end = BASE.index[5000]
    assert s.scan(pd.Timestamp("2026-03-18 12:00", tz="UTC").to_pydatetime(), r) == []   # nothing approved: nothing sent


def test_outcomes():
    s = setup()
    df = BASE.iloc[:3000]
    s.feed.end = df.index[-1]
    t = df.index[-100]
    entry = float(df.close.iloc[-100])
    up = {"id": 1, "symbol": "EURUSD", "timeframe": "M5", "side": "buy", "bar_time": t.isoformat(), "entry": entry, "sl": entry - 1.0, "tp1": entry + 1e-6}
    dn = {"id": 2, "symbol": "EURUSD", "timeframe": "M5", "side": "buy", "bar_time": t.isoformat(), "entry": entry, "sl": entry - 1e-6, "tp1": entry + 1.0}
    pend = {"id": 3, "symbol": "EURUSD", "timeframe": "M5", "side": "buy", "bar_time": df.index[-2].isoformat(), "entry": entry, "sl": entry - 1.0, "tp1": entry + 1.0}
    got = {u["id"]: u for u in s.outcomes([up, dn, pend], df.index[-1].to_pydatetime())}
    assert got[1]["outcome"] == "tp" and got[2]["outcome"] == "sl" and 3 not in got      # id 3 is still open


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all scanner tests passed")
