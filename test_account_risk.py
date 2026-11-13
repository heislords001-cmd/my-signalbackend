"""Stop sizing for a $10 account. No internet needed."""
import os, sys
sys.path.insert(0, '.')
os.environ.pop("ACCOUNT_USD", None); os.environ.pop("RISK_PCT", None)
import account_risk as risk

def ok(n): print("ok", n)

assert risk.budget_usd() == 0.5; ok("a $10 account at 5% risks $0.50 per trade")

# EURUSD at 1.1000: 0.01 lots moves $1000 per 1.0 price move, so $0.50 allows a 0.0005 (5 pip) stop
f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010)          # a 20 pip stop
assert f is not None and f["tightened"] and abs(f["sl"] - 1.0995) < 1e-9 and f["risk_usd"] <= 0.5
ok("a 20 pip stop is pulled in to 5 pips so it costs no more than $0.50")

f = risk.fit_stop("EURUSD", "sell", 1.1000, 1.1003, 0.0010)          # a 3 pip stop already fits
assert f is not None and not f["tightened"] and abs(f["sl"] - 1.1003) < 1e-9
ok("a stop that already fits is left alone")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010)
assert abs(f["tp1"] - (1.1000 + 1.5 * 0.0005)) < 1e-9 and abs(f["tp2"] - (1.1000 + 3.0 * 0.0005)) < 1e-9
ok("targets are recalculated from the new stop (1.5R and 3R)")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0012)          # ATR is wide, so the 5 pip stop is below the floor
assert f is None
ok("a signal too volatile for the budget is skipped, not given a dangerous stop")

f = risk.fit_stop("EURUSD", "buy", 1.1000, 1.0980, 0.0010, budget=1.0)  # a bigger budget allows a wider stop
assert f is not None and abs(f["risk_usd"] - 1.0) < 0.01
ok("the budget can be changed")

os.environ["ACCOUNT_USD"] = "50"
assert risk.budget_usd() == 2.5; ok("the account size comes from the ACCOUNT_USD setting")
print("\nall risk checks passed")
