"""Member-side cloud client. Signs in as the member (no service key ever leaves the server) and talks to
Supabase under that member's own row-level security, so a member can only touch their own rows."""
from __future__ import annotations

import dataclasses
import os
import time

import requests

from config import Rules


def load_env(path: str = ".env") -> None:
    """Tiny .env reader so Windows users do not need to export variables by hand."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def rules_from(*layers: dict | None) -> Rules:
    """Defaults, then each layer on top (later wins). Unknown keys are ignored."""
    allowed = {f.name for f in dataclasses.fields(Rules)}
    merged: dict = {}
    for layer in layers:
        merged.update({k: v for k, v in (layer or {}).items() if k in allowed})
    return Rules(**merged)


class Cloud:
    def __init__(self, url: str, anon_key: str, email: str, password: str):
        self.url, self.anon, self.email, self.password = url.rstrip("/"), anon_key, email, password
        self.token = self.refresh = self.uid = ""
        self.exp = 0.0
        self._auth("password", {"email": email, "password": password})

    def _auth(self, grant: str, body: dict) -> None:
        r = requests.post(f"{self.url}/auth/v1/token?grant_type={grant}", headers={"apikey": self.anon}, json=body, timeout=20)
        r.raise_for_status()
        d = r.json()
        self.token, self.refresh, self.uid = d["access_token"], d["refresh_token"], d["user"]["id"]
        self.exp = time.time() + d["expires_in"] - 60

    def _head(self, extra: dict | None = None) -> dict:
        if time.time() > self.exp:
            try:
                self._auth("refresh_token", {"refresh_token": self.refresh})
            except requests.RequestException:
                self._auth("password", {"email": self.email, "password": self.password})
        return {"apikey": self.anon, "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", **(extra or {})}

    def rows(self, table: str, query: str = "select=*") -> list:
        r = requests.get(f"{self.url}/rest/v1/{table}?{query}", headers=self._head(), timeout=20)
        r.raise_for_status()
        return r.json()

    def upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        r = requests.post(f"{self.url}/rest/v1/{table}?on_conflict={conflict}", headers=self._head({"Prefer": "resolution=merge-duplicates"}), json=rows, timeout=20)
        r.raise_for_status()

    def delete(self, table: str, query: str) -> None:
        requests.delete(f"{self.url}/rest/v1/{table}?{query}", headers=self._head(), timeout=20).raise_for_status()
