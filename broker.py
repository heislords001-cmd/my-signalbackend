"""Broker adapters. The engine only talks to the Broker interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import pandas as pd

from config import PAIRS


@dataclass
class Account:
    balance: float
    equity: float
    leverage: int = 500


@dataclass
class Position:
    ticket: int
    symbol: str
    side: str            # 'buy' | 'sell'
    lot: float
    entry: float
    sl: float | None
    tp: float | None
    profit: float        # floating, account currency
    tag: str             # 'scalp' | 'runner'
    opened: datetime


@dataclass
class Deal:
    ticket: int          # position ticket it closed
    symbol: str
    profit: float
    tag: str | None
    time: datetime


class Broker(ABC):
    @abstractmethod
    def account(self) -> Account: ...
    @abstractmethod
    def positions(self) -> list[Position]: ...
    @abstractmethod
    def quote(self, symbol: str) -> tuple[float, float]: ...          # (bid, ask)
    @abstractmethod
    def candles(self, symbol: str, interval: str, n: int) -> pd.DataFrame: ...  # closed candles only
    @abstractmethod
    def open(self, symbol: str, side: str, lot: float, sl: float | None, tp: float | None, tag: str) -> int: ...
    @abstractmethod
    def close(self, ticket: int) -> None: ...
    @abstractmethod
    def modify_sl(self, ticket: int, sl: float) -> None: ...
    @abstractmethod
    def closed_deals(self, since: datetime) -> list[Deal]: ...


def usd_per_unit(symbol: str, price: float) -> float:
    return 1.0 if symbol.endswith("USD") else 1.0 / price  # USDJPY, USDCHF, USDCAD profit is in the quote currency


def money(symbol: str, lot: float, price_diff: float, price: float) -> float:
    return price_diff * lot * PAIRS[symbol].contract * usd_per_unit(symbol, price)


class PaperBroker(Broker):
    """Simulated broker for tests and dry runs. Prices are pushed in with set_quote()."""

    def __init__(self, balance: float = 10_000.0, spread: float = 0.00001, leverage: int = 500):
        self.leverage = leverage
        self.balance, self.spread, self.clock = balance, spread, datetime.now(timezone.utc)
        self.q: dict[str, tuple[float, float]] = {}
        self.data: dict[tuple[str, str], pd.DataFrame] = {}
        self._pos: dict[int, Position] = {}
        self.deals: list[Deal] = []
        self._n = 1000

    def set_quote(self, symbol: str, mid: float) -> None:
        self.q[symbol] = (mid - self.spread / 2, mid + self.spread / 2)
        bid, ask = self.q[symbol]
        for p in list(self._pos.values()):
            if p.symbol != symbol:
                continue
            px = bid if p.side == "buy" else ask
            hit_tp = p.tp is not None and ((p.side == "buy" and bid >= p.tp) or (p.side == "sell" and ask <= p.tp))
            hit_sl = p.sl is not None and ((p.side == "buy" and bid <= p.sl) or (p.side == "sell" and ask >= p.sl))
            if hit_tp or hit_sl:
                self._close(p, p.tp if hit_tp else p.sl)

    def _pnl(self, p: Position, px: float) -> float:
        d = 1 if p.side == "buy" else -1
        return money(p.symbol, p.lot, d * (px - p.entry), px)

    def _close(self, p: Position, px: float) -> None:
        profit = self._pnl(p, px)
        self.balance += profit
        self.deals.append(Deal(p.ticket, p.symbol, profit, p.tag, self.clock))
        del self._pos[p.ticket]

    def account(self) -> Account:
        return Account(self.balance, self.balance + sum(p.profit for p in self.positions()), self.leverage)

    def positions(self) -> list[Position]:
        out = []
        for p in self._pos.values():
            bid, ask = self.q[p.symbol]
            out.append(replace(p, profit=self._pnl(p, bid if p.side == "buy" else ask)))
        return out

    def quote(self, symbol):
        return self.q[symbol]

    def candles(self, symbol, interval, n):
        return self.data.get((symbol, interval), pd.DataFrame(columns=["open", "high", "low", "close"])).tail(n)

    def open(self, symbol, side, lot, sl, tp, tag):
        bid, ask = self.q[symbol]
        self._n += 1
        self._pos[self._n] = Position(self._n, symbol, side, lot, ask if side == "buy" else bid, sl, tp, 0.0, tag, self.clock)
        return self._n

    def close(self, ticket):
        p = self._pos[ticket]
        bid, ask = self.q[p.symbol]
        self._close(p, bid if p.side == "buy" else ask)

    def modify_sl(self, ticket, sl):
        self._pos[ticket].sl = sl

    def closed_deals(self, since):
        return [d for d in self.deals if d.time >= since]


class MT5Broker(Broker):
    """Real MT5 account. Needs Windows, the MT5 terminal running, and `pip install MetaTrader5`.
    Needs a HEDGING account (the usual kind for FBS) so each trade is its own position."""

    MAGIC = 440044

    def __init__(self, login: int, password: str, server: str, suffix: str = "", mode: str = "demo"):
        import MetaTrader5 as mt5
        self.mt5, self.suffix, self._sel = mt5, suffix, set()
        if not mt5.initialize(login=int(login), password=password, server=server):
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
        demo = mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        if (mode == "demo") != demo:
            raise RuntimeError(f"TRADING_MODE is '{mode}' but the MT5 account is {'demo' if demo else 'real'}. Stopping.")
        self.tf = {"5m": mt5.TIMEFRAME_M5, "1h": mt5.TIMEFRAME_H1}

    def _s(self, symbol: str) -> str:
        s = symbol + self.suffix
        if s not in self._sel:
            self.mt5.symbol_select(s, True)      # must be in Market Watch before MT5 serves its data
            self._sel.add(s)
        return s

    def account(self):
        i = self.mt5.account_info()
        return Account(i.balance, i.equity, i.leverage)

    def positions(self):
        m = self.mt5
        out = []
        for p in m.positions_get() or []:
            if p.magic != self.MAGIC:
                continue
            out.append(Position(p.ticket, p.symbol.removesuffix(self.suffix) if self.suffix else p.symbol,
                                "buy" if p.type == m.POSITION_TYPE_BUY else "sell", p.volume, p.price_open,
                                p.sl or None, p.tp or None, p.profit + p.swap,
                                p.comment.removeprefix("fx:") or "scalp", datetime.fromtimestamp(p.time, timezone.utc)))
        return out

    def quote(self, symbol):
        t = self.mt5.symbol_info_tick(self._s(symbol))
        return t.bid, t.ask

    def candles(self, symbol, interval, n):
        rates = self.mt5.copy_rates_from_pos(self._s(symbol), self.tf[interval], 1, n)  # start at 1: skip the forming candle
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"], unit="s", utc=True)
        return df[["open", "high", "low", "close"]]

    def _volume(self, info, lot: float) -> float:
        v = round(lot / info.volume_step) * info.volume_step
        return round(max(info.volume_min, min(info.volume_max, v)), 2)

    def _send(self, req: dict):
        res = self.mt5.order_send(req)
        if res is None or res.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order rejected: {getattr(res, 'retcode', None)} {getattr(res, 'comment', '')}")
        return res

    def open(self, symbol, side, lot, sl, tp, tag):
        m, s = self.mt5, self._s(symbol)
        info = m.symbol_info(s)
        bid, ask = self.quote(symbol)
        fill = m.ORDER_FILLING_IOC if info.filling_mode & 2 else m.ORDER_FILLING_FOK if info.filling_mode & 1 else m.ORDER_FILLING_RETURN
        d = info.digits
        res = self._send({
            "action": m.TRADE_ACTION_DEAL, "symbol": s, "volume": self._volume(info, lot),
            "type": m.ORDER_TYPE_BUY if side == "buy" else m.ORDER_TYPE_SELL, "price": ask if side == "buy" else bid,
            "sl": round(sl, d) if sl else 0.0, "tp": round(tp, d) if tp else 0.0, "deviation": 20,
            "magic": self.MAGIC, "comment": f"fx:{tag}", "type_time": m.ORDER_TIME_GTC, "type_filling": fill})
        return res.order

    def close(self, ticket):
        m = self.mt5
        p = (m.positions_get(ticket=ticket) or [None])[0]
        if p is None:
            return
        info = m.symbol_info(p.symbol)
        t = m.symbol_info_tick(p.symbol)
        buy = p.type == m.POSITION_TYPE_BUY
        fill = m.ORDER_FILLING_IOC if info.filling_mode & 2 else m.ORDER_FILLING_FOK if info.filling_mode & 1 else m.ORDER_FILLING_RETURN
        self._send({"action": m.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "position": ticket,
                    "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, "price": t.bid if buy else t.ask,
                    "deviation": 20, "magic": self.MAGIC, "comment": "fx:close", "type_filling": fill})

    def modify_sl(self, ticket, sl):
        m = self.mt5
        p = (m.positions_get(ticket=ticket) or [None])[0]
        if p is not None:
            self._send({"action": m.TRADE_ACTION_SLTP, "position": ticket, "symbol": p.symbol,
                        "sl": round(sl, m.symbol_info(p.symbol).digits), "tp": p.tp})

    def closed_deals(self, since):
        import time
        m = self.mt5
        t = m.symbol_info_tick(self._s("EURUSD"))
        offset = round((t.time - time.time()) / 1800) * 1800 if t else 0   # broker clock vs UTC
        lo = datetime.fromtimestamp(since.timestamp() + offset - 86400, timezone.utc).replace(tzinfo=None)
        hi = datetime.fromtimestamp(time.time() + offset + 86400, timezone.utc).replace(tzinfo=None)
        out = []
        for d in m.history_deals_get(lo, hi) or []:
            if d.magic == self.MAGIC and d.entry == m.DEAL_ENTRY_OUT and d.time >= since.timestamp() + offset:
                out.append(Deal(d.position_id, d.symbol.removesuffix(self.suffix) if self.suffix else d.symbol,
                                d.profit + d.swap + d.commission, None, datetime.fromtimestamp(d.time - offset, timezone.utc)))
        return out
