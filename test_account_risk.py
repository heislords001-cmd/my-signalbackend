"""Stop sizing for a $10 account. No internet needed."""
import os, sys
sys.path.insert(0, '.')
os.environ.pop("ACCOUNT_USD", None); os.environ.pop("RISK_PCT", None)
import account_risk as risk

def ok(n): print("ok", n)

assert risk.budget_usd() == 1.0; ok("the default is a $10 account at 10%, so $1.00 per trade")

os.environ["RISK_PCT"] = "5"                      # the tests below use 5% ($0.50) so the numbers are easy to check
assert risk.budget_usd() == 0.5

# EURUSD at 1.1000: 0.01 lots moves $1000 per 1.0 price move, so $0.50 allows a 0.0005 (5 pip) stop
f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010)
assert f is not None and f["tightened"] and abs(f["sl"] - 1.0995) < 1e-9 and f["risk_usd"] <= 0.5
ok("a 20 pip stop is pulled in to 5 pips so it costs no more than $0.50")

f = risk.fit_stop("EURUSD", "sell", 1.1000, 1.1003, 0.0010)
assert f is not None and not f["tightened"] and abs(f["sl"] - 1.1003) < 1e-9
ok("a stop that already fits is left alone")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010)
assert abs(f["tp1"] - (1.1000 + 1.5 * 0.0005)) < 1e-9 and abs(f["tp2"] - (1.1000 + 3.0 * 0.0005)) < 1e-9
ok("targets are recalculated from the new stop (1.5R and 3R)")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0012)
assert f is None
ok("a signal too volatile for the budget is skipped, not given a dangerous stop")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010, budget=1.0)
assert f is not None and abs(f["risk_usd"] - 1.0) < 0.01
ok("the budget can be changed")

os.environ["RISK_PCT"] = "10"
assert risk.budget_usd() == 1.0; ok("RISK_PCT can be raised back to 10%")


# a too-wide stop is published with a warning that states the cost; a fitting stop has no warning
os.environ["RISK_PCT"] = "10"
w = risk.stop_warning("EURUSD", 1.1000, 1.0980)              # 20 pips at 0.01 lots = $2.00, budget $1.00
assert w and "costs $2.00" in w and "budget $1.00" in w
assert risk.stop_warning("EURUSD", 1.1000, 1.0995) is None   # 5 pips = $0.50, fits
print("ok a too-wide stop gets a warning with its cost; a fitting stop does not")
print("warning checks passed")
