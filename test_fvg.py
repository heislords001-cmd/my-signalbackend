"""Fair value gap strategy tests on a built market. No internet needed."""
import sys
sys.path.insert(0, '.')
import numpy as np
import pandas as pd
import strategies as S

def build(n=320, gap_at=300, retrace_at=303, bullish=True):
    idx = pd.date_range("2026-03-02", periods=n, freq="15min", tz="UTC")
    rng = np.random.default_rng(1)
    base = 10 + np.cumsum(rng.normal(0.02, 0.05, n))
    o = base.copy(); c = base + rng.normal(0, 0.03, n)
    h = np.maximum(o, c) + 0.1; l = np.minimum(o, c) - 0.1
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=idx)
    # a clear bullish gap: candle t-2 tops at 12.0, candle t bottoms at 12.6
    g = gap_at
    df.iloc[g - 2, df.columns.get_loc("high")] = 12.0
    df.iloc[g - 2, df.columns.get_loc("close")] = 11.9; df.iloc[g - 2, df.columns.get_loc("open")] = 11.8
    df.iloc[g - 1, df.columns.get_loc("open")] = 11.9; df.iloc[g - 1, df.columns.get_loc("close")] = 12.8
    df.iloc[g - 1, df.columns.get_loc("high")] = 12.9; df.iloc[g - 1, df.columns.get_loc("low")] = 11.85
    df.iloc[g, df.columns.get_loc("low")] = 12.6; df.iloc[g, df.columns.get_loc("open")] = 12.7; df.iloc[g, df.columns.get_loc("close")] = 12.9
    df.iloc[g, df.columns.get_loc("high")] = 13.0
    # price comes back into the gap on the retrace bar and closes back up
    r = retrace_at
    df.iloc[r, df.columns.get_loc("low")] = 12.3; df.iloc[r, df.columns.get_loc("open")] = 12.4; df.iloc[r, df.columns.get_loc("close")] = 12.7
    df.iloc[r, df.columns.get_loc("high")] = 12.8
    return df

def ok(n): print("ok", n)

trend_up = pd.Series(1, index=build().index)
df = build()
out = S.fvg_retrace(df, trend_up)
assert len(out) >= 1 and out.index[-1] == df.index[303] and out.iloc[-1]["side"] == 1, out
ok("a bullish gap that price retraces into and closes up from gives a buy")

sl = out.iloc[-1]["sl"]
assert sl < 12.0 and sl > 11.0, sl                      # stop sits just below the gap's bottom (12.0)
ok("the stop sits beyond the bottom of the gap")

# no look-ahead: the signal on the retrace bar must not change when later candles are removed
short = df.iloc[: 304]
out2 = S.fvg_retrace(short, pd.Series(1, index=short.index))
assert out2.index[-1] == df.index[303]
ok("the signal does not depend on candles that come later (no look-ahead)")

# a trend against the gap gives no buy
assert len(S.fvg_retrace(df, pd.Series(-1, index=df.index)).query("side == 1")) == 0
ok("a buy gap is ignored when the trend is down")

# a gap that price has already closed through is dropped
broken = build()
broken.iloc[305:307, broken.columns.get_loc("close")] = 11.5          # price closes through the gap's bottom
broken.iloc[307, broken.columns.get_loc("low")] = 12.3; broken.iloc[307, broken.columns.get_loc("open")] = 12.4
broken.iloc[307, broken.columns.get_loc("close")] = 12.7; broken.iloc[307, broken.columns.get_loc("high")] = 12.8
after = S.fvg_retrace(broken, trend_up)
assert len(after[after.index >= broken.index[305]]) == 0
ok("a gap is dropped once price closes below it")

assert "fvg_retrace" in S.SIGNAL_FUNCS and S.NAMES["fvg_retrace"] == "Fair value gap"
ok("the strategy is registered so it gets rated and scanned")
print("\nall fair value gap checks passed")
