"""Yahoo feed clean-up, with Yahoo itself faked. Run: python test_yahoofeed.py"""
from __future__ import annotations

import numpy as np
import pandas as pd

import yahoofeed


def fake_download(ticker, interval, period, **kw):
    now = pd.Timestamp.now(tz="UTC").floor("5min")
    idx = pd.date_range(end=now, periods=300, freq="5min")            # last candle is still forming
    c = 1.1 + np.cumsum(np.random.default_rng(1).normal(0, 0.0002, 300))
    df = pd.DataFrame({"Open": c, "High": c + 0.0003, "Low": c - 0.0003, "Close": c, "Adj Close": c, "Volume": 0}, index=idx.tz_localize(None))
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])   # newer yfinance returns two-level columns
    return df


def test_clean_candles():
    yahoofeed.yf.download = fake_download
    f = yahoofeed.YahooFeed()
    m5 = f.candles("EURUSD", "M5", 100)
    assert list(m5.columns) == ["open", "high", "low", "close"] and len(m5) == 100
    assert str(m5.index.tz) == "UTC"
    assert m5.index[-1] + pd.Timedelta(minutes=5) <= pd.Timestamp.now(tz="UTC")        # forming candle removed
    assert f.candles("EURUSD", "M5", 5).index[-1] == m5.index[-1]                       # cached, consistent
    assert f.candles("NOPE", "M5", 5).shape[0] == 5                                    # unknown name falls back to itself


def test_empty_and_h4():
    yahoofeed.yf.download = lambda *a, **k: pd.DataFrame()
    assert len(yahoofeed.YahooFeed().candles("EURUSD", "H1", 50)) == 0
    def hourly(ticker, interval, period, **kw):
        idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("1h"), periods=200, freq="1h").tz_localize(None)
        c = np.linspace(1.0, 1.2, 200)
        return pd.DataFrame({"Open": c, "High": c + .001, "Low": c - .001, "Close": c, "Volume": 0}, index=idx)
    yahoofeed.yf.download = hourly
    h4 = yahoofeed.YahooFeed().candles("EURUSD", "H4", 30)
    assert len(h4) == 30 and (h4.index.hour % 4 == 0).all()


if __name__ == "__main__":
    test_clean_candles(); test_empty_and_h4()
    print("all yahoo feed tests passed")
