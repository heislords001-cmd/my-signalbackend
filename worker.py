"""Scanner worker. Runs all day, Monday to Friday, on your VPS (Linux is fine). It only READS prices and never trades.
Prices come from Yahoo Finance by default (free, no account). Set FEED=mt5 on a Windows machine with MT5 for real broker prices."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from cloud import load_env, rules_from
from scanner_core import Scanner
from strategies import NAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("worker")


class Db:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/") + "/rest/v1"
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def get(self, table: str, query: str) -> list:
        r = requests.get(f"{self.url}/{table}?{query}", headers=self.h, timeout=20)
        r.raise_for_status()
        return r.json()

    def patch(self, table: str, query: str, body: dict) -> None:
        requests.patch(f"{self.url}/{table}?{query}", headers=self.h, json=body, timeout=20).raise_for_status()

    def upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        h = {**self.h, "Prefer": "resolution=merge-duplicates"}
        requests.post(f"{self.url}/{table}?on_conflict={conflict}", headers=h, json=rows, timeout=30).raise_for_status()

    def new_signal(self, row: dict) -> bool:
        h = {**self.h, "Prefer": "resolution=ignore-duplicates,return=representation"}
        r = requests.post(f"{self.url}/signals?on_conflict=symbol,side,timeframe,strategy,bar_time", headers=h, json=row, timeout=20)
        r.raise_for_status()
        return bool(r.json())          # empty when it was a duplicate


def telegram(text: str) -> None:
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15)


def make_feed():
    if (os.getenv("FEED") or "yahoo") == "mt5":
        from mt5feed import MT5Feed
        return MT5Feed(os.environ["MT5_LOGIN"], os.environ["MT5_PASSWORD"], os.environ["MT5_SERVER"], os.getenv("MT5_SUFFIX", ""))
    from yahoofeed import YahooFeed
    return YahooFeed()


def main() -> None:
    load_env()
    db = Db(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])   # server key: this program stays on YOUR machine
    sc = Scanner(make_feed())
    last_rated, wait = 0.0, 15
    log.info("Scanner started.")
    while True:
        try:
            now = datetime.now(timezone.utc)
            db.patch("scanner_state", "id=eq.1", {"heartbeat": now.isoformat()})
            if db.get("scanner_state", "id=eq.1")[0]["running"]:
                g = db.get("settings", "id=eq.1&select=data")
                r = rules_from(g[0]["data"] if g else {})
                wait = r.scan_every_sec
                if not sc.ratings or time.time() - last_rated > 86400:       # once a day: re-test every strategy on fresh history
                    log.info("Backtesting every pair, timeframe and strategy. This takes a few minutes...")
                    rows = sc.rate_all(r)
                    db.upsert("strategy_stats", rows, "symbol,timeframe,strategy")
                    last_rated = time.time()
                    log.info("Approved %d of %d combinations.", sum(x["enabled"] for x in rows), len(rows))
                for s in sc.scan(now, r):
                    if db.new_signal(s):
                        log.info("signal %s %s %s %s", s["symbol"], s["side"], s["timeframe"], s["strategy"])
                        telegram(f"{s['side'].upper()} {s['symbol']} · {s['timeframe']} · {NAMES[s['strategy']]}\nEntry {s['entry']}\nStop {s['sl']}\nTP1 {s['tp1']}  TP2 {s['tp2']}\nValid until {s['expires_at'][11:16]} UTC, hold up to {s['max_hold_min'] // 60}h")
                since = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
                open_sigs = db.get("signals", f"outcome=is.null&tp1=not.is.null&created_at=gte.{since}&select=id,symbol,timeframe,side,bar_time,entry,sl,tp1&limit=200")
                for u in sc.outcomes(open_sigs, now):
                    db.patch("signals", f"id=eq.{u['id']}", {k: v for k, v in u.items() if k != "id"})
            else:
                wait = 15
        except Exception as e:
            log.warning("loop error: %s", e)
            try:
                db.patch("scanner_state", "id=eq.1", {"last_error": str(e)[:300]})
            except Exception:
                pass
        time.sleep(wait)


if __name__ == "__main__":
    main()
