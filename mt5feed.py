"""Real broker candles from MT5 (Windows, MT5 running and logged in). Used by the scanner."""
from __future__ import annotations

import os
import time

import pandas as pd


class MT5Feed:
    def __init__(self, login, password, server, suffix: str = ""):
        import MetaTrader5 as mt5
        self.mt5, self.suffix = mt5, suffix
        if not mt5.initialize(login=int(login), password=password, server=server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        self.tf = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        self.offset = int(os.getenv("MT5_SERVER_UTC_OFFSET_HOURS") or "99") * 3600   # 99 = work it out from a live tick
        if self.offset == 99 * 3600:
            self.offset = self._detect()

    def _sym(self, symbol: str) -> str:
        s = symbol + self.suffix
        self.mt5.symbol_select(s, True)          # a symbol must be in Market Watch before MT5 will give its data
        return s

    def _detect(self) -> int:
        t = self.mt5.symbol_info_tick(self._sym("EURUSD"))
        if not t:
            raise RuntimeError("Cannot read a tick. Set MT5_SERVER_UTC_OFFSET_HOURS in .env (for example 3).")
        hours = round((t.time - time.time()) / 3600)
        if abs(hours) > 12:
            raise RuntimeError("Market looks closed, so the broker's time zone could not be detected. Set MT5_SERVER_UTC_OFFSET_HOURS in .env.")
        return hours * 3600

    def candles(self, symbol: str, tf: str, n: int) -> pd.DataFrame:
        rates = self.mt5.copy_rates_from_pos(self._sym(symbol), self.tf[tf], 1, n)   # start at 1: skip the forming candle
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close"])
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"] - self.offset, unit="s", utc=True)           # broker time -> real UTC
        return df[["open", "high", "low", "close"]]

    def spread(self, symbol: str) -> float:
        i = self.mt5.symbol_info(self._sym(symbol))
        return float(i.spread * i.point) if i else 0.0
