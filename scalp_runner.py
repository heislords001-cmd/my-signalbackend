"""The scalp run on GitHub Actions. Started by Start bot, stopped by Stop bot.

Every minute, while forex is open and at least one member has both scalp mode and the bot on:
  1. read the market for every pair (the same way the scanner does),
  2. make each pair's scalp plan (scalp_plan.py, the same rules the site uses),
  3. send the plans to the site, which places the orders for those members.
It stops when nobody is on, when the market closes, or after 330 minutes. Keys never leave the site."""
from __future__ import annotations
import logging
import os
import time
from datetime import datetime, timezone

import requests

import scanner_core as sc
from config import Rules
import scalp_post

log = logging.getLogger("scalp")


def members_on(url: str, key: str) -> set[str]:
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    bots = requests.get(f"{url}/rest/v1/bot_state?bot_on=eq.true&select=user_id", headers=h, timeout=20).json()
    scal = requests.get(f"{url}/rest/v1/user_settings?data->>scalp_enabled=eq.true&select=user_id", headers=h, timeout=20).json()
    return {r["user_id"] for r in bots} & {r["user_id"] for r in scal}


def scanner_on(url: str, key: str) -> bool:
    """The bot works only while the scanner is on: running, and checked in within the last 3 minutes."""
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows = requests.get(f"{url}/rest/v1/scanner_state?id=eq.1&select=running,heartbeat", headers=h, timeout=20).json()
    if not rows or not rows[0].get("running") or not rows[0].get("heartbeat"):
        return False
    beat = datetime.fromisoformat(str(rows[0]["heartbeat"]).replace("Z", "+00:00"))
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - beat).total_seconds() < 180


def run(feed, members, post=scalp_post.post_plans, market=sc.market_open, sleep=time.sleep, scanner=lambda: True,
        now=lambda: datetime.now(timezone.utc), interval: float = 60, max_loops: int | None = None) -> str:
    s = sc.Scanner(feed)
    loops = 0
    started = time.time()
    while True:
        if max_loops is not None and loops >= max_loops:
            return "loop limit"
        if max_loops is None and time.time() - started > 330 * 60:
            return "time limit"
        t = now()
        if not market(t):
            return "market closed"
        if not scanner():
            return "scanner is off"
        if not members():
            return "nobody has scalp on"
        rows = s.snapshot(t, Rules())
        ready = [x['symbol'] + ' ' + str(x.get('trend')) for x in rows]
        log.info('scalp check %s: %s', t.strftime('%H:%M:%S'), ', '.join(ready) or 'no pairs')
        post(rows, t)
        loops += 1
        sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from worker import make_feed
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    print("scalp run:", run(make_feed(), members=lambda: members_on(url, key), scanner=lambda: scanner_on(url, key)))
