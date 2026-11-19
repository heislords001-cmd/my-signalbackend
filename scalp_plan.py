"""The scalp decision, ported from the site's planScalp so it runs on the GitHub scanner run.
Rules are identical: they must match lib/_trade.ts. test_scalp_plan.py checks both give the same answer."""
from __future__ import annotations
import math
from datetime import datetime, timezone

SCALP_TP_ATR = 0.5     # take profit: half a typical candle
SCALP_SL_ATR = 2.0     # emergency stop: two typical candles
STALE_MS = 10 * 60_000
SCALP_SYMBOLS = {"EURUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "XAUUSD"}   # the pairs the site trades (SYMBOLS in _trade.ts)


def plan(row: dict, now_ms: float | None = None) -> dict:
    """Returns {'ok': True, side, entry, sl, tp1, updated_at} or {'ok': False, reason}."""
    now_ms = datetime.now(timezone.utc).timestamp() * 1000 if now_ms is None else now_ms
    no = lambda reason: {"ok": False, "reason": reason}
    if row.get("symbol") not in SCALP_SYMBOLS:
        return no("unknown symbol")
    trend = row.get("trend")
    side = "buy" if trend == "buy" else "sell" if trend == "sell" else None
    if not side:
        return no("no confirmed trend")
    try:
        p, e, a = float(row["price"]), float(row["ema50"]), float(row["atr"])
    except (KeyError, TypeError, ValueError):
        return no("bad market numbers")
    if not all(math.isfinite(x) and x > 0 for x in (p, e, a)):
        return no("bad market numbers")
    at = _parse_ms(row.get("updated_at"))
    if at is None or now_ms - at > STALE_MS:
        return no("market data is stale")
    if (p <= e) if side == "buy" else (p >= e):
        return no("price is on the wrong side of the average")
    if abs(p - e) > 1.5 * a:
        return no("price has run too far from the average")
    d = 1 if side == "buy" else -1
    return {"ok": True, "side": side, "entry": p, "sl": p - d * SCALP_SL_ATR * a, "tp1": p + d * SCALP_TP_ATR * a,
            "symbol": row["symbol"], "updated_at": row["updated_at"]}


def _parse_ms(v) -> float | None:
    if v is None:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp() * 1000
