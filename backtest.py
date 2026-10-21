"""Backtester. Replays a strategy's signals over history and measures what it would have done.
Pessimistic on purpose: if stop and target are both touched in one candle, it counts as a loss, and every trade pays a cost."""
from __future__ import annotations

import numpy as np
import pandas as pd

COST_ATR = 0.1   # assumed spread + slippage per trade, as a share of ATR


def resolve(side: int, entry: float, sl: float, tp: float, hi, lo, cl, max_hold: int):
    """Walk the candles AFTER the signal. Returns (outcome, r, candles) or None while still undecided."""
    risk = abs(entry - sl)
    rr = abs(tp - entry) / risk
    hi, lo, cl = hi[:max_hold], lo[:max_hold], cl[:max_hold]
    for j in range(len(hi)):
        sl_hit = lo[j] <= sl if side == 1 else hi[j] >= sl
        tp_hit = hi[j] >= tp if side == 1 else lo[j] <= tp
        if sl_hit:
            return "sl", -1.0, j + 1
        if tp_hit:
            return "tp", rr, j + 1
    if len(hi) < max_hold or len(hi) == 0:
        return None
    return "expired", float((cl[-1] - entry) * side / risk), len(hi)


def simulate(df: pd.DataFrame, sigs: pd.DataFrame, max_hold: int, cost_atr: float = COST_ATR) -> pd.DataFrame:
    """One trade at a time per combo. Returns r (in units of risk, after cost) indexed by signal time."""
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    busy, rows = -1, []
    for i, s in zip(df.index.get_indexer(sigs.index), sigs.itertuples()):
        if i <= busy:
            continue
        res = resolve(int(s.side), s.entry, s.sl, s.tp1, hi[i + 1:], lo[i + 1:], cl[i + 1:], max_hold)
        if res is None:
            continue
        outcome, r, bars = res
        busy = i + bars
        rows.append((df.index[i], r - cost_atr * s.atr / abs(s.entry - s.sl), outcome))
    return pd.DataFrame(rows, columns=["time", "r", "outcome"]).set_index("time")


def stats(r: pd.Series) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "pf": 0.0, "expectancy": 0.0, "max_dd": 0.0}
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    return {"n": n, "win_rate": float((r > 0).mean()), "pf": float(min(99.0, win / loss)) if loss > 0 else 99.0,
            "expectancy": float(r.mean()), "max_dd": float((eq.cummax() - eq).max())}


def rate(sigs: pd.DataFrame, df: pd.DataFrame, max_hold: int, min_test: int = 15) -> dict:
    """Judge a strategy on data it was NOT tuned on: the first 70% is the trial, the last 30% is the exam. Both must pass."""
    trades = simulate(df, sigs, max_hold) if len(sigs) else pd.DataFrame(columns=["r", "outcome"])
    allst = stats(trades["r"])
    if allst["n"] == 0:
        return {**allst, "train_pf": 0.0, "test_pf": 0.0, "test_n": 0, "ok": False, "grade": None}
    cut = df.index[int(len(df) * 0.7)]
    tr, te = stats(trades.loc[trades.index < cut, "r"]), stats(trades.loc[trades.index >= cut, "r"])
    ok = te["n"] >= min_test and tr["pf"] >= 1.1 and te["pf"] >= 1.15 and te["expectancy"] > 0
    # grade A = passed a stricter exam (Premium), B = passed the basic exam, None = not approved
    grade = ("A" if te["pf"] >= 1.5 and te["n"] >= 25 and tr["pf"] >= 1.3 else "B") if ok else None
    return {**allst, "train_pf": tr["pf"], "test_pf": te["pf"], "test_n": te["n"], "ok": bool(ok), "grade": grade}
