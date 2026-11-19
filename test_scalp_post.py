"""The scanner sends only valid scalp plans to the site, and only when the site settings are present. No internet needed."""
import sys, os, logging
sys.path.insert(0, '.')
import unittest.mock as m
from datetime import datetime, timezone
import worker
logging.disable(logging.CRITICAL)
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
GOOD = {"symbol": "EURUSD", "trend": "buy", "price": 1.1005, "ema50": 1.1000, "atr": 0.0010, "updated_at": NOW.isoformat()}
BAD = {"symbol": "EURUSD", "trend": "buy", "price": 1.0990, "ema50": 1.1000, "atr": 0.0010, "updated_at": NOW.isoformat()}   # below the average: refused

# 1. no site settings: nothing is sent
os.environ.pop("SITE_URL", None); os.environ.pop("WEBHOOK_SECRET", None)
with m.patch("requests.post") as p:
    worker.post_scalp_plans([GOOD], NOW)
    assert p.call_count == 0
print("ok nothing is sent until SITE_URL and WEBHOOK_SECRET are set")

# 2. a valid plan is sent with the secret; a refused row is not
os.environ["SITE_URL"] = "https://mysignalfrontend.vercel.app"; os.environ["WEBHOOK_SECRET"] = "s3cret"
class R: status_code = 200
with m.patch("requests.post", return_value=R()) as p:
    worker.post_scalp_plans([GOOD, BAD], NOW)
    assert p.call_count == 1
    url = p.call_args[0][0]; kw = p.call_args[1]
    assert url == "https://mysignalfrontend.vercel.app/api/scalp-order"
    assert kw["headers"]["Authorization"] == "Bearer s3cret"
    body = kw["json"]
    assert body["side"] == "buy" and abs(body["entry"] - 1.1005) < 1e-9 and abs(body["sl"] - 1.1005 + 0.002) < 1e-9 and abs(body["tp1"] - 1.1005 - 0.0005) < 1e-9
print("ok a valid plan is sent with the secret and the right stop and target; a refused one is not")

# 3. the site being down does not stop the scanner run
import requests
with m.patch("requests.post", side_effect=requests.ConnectionError("down")):
    worker.post_scalp_plans([GOOD], NOW)
print("ok a failed send is logged, not raised")
print("\nscalp post checks passed")
