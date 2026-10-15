"""Free price feed from Yahoo Finance. Works on any computer (Linux included), needs no account or key.
Prices are close to your broker's but not identical, and can run a few minutes behind."""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

# timeframe -> (Yahoo interval, how far back Yahoo allows, minutes per candle). H4 is built from H1.
SRC = {"M5": ("5m", "60d", 5), "M15": ("15m", "60d", 15), "H1": ("1h", "730d", 60), "D1": ("1d", "10y", 1440)}
TICKERS = {"EURUSD": ["EURUSD=X"], "USDCHF": ["CHF=X"], "USDCAD": ["CAD=X"], "USDJPY": ["JPY=X"],
           "AUDUSD": ["AUDUSD=X"], "XAUUSD": ["XAUUSD=X", "GC=F"]}


class YahooFeed:
    def __init__(self):
        self.cache: dict[tuple, tuple[float, pd.DataFrame]] = {}

    def _raw(self, symbol: str, interval: str, period: str) -> pd.DataFrame:
        key = (symbol, interval)
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < 45:
            return hit[1]
        df = pd.DataFrame()
        for ticker in TICKERS.get(symbol, [symbol]):
            for attempt in range(3):
                try:
                    df = yf.download(ticker, interval=interval, period=period, progress=False, auto_adjust=False, threads=False)
                except Exception:
                    df = pd.DataFrame()
                if len(df):
                    break
                time.sleep(2 * (attempt + 1))
            if len(df):
                break
        self.cache[key] = (time.time(), df)
        return df

    def candles(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        interval, period, minutes = SRC["H1" if tf == "H4" else tf]
        df = self._raw(symbol, interval, period)
        if len(df) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close"])
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
        idx = pd.to_datetime(df.index)
        df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        if tf == "H4":
            df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            minutes = 240
        df = df[df.index + pd.Timedelta(minutes=minutes) <= pd.Timestamp.now(tz="UTC")]   # closed candles only
        return df.tail(n)
