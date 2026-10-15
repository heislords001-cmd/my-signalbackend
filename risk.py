"""Account-level protection. Scalps carry no stop loss, so these limits ARE the safety net."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from broker import Account, Position, money
from config import Pair, Rules


def breach(acct: Account, positions: list[Position], day_start_equity: float, r: Rules) -> str | None:
    """'basket' when floating loss is too deep, 'daily' when the day's drop is too deep, else None."""
    floating = sum(p.profit for p in positions)
    if acct.balance > 0 and floating <= -r.basket_stop_pct / 100 * acct.balance:
        return "basket"
    if day_start_equity > 0 and acct.equity - day_start_equity <= -r.daily_loss_pct / 100 * day_start_equity:
        return "daily"
    return None


def can_open(positions: list[Position], symbol: str, pair: Pair, lot: float, r: Rules) -> bool:
    if lot <= 0 or lot > min(pair.max_lot, r.max_lot_per_trade) + 1e-9:
        return False
    return sum(p.lot for p in positions) + lot <= r.max_total_lots + 1e-9


def in_blackout(now: datetime, r: Rules) -> bool:
    for w in r.blackouts:
        try:
            a, b = (datetime.fromisoformat(x).replace(tzinfo=timezone.utc) for x in w.split("/"))
        except ValueError:
            continue
        if a <= now <= b:
            return True
    return False


def open_risk(positions: list[Position]) -> float:
    """Money lost if every open stop is hit right now (stops already past breakeven count as zero)."""
    total = 0.0
    for p in positions:
        if p.sl is None:
            continue
        d = 1 if p.side == "buy" else -1
        total += money(p.symbol, p.lot, max(0.0, d * (p.entry - p.sl)), p.entry)
    return total


def margin_usd(symbol: str, pair: Pair, lot: float, price: float, leverage: int) -> float:
    notional = lot * pair.contract * (1.0 if symbol.startswith("USD") else price)
    return notional / max(1, leverage)


def fit_lot(symbol: str, desired: float, price: float, stop_dist: float, budget_left: float) -> float:
    """Biggest lot (0.01 steps) not above `desired` whose stop loss fits in the remaining budget; 0 if none."""
    per_lot = money(symbol, 1.0, stop_dist, price)
    if per_lot <= 0 or budget_left <= 0:
        return 0.0
    lot = math.floor(min(desired, budget_left / per_lot) * 100 + 1e-9) / 100
    return lot if lot >= 0.01 else 0.0
