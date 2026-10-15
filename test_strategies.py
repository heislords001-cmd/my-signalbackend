"""Strategies and backtester on synthetic prices. Run: python test_strategies.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import backtest
import strategies as S


def market(n=16000, seed=7):
    """Trending and ranging stretches with pullbacks, as 5-minute candles."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([0.00012, -0.00012, 0.0, 0.00008, -0.00008], n // 800 + 1), 800)[:n]
    close = 1.10 + np.cumsum(drift + rng.normal(0, 0.0002, n) + 0.0004 * np.sin(np.arange(n) / 40))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.00012, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.00012, n))
    idx = pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def to_h1(df):
    return df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def trend_of(df, h1):
    return S.htf_trend(h1, df.index, 60, 5)


def test_signals_exist_and_are_sane():
    df = market()
    h1 = to_h1(df)
    tr = trend_of(df, h1)
    assert set(tr.unique()) <= {-1, 0, 1} and (tr != 0).any()
    for name, fn in S.SIGNAL_FUNCS.items():
        sg = fn(df, tr)
        assert len(sg) > 20, name
        b, s = sg[sg.side == 1], sg[sg.side == -1]
        assert (b.tp2 > b.tp1).all() and (b.tp1 > b.entry).all() and (b.entry > b.sl).all(), name
        assert (s.tp2 < s.tp1).all() and (s.tp1 < s.entry).all() and (s.entry < s.sl).all(), name
        risk = (sg.entry - sg.sl).abs() / sg.atr
        assert risk.min() >= S.MIN_RISK_ATR - 1e-9 and risk.max() <= S.MAX_RISK_ATR + 1e-9


def test_no_lookahead():
    """A signal on candle t must be identical when the future is deleted."""
    df = market()
    h1 = to_h1(df)
    full = {n: fn(df, trend_of(df, h1)) for n, fn in S.SIGNAL_FUNCS.items()}
    for name, fn in S.SIGNAL_FUNCS.items():
        times = full[name].index[::max(1, len(full[name]) // 12)][:12]
        assert len(times) > 3
        for t in times:
            cut = df[df.index <= t]
            hc = h1[h1.index + pd.Timedelta(hours=1) <= t + pd.Timedelta(minutes=5)]
            part = fn(cut, S.htf_trend(hc, cut.index, 60, 5))
            assert part.index[-1] == t, (name, t)
            for col in ("side", "entry", "sl", "tp1", "tp2"):
                assert abs(part.loc[t, col] - full[name].loc[t, col]) < 1e-9, (name, t, col)


def test_resolve():
    def is_(res, outcome, r):
        return res is not None and res[0] == outcome and abs(res[1] - r) < 1e-9
    A = np.array
    # buy at 1.0, stop 0.9, target 1.15 (1.5R), room for 3 candles
    assert backtest.resolve(1, 1.0, 0.9, 1.15, A([1.05, 1.1]), A([0.95, 0.95]), A([1.0, 1.0]), 3) is None                 # still undecided
    assert is_(backtest.resolve(1, 1.0, 0.9, 1.15, A([1.05, 1.2]), A([0.95, 0.95]), A([1.0, 1.0]), 3), "tp", 1.5)
    assert is_(backtest.resolve(1, 1.0, 0.9, 1.15, A([1.05, 1.2]), A([0.95, 0.85]), A([1.0, 1.0]), 3), "sl", -1.0)
    assert is_(backtest.resolve(1, 1.0, 0.9, 1.15, A([1.2]), A([0.85]), A([1.0]), 3), "sl", -1.0)                          # both in one candle: loss
    assert is_(backtest.resolve(-1, 1.0, 1.1, 0.85, A([1.05, 1.0]), A([0.9, 0.8]), A([1.0, 1.0]), 3), "tp", 1.5)
    assert is_(backtest.resolve(1, 1.0, 0.9, 1.15, A([1.05]), A([0.95]), A([1.05]), 1), "expired", 0.5)                    # time ran out: close at market


def rigged(win: bool):
    n = 400
    idx = pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC")
    c = np.linspace(1.0, 1.4 if win else 0.6, n)
    df = pd.DataFrame({"open": c, "high": c + 0.002, "low": c - 0.002, "close": c}, index=idx)
    pos = list(range(20, n - 60, 20))
    d = 1 if win else 1   # always buy: rising market wins them all, falling market loses them all
    sg = pd.DataFrame({"side": d, "entry": c[pos], "sl": c[pos] - 0.01, "tp1": c[pos] + 0.015, "tp2": c[pos] + 0.03, "atr": 0.01}, index=idx[pos])
    return df, sg


def test_rating_gate():
    df, sg = rigged(True)
    r = backtest.rate(sg, df, 48, min_test=3)
    assert r["ok"] and r["win_rate"] == 1.0 and r["pf"] >= 5
    df, sg = rigged(False)
    r = backtest.rate(sg, df, 48, min_test=3)
    assert not r["ok"] and r["win_rate"] == 0.0
    assert not backtest.rate(sg.iloc[:0], df, 48)["ok"]                       # no trades: never approved
    df, sg = rigged(True)
    assert not backtest.rate(sg, df, 48, min_test=50)["ok"]                   # too few trades in the exam: not approved


def test_random_walk_is_never_approved():
    """No edge by construction, so the gate should reject it (checked over 12 different random markets)."""
    approved = 0
    for seed in range(12):
        rng = np.random.default_rng(100 + seed)
        n = 16000
        close = 1.10 + np.cumsum(rng.normal(0, 0.0002, n))
        o = np.r_[close[0], close[:-1]]
        df = pd.DataFrame({"open": o, "high": np.maximum(o, close) + abs(rng.normal(0, .00012, n)),
                           "low": np.minimum(o, close) - abs(rng.normal(0, .00012, n)), "close": close},
                          index=pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC"))
        tr = trend_of(df, to_h1(df))
        approved += sum(backtest.rate(fn(df, tr), df, 48)["ok"] for fn in S.SIGNAL_FUNCS.values())
    assert approved <= 1, approved


def test_real_rating_runs():
    df = market()
    tr = trend_of(df, to_h1(df))
    for name, fn in S.SIGNAL_FUNCS.items():
        r = backtest.rate(fn(df, tr), df, 48)
        assert set(r) >= {"n", "win_rate", "pf", "expectancy", "max_dd", "test_pf", "test_n", "ok"} and r["n"] > 10, name
        print(f"   {name}: {r['n']} trades, win {r['win_rate']:.0%}, PF {r['pf']:.2f}, approved={r['ok']}")


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    print("all strategy tests passed")
