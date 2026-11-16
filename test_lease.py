"""Only one scanner may run at a time. No internet needed."""
import sys, logging
sys.path.insert(0, '.')
import unittest.mock as m
import worker
logging.disable(logging.CRITICAL)

class R:
    def __init__(self, body): self.status_code = 200; self._b = body
    def json(self): return self._b
    def raise_for_status(self): pass

db = worker.Db("https://x.supabase.co", "k")
# 1. a live scanner holds the lease: the claim is refused
with m.patch("worker.requests.patch", return_value=R([])) as p:
    assert db.claim_lease() is False
    assert "heartbeat.lt." in p.call_args[0][0] and "heartbeat.is.null" in p.call_args[0][0]
print("ok a second scanner is refused while one is alive")
# 2. the lease is free: the claim is granted
with m.patch("worker.requests.patch", return_value=R([{"id": 1}])):
    assert db.claim_lease() is True
print("ok the first scanner gets the lease")
# 3. releasing frees it at once, so Stop then Start works straight away
with m.patch.object(db, "_patch") as pt:
    db.release_lease()
    assert pt.call_args[0][2] == {"heartbeat": None}
print("ok stopping releases the lease immediately")
print("\nlease checks passed")
