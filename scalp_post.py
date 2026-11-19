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
        return                      # scalping stays off until SITE_URL and WEBHOOK_SECRET are set
    for row in rows:
        p = scalp_plan.plan(row, now_ms=now.timestamp() * 1000)
        if not p.get("ok"):
            continue
        try:
            r = requests.post(f"{url}/api/scalp-order", headers={"Authorization": f"Bearer {secret}"},
                              json={k: p[k] for k in ("symbol", "side", "entry", "sl", "tp1", "updated_at")}, timeout=60)
            log.info("scalp %s %s: site answered %s", p["symbol"], p["side"], r.status_code)
        except requests.RequestException as e:
            log.warning("scalp %s not sent: %s", p["symbol"], e)
