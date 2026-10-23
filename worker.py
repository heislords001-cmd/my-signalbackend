"""Scanner worker. Runs all day, Monday to Friday. It only READS prices and never trades.
Prices come from Yahoo Finance (free). It can run on Railway, any Linux server, or your own PC.
With SUPABASE_URL and SUPABASE_SERVICE_KEY set, it feeds your website. Without them it runs in LOCAL mode:
signals go to Telegram and to files in the data folder."""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from cloud import load_env, rules_from
from localstore import LocalStore
from notify import format_signal, telegram
from scanner_core import Scanner, fresh

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("worker")


class Db:
    """Your Supabase database (ONLINE mode)."""

    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/") + "/rest/v1"
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _get(self, table: str, query: str) -> list:
        r = requests.get(f"{self.url}/{table}?{query}", headers=self.h, timeout=20)
        r.raise_for_status()
        return r.json()

    def _patch(self, table: str, query: str, body: dict) -> None:
        requests.patch(f"{self.url}/{table}?{query}", headers=self.h, json=body, timeout=20).raise_for_status()

    def running(self) -> bool:
        return bool(self._get("scanner_state", "id=eq.1")[0]["running"])

    def beat(self, now: datetime) -> None:
        self._patch("scanner_state", "id=eq.1", {"heartbeat": now.isoformat()})

    def error(self, msg: str) -> None:
        self._patch("scanner_state", "id=eq.1", {"last_error": msg[:300]})

    def settings(self) -> dict:
        g = self._get("settings", "id=eq.1&select=data")
        return g[0]["data"] if g else {}

    def load_stats(self) -> list[dict]:
        return self._get("strategy_stats", "select=*")

    def recent_signals(self, since_iso: str) -> list[dict]:
        return self._get("signals", f"created_at=gte.{since_iso}&select=symbol,side,timeframe,strategy,bar_time&limit=500")

    def save_stats(self, rows: list[dict]) -> None:
        h = {**self.h, "Prefer": "resolution=merge-duplicates"}
        requests.post(f"{self.url}/strategy_stats?on_conflict=symbol,timeframe,strategy", headers=h, json=rows, timeout=30).raise_for_status()

    def save_summary(self, summary: dict) -> None:
        self._patch("scanner_state", "id=eq.1", {**summary, "last_error": None})

    def new_signal(self, row: dict) -> bool:
        h = {**self.h, "Prefer": "resolution=ignore-duplicates,return=representation"}
        r = requests.post(f"{self.url}/signals?on_conflict=symbol,side,timeframe,strategy,bar_time", headers=h, json=row, timeout=20)
        r.raise_for_status()
        return bool(r.json())          # empty when it was a duplicate

    def open_signals(self, since_iso: str) -> list[dict]:
        return self._get("signals", f"outcome=is.null&tp1=not.is.null&created_at=gte.{since_iso}&select=id,symbol,timeframe,side,bar_time,entry,sl,tp1&limit=200")

    def update_signal(self, id: int, fields: dict) -> None:
        self._patch("signals", f"id=eq.{id}", fields)


def make_feed():
    if (os.getenv("FEED") or "yahoo") == "mt5":
        from mt5feed import MT5Feed
        return MT5Feed(os.environ["MT5_LOGIN"], os.environ["MT5_PASSWORD"], os.environ["MT5_SERVER"], os.getenv("MT5_SUFFIX", ""))
    from yahoofeed import YahooFeed
    return YahooFeed()


def print_table(rows: list[dict]) -> None:
    print("\nStrategy test results (best first). APPROVED = passed the backtest.")
    print(f"{'pair':8}{'time':6}{'strategy':18}{'trades':>7}{'wins':>7}{'PF':>7}  status")
    for x in sorted(rows, key=lambda r: r["pf"], reverse=True)[:12]:
        print(f"{x['symbol']:8}{x['timeframe']:6}{x['strategy']:18}{x['trades']:>7}{x['win_rate'] * 100:>6.0f}%{x['pf']:>7.2f}  {'APPROVED' if x['enabled'] else 'not approved'}")
    print()


def cycle(store, sc: Scanner, now: datetime, unapproved: bool, state: dict, once: bool = False) -> int:
    """One pass: test strategies if due, look for new signals, track how old ones ended. Returns seconds to wait.
    once=True is for cron hosts: every run is a fresh start, so it reuses the saved results instead of re-testing."""
    store.beat(now)
    if not store.running():
        return 15
    r = rules_from(store.settings())
    if once and not sc.ratings:
        saved = store.load_stats()
        if fresh(saved):
            sc.load_ratings(saved)
    if not sc.ratings or (not once and time.time() - state.get("rated", 0.0) > 86400):      # re-test every strategy about once a day
        log.info("Testing every pair, timeframe and strategy. This takes a few minutes...")
        rows = sc.rate_all(r)
        store.save_stats(rows)
        state["rated"] = time.time()
        log.info("Approved %d of %d combinations.", sum(x["enabled"] for x in rows), len(rows))
        if isinstance(store, LocalStore):
            print_table(rows)
    if hasattr(store, "save_summary"):
        store.save_summary(sc.summary())
    since = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if once:
        sc.seed_cooldown(store.recent_signals(since))
    for s in sc.scan(now, r, unapproved, gate_clock=once):
        if store.new_signal(s):
            msg = format_signal(s)
            log.info("New signal:\n%s", msg)
            telegram(msg)
    if not once or now.minute % 5 == 0:
        for u in sc.outcomes(store.open_signals(since), now):
            store.update_signal(u["id"], {k: v for k, v in u.items() if k != "id"})
    return r.scan_every_sec


def main() -> None:
    load_env()
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    store = Db(url, key) if url and key else LocalStore()
    local = isinstance(store, LocalStore)
    unapproved = (os.getenv("SEND_UNAPPROVED") or "yes").lower() == "yes"   # testing month: also send untested signals, clearly marked (only you can see them on the site)
    sc = Scanner(make_feed())
    log.info("Scanner started in %s mode.", "LOCAL (files and Telegram)" if local else "ONLINE (Supabase)")
    if telegram("FX Desk scanner started."):
        log.info("Telegram is connected.")
    elif local:
        log.info("Telegram is not set up, so signals only show in this window and in the data folder.")
    state: dict = {}
    if "--once" in sys.argv:                          # cron hosts (Render Cron Job, GitHub Actions): do one pass and exit
        try:
            cycle(store, sc, datetime.now(timezone.utc), unapproved, state, once=True)
        except Exception as e:
            log.error("run failed: %s", e)
            try:
                store.error(str(e))
            except Exception:
                pass
            sys.exit(1)
        return
    wait = 15
    while True:
        try:
            wait = cycle(store, sc, datetime.now(timezone.utc), unapproved, state)
        except Exception as e:
            log.warning("loop error: %s", e)
            try:
                store.error(str(e))
            except Exception:
                pass
        time.sleep(wait)


if __name__ == "__main__":
    main()
