"""Trading engine: scalp book + runner book, trend campaigns, trailing stops, kill switch. Broker-agnostic."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import risk
import strategy
from broker import Broker, Position, money
from config import PAIRS, Pair, Rules

log = logging.getLogger("engine")


@dataclass
class Campaign:
    side: str
    started: datetime
    realised: float = 0.0   # closed scalp profit in this campaign; it pays for runner risk


class Engine:
    def __init__(self, broker: Broker):
        self.b = broker
        self.campaigns: dict[str, Campaign] = {}
        self.pause_until: dict[str, datetime] = {}
        self.r0: dict[int, float] = {}        # runner ticket -> initial stop distance
        self.tags: dict[int, str] = {}        # ticket -> 'scalp' | 'runner'
        self.counted: set[int] = set()
        self.day = None
        self.day_start_equity = 0.0
        self.closed_today = 0.0
        self.halt_until: datetime | None = None
        self.note = ""
        self.results: dict[str, deque] = {}   # recent closed-trade profits per pair

    # ---- main loop step -------------------------------------------------
    def tick(self, now: datetime, r: Rules, bot_on: bool, kill: bool) -> dict:
        acct = self.b.account()
        if self.day != now.date():
            self.day, self.day_start_equity, self.closed_today = now.date(), acct.equity, 0.0
            self.counted.clear()
        pos = self.b.positions()
        for p in pos:
            self.tags[p.ticket] = p.tag
        self._tally(now, r)

        if kill:
            self._close_all(pos)
            self.campaigns.clear()
            self.note = f"Kill switch used at {now:%H:%M}. All trades closed."
            return self.snapshot()

        why = risk.breach(acct, pos, self.day_start_equity, r)
        if why:
            self._close_all(pos)
            self.campaigns.clear()
            self.halt_until = (datetime.combine(now.date() + timedelta(days=1), time.min, timezone.utc)
                               if why == "daily" else now + timedelta(minutes=r.basket_cooldown_min))
            self.note = f"{why.capitalize()} loss limit hit at {now:%H:%M}. All trades closed."
            return self.snapshot()

        self._manage_runners(self.b.positions(), r)
        halted = self.halt_until is not None and now < self.halt_until
        if bot_on and not halted and strategy.in_session(now, r) and not risk.in_blackout(now, r):
            self.halt_until = None
            for sym, pair in PAIRS.items():
                if sym in r.pairs_off:
                    continue
                self._symbol(sym, pair, now, r)
        return self.snapshot()

    # ---- per pair ---------------------------------------------------------
    def _symbol(self, sym: str, pair: Pair, now: datetime, r: Rules) -> None:
        if now < self.pause_until.get(sym, now):
            return
        try:
            h1, m5 = self.b.candles(sym, "1h", 400), self.b.candles(sym, "5m", 400)
            side = strategy.trend(h1, r)
            camp = self.campaigns.get(sym)
            if camp and (side != camp.side or now - camp.started > timedelta(hours=r.campaign_max_hours)):
                self._end_campaign(sym)
                if side == camp.side:                       # ran out of time, not out of trend: rest a while
                    self.pause_until[sym] = now + timedelta(minutes=r.campaign_pause_min)
                    return
                camp = None
            if side is None:
                return

            bid, ask = self.b.quote(sym)
            mid = (bid + ask) / 2
            f = float(strategy.ema(m5["close"], r.ema_fast).iloc[-1])
            atr = strategy.atr(m5, r.atr_period)
            a = float(atr.iloc[-1])
            if a <= 0 or ask - bid > r.max_spread_atr * a:
                return
            if pair.expansion and a < pair.expansion * float(atr.tail(200).median()):
                return                                      # e.g. gold: only when volatility is expanding
            sig = strategy.setup(m5, side, pair, r)
            mine = [p for p in self.b.positions() if p.symbol == sym]
            scalps = [p for p in mine if p.tag == "scalp"]
            runners = [p for p in mine if p.tag == "runner"]

            if camp is None:                                # ignition: first pullback of a confirmed trend
                if sig and self._scalp(sym, side, pair, atr, a, r):
                    self.campaigns[sym] = Campaign(side, now)
                return

            on_side = mid > f if side == "buy" else mid < f
            spaced = all(abs(mid - p.entry) >= r.scalp_spacing_atr * a for p in scalps)
            if on_side and abs(mid - f) <= 1.5 * a and spaced and len(scalps) < min(r.scalp_target, pair.max_scalps):
                self._scalp(sym, side, pair, atr, a, r)

            if sig and len(runners) < r.runner_max:         # runners only once scalp profit covers their stop loss
                lot = self._lot(atr, pair, r)
                risk_usd = money(sym, lot, r.runner_sl_atr * a, mid)
                if camp.realised + sum(p.profit for p in scalps) >= risk_usd:
                    self._runner(sym, side, pair, atr, a, r)
        except Exception as e:                              # one bad pair must not stop the others
            log.warning("%s: %s", sym, e)

    def _lot(self, atr, pair: Pair, r: Rules) -> float:
        return max(0.01, min(strategy.lot_size(atr, pair), r.max_lot_per_trade))

    def _px(self, sym: str, side: str) -> float:
        bid, ask = self.b.quote(sym)
        return ask if side == "buy" else bid

    def _fit(self, sym, pair, desired, px, stop, r) -> float:
        """Small account mode: biggest lot that fits the risk budget and the margin cap, else 0."""
        acct, pos = self.b.account(), self.b.positions()
        left = r.risk_budget_pct / 100 * acct.equity - risk.open_risk(pos)
        lot = risk.fit_lot(sym, desired, px, stop, left)
        if lot <= 0:
            return 0.0
        used = sum(risk.margin_usd(p.symbol, PAIRS[p.symbol], p.lot, p.entry, acct.leverage) for p in pos)
        if used + risk.margin_usd(sym, pair, lot, px, acct.leverage) > r.margin_use_max_pct / 100 * acct.equity:
            return 0.0
        return lot

    def _order(self, sym, side, pair, atr, a, r, kind: str) -> bool:
        lot = self._lot(atr, pair, r)
        px, d = self._px(sym, side), 1 if side == "buy" else -1
        stop = (r.runner_sl_atr if kind == "runner" else r.hard_stop_atr) * a
        sl = px - d * stop if kind == "runner" or r.small_account else None
        tp = px + d * r.scalp_tp_atr * a if kind == "scalp" else None
        if r.small_account:
            lot = self._fit(sym, pair, lot, px, stop, r)
            if lot <= 0:
                return False
        if not risk.can_open(self.b.positions(), sym, pair, lot, r):
            return False
        t = self.b.open(sym, side, lot, sl, tp, kind)
        self.tags[t] = kind
        if kind == "runner":
            self.r0[t] = r.runner_sl_atr * a
        return True

    def _scalp(self, sym, side, pair, atr, a, r) -> bool:
        return self._order(sym, side, pair, atr, a, r, "scalp")

    def _runner(self, sym, side, pair, atr, a, r) -> bool:
        return self._order(sym, side, pair, atr, a, r, "runner")

    def _end_campaign(self, sym: str) -> None:
        """Trend lost (or time up): close the scalps, lock runners at breakeven if they are in profit."""
        self.campaigns.pop(sym, None)
        for p in self.b.positions():
            if p.symbol != sym:
                continue
            if p.tag == "scalp":
                self._safe_close(p)
            elif p.tag == "runner" and p.sl is not None:
                d = 1 if p.side == "buy" else -1
                bid, ask = self.b.quote(sym)
                if d * ((bid if d == 1 else ask) - p.entry) > 0 and d * (p.entry - p.sl) > 0:
                    self.b.modify_sl(p.ticket, p.entry)

    # ---- runners -------------------------------------------------------------
    def _manage_runners(self, pos: list[Position], r: Rules) -> None:
        """Breakeven at +1R, then trail behind the 5m EMA 50. The stop only ever moves in our favour."""
        for p in pos:
            if p.tag != "runner" or p.sl is None:
                continue
            try:
                d = 1 if p.side == "buy" else -1
                bid, ask = self.b.quote(p.symbol)
                price = bid if d == 1 else ask
                m5 = self.b.candles(p.symbol, "5m", 400)
                f = float(strategy.ema(m5["close"], r.ema_fast).iloc[-1])
                a = float(strategy.atr(m5, r.atr_period).iloc[-1])
                r0 = self.r0.get(p.ticket) or abs(p.entry - p.sl)
                new = p.sl
                if d * (price - p.entry) >= r0 and d * (new - p.entry) < 0:
                    new = p.entry
                if d * (new - p.entry) >= 0:
                    trail = f - d * 0.25 * a
                    if d * (trail - new) > 0:
                        new = trail
                if new != p.sl and d * (price - new) > 0:
                    self.b.modify_sl(p.ticket, new)
            except Exception as e:
                log.warning("trail %s: %s", p.ticket, e)

    # ---- housekeeping ---------------------------------------------------------
    def _tally(self, now: datetime, r: Rules) -> None:
        since = datetime.combine(self.day, time.min, timezone.utc)
        for d in self.b.closed_deals(since):
            if d.ticket in self.counted:
                continue
            self.counted.add(d.ticket)
            self.closed_today += d.profit
            h = self.results.setdefault(d.symbol, deque(maxlen=10))
            h.append(d.profit)
            if len(h) >= r.adapt_min_trades and sum(h) < 0:      # keeps losing: rest this pair
                self.pause_until[d.symbol] = now + timedelta(hours=r.pair_rest_hours)
                self.note = f"{d.symbol} resting after a losing run."
                h.clear()
            c = self.campaigns.get(d.symbol)
            if c and (d.tag or self.tags.get(d.ticket)) == "scalp":
                c.realised += d.profit

    def _safe_close(self, p: Position) -> None:
        try:
            self.b.close(p.ticket)
        except Exception as e:
            log.error("close %s failed: %s", p.ticket, e)

    def _close_all(self, pos: list[Position]) -> None:
        for p in pos:
            self._safe_close(p)

    def snapshot(self) -> dict:
        acct, pos = self.b.account(), self.b.positions()
        floating = sum(p.profit for p in pos)
        bal = acct.balance or 1.0
        dse = self.day_start_equity or acct.equity or 1.0
        return {
            "account": {"balance": round(acct.balance, 2), "equity": round(acct.equity, 2), "floating": round(floating, 2),
                        "closed_today": round(self.closed_today, 2),
                        "scalps": sum(p.tag == "scalp" for p in pos), "runners": sum(p.tag == "runner" for p in pos),
                        "basket_pct": round(max(0.0, -floating) / bal * 100, 2),
                        "daily_pct": round(max(0.0, dse - acct.equity) / dse * 100, 2),
                        "lots": round(sum(p.lot for p in pos), 2)},
            "positions": pos, "note": self.note,
        }
