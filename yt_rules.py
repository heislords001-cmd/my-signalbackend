"""
YouTube transcript ingestion + rule extraction, baked into the FX Desk backend.
The worker calls `maybe_refresh_rules()` once a day to pull fresh rules from
configured channels and saves them in Supabase (table: yt_rules). The scanner
can then use those rules as extra confirmation context, but validate_trade()
still enforces the safety gate before anything is logged as APPROVED.

No audio is downloaded. Only YouTube's own auto-generated English transcripts
are used. Nothing executes a trade.

Environment variables (all optional — the feature is silently skipped if absent):
  YOUTUBE_API_KEY         YouTube Data API v3 key
  ANTHROPIC_API_KEY       Anthropic API key
  YT_CHANNEL_IDS          comma-separated channel IDs (default: Rayner Teo + The Trading Channel)
  YT_MAX_VIDEOS_PER_RUN   how many latest videos to check per channel (default: 3)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("yt_rules")

DEFAULT_CHANNELS = [
    "UCsT0YIqwnpJCM-mx7-gSA4Q",   # Rayner Teo
    "UCiNPFMEplBaGD-Y-emJElXw",   # The Trading Channel
]

EXTRACT_PROMPT = """\
You are a strict trading-rule parser. Read the transcript and return ONLY valid JSON.

Rules:
• Include ONLY concrete, testable technical conditions.
  Good: "RSI < 30 AND price above 200 EMA"
  Bad:  "the market is in a bearish macro environment"
• Ignore opinions, market outlook, sponsor text, and mindset advice.
• Each list item must be a single standalone rule, not a paragraph.
• If no concrete rule exists for a field, use an empty list.

Return ONLY this JSON (no extra text, no markdown):
{
  "video_id": "<video id>",
  "title_guess": "<short title from context, or empty>",
  "Entry_Rules": ["<rule>", ...],
  "Exit_Rules": ["<rule>", ...],
  "Confirmation_Triggers": ["<condition that must be true before entry>", ...],
  "Risk_Notes": ["<concrete risk or position-sizing rule>", ...]
}

Transcript:
"""

# ── low-level helpers ──────────────────────────────────────────────────────

def _youtube_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "")

def _anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")

def _configured() -> bool:
    return bool(_youtube_key() and _anthropic_key())


def _video_ids(channel_id: str, max_results: int) -> list[str]:
    r = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"key": _youtube_key(), "channelId": channel_id, "part": "id",
                "order": "date", "type": "video", "maxResults": max_results},
        timeout=20,
    )
    r.raise_for_status()
    return [i["id"]["videoId"] for i in r.json().get("items", [])]


def _transcript(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        entries = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
        return " ".join(e["text"] for e in entries)
    except Exception as exc:
        log.debug("No transcript for %s: %s", video_id, exc)
        return ""


def _extract(transcript: str, video_id: str) -> Optional[dict]:
    prompt = EXTRACT_PROMPT + transcript[:12000]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": _anthropic_key(), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 1024,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["content"][0]["text"].strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    return json.loads(text[start:end])


# ── safety gate ────────────────────────────────────────────────────────────

@dataclass
class ProposedOrder:
    symbol: str
    side: str           # "buy" or "sell"
    entry: float
    stop_loss: float
    take_profit: float
    size_lots: float
    confirmation: str
    source_video: str = ""
    rules_applied: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    order: ProposedOrder
    verdict: str        # "APPROVED" or "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


MAX_DAILY_LOSS_USD: float = float(os.environ.get("MAX_DAILY_LOSS_USD", "50"))
MAX_LOT_SIZE: float       = float(os.environ.get("MAX_LOT_SIZE", "0.10"))
MIN_RR_RATIO: float       = float(os.environ.get("MIN_RR_RATIO", "1.5"))


def validate_trade(order: ProposedOrder, today_loss_usd: float = 0.0) -> ValidationResult:
    """
    Run every safety check. Returns APPROVED only if all pass.
    Writes every result to audit.jsonl. Never sends an order anywhere.
    """
    reasons: list[str] = []
    if order.side not in ("buy", "sell"):
        reasons.append(f"Unknown side '{order.side}' — must be buy or sell.")
    if any(v <= 0 for v in (order.entry, order.stop_loss, order.take_profit)):
        reasons.append("Entry, stop loss and take profit must all be positive.")
    if order.side == "buy":
        if order.stop_loss >= order.entry:
            reasons.append(f"Buy stop loss {order.stop_loss} must be below entry {order.entry}.")
        if order.take_profit <= order.entry:
            reasons.append(f"Buy take profit {order.take_profit} must be above entry {order.entry}.")
    elif order.side == "sell":
        if order.stop_loss <= order.entry:
            reasons.append(f"Sell stop loss {order.stop_loss} must be above entry {order.entry}.")
        if order.take_profit >= order.entry:
            reasons.append(f"Sell take profit {order.take_profit} must be below entry {order.entry}.")
    if not (0 < order.size_lots <= MAX_LOT_SIZE):
        reasons.append(f"Lot size {order.size_lots} outside allowed range (0, {MAX_LOT_SIZE}].")
    if not reasons:
        risk   = abs(order.entry - order.stop_loss)
        reward = abs(order.take_profit - order.entry)
        rr     = reward / risk if risk else 0.0
        if rr < MIN_RR_RATIO:
            reasons.append(f"R:R {rr:.2f} is below the minimum {MIN_RR_RATIO}.")
    if today_loss_usd >= MAX_DAILY_LOSS_USD:
        reasons.append(f"Daily loss limit reached: ${today_loss_usd:.2f} >= ${MAX_DAILY_LOSS_USD}.")
    if not order.confirmation.strip():
        reasons.append("A confirmation condition is required (e.g. 'H1 candle closed above 200 EMA').")
    verdict = "BLOCKED" if reasons else "APPROVED"
    result  = ValidationResult(order=order, verdict=verdict, reasons=reasons)
    _audit(result)
    return result


def _audit(r: ValidationResult) -> None:
    line = json.dumps({
        "timestamp": r.timestamp, "verdict": r.verdict, "symbol": r.order.symbol,
        "side": r.order.side, "entry": r.order.entry, "sl": r.order.stop_loss,
        "tp": r.order.take_profit, "lots": r.order.size_lots,
        "confirmation": r.order.confirmation, "reasons": r.reasons,
        "source": r.order.source_video, "rules": r.order.rules_applied,
    })
    log.info("TRADE %s | %s", r.verdict, line)
    Path("audit.jsonl").open("a").write(line + "\n")


# ── once-a-day refresh called from worker.py ──────────────────────────────

def maybe_refresh_rules(store=None) -> list[dict]:
    """
    Called once a day from the worker. Pulls fresh rules from YouTube and saves
    them to Supabase (if store supports it) and to rules.jsonl locally.
    Returns the list of newly extracted rule objects (may be empty).

    Silently does nothing when YOUTUBE_API_KEY or ANTHROPIC_API_KEY is absent.
    """
    if not _configured():
        log.debug("yt_rules: keys not set, skipping")
        return []

    channel_ids = [c.strip() for c in os.environ.get("YT_CHANNEL_IDS", "").split(",") if c.strip()] or DEFAULT_CHANNELS
    max_vid     = int(os.environ.get("YT_MAX_VIDEOS_PER_RUN", "3"))
    seen        = _load_seen()
    results: list[dict] = []

    for channel in channel_ids:
        try:
            ids = _video_ids(channel, max_vid)
        except Exception as exc:
            log.warning("yt_rules: could not fetch videos from %s: %s", channel, exc)
            continue

        for vid in ids:
            if vid in seen:
                continue
            transcript = _transcript(vid)
            if not transcript:
                continue
            try:
                rules = _extract(transcript, vid)
            except Exception as exc:
                log.warning("yt_rules: extraction failed for %s: %s", vid, exc)
                continue
            if not rules:
                continue
            rules["fetched_at"] = datetime.now(timezone.utc).isoformat()
            _save_local(rules)
            if store and hasattr(store, "save_yt_rules"):
                try:
                    store.save_yt_rules([rules])
                except Exception as exc:
                    log.warning("yt_rules: could not save to Supabase: %s", exc)
            seen.add(vid)
            _save_seen(seen)
            results.append(rules)
            log.info(
                "yt_rules: %s — %d entry, %d exit, %d confirm, %d risk",
                vid,
                len(rules.get("Entry_Rules", [])), len(rules.get("Exit_Rules", [])),
                len(rules.get("Confirmation_Triggers", [])), len(rules.get("Risk_Notes", [])),
            )
            time.sleep(1)   # be kind to the Anthropic API

    return results


def _load_seen() -> set[str]:
    p = Path("yt_seen.txt")
    return set(p.read_text().splitlines()) if p.exists() else set()


def _save_seen(seen: set[str]) -> None:
    Path("yt_seen.txt").write_text("\n".join(sorted(seen)))


def _save_local(rules: dict) -> None:
    Path("rules.jsonl").open("a").write(json.dumps(rules) + "\n")
