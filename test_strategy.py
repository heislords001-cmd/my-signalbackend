"""Sanity tests on synthetic prices (no internet needed). Run: python test_strategy.py"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

import strategy
from config import PAIRS, Rules

R = Rules()


def make(n, drift, step, seed=1):
    rng = np.random.default_rng(seed)
    close = 1.10 + np.cumsum(drift + rng.normal(0, 0.00008, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.00005
    low = np.minimum(open_, close) - 0.00005
    idx = pd.date_range("2026-09-01", periods=n, freq=step, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def test_trend():
    assert strategy.trend(make(600, 0.0004, "1h"), R) == "buy"
    assert strategy.trend(make(600, -0.0004, "1h"), R) == "sell"
    assert strategy.trend(make(600, 0.0, "1h"), R) is None
    assert strategy.trend(make(100, 0.0004, "1h"), R) is None  # not enough history


def pullback(drift, side):
    m5 = make(400, drift, "5min")
    f = strategy.ema(m5["close"], 50).iloc[-1]
    a = strategy.atr(m5).iloc[-1]
    d = 1 if side == "buy" else -1
    m5.iloc[-2, m5.columns.get_loc("low" if side == "buy" else "high")] = f
    last = m5.index[-1]
    m5.loc[last, ["open", "close"]] = [f, f + d * 0.8 * a]
    m5.loc[last, "high"] = max(f, f + d * 0.8 * a) + 0.00005
    m5.loc[last, "low"] = min(f, f + d * 0.8 * a) - 0.00005
    return m5


def test_setup():
    for drift, side in ((0.00004, "buy"), (-0.00004, "sell")):
        s = strategy.setup(pullback(drift, side), side, PAIRS["EURUSD"], R)
        assert s and s["side"] == side
        if side == "buy":
            assert s["scalp_tp"] > s["entry"] > s["runner_sl"]
        else:
            assert s["scalp_tp"] < s["entry"] < s["runner_sl"]
        assert 0.025 <= s["lot"] <= PAIRS["EURUSD"].max_lot
    assert strategy.setup(make(400, 0.00004, "5min"), None, PAIRS["EURUSD"], R) is None


def test_session():
    ok = datetime(2026, 10, 12, 13, tzinfo=timezone.utc)      # Monday 13:00 UTC
    assert strategy.in_session(ok, R)
    assert not strategy.in_session(ok.replace(hour=20), R)
    assert not strategy.in_session(datetime(2026, 10, 10, 13, tzinfo=timezone.utc), R)  # Saturday


if __name__ == "__main__":
    test_trend(); test_setup(); test_session()
    print("all tests passed")
