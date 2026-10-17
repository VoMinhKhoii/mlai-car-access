"""Gemini's demo cap, shared by every server process. Paid access is opt-in."""
from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import STORE

FILE = STORE / "gemini_paid_usage.json"
LIMIT = 3.0
INPUT_USD_PER_M = 1.5
OUTPUT_USD_PER_M = 9.0
# Gemini includes thinking in this allowance, even when no visible parts are returned.
AGENT_OUTPUT_TOKENS = 2048
MAX_OUTPUT_TOKENS = 8192
PACIFIC = ZoneInfo("America/Los_Angeles")


def daily_quota_error(status: int, text: str) -> bool:
    """Only daily quota exhaustion disables the shared project, never a transient 429."""
    normalized = re.sub(r"[^a-z0-9]", "", text.lower())
    return status in (403, 429) and ("quota" in normalized or "resourceexhausted" in normalized) and (
        "perday" in normalized or "daily" in normalized)


def cool_down_free_project(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(PACIFIC)
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=PACIFIC)
    with ledger() as u:
        u["free_project_cooldown_until"] = midnight.timestamp()


def free_project_available() -> bool:
    with ledger() as u:
        return u.get("free_project_cooldown_until", 0) <= datetime.now(timezone.utc).timestamp()


@contextmanager
def ledger():
    STORE.mkdir(parents=True, exist_ok=True)
    with open(STORE / "gemini_paid_usage.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        u = json.loads(FILE.read_text()) if FILE.exists() else {}
        u.setdefault("spent_usd", 0.0)
        u.setdefault("free_calls", 0)
        u.setdefault("paid_calls", 0)
        u.setdefault("reservations", {})
        try:
            yield u
        finally:
            tmp = FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(u, ensure_ascii=False, indent=2))
            tmp.replace(FILE)


def report():
    with ledger() as u:
        return {**u, "limit_usd": LIMIT, "reserved_usd": sum(u["reservations"].values()),
                "paid_enabled": os.environ.get("AGENT_ALLOW_PAID") == "1"}


def free_call():
    with ledger() as u:
        if u.get("free_project_cooldown_until", 0) > datetime.now(timezone.utc).timestamp():
            raise ValueError("Free Gemini project allowance exhausted; wait until midnight Pacific time.")
        limit = int(os.environ.get("AGENT_FREE_CALL_LIMIT", "0"))
        if limit and u["free_calls"] >= limit:
            raise ValueError("Free Gemini request limit reached; retry later.")
        u["free_calls"] += 1


def reserve(body: dict, *, job_id: str | None = None, job_limit_usd: float = 1.0,
            leave_usd: float = 0.0) -> str:
    # UTF-8 bytes bound input tokens conservatively; reserve the entire output allowance too.
    import uuid
    ceiling = (len(json.dumps(body, ensure_ascii=False).encode()) + 4096) * INPUT_USD_PER_M / 1e6
    ceiling += max(AGENT_OUTPUT_TOKENS, body.get("generationConfig", {}).get(
        "maxOutputTokens", AGENT_OUTPUT_TOKENS)) * OUTPUT_USD_PER_M / 1e6
    with ledger() as u:
        call_limit = int(os.environ.get("AGENT_PAID_CALL_LIMIT", "0"))
        if call_limit and u["paid_calls"] >= call_limit:
            raise ValueError("Paid Gemini request limit reached; retry later.")
        limit = min(LIMIT, float(os.environ.get("AGENT_PAID_LIMIT_USD", str(LIMIT))))
        if job_id:
            # Job and global reservations share ONE flock/transaction. Restarting
            # a worker cannot reset its allowance, or race the live demo agent.
            job = u.setdefault("jobs", {}).setdefault(job_id, {"spent_usd": 0.0, "reservations": {}})
            if job["spent_usd"] + sum(job["reservations"].values()) + ceiling > min(1.0, job_limit_usd):
                raise ValueError("Imagery job reached its paid ceiling (at most 1 USD).")
            limit = min(limit, LIMIT - max(0.0, leave_usd))
        if u["spent_usd"] + sum(u["reservations"].values()) + ceiling >= limit:
            raise ValueError("Gemini budget reached (3 USD); the next request cannot be guaranteed within budget.")
        rid = uuid.uuid4().hex
        u["reservations"][rid] = ceiling
        if job_id:
            job["reservations"][rid] = ceiling
        u["paid_calls"] += 1
        return rid


def finish(rid: str, usage: dict | None, rejected: bool = False):
    with ledger() as u:
        ceiling = u["reservations"].pop(rid)
        if usage is not None:
            inp = usage.get("promptTokenCount", 0)
            out = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
            cost = (INPUT_USD_PER_M * inp + OUTPUT_USD_PER_M * out) / 1e6
            u["prompt_tokens"] = u.get("prompt_tokens", 0) + inp
            u["output_tokens"] = u.get("output_tokens", 0) + out
            u["thought_tokens"] = u.get("thought_tokens", 0) + usage.get("thoughtsTokenCount", 0)
        else:
            cost = 0 if rejected else ceiling  # an ambiguous network failure might still be billed
        u["spent_usd"] += cost
        for job in u.get("jobs", {}).values():
            if rid in job.get("reservations", {}):
                job["reservations"].pop(rid)
                job["spent_usd"] += cost
        u["recent_paid_usage"] = (u.get("recent_paid_usage", []) + [
            {"usageMetadata": usage, "cost_usd": cost}])[-100:]
        u["updated_at"] = datetime.now(timezone.utc).isoformat()


def free_usage(usage: dict | None):
    """Record successful free responses, including thinking-only/empty candidates."""
    if usage is None:
        return
    with ledger() as u:
        for field, token in (("free_prompt_tokens", "promptTokenCount"),
                             ("free_candidate_tokens", "candidatesTokenCount"),
                             ("free_thought_tokens", "thoughtsTokenCount")):
            u[field] = u.get(field, 0) + usage.get(token, 0)
        u["last_free_usage"] = usage
