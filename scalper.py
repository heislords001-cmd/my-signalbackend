"""
Scalper for MT5 (Exness or any MT5 broker). Works on the Broker interface in broker.py.

How a cluster works:
  1. Trend agrees (buy or sell): open `positions` trades at the current lot size, in that one direction.
  2. The cluster closes when its total profit reaches the target (target_usd per trade).
  3. A winning cluster grows the lot size (up to max_lot). Half of the banked profit goes to a reserve
     that the scalper never trades. A losing cluster (or a stop) resets the lot size to base.
  4. If the trend flips, the open cluster is closed at once.
  5. Limits: at most max_open positions at once, a daily loss cap that halts new clusters, and an
     emergency stop on every position (set on the broker, so it works even if the bot is offline).

Nothing here decides a trade by itself: it only acts on the trend that the scanner measures.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from broker import Broker, money


@dataclass
class ScalpCfg:
    base_lot: float = 0.01
    max_lot: float = 0.02
    positions: int = 3
    target_usd: float = 0.50          # profit target per position
    reserve_share: float = 0.50       # share of banked profit kept in reserve
    daily_loss_cap: float = 5.0       # stop opening new clusters after this much loss in a day
    cluster_stop_usd: float = 3.0     # close a cluster that is down this much
    max_open: int = 6
    stop_atr: float = 2.0             # emergency stop on each position, in ATR


@dataclass
class Scalper:
    broker: Broker
    symbol: str
    cfg: ScalpCfg = field(default_factory=ScalpCfg)
    state: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def __post_init__(self):
        self.state.setdefault("lot", self.cfg.base_lot)
        self.state.setdefault("reserve", 0.0)
        self.state.setdefault("day", None)
        self.state.setdefault("day_realized", 0.0)
        self.state.setdefault("next_cid", 1)
        self.state.setdefault("history", [])

    # ── helpers ──────────────────────────────────────────────────────────────
    def _tag(self, cid: int) -> str:
        return f"scalp:{self.symbol}:{cid}"

    def _mine(self):
        prefix = f"scalp:{self.symbol}:"
        return [p for p in self.broker.positions() if p.tag.startswith(prefix)]

    @staticmethod
    def _cid(tag: str) -> int:
        return int(tag.rsplit(":", 1)[1])

    def _mid(self) -> float:
        bid, ask = self.broker.quote(self.symbol)
        return (bid + ask) / 2

    def _record(self, cid: int, side: str, realized: float, reason: str, now: datetime):
        self.state["day_realized"] += realized
        if realized > 0:
            banked = realized
            self.state["reserve"] += banked * self.cfg.reserve_share
            self.state["lot"] = min(self.cfg.max_lot, round(self.state["lot"] * 2, 2))
        else:
            self.state["lot"] = self.cfg.base_lot
        self.state["history"].append({"cid": cid, "side": side, "result": round(realized, 2), "reason": reason, "at": now.isoformat()})
        self.log.append(f"cluster {cid} {side} closed {reason}: {realized:+.2f} USD, next lot {self.state['lot']}")

    # ── one pass: call this on every check (each tick or each minute) ─────────
    def step(self, trend: str, atr: float, now: datetime) -> list[str]:
        self.log = []
        day = now.date().isoformat()
        if self.state["day"] != day:
            self.state["day"] = day
            self.state["day_realized"] = 0.0

        # 1. manage open clusters
        clusters: dict[int, list] = {}
        for p in self._mine():
            clusters.setdefault(self._cid(p.tag), []).append(p)
        for cid, ps in clusters.items():
            side = ps[0].side
            floating = sum(p.profit for p in ps)
            reason = None
            if trend != side:
                reason = "trend changed"
            elif floating >= self.cfg.target_usd * len(ps):
                reason = "target reached"
            elif floating <= -self.cfg.cluster_stop_usd:
                reason = "cluster stop"
            if reason:
                for p in ps:
                    self.broker.close(p.ticket)
                self._record(cid, side, floating, reason, now)

        # 2. open a new cluster only if nothing is open, the trend agrees, and the limits allow it
        open_now = self._mine()
        floating_now = sum(p.profit for p in open_now)
        halted = self.state["day_realized"] + floating_now <= -self.cfg.daily_loss_cap
        if open_now or trend not in ("buy", "sell") or halted:
            if halted and not open_now:
                self.log.append("daily loss cap reached: no new clusters today")
            return self.log
        if len(open_now) + self.cfg.positions > self.cfg.max_open:
            return self.log

        cid = self.state["next_cid"]
        self.state["next_cid"] = cid + 1
        mid = self._mid()
        lot = self.state["lot"]
        sl = mid - self.cfg.stop_atr * atr if trend == "buy" else mid + self.cfg.stop_atr * atr
        for _ in range(self.cfg.positions):
            self.broker.open(self.symbol, trend, lot, round(sl, 5), None, self._tag(cid))
        self.log.append(f"cluster {cid} {trend} opened: {self.cfg.positions} x {lot} lots")
        return self.log
