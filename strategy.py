"""EMA 50/200 trend filter (1h) + pullback entry (5m). Pure functions, no I/O."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from config import Pair, Rules


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def trend(h1: pd.DataFrame, r: Rules) -> str | None:
    """'buy' / 'sell' when the 1h chart confirms a trend, else None."""
    if len(h1) < r.ema_slow + 20:
        return None
    c = h1["close"]
    fast, slow = ema(c, r.ema_fast).iloc[-1], ema(c, r.ema_slow).iloc[-1]
    strength = adx(h1, r.atr_period).iloc[-1]
    if np.isnan(strength) or strength < r.adx_min:
        return None
    if c.iloc[-1] > slow and fast > slow:
        return "buy"
    if c.iloc[-1] < slow and fast < slow:
        return "sell"
    return None


def lot_size(a: pd.Series, pair: Pair) -> float:
    """Smaller lots when the market is wilder than usual, bigger when calmer, always inside the caps."""
    ref = float(a.tail(200).median())
    return round(min(pair.max_lot, max(pair.base_lot * 0.5, pair.base_lot * ref / float(a.iloc[-1]))), 2)


def setup(m5: pd.DataFrame, side: str | None, pair: Pair, r: Rules) -> dict | None:
    """Pullback to the 5m EMA 50 that closes back in the trend direction."""
    if side is None or len(m5) < r.ema_slow + 20:
        return None
    f = ema(m5["close"], r.ema_fast).iloc[-1]
    a = atr(m5, r.atr_period)
    now_atr = float(a.iloc[-1])
    bar, prev = m5.iloc[-1], m5.iloc[-2]
    tol = r.pullback_atr * now_atr
    if side == "buy":
        ok = min(prev["low"], bar["low"]) <= f + tol and bar["close"] > f and bar["close"] > bar["open"]
    else:
        ok = max(prev["high"], bar["high"]) >= f - tol and bar["close"] < f and bar["close"] < bar["open"]
    if not ok or now_atr <= 0:
        return None

    d = 1 if side == "buy" else -1
    entry = float(bar["close"])
    nd = 5 if entry < 50 else 3
    return {
        "side": side,
        "entry": round(entry, nd),
        "scalp_tp": round(entry + d * r.scalp_tp_atr * now_atr, nd),
        "runner_sl": round(entry - d * r.runner_sl_atr * now_atr, nd),
        "lot": lot_size(a, pair),
        "atr": round(now_atr, nd),
        "bar_time": m5.index[-1].isoformat(),
    }


def in_session(now: datetime, r: Rules) -> bool:
    return now.weekday() < 5 and r.session_start_utc <= now.hour < r.session_end_utc
