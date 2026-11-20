"""The scalp run: posts plans while someone is on, and stops on its own. No internet needed."""
import sys, logging
sys.path.insert(0, '.')
from datetime import datetime, timezone
import scalp_runner
import test_scanner as T
logging.disable(logging.CRITICAL)
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

# 1. nobody has scalp on: it stops straight away and sends nothing
sent = []
r = scalp_runner.run(T.FakeFeed(), members=lambda: set(), post=lambda plans: sent.append(1), market=lambda t: True,
                     sleep=lambda s: None, now=lambda: NOW, max_loops=5)
assert r == "nobody has scalp on" and sent == []
print("ok nobody on: it stops without sending anything")

# 2. market closed: it stops straight away
r = scalp_runner.run(T.FakeFeed(), members=lambda: {"a"}, post=lambda plans: sent.append(1), market=lambda t: False,
                     sleep=lambda s: None, now=lambda: NOW, max_loops=5)
assert r == "market closed" and sent == []
print("ok market closed: it stops without sending anything")

# 3. someone on and the market open: one post per minute, until the loop limit
posts = []
r = scalp_runner.run(T.FakeFeed(), members=lambda: {"a"}, post=lambda plans: posts.append(1), market=lambda t: True,
                     sleep=lambda s: None, now=lambda: NOW, max_loops=3)
assert r == "loop limit" and len(posts) == 3
print("ok someone on: a monitor call every check")

# 4. the member switches off mid-run: it stops at the next check
state = {"n": 0}
def members():
    state["n"] += 1
    return {"a"} if state["n"] <= 2 else set()
posts2 = []
r = scalp_runner.run(T.FakeFeed(), members=members, post=lambda plans: posts2.append(1), market=lambda t: True,
                     sleep=lambda s: None, now=lambda: NOW, max_loops=10)
assert r == "nobody has scalp on" and len(posts2) == 2
print("ok switched off mid-run: it stops at the next check")
# 5. the scanner is off: the bot does nothing, even with members on
posts3 = []
r = scalp_runner.run(T.FakeFeed(), members=lambda: {"a"}, post=lambda plans: posts3.append(1), market=lambda t: True,
                     scanner=lambda: False, sleep=lambda s: None, now=lambda: NOW, max_loops=5)
assert r == "scanner is off" and posts3 == []
print("ok scanner off: the bot does nothing")
print("\nscalp run checks passed")
