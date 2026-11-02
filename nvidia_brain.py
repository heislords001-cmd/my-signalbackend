"""
Optional AI signal brain using NVIDIA NIM (build.nvidia.com).
If NVIDIA_API_KEY is set, the worker calls this instead of using rules alone.
It sends the current market snapshot plus extracted YouTube rules to the model
and asks for a structured signal: BUY, SELL, or SKIP with reasoning.

Nothing here executes a trade. It only returns a signal suggestion that the
existing scanner can attach to a signal row before saving.
"""
from __future__ import annotations
import json, logging, os
import requests

log = logging.getLogger("nvidia_brain")

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.1-70b-instruct"   # available free on build.nvidia.com

SIGNAL_PROMPT = """\
You are a professional forex trading signal analyst.

Current market snapshot:
{snapshot}

YouTube trading rules loaded for this pair:
{rules}

Based ONLY on the snapshot and the rules above, respond with a JSON object and nothing else:
{{
  "signal": "BUY" or "SELL" or "SKIP",
  "confidence": 0.0 to 1.0,
  "reasoning": "one sentence"
}}

Rules:
- Signal BUY only if the snapshot clearly matches a BUY rule.
- Signal SELL only if the snapshot clearly matches a SELL rule.
- If in doubt, signal SKIP. A missed trade is better than a wrong one.
- Do not invent levels or rules not in the snapshot or rules list.
"""

def _key() -> str:
    return os.environ.get("NVIDIA_API_KEY", "")

def configured() -> bool:
    return bool(_key())

def get_signal(snapshot: dict, yt_rules: list[dict]) -> dict | None:
    """
    Ask the NVIDIA model whether the current snapshot is a BUY, SELL, or SKIP.
    Returns a dict with keys: signal, confidence, reasoning.
    Returns None if the key is absent or the call fails.
    """
    if not configured():
        return None

    # flatten rules to a readable bullet list
    bullets: list[str] = []
    for r in yt_rules:
        for rule in r.get("Entry_Rules", []):
            bullets.append(f"ENTRY: {rule}")
        for rule in r.get("Confirmation_Triggers", []):
            bullets.append(f"CONFIRM: {rule}")
        for rule in r.get("Risk_Notes", []):
            bullets.append(f"RISK: {rule}")
    rules_text = "\n".join(bullets) if bullets else "No specific rules loaded yet."

    snap_text = json.dumps({k: v for k, v in snapshot.items() if k != "updated_at"}, indent=2)
    prompt = SIGNAL_PROMPT.format(snapshot=snap_text, rules=rules_text)

    try:
        r = requests.post(
            f"{NVIDIA_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
            json={"model": os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL),
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 200, "temperature": 0.1},
            timeout=30,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        start, end = text.find("{"), text.rfind("}") + 1
        result = json.loads(text[start:end])
        assert result.get("signal") in ("BUY", "SELL", "SKIP")
        log.info("nvidia_brain: %s %s (%.2f) — %s", snapshot.get("symbol", "?"),
                 result["signal"], float(result["confidence"]), result["reasoning"])
        return result
    except Exception as exc:
        log.warning("nvidia_brain: call failed for %s: %s", snapshot.get("symbol", "?"), exc)
        return None
