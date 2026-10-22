"""Small account mode, gold filter and pair rest. Run: python test_small.py"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import risk
from broker import Deal, PaperBroker
from config import PAIRS, PRESETS, Rules
from engine import Engine
from test_engine import R, T0, env, step, tags
from test_strategy import make, pullback

SMALL = Rules(**PRESETS["small"])


def small_env(balance, leverage):
    b = PaperBroker(balance=balance, leverage=leverage)
    from test_strategy import make, pullback
    m5 = pullback(0.00004, "buy")
    b.data[("EURUSD", "1h")], b.data[("EURUSD", "5m")] = make(600, 0.0004, "1h"), m5
    mid = float(m5["close"].iloc[-1])
    b.set_quote("EURUSD", mid)
    return b, Engine(b), mid


def run(b, e, r, mid, steps=6, drift=0.00012):
    peak = 0
    for i in range(steps):
        b.set_quote("EURUSD", mid + i * drift)         # slow drift: spacing allows a refill before the first TP is hit
        step(b, e, T0 + timedelta(minutes=i), r)
        eq = b.account().equity
        assert risk.open_risk(b.positions()) <= r.risk_budget_pct / 100 * eq + 1e-6
        assert all(p.sl is not None and p.lot == 0.01 for p in b.positions())   # every trade has a stop, min lot
        peak = max(peak, len(b.positions()))
    return peak


def test_ten_dollars_low_leverage_margin_cap():
    b, e, mid = small_env(10.0, 500)
    assert run(b, e, SMALL, mid) == 1                   # at 1:500, 40% margin cap fits exactly one 0.01 trade


def test_ten_dollars_high_leverage_risk_budget():
    b, e, mid = small_env(10.0, 3000)
    assert run(b, e, SMALL, mid) == 2                   # margin is no problem at 1:3000, two trades fit the budget
    b, e, mid = small_env(10.0, 3000)
    assert run(b, e, replace(SMALL, risk_budget_pct=10.0), mid) == 1   # a tighter budget allows only one


def test_gold_blocked_by_budget_and_by_volatility_filter():
    def gold_env(balance):
        b = PaperBroker(balance=balance, leverage=500)
        b.data[("XAUUSD", "1h")] = make(600, 0.0004, "1h") * 3500
        b.data[("XAUUSD", "5m")] = pullback(0.00004, "buy") * 3500
        b.set_quote("XAUUSD", float(b.data[("XAUUSD", "5m")]["close"].iloc[-1]))
        return b, Engine(b)
    gold = PAIRS["XAUUSD"]
    try:
        PAIRS["XAUUSD"] = replace(gold, expansion=3.0)   # demands volatility 3x normal: this market is not there
        b, e = gold_env(10_000.0)
        step(b, e, T0)
        assert b.positions() == []
        PAIRS["XAUUSD"] = gold                           # default filter (1.2x): the last candle is a big one, so it passes
        b, e = gold_env(10_000.0)
        step(b, e, T0)
        assert tags(b) == ["scalp"]
        b, e = gold_env(10.0)
        step(b, e, T0, SMALL)
        assert b.positions() == []                       # $10 cannot carry a gold stop or its margin
    finally:
        PAIRS["XAUUSD"] = gold


def test_losing_pair_rests_then_returns():
    b, e, m5, mid, a, f = env()
    wide = replace(R, session_end_utc=24)
    for i in range(8):
        b.deals.append(Deal(i + 1, "EURUSD", -1.0, "scalp", T0))
    step(b, e, T0, wide)
    assert b.positions() == [] and "resting" in e.note
    step(b, e, T0 + timedelta(hours=5), wide)
    assert b.positions() == []
    step(b, e, T0 + timedelta(hours=6, minutes=1), wide)
    assert tags(b) == ["scalp"]


def test_pairs_off():
    b, e, *_ = env()
    step(b, e, T0, replace(R, pairs_off=["EURUSD"]))
    assert b.positions() == []


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all small-account tests passed")
