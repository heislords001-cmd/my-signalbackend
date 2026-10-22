"""Run: python test_cloud.py"""
from __future__ import annotations

import os
import tempfile

from cloud import load_env, rules_from


def test_rules_layers():
    r = rules_from({"adx_min": 30, "nope": 1}, {"adx_min": 20, "max_lot_per_trade": 0.01, "small_account": True})
    assert r.adx_min == 20 and r.max_lot_per_trade == 0.01 and r.small_account is True and r.ema_fast == 50
    assert rules_from(None, {}).adx_min == 25


def test_env_file():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
        f.write('# c\nFX_TEST_A=hello\nFX_TEST_B="quoted value"\n')
    load_env(f.name)
    assert os.environ["FX_TEST_A"] == "hello" and os.environ["FX_TEST_B"] == "quoted value"
    os.unlink(f.name)


if __name__ == "__main__":
    test_rules_layers(); test_env_file()
    print("all cloud tests passed")
