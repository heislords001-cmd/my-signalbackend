"""The scanner's strategies. Each one receives closed candles of the entry timeframe plus the higher-timeframe
trend and returns EVERY signal as a table (one row per signal candle). A signal on candle i only uses data up to
candle i, so the same code can be backtested and run live."""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy import adx, atr, ema

TF_MIN = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}
# entry timeframe -> (higher timeframe that must agree, candles a signal stays valid, max candles to hold the trade)
TIMEFRAMES = {"M5": ("H1", 3, 48), "M15": ("H4", 3, 32), "H1": ("D1", 2, 24)}
MIN_RISK_ATR, MAX_RISK_ATR = 0.8, 2.5      # stop distance bounds, in ATR
TP1_R, TP2_R = 1.5, 3.0                    # targets as multiples of the risk


def htf_trend(htf: pd.DataFrame, ltf_index: pd.DatetimeIndex, htf_min: int, ltf_min: int, adx_min: float = 25.0) -> pd.Series:
    """+1 up, -1 down, 0 none, on the entry-timeframe index. A higher candle only counts after it has CLOSED."""
    if len(htf) == 0:
        return pd.Series(0, index=ltf_index)
    c = htf["close"]
    f, s, a = ema(c, 50), ema(c, 200), adx(htf)
    t = pd.Series(0, index=htf.index)
    t[(c > s) & (f > s) & (a >= adx_min)] = 1
    t[(c < s) & (f < s) & (a >= adx_min)] = -1
    t.iloc[:230] = 0                                            # EMA 200 needs history before it means anything
    t.index = t.index + pd.Timedelta(minutes=htf_min)
    decide = ltf_index + pd.Timedelta(minutes=ltf_min)          # we decide when the entry candle closes
    known = t.reindex(t.index.union(decide)).ffill().reindex(decide).fillna(0).astype(int)
    return pd.Series(known.values, index=ltf_index)


def _pack(df, a, buy, sell, sl_buy, sl_sell) -> pd.DataFrame:
    c = df["close"]
    buy, sell = buy & ~sell, sell & ~buy
    side = pd.Series(0, index=df.index)
    side[buy], side[sell] = 1, -1
    sl = pd.Series(np.nan, index=df.index)
    sl[buy], sl[sell] = sl_buy[buy], sl_sell[sell]
    risk = (c - sl).abs().clip(lower=MIN_RISK_ATR * a)
    ok = (side != 0) & (risk <= MAX_RISK_ATR * a) & (np.arange(len(df)) >= 250)   # skip the indicator warm-up
    out = pd.DataFrame({"side": side, "entry": c, "sl": c - side * risk, "tp1": c + side * TP1_R * risk,
                        "tp2": c + side * TP2_R * risk, "atr": a})
    return out[ok]


def trend_pullback(df: pd.DataFrame, trend: pd.Series) -> pd.DataFrame:
    """Higher timeframe trend is up/down; price pulls back to EMA 50 and a candle closes back in the trend direction."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    f, a = ema(c, 50), atr(df)
    lo2, hi2 = np.minimum(l, l.shift()), np.maximum(h, h.shift())
    buy = (trend == 1) & (lo2 <= f + 0.25 * a) & (c > f) & (c > o)
    sell = (trend == -1) & (hi2 >= f - 0.25 * a) & (c < f) & (c < o)
    return _pack(df, a, buy, sell, lo2 - 0.25 * a, hi2 + 0.25 * a)


def structure_retest(df: pd.DataFrame, trend: pd.Series, k: int = 3, window: int = 12) -> pd.DataFrame:
    """Market structure: price breaks the last swing high (low), comes back to retest that level and holds it.
    A swing is only known k candles after it formed, so nothing here looks into the future."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    a, n = atr(df), len(df)
    pos = np.arange(n)

    def swing(s: pd.Series, top: bool) -> pd.Series:
        ext = s.rolling(2 * k + 1, center=True).max() if top else s.rolling(2 * k + 1, center=True).min()
        return s.where(s == ext).shift(k).ffill()

    def since(event: pd.Series) -> pd.Series:
        return pd.Series(pos - pd.Series(np.where(event, pos, np.nan), index=df.index).ffill().values, index=df.index)

    sh, sw = swing(h, True).shift(), swing(l, False).shift()          # levels known BEFORE this candle
    up, dn = (c > sh) & (c.shift() <= sh), (c < sw) & (c.shift() >= sw)
    up_lvl, dn_lvl = sh.where(up).ffill(), sw.where(dn).ffill()
    buy = (since(up) >= 2) & (since(up) <= window) & (l <= up_lvl + 0.3 * a) & (c > up_lvl) & (c > o) & (trend >= 0)
    sell = (since(dn) >= 2) & (since(dn) <= window) & (h >= dn_lvl - 0.3 * a) & (c < dn_lvl) & (c < o) & (trend <= 0)
    return _pack(df, a, buy, sell, np.minimum(l, l.shift()) - 0.2 * a, np.maximum(h, h.shift()) + 0.2 * a)


SIGNAL_FUNCS = {"trend_pullback": trend_pullback, "structure_retest": structure_retest}
NAMES = {"trend_pullback": "Trend pullback", "structure_retest": "Structure retest"}
