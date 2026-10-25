"""Cron mode: every run is a brand-new process that must not re-test, re-send or hammer the price feed. Run: python test_cron.py"""
from __future__ import annotations

import tempfile
from datetime import timedelta

import pandas as pd

import scanner_core as sc
import strategies as S
import worker
from config import Rules
from localstore import LocalStore
from test_scanner import BASE, setup as scan_setup
from test_strategies import to_h1


def a_signal_candle():
    sg = S.trend_pullback(BASE, S.htf_trend(to_h1(BASE), BASE.index, 60, 5))
    return [x for x in sg.index[len(sg) // 3:] if x.weekday() < 5][0]


def test_new_process_each_minute():
    first = scan_setup()
    store = LocalStore(tempfile.mkdtemp())
    t = a_signal_candle()
    first.feed.end = t + pd.Timedelta(minutes=4)
    now = (t + pd.Timedelta(minutes=5, seconds=2)).to_pydatetime()
    worker.cycle(store, first, now, True, {}, once=True)                      # run 1: nothing saved yet, so it tests everything
    assert store.load_stats() and sc.fresh(store.load_stats())
    sent = open(store.jsonl).read().splitlines()
    assert any('"trend_pullback"' in x for x in sent)

    second = sc.Scanner(first.feed)                                           # run 2: a brand-new process
    def boom(r):
        raise AssertionError("re-tested the strategies on every run")
    second.rate_all = boom
    worker.cycle(store, second, now + timedelta(seconds=40), True, {}, once=True)
    assert set(second.ratings) == set(first.ratings)                          # it reused the saved results
    assert open(store.jsonl).read().splitlines() == sent                      # and did not send the same signal again


def tf_scanner(tf: str):
    s = scan_setup()                                               # patches the pair list and timeframes for the tests...
    sc.TIMEFRAMES = {tf: S.TIMEFRAMES[tf]}                         # ...then we pick the one timeframe under test
    return s


def count_calls(s):
    calls = {"n": 0}
    real = s.feed.candles
    s.feed.candles = lambda *a, **k: (calls.update(n=calls["n"] + 1), real(*a, **k))[1]
    return calls


def test_slow_timeframes_only_look_after_a_candle_closes():
    s = tf_scanner("M15")
    s.rate_all(Rules())
    for k in s.ratings:
        s.ratings[k]["ok"] = True
    t = [x.floor("15min") for x in BASE.index[5000:5100] if x.weekday() < 5][0]
    s.feed.end = t + pd.Timedelta(minutes=14)
    calls = count_calls(s)
    s.scan((t + pd.Timedelta(minutes=12)).to_pydatetime(), Rules(), True, gate_clock=True)     # 12 minutes into the candle: quiet
    assert calls["n"] == 0
    s.scan((t + pd.Timedelta(minutes=16)).to_pydatetime(), Rules(), True, gate_clock=True)     # a candle just closed: it looks
    assert calls["n"] > 0


def test_five_minute_candles_are_never_skipped_by_a_late_run():
    s = tf_scanner("M5")
    s.rate_all(Rules())
    for k in s.ratings:
        s.ratings[k]["ok"] = True
    t = a_signal_candle()
    s.feed.end = t + pd.Timedelta(minutes=4)
    calls = count_calls(s)
    for late in (0, 1, 2, 3, 4):                                  # runs landing 0 to 4 minutes after the boundary all still look
        s.last_bar.clear()
        calls["n"] = 0
        s.scan((t + pd.Timedelta(minutes=5 + late)).to_pydatetime(), Rules(), True, gate_clock=True)
        assert calls["n"] > 0, late


def test_cooldown_survives_restarts():
    s = scan_setup()
    s.seed_cooldown([{"symbol": "EURUSD", "side": "buy", "timeframe": "M5", "strategy": "trend_pullback", "bar_time": "2026-03-10T12:00:00+00:00"},
                     {"symbol": "EURUSD", "side": "buy", "timeframe": "M5", "strategy": "trend_pullback", "bar_time": "2026-03-10T11:00:00+00:00"}])
    assert s.last_sent[("EURUSD", "buy", "M5", "trend_pullback")] == pd.Timestamp("2026-03-10T12:00:00+00:00")


def test_stale_results_are_retested():
    old = [{"updated_at": "2020-01-01T00:00:00Z"}]
    assert not sc.fresh(old) and not sc.fresh([]) and sc.fresh([{"updated_at": pd.Timestamp.now(tz="UTC").isoformat()}])


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all cron tests passed")
