"""Reviewed community and AI reports (R-08).

Guests (driver confirmations, temporary blockages) and AI extractions (text, driver photos) never write evidence
directly. Each becomes one report keyed by a stable report_id in STORE/pending_reports.json:

    pending ──approve──▶ approved ──projection──▶ the evidence file of its type
       │ └──reject──▶ rejected
       └──(time)──▶ expired (never promotable)

The approved state is committed atomically before the projection is written. Every projected line carries its
report_id, so `reconcile()` (run at startup and after each approval) re-projects any approved report missing from
its target without ever writing one twice. Camera flood readings are the one exception (see cameras.py): they come
from the city's own camera portal, not from users, and are published as observations.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone

from .config import STORE
from .storage import read_json, write_json

VN_TZ = timezone(timedelta(hours=7))
PENDING_FILE = STORE / "pending_reports.json"
QUARANTINE_DIR = STORE / "quarantine"
CONFIRM_FILE = STORE / "confirmations.jsonl"
BLOCKAGE_FILE = STORE / "blockages.jsonl"
LIVE_FLOOD_FILE = STORE / "live_flood_reports.jsonl"
REVIEW_LOG = STORE / "review_queue.jsonl"   # raw AI extraction log, kept as written
SCHEMA_VERSION = 1
TYPES = ("confirmation", "blockage", "flood_report", "stop_rule", "photo_reading")
TARGETS = {"confirmation": CONFIRM_FILE, "blockage": BLOCKAGE_FILE, "flood_report": LIVE_FLOOD_FILE}
PAGE_MAX = 100
GUEST_REPORTS_PER_HOUR = 20

_lock = threading.Lock()
_rate: dict[tuple[str, str], list[float]] = {}


class Conflict(Exception):
    """The report is not in a state that allows this transition (already decided, or expired)."""


class RateLimited(Exception):
    pass


def _now() -> datetime:
    return datetime.now(VN_TZ)


def _load() -> dict:
    data = read_json(PENDING_FILE, None)  # CorruptState propagates: never guess review state
    if data is None:
        return {"schema_version": SCHEMA_VERSION, "reports": {}}
    return data


def _save(data: dict) -> None:
    write_json(PENDING_FILE, data, indent=1)


def _expiry(kind: str, payload: dict, now: datetime) -> datetime:
    if kind == "blockage":  # a temporary blockage is only true for the day it was reported
        return datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), VN_TZ)
    if kind == "flood_report":  # a flood observation is only valid near its time (FLOOD_REPORT_VALID_H)
        try:
            seen = datetime.fromisoformat(payload.get("observed_at") or "")
            seen = seen if seen.tzinfo else seen.replace(tzinfo=VN_TZ)
        except ValueError:
            seen = now
        return seen + timedelta(hours=2)
    return now + timedelta(days=30)


def _effective(r: dict, now: datetime) -> dict:
    if r["status"] == "pending" and datetime.fromisoformat(r["expires_at"]) <= now:
        return {**r, "status": "expired"}
    return r


def allow_guest(client: str, bucket: str = "reports") -> None:
    now = time.monotonic()
    key = (bucket, client)
    with _lock:
        recent = [t for t in _rate.get(key, []) if now - t < 3600]
        if len(recent) >= GUEST_REPORTS_PER_HOUR:
            raise RateLimited()
        recent.append(now)
        _rate[key] = recent
        if len(_rate) > 4096:
            for k in list(_rate)[:1024]:
                _rate.pop(k, None)


def submit(kind: str, payload: dict, source: str, report_id: str | None = None, legacy: bool = False) -> dict:
    if kind not in TYPES:
        raise ValueError(kind)
    now = _now()
    rid = report_id or f"r-{now.strftime('%Y%m%d')}-{secrets.token_hex(6)}"
    rec = {"report_id": rid, "type": kind, "payload": payload, "source": source, "status": "pending",
           "created_at": now.isoformat(timespec="seconds"),
           "expires_at": _expiry(kind, payload, now).isoformat(timespec="seconds"),
           "reviewer": None, "reviewed_at": None, "revision": 1, "legacy": legacy,
           "publish_target": TARGETS[kind].name if kind in TARGETS else None}
    with _lock:
        data = _load()
        if rid in data["reports"]:
            return data["reports"][rid]  # idempotent resubmission (legacy migration re-run)
        data["reports"][rid] = rec
        _save(data)
    return rec


def list_reports(status: str | None = None, cursor: str | None = None, limit: int = 50) -> dict:
    """Oldest first, `limit` per page; `next_cursor` is the last report_id of this page."""
    limit = max(1, min(PAGE_MAX, limit))
    now = _now()
    with _lock:
        items = [_effective(r, now) for r in _load()["reports"].values()]
    items.sort(key=lambda r: (r["created_at"], r["report_id"]))
    if status:
        items = [r for r in items if r["status"] == status]
    if cursor:
        ids = [r["report_id"] for r in items]
        items = items[ids.index(cursor) + 1:] if cursor in ids else []
    page = items[:limit]
    return {"items": page, "next_cursor": page[-1]["report_id"] if len(items) > limit else None,
            "remaining": len(items)}


def decide(report_id: str, approve: bool, reviewer: str, revision: int | None = None) -> dict:
    """pending → approved|rejected. Repeating the same decision is a no-op; anything else is a Conflict."""
    now = _now()
    with _lock:
        data = _load()
        r = data["reports"].get(report_id)
        if r is None:
            raise KeyError(report_id)
        target = "approved" if approve else "rejected"
        if r["status"] == target:
            return r  # idempotent
        if _effective(r, now)["status"] != "pending":
            raise Conflict(f"báo cáo đang ở trạng thái {_effective(r, now)['status']}")
        if revision is not None and revision != r["revision"]:
            raise Conflict("báo cáo đã thay đổi, tải lại danh sách")
        r.update(status=target, reviewer=reviewer, reviewed_at=now.isoformat(timespec="seconds"),
                 revision=r["revision"] + 1)
        _save(data)  # the decision is durable before any projection is written
    if approve:
        reconcile()
    return r


def _project_line(r: dict) -> dict | None:
    p = r["payload"]
    if r["type"] == "confirmation":
        return {**p, "report_id": r["report_id"]}
    if r["type"] == "blockage":
        return {**p, "report_id": r["report_id"]}
    if r["type"] == "flood_report":
        return {**p, "kind": "flood_report", "report_id": r["report_id"], "reviewed": True}
    return None


def _ids_in(path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rid = json.loads(line).get("report_id") if line.strip() else None
        except ValueError:
            continue
        if rid:
            out.add(rid)
    return out


def reconcile() -> int:
    """Append every approved report missing from its target. Returns how many lines were written."""
    written = 0
    with _lock:
        reports = list(_load()["reports"].values())
        present = {t: _ids_in(path) for t, path in TARGETS.items()}
        for r in reports:
            if r["status"] != "approved" or r["type"] not in TARGETS or r["report_id"] in present[r["type"]]:
                continue
            line = _project_line(r)
            if line is None:
                continue
            path = TARGETS[r["type"]]
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                f.flush()
            present[r["type"]].add(r["report_id"])
            written += 1
    return written


def _quarantine(path, keep) -> list[dict]:
    """Move unreviewed lines of a community file aside (backup kept) and return them parsed."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    legacy, kept = [], []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            legacy.append({"_unparsed": line})
            continue
        (kept if keep(obj) else legacy).append(obj)
    if not legacy:
        return []
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _now().strftime("%Y%m%dT%H%M%S")
    (QUARANTINE_DIR / f"{path.stem}.{stamp}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in kept), encoding="utf-8")
    tmp.replace(path)
    return legacy


def _legacy_id(obj: dict) -> str:
    return "legacy-" + hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def migrate_legacy() -> dict:
    """One-time and idempotent: unreviewed community lines become pending reports; the raw AI log stays as is."""
    counts = {"confirmation": 0, "blockage": 0, "ai": 0}
    for obj in _quarantine(CONFIRM_FILE, lambda o: bool(o.get("report_id"))):
        if "_unparsed" not in obj:
            submit("confirmation", obj, "Tài xế báo (dữ liệu cũ, chưa duyệt)", _legacy_id(obj), legacy=True)
            counts["confirmation"] += 1
    for obj in _quarantine(BLOCKAGE_FILE, lambda o: bool(o.get("report_id"))):
        if "_unparsed" not in obj and obj.get("date") != "demo":
            submit("blockage", obj, "Tài xế báo (dữ liệu cũ, chưa duyệt)", _legacy_id(obj), legacy=True)
            counts["blockage"] += 1
    # AI flood reports that were auto-published by the old model gate (no report_id, not from a camera).
    for obj in _quarantine(LIVE_FLOOD_FILE, lambda o: bool(o.get("report_id")) or o.get("source") == "camera"):
        if "_unparsed" not in obj:
            submit("flood_report", obj, "AI trích xuất (dữ liệu cũ, chưa duyệt)", _legacy_id(obj), legacy=True)
            counts["ai"] += 1
    return counts


def today() -> str:
    return date.today().isoformat()
