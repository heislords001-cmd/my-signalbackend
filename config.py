"""Every tunable rule lives here. Dashboard Settings override Rules fields at runtime."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pair:
    yf: str          # Yahoo Finance ticker (free price feed)
    base_lot: float  # starting lot per scalp
    max_lot: float   # hard ceiling per position
    max_scalps: int  # cap on open scalps
    contract: int = 100_000  # units per 1.00 lot
    expansion: float = 0.0   # >0: only trade when 5m ATR is at least this multiple of its normal level


PAIRS = {
    "EURUSD": Pair("EURUSD=X", 0.05, 0.10, 20),
    "USDCHF": Pair("CHF=X", 0.05, 0.10, 20),
    "USDCAD": Pair("CAD=X", 0.05, 0.10, 20),
    "USDJPY": Pair("JPY=X", 0.05, 0.10, 20),
    "AUDUSD": Pair("AUDUSD=X", 0.05, 0.10, 20),
    "XAUUSD": Pair("XAUUSD=X", 0.01, 0.03, 8, 100, 1.2),  # gold: smaller lots, lower cap
}


@dataclass
class Rules:
    ema_fast: int = 50
    ema_slow: int = 200
    adx_min: float = 25.0
    atr_period: int = 14
    pullback_atr: float = 0.25    # how close price must come to the 5m EMA 50
    scalp_tp_atr: float = 0.5     # scalp take-profit distance, in ATR
    runner_sl_atr: float = 1.5    # runner stop-loss distance, in ATR
    session_start_utc: int = 12   # 1pm Nigeria time
    session_end_utc: int = 16     # 5pm Nigeria time
    scan_every_sec: int = 20       # how often the scanner wakes up (it only works when a new candle has closed)
    scan_start_utc: int = 0        # scanner hours: all day, Monday to Friday
    scan_end_utc: int = 24
    cooldown_bars: int = 6        # no repeat signal on same pair+side within 6 five-minute bars
    # --- Phase 2: trading ---
    scalp_target: int = 6         # scalps kept open per pair while a trend campaign runs (hard cap: Pair.max_scalps)
    scalp_spacing_atr: float = 0.4  # new scalp must be this far (in ATR) from every open scalp
    runner_max: int = 3
    max_lot_per_trade: float = 0.10
    max_total_lots: float = 3.0
    basket_stop_pct: float = 3.0   # close everything if floating loss reaches this % of balance
    daily_loss_pct: float = 3.0    # close everything and stop for the day at this % equity drop
    basket_cooldown_min: int = 30
    campaign_max_hours: float = 4.0
    campaign_pause_min: int = 30
    max_spread_atr: float = 0.2    # skip entries when spread is wider than this share of ATR
    blackouts: list = field(default_factory=list)  # ["2026-10-14T12:25/2026-10-14T13:05", ...] UTC news windows
    # --- small account mode: every trade has a stop, and total open risk is capped by a budget ---
    small_account: bool = False
    risk_budget_pct: float = 15.0   # max total loss (% of equity) if every open stop is hit
    hard_stop_atr: float = 2.0      # emergency stop on every scalp in small mode
    margin_use_max_pct: float = 40.0
    pairs_off: list = field(default_factory=list)
    pair_rest_hours: float = 6.0    # a pair that keeps losing rests this long
    adapt_min_trades: int = 8


PRESETS = {
    "small": {"small_account": True, "scalp_target": 2, "runner_max": 1, "max_lot_per_trade": 0.01,
              "max_total_lots": 0.05, "risk_budget_pct": 15.0, "hard_stop_atr": 2.0, "margin_use_max_pct": 40.0,
              "basket_stop_pct": 12.0, "daily_loss_pct": 20.0},
}
