"""Keeps everything in plain files next to the scanner, so it can run on a PC with no database and no website.
signals.jsonl is the record; signals.csv is the same thing in a form you can open in Excel."""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone


class LocalStore:
    def __init__(self, folder: str = "data"):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        self.jsonl = os.path.join(folder, "signals.jsonl")
        self.csv = os.path.join(folder, "signals.csv")
        self.stats = os.path.join(folder, "strategy_stats.json")

    def running(self) -> bool:
        return True

    def beat(self, now) -> None:
        pass

    def error(self, msg: str) -> None:
        print("Problem:", msg)

    def settings(self) -> dict:
        p = os.path.join(self.dir, "settings.json")
        return json.load(open(p)) if os.path.exists(p) else {}

    def save_stats(self, rows: list[dict]) -> None:
        json.dump(rows, open(self.stats, "w"), indent=1)

    def _all(self) -> list[dict]:
        if not os.path.exists(self.jsonl):
            return []
        return [json.loads(x) for x in open(self.jsonl) if x.strip()]

    def _write(self, rows: list[dict]) -> None:
        with open(self.jsonl, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
        cols = ["created_at", "symbol", "side", "timeframe", "strategy", "approved", "entry", "sl", "tp1", "tp2", "expires_at", "max_hold_min", "outcome", "result_r"]
        with open(self.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    def new_signal(self, row: dict) -> bool:
        rows = self._all()
        key = lambda r: (r["symbol"], r["side"], r["timeframe"], r["strategy"], r["bar_time"])
        if any(key(r) == key(row) for r in rows):
            return False
        rows.append({"id": max([r["id"] for r in rows], default=0) + 1, "created_at": datetime.now(timezone.utc).isoformat(), **row, "outcome": None, "result_r": None})
        self._write(rows)
        return True

    def open_signals(self, since_iso: str) -> list[dict]:
        return [r for r in self._all() if r.get("outcome") is None and r["created_at"] >= since_iso]

    def update_signal(self, id: int, fields: dict) -> None:
        rows = self._all()
        for r in rows:
            if r["id"] == id:
                r.update(fields)
        self._write(rows)
