"""Engine tests with a simulated broker. Run: python test_engine.py"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import strategy
from broker import PaperBroker
from config import PAIRS, Rules
from engine import Engine
from test_strategy import make, pullback

R = Rules()
T0 = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)   # Monday, inside session
P = PAIRS["EURUSD"]


def env():
    b = PaperBroker()
    m5 = pullback(0.00004, "buy")
    b.data[("EURUSD", "1h")], b.data[("EURUSD", "5m")] = make(600, 0.0004, "1h"), m5
    mid = float(m5["close"].iloc[-1])
    b.set_quote("EURUSD", mid)
    f = float(strategy.ema(m5["close"], 50).iloc[-1])
    return b, Engine(b), m5, mid, float(strategy.atr(m5).iloc[-1]), f


def step(b, e, now, r=R, on=True, kill=False):
    b.clock = now
    return e.tick(now, r, on, kill)


def tags(b):
    return sorted(p.tag for p in b.positions())


def test_ignition_and_spacing():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    p = b.positions()
    assert tags(b) == ["scalp"] and p[0].sl is None and p[0].tp > p[0].entry and "EURUSD" in e.campaigns
    step(b, e, T0 + timedelta(minutes=1))
    assert len(b.positions()) == 1                       # same price: spacing blocks a second scalp
    b.set_quote("EURUSD", mid + 0.5 * a)
    step(b, e, T0 + timedelta(minutes=2))
    assert tags(b) == ["scalp", "scalp"]                 # price moved far enough: refill


def test_scalp_tp_then_reopen_and_funding():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    b.set_quote("EURUSD", mid + 0.6 * a)                 # first scalp hits take-profit
    assert len(b.positions()) == 0 and b.deals[0].profit > 0
    step(b, e, T0 + timedelta(minutes=1))
    assert tags(b) == ["scalp"]                          # closed at profit, reopened
    assert e.campaigns["EURUSD"].realised > 0 and "runner" not in tags(b)   # not funded enough for a runner yet


def test_runner_funded_then_trails():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    e.campaigns["EURUSD"].realised = 100.0               # scalps have banked enough to pay for a runner
    step(b, e, T0 + timedelta(minutes=1))
    run = [p for p in b.positions() if p.tag == "runner"]
    assert len(run) == 1 and run[0].sl < run[0].entry and run[0].tp is None
    t, entry, r0 = run[0].ticket, run[0].entry, e.r0[run[0].ticket]
    b.set_quote("EURUSD", entry + 1.05 * r0)
    step(b, e, T0 + timedelta(minutes=2))
    sl = {p.ticket: p for p in b.positions()}[t].sl
    assert abs(sl - entry) < 1e-9                        # +1R: stop moved to breakeven
    b.data[("EURUSD", "5m")] = m5 + 0.0009               # trend moves on, EMA 50 rises
    b.set_quote("EURUSD", entry + 3 * a + 0.0009)
    step(b, e, T0 + timedelta(minutes=3))
    sl2 = {p.ticket: p for p in b.positions()}[t].sl
    assert sl2 > entry                                   # now trailing in profit
    b.data[("EURUSD", "5m")] = m5                        # EMA drops back: stop must never move backwards
    step(b, e, T0 + timedelta(minutes=4))
    assert {p.ticket: p for p in b.positions()}[t].sl == sl2


def test_kill_switch():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    step(b, e, T0 + timedelta(minutes=1), kill=True)
    assert b.positions() == [] and not e.campaigns and "Kill" in e.note


def test_basket_stop_and_cooldown():
    b, e, m5, mid, a, f = env()
    r = replace(R, basket_stop_pct=0.001)                # $0.10 on a $10,000 balance
    step(b, e, T0, r)
    b.set_quote("EURUSD", mid - 0.0001)
    step(b, e, T0 + timedelta(minutes=1), r)
    assert b.positions() == [] and "Basket" in e.note
    step(b, e, T0 + timedelta(minutes=5), r)
    assert b.positions() == []                           # halted during cooldown
    step(b, e, T0 + timedelta(minutes=32), r)
    assert tags(b) == ["scalp"]                          # trading resumes after cooldown


def test_daily_loss_halts_until_tomorrow():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    b.balance -= 400                                     # equity drops 4% on the day
    step(b, e, T0 + timedelta(minutes=1))
    assert b.positions() == [] and e.halt_until.date() == (T0 + timedelta(days=1)).date()
    step(b, e, T0 + timedelta(hours=2))
    assert b.positions() == []


def test_limits_and_gates():
    b, e, *_ = env()
    step(b, e, T0, replace(R, max_total_lots=0.02))      # smaller than one 0.03 lot trade
    assert b.positions() == []
    step(b, e, T0, on=False)                             # bot off: no new trades
    assert b.positions() == []
    step(b, e, T0.replace(hour=20))                      # outside session
    assert b.positions() == []
    step(b, e, T0, replace(R, blackouts=["2026-10-12T12:55/2026-10-12T13:10"]))   # news window
    assert b.positions() == []
    step(b, e, T0 + timedelta(minutes=30))
    assert tags(b) == ["scalp"]


def test_trend_loss_closes_scalps_keeps_runner():
    b, e, m5, mid, a, f = env()
    step(b, e, T0)
    e.campaigns["EURUSD"].realised = 100.0
    step(b, e, T0 + timedelta(minutes=1))
    assert "runner" in tags(b)
    b.data[("EURUSD", "1h")] = make(600, 0.0, "1h")      # trend gone
    step(b, e, T0 + timedelta(minutes=2))
    assert tags(b) == ["runner"] and not e.campaigns


def test_campaign_time_limit_pauses():
    b, e, *_ = env()
    step(b, e, T0)
    step(b, e, T0 + timedelta(hours=3, minutes=59))
    step(b, e, T0 + timedelta(hours=4, minutes=1), replace(R, session_end_utc=24))
    assert "scalp" not in tags(b) and "EURUSD" not in e.campaigns   # closed and resting
    step(b, e, T0 + timedelta(hours=4, minutes=10), replace(R, session_end_utc=24))
    assert b.positions() == []                                      # still resting
    step(b, e, T0 + timedelta(hours=4, minutes=35), replace(R, session_end_utc=24))
    assert tags(b) == ["scalp"]                                     # rest over, new campaign


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all engine tests passed")
