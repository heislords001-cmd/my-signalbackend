"""
Diagnostics on REAL market data, run from GitHub Actions (Run workflow button). Nothing here trades or publishes.

1. Market data check: for every pair and timeframe, rows, first and last candle, age, duplicates, gaps, bad prices.
2. Real backtest: the scanner's own rating on the real history, one line per strategy combination.
3. Noise baseline: the same bars with their returns shuffled (same volatility, no real structure).
   If the approval rule approves about as many shuffled combinations as real ones, the rule is not finding edge.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import scanner_core as sc
from config import Rules

log = logging.getLogger("diagnose")
TFS = ["M5", "M15", "H1"]
EXPECTED_MIN = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def data_report(feed) -> list[str]:
    lines = [f"{'pair':8s} {'tf':4s} {'rows':>6s} {'last candle (UTC)':>20s} {'age_min':>8s} {'dups':>5s} {'max_gap_min':>11s} {'bad':>4s}"]
    now = datetime.now(timezone.utc)
    for sym in sc.PAIRS:
        for tf in TFS:
            try:
                df = feed.candles(sym, tf, sc.HIST[tf])
            except Exception as e:
                lines.append(f"{sym:8s} {tf:4s} ERROR {e}")
                continue
            if df is None or len(df) == 0:
                lines.append(f"{sym:8s} {tf:4s} {0:6d} {'NO DATA':>20s}")
                continue
            idx = pd.DatetimeIndex(df.index)
            last = idx[-1]
            age = (now - last.to_pydatetime()).total_seconds() / 60 if last.tzinfo else float("nan")
            dups = int(idx.duplicated().sum())
            gaps = np.diff(idx.asi8) / 6e10 if len(idx) > 1 else np.array([0.0])
            max_gap = float(np.max(gaps)) if len(gaps) else 0.0
            bad = int(((df[["open", "high", "low", "close"]] <= 0).any(axis=1) | df[["open", "high", "low", "close"]].isna().any(axis=1)).sum())
            lines.append(f"{sym:8s} {tf:4s} {len(df):6d} {str(last)[:19]:>20s} {age:8.0f} {dups:5d} {max_gap:11.0f} {bad:4d}")
    return lines


def rating_table(scanner) -> tuple[list[str], int]:
    rows = []
    for (sym, tf, name), r in sorted(scanner.ratings.items(), key=lambda kv: -(kv[1].get("test_pf") or 0)):
        rows.append(f"{sym:8s} {tf:4s} {name:18s} trades={r['n']:5d} win={r['win_rate']:.2f} pf={r['pf']:.2f} "
                    f"train_pf={r.get('train_pf', 0):.2f} test_pf={r['test_pf']:.2f} test_n={r['test_n']:4d} "
                    f"{'APPROVED' if r['ok'] else ''}")
    approved = sum(1 for r in scanner.ratings.values() if r["ok"])
    return rows, approved


def shuffled_feed(feed, seed: int = 7):
    """Same candles, returns shuffled in time: keeps volatility, destroys any real structure."""
    rng = np.random.default_rng(seed)

    class Shuffled:
        def candles(self, sym, tf, n):
            df = feed.candles(sym, tf, n).copy()
            if len(df) < 10:
                return df
            c = df["close"].values
            r = np.diff(np.log(c))
            rng.shuffle(r)
            new_c = c[0] * np.exp(np.r_[0.0, np.cumsum(r)])
            scale = new_c / c
            for col in ("open", "high", "low"):
                df[col] = df[col].values * scale
            df["close"] = new_c
            return df
    return Shuffled()


def run(feed) -> str:
    out = ["=== 1. MARKET DATA CHECK (real candles) ==="]
    out += data_report(feed)
    real = sc.Scanner(feed)
    real.rate_all(Rules())
    rows, real_ok = rating_table(real)
    out += ["", "=== 2. REAL BACKTEST (strategy combinations, best test profit factor first) ==="] + rows
    out += [f"approved on real data: {real_ok} of {len(real.ratings)}"]
    base = sc.Scanner(shuffled_feed(feed))
    base.rate_all(Rules())
    _, noise_ok = rating_table(base)
    out += ["", "=== 3. NOISE BASELINE (same bars, returns shuffled) ==="]
    out += [f"approved on shuffled data: {noise_ok} of {len(base.ratings)}"]
    out += ["", "How to read this: real approvals should clearly beat the shuffled count. If they do not, the strategies have no edge."]
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from worker import make_feed
    print(run(make_feed()))
