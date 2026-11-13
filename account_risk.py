"""Sizes each signal's stop loss to a dollar budget, so one stop-out cannot wipe a small account.

The stop is measured at the smallest lot (0.01), because that is the lot a small account actually trades.
  budget      = ACCOUNT_USD x RISK_PCT        (default: $10 x 10% = $1.00 per trade)
  If the volatility stop costs more than the budget at 0.01 lots, the stop is pulled in to fit the budget.
  If it cannot be pulled in without going below FLOOR_ATR x ATR (too tight to be meaningful), the signal is skipped.
Targets are then recalculated from the new stop, keeping the same multiples (1.5R and 3R).
"""
from __future__ import annotations
import os

from broker import money
from strategies import TP1_R, TP2_R

MIN_LOT = 0.01
FLOOR_ATR = 0.5


def account_usd() -> float:
    return float(os.environ.get("ACCOUNT_USD") or 10)


def risk_pct() -> float:
    return float(os.environ.get("RISK_PCT") or 10) / 100


def budget_usd() -> float:
    return account_usd() * risk_pct()


def fit_stop(symbol: str, side: str, entry: float, sl: float, atr: float, budget: float | None = None):
    """Returns the sized sl, tp1, tp2 and the dollar risk at 0.01 lots, or None if the trade does not fit the budget."""
    budget = budget_usd() if budget is None else budget
    d = 1 if side == "buy" else -1
    risk = abs(entry - sl)
    usd_per_price = money(symbol, MIN_LOT, 1.0, entry)
    max_risk = budget / usd_per_price
    if max_risk < FLOOR_ATR * atr:
        return None
    new_risk = min(risk, max_risk)
    return {
        "sl": entry - d * new_risk,
        "tp1": entry + d * TP1_R * new_risk,
        "tp2": entry + d * TP2_R * new_risk,
        "risk_usd": round(new_risk * usd_per_price, 2),
        "tightened": new_risk < risk,
    }
