"""Worker wiring, local files, messages and Telegram setup. Run: python test_worker.py"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import timedelta

import pandas as pd

import notify
import scanner_core as sc
import telegram_setup
import worker
from config import Rules
from localstore import LocalStore
from test_scanner import BASE, FakeFeed, setup as scan_setup
from test_strategies import to_h1
import strategies as S

SIG = {"symbol": "EURUSD", "side": "buy", "timeframe": "M5", "htf": "H1", "strategy": "trend_pullback", "entry": 1.1, "sl": 1.098, "tp1": 1.103,
       "tp2": 1.106, "bar_time": "2026-03-10T12:00:00+00:00", "expires_at": "2026-03-10T12:20:00+00:00", "max_hold_min": 240,
       "win_rate": 0.6, "pf": 1.5, "bt_trades": 40, "approved": True, "grade": "A"}


def test_local_store():
    d = tempfile.mkdtemp()
    s = LocalStore(d)
    assert s.running() and s.new_signal(dict(SIG)) and not s.new_signal(dict(SIG))             # duplicate ignored
    assert s.new_signal({**SIG, "side": "sell"})
    rows = [json.loads(x) for x in open(os.path.join(d, "signals.jsonl"))]
    assert [r["id"] for r in rows] == [1, 2] and rows[0]["outcome"] is None
    assert len(s.open_signals("2000-01-01")) == 2
    s.update_signal(1, {"outcome": "tp", "result_r": 1.5})
    assert [r["id"] for r in s.open_signals("2000-01-01")] == [2]
    csv = open(os.path.join(d, "signals.csv")).read().splitlines()
    assert csv[0].startswith("created_at,symbol,side") and len(csv) == 3 and "tp" in csv[1]
    s.save_stats([{"a": 1}]); assert json.load(open(s.stats)) == [{"a": 1}]


def test_message_and_telegram():
    m = notify.format_signal(SIG)
    assert "BUY EURUSD" in m and "M5" in m and "Trend pullback" in m and "Stop 1.098" in m and "TP2 1.106" in m and "UNTESTED" not in m and "PREMIUM grade A" in m
    assert "UNTESTED" in notify.format_signal({**SIG, "approved": False}) and "Backtest: 60% wins" in m
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        os.environ.pop(k, None)
    assert notify.telegram("hi") is False                                                      # not set up: quietly does nothing


def test_telegram_setup():
    calls = {"n": 0}
    def fake_api(token, method, **p):
        calls["n"] += 1
        return {"result": [] if calls["n"] < 3 else [{"message": {"chat": {"id": 987654}}}]}
    telegram_setup.api, telegram_setup.time.sleep = fake_api, lambda s: None
    assert telegram_setup.find_chat("t") == 987654 and calls["n"] == 3
    d = tempfile.mkdtemp(); p = os.path.join(d, ".env")
    open(p, "w").write("SUPABASE_URL=keep\nTELEGRAM_BOT_TOKEN=\nFEED=yahoo\n")
    telegram_setup.write_env({"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": 5}, p)
    out = open(p).read().splitlines()
    assert out == ["SUPABASE_URL=keep", "TELEGRAM_BOT_TOKEN=tok", "FEED=yahoo", "TELEGRAM_CHAT_ID=5"]


def test_db_strips_local_only_field():
    sent = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return [{"id": 1}]
    worker.requests.post = lambda url, headers=None, json=None, timeout=None: (sent.update(body=json, url=url), R())[1]
    assert worker.Db("https://x.supabase.co", "k").new_signal(dict(SIG)) is True
    assert "approved" not in sent["body"] and "on_conflict=symbol,side,timeframe,strategy,bar_time" in sent["url"]


def test_full_cycle_local():
    """Rate -> find a signal -> save it -> second pass adds nothing -> a later pass tracks the outcome."""
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        os.environ.pop(k, None)
    scanner = scan_setup()
    store = LocalStore(tempfile.mkdtemp())
    sg = S.trend_pullback(BASE, S.htf_trend(to_h1(BASE), BASE.index, 60, 5))
    t = [x for x in sg.index[len(sg) // 3:] if x.weekday() < 5][0]
    scanner.feed.end = t + pd.Timedelta(minutes=4)
    now = (t + pd.Timedelta(minutes=5, seconds=2)).to_pydatetime()
    state: dict = {}
    wait = worker.cycle(store, scanner, now, True, state)
    assert wait == Rules().scan_every_sec and state["rated"] > 0
    saved = [json.loads(x) for x in open(store.jsonl)]
    assert any(r["strategy"] == "trend_pullback" and r["bar_time"] == t.isoformat() for r in saved)
    assert all("approved" in r and r["outcome"] is None for r in saved)
    n = len(saved)
    worker.cycle(store, scanner, now + timedelta(seconds=30), True, state)
    assert len(open(store.jsonl).read().splitlines()) == n                                     # same candle: nothing new


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all worker tests passed")
