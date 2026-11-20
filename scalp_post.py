"""Sends the scalp plans from the scanner run to the site, which places the orders.
Lives in its own file so the scanner itself only makes one call. Keys never leave the site."""
from __future__ import annotations
import logging
import os
from datetime import datetime

import requests

import scalp_plan

log = logging.getLogger("scalp_post")


def post_plans(rows: list[dict], now: datetime) -> None:
    url = (os.environ.get("SITE_URL") or "").rstrip("/")
    secret = (os.environ.get("WEBHOOK_SECRET") or "").strip()
    if not url or not secret:
        # say so in the log, so a missing secret never looks like "nothing happened"
        log.warning("scalp plans NOT sent: SITE_URL or WEBHOOK_SECRET is missing in the GitHub secrets")
        return
    for row in rows:
        p = scalp_plan.plan(row, now_ms=now.timestamp() * 1000)
        if not p.get("ok"):
            continue
        try:
            r = requests.post(f"{url}/api/scalp-order", headers={"Authorization": f"Bearer {secret}"},
                              json={k: p[k] for k in ("symbol", "side", "entry", "sl", "tp1", "updated_at")}, timeout=60)
            log.info("scalp %s %s: site answered %s %s", p["symbol"], p["side"], r.status_code, str(getattr(r, "text", ""))[:300])
        except requests.RequestException as e:
            log.warning("scalp %s not sent: %s", p["symbol"], e)


def post_monitor(plans: dict) -> None:
    """Every 15 seconds: send the latest plan for each pair to the site's monitor. It closes what the rules say and opens the next."""
    url = (os.environ.get("SITE_URL") or "").rstrip("/")
    secret = (os.environ.get("WEBHOOK_SECRET") or "").strip()
    if not url or not secret:
        log.warning("scalp monitor NOT called: SITE_URL or WEBHOOK_SECRET is missing in the GitHub secrets")
        return
    try:
        r = requests.post(f"{url}/api/scalp-monitor", headers={"Authorization": f"Bearer {secret}"},
                          json={"plans": plans}, timeout=60)
        log.info("scalp monitor: site answered %s %s", r.status_code, str(getattr(r, "text", ""))[:300])
    except requests.RequestException as e:
        log.warning("scalp monitor not reached: %s", e)
