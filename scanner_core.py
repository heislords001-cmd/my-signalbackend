"""Scanner brain, no network code: rates every (pair, timeframe, strategy) by backtest, then watches for fresh
signals and tracks how each signal ended. worker.py connects it to MT5 and Supabase."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

import backtest
from config import PAIRS, Rules
from strategies import NAMES, SIGNAL_FUNCS, TF_MIN, TIMEFRAMES, htf_trend

log = logging.getLogger("scanner")
HIST = {"M5": 40000, "M15": 20000, "H1": 10000, "H4": 3000, "D1": 1000}   # candles used for backtests
NOT_ENOUGH_DATA = {"n": 0, "win_rate": 0.0, "pf": 0.0, "expectancy": 0.0, "max_dd": 0.0, "test_pf": 0.0, "test_n": 0, "ok": False, "grade": None}
LIVE = 1500                                                              # candles used to look for a live signal


def fresh(rows: list[dict], hours: float = 26) -> bool:
    """True when the saved strategy results are recent enough to trust without testing again."""
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    return bool(rows) and all(pd.Timestamp(r["updated_at"]) > cutoff for r in rows)


def _round(x: float, ref: float) -> float:
    return round(float(x), 5 if ref < 50 else 3)


class Scanner:
    def __init__(self, feed):
        self.feed = feed
        self.ratings: dict[tuple, dict] = {}
        self.last_bar: dict[tuple, pd.Timestamp] = {}
        self.last_sent: dict[tuple, pd.Timestamp] = {}
        self.htf_cache: dict[tuple, tuple[datetime, pd.DataFrame]] = {}

    def summary(self) -> dict:
        """What the site should tell you: how many strategy combinations exist, how many passed, and why it may be quiet."""
        combos = len(self.ratings)
        with_data = sum(1 for x in self.ratings.values() if x["n"] > 0)
        approved = sum(1 for x in self.ratings.values() if x["ok"])
        if combos == 0 or with_data == 0:
            note = "No price data came back from Yahoo, so nothing could be tested. If this runs on GitHub, Yahoo may be blocking it."
        elif approved == 0:
            note = "No strategy has passed the test yet, so no approved signals are sent. Untested signals are shown to you only, marked Untested."
        else:
            note = f"{approved} of {combos} strategy combinations passed the test."
        return {"approved": approved, "combos": combos, "note": note}

    def load_ratings(self, rows: list[dict]) -> None:
        for x in rows:
            self.ratings[(x["symbol"], x["timeframe"], x["strategy"])] = {
                "ok": bool(x["enabled"]), "n": x.get("trades") or 0, "win_rate": float(x.get("win_rate") or 0), "pf": float(x.get("pf") or 0),
                "expectancy": float(x.get("expectancy") or 0), "max_dd": float(x.get("max_dd") or 0), "test_pf": float(x.get("test_pf") or 0),
                "test_n": x.get("test_n") or 0, "grade": None}

    def seed_cooldown(self, rows: list[dict]) -> None:
        for x in rows:
            key, ts = (x["symbol"], x["side"], x["timeframe"], x["strategy"]), pd.Timestamp(x["bar_time"])
            if key not in self.last_sent or ts > self.last_sent[key]:
                self.last_sent[key] = ts

    # ---- daily: which strategies deserve to send signals ---------------------
    def rate_all(self, r: Rules) -> list[dict]:
        rows = []
        for sym in PAIRS:
            for tf, (htf, _valid, hold) in TIMEFRAMES.items():
                try:
                    df, h = self.feed.candles(sym, tf, HIST[tf]), self.feed.candles(sym, htf, HIST[htf])
                    trend = htf_trend(h, df.index, TF_MIN[htf], TF_MIN[tf], r.adx_min)
                except Exception as e:
                    log.warning("rating %s %s skipped: %s", sym, tf, e)
                    continue
                for name, fn in SIGNAL_FUNCS.items():
                    res = backtest.rate(fn(df, trend), df, hold) if len(df) > 300 else dict(NOT_ENOUGH_DATA)
                    self.ratings[(sym, tf, name)] = res
                    rows.append({"symbol": sym, "timeframe": tf, "strategy": name, "enabled": res["ok"], "trades": res["n"],
                                 "win_rate": round(res["win_rate"], 4), "pf": round(res["pf"], 3), "expectancy": round(res["expectancy"], 4),
                                 "max_dd": round(res["max_dd"], 2), "test_pf": round(res["test_pf"], 3), "test_n": res["test_n"],
                                 "updated_at": datetime.utcnow().isoformat() + "Z"})
        return rows

    # ---- every cycle: look for a signal on any candle that just closed ----------
    def _htf(self, sym: str, htf: str, now: datetime) -> pd.DataFrame:
        hit = self.htf_cache.get((sym, htf))
        if hit is None or now - hit[0] > timedelta(minutes=max(1, TF_MIN[htf] // 4)):
            hit = (now, self.feed.candles(sym, htf, min(LIVE, HIST[htf])))
            self.htf_cache[(sym, htf)] = hit
        return hit[1]

    def scan(self, now: datetime, r: Rules, unapproved: bool = False, gate_clock: bool = False) -> list[dict]:
        out: list[dict] = []
        if now.weekday() >= 5 or not (r.scan_start_utc <= now.hour < r.scan_end_utc):
            return out
        ts = pd.Timestamp(now).tz_localize("UTC") if pd.Timestamp(now).tzinfo is None else pd.Timestamp(now)
        for sym in PAIRS:
            if sym in r.pairs_off:
                continue
            for tf, (htf, valid, hold) in TIMEFRAMES.items():
                if gate_clock and (now.hour * 60 + now.minute) % TF_MIN[tf] >= 3:
                    continue                                    # cron mode: only look in the 3 minutes after a candle closes
                names = [n for n in SIGNAL_FUNCS if unapproved or self.ratings.get((sym, tf, n), {}).get("ok")]
                last = self.last_bar.get((sym, tf))
                if not names or (last is not None and ts < last + pd.Timedelta(minutes=2 * TF_MIN[tf])):
                    continue                                    # nothing approved, or the next candle has not closed yet
                try:
                    df = self.feed.candles(sym, tf, LIVE)
                    if len(df) < 300 or (last is not None and df.index[-1] <= last):
                        continue
                    self.last_bar[(sym, tf)] = df.index[-1]
                    bar_close = df.index[-1] + pd.Timedelta(minutes=TF_MIN[tf])
                    if ts - bar_close > pd.Timedelta(minutes=valid * TF_MIN[tf]):
                        continue                                # stale (for example after an outage)
                    trend = htf_trend(self._htf(sym, htf, now), df.index, TF_MIN[htf], TF_MIN[tf], r.adx_min)
                    spread = self.feed.spread(sym) if hasattr(self.feed, "spread") else 0.0
                    for name in names:
                        sg = SIGNAL_FUNCS[name](df, trend)
                        if sg.empty or sg.index[-1] != df.index[-1]:
                            continue
                        s = sg.iloc[-1]
                        if spread and spread > r.max_spread_atr * s.atr:
                            continue
                        side = "buy" if s.side == 1 else "sell"
                        key = (sym, side, tf, name)
                        if key in self.last_sent and df.index[-1] - self.last_sent[key] < pd.Timedelta(minutes=r.cooldown_bars * TF_MIN[tf]):
                            continue
                        self.last_sent[key] = df.index[-1]
                        rt = self.ratings.get((sym, tf, name), NOT_ENOUGH_DATA)
                        e = s.entry
                        out.append({"symbol": sym, "side": side, "timeframe": tf, "htf": htf, "strategy": name,
                                    "entry": _round(e, e), "sl": _round(s.sl, e), "tp1": _round(s.tp1, e), "tp2": _round(s.tp2, e),
                                    "atr": _round(s.atr, e), "bar_time": df.index[-1].isoformat(),
                                    "expires_at": (bar_close + pd.Timedelta(minutes=valid * TF_MIN[tf])).isoformat(),
                                    "max_hold_min": hold * TF_MIN[tf], "win_rate": round(rt["win_rate"], 4),
                                    "pf": round(rt["pf"], 3), "bt_trades": rt["n"], "approved": bool(rt["ok"])})
                except Exception as ex:
                    log.warning("%s %s: %s", sym, tf, ex)
        return out

    # ---- how did earlier signals end? ---------------------------------------------
    def outcomes(self, open_signals: list[dict], now: datetime) -> list[dict]:
        updates = []
        for s in open_signals:
            try:
                tf = s["timeframe"]
                if tf not in TIMEFRAMES:
                    continue
                hold = TIMEFRAMES[tf][2]
                df = self.feed.candles(s["symbol"], tf, 600)
                after = df[df.index > pd.Timestamp(s["bar_time"])]
                res = backtest.resolve(1 if s["side"] == "buy" else -1, s["entry"], s["sl"], s["tp1"],
                                       after["high"].values, after["low"].values, after["close"].values, hold)
                if res:
                    updates.append({"id": s["id"], "outcome": res[0], "result_r": round(res[1], 3), "closed_at": now.isoformat()})
            except Exception as ex:
                log.warning("outcome %s: %s", s.get("id"), ex)
        return updates
