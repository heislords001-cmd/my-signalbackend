"""Member bot. Runs on YOUR Windows PC next to MT5. Signs in as you, reads your On/Off + Kill + settings,
trades your own broker account, and publishes your trades to your page on the site."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from broker import MT5Broker, PaperBroker
from cloud import Cloud, load_env, rules_from
from engine import Engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("bot")


def make_broker():
    mode = os.getenv("TRADING_MODE", "demo")
    if mode == "live" and os.getenv("I_UNDERSTAND_LIVE_RISK") != "yes":
        raise SystemExit("Live mode needs I_UNDERSTAND_LIVE_RISK=yes in your .env file.")
    if os.getenv("BROKER", "mt5") == "paper":
        return PaperBroker()
    return MT5Broker(os.environ["MT5_LOGIN"], os.environ["MT5_PASSWORD"], os.environ["MT5_SERVER"], os.getenv("MT5_SUFFIX", ""), mode)


def publish(cloud: Cloud, snap: dict) -> None:
    uid = cloud.uid
    cloud.upsert("bot_account", [{"user_id": uid, **snap["account"], "updated_at": datetime.now(timezone.utc).isoformat()}], "user_id")
    rows = [{"user_id": uid, "ticket": p.ticket, "symbol": p.symbol, "side": p.side, "lot": p.lot, "entry": p.entry, "sl": p.sl,
             "tp": p.tp, "profit": round(p.profit, 2), "tag": p.tag, "opened_at": p.opened.isoformat()} for p in snap["positions"]]
    if rows:
        cloud.upsert("bot_positions", rows, "user_id,ticket")
    keep = ",".join(str(r["ticket"]) for r in rows)
    cloud.delete("bot_positions", f"user_id=eq.{uid}&" + (f"ticket=not.in.({keep})" if rows else "ticket=gt.0"))


def main() -> None:
    load_env()
    cloud = Cloud(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"], os.environ["FX_EMAIL"], os.environ["FX_PASSWORD"])
    engine = Engine(make_broker())
    uid, glob, mine, last_cfg = cloud.uid, {}, {}, 0.0
    log.info("Signed in. Bot is running.")
    while True:
        try:
            if time.time() - last_cfg > 30:      # settings change rarely: refresh every 30 seconds
                g = cloud.rows("settings", "id=eq.1&select=data")
                u = cloud.rows("user_settings", f"user_id=eq.{uid}&select=data")
                glob, mine, last_cfg = (g[0]["data"] if g else {}), (u[0]["data"] if u else {}), time.time()
            st = (cloud.rows("bot_state", f"user_id=eq.{uid}&select=bot_on,kill_requested") or [{}])[0]
            kill = bool(st.get("kill_requested"))
            # no row (or no active Auto-trading plan) reads as OFF: no new trades, open ones keep their stops
            snap = engine.tick(datetime.now(timezone.utc), rules_from(glob, mine), bool(st.get("bot_on")), kill)
            patch = {"user_id": uid, "note": snap["note"]}
            if kill:
                patch.update(kill_requested=False, bot_on=False)
            cloud.upsert("bot_state", [patch], "user_id")
            publish(cloud, snap)
        except Exception as e:
            log.warning("loop error: %s", e)
        time.sleep(5)


if __name__ == "__main__":
    main()
