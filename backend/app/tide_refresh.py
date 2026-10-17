"""Refresh Phú An extrema from Đài KTTV Nam Bộ's latest five-day PDF, without AI.

Unrecognised layouts, stale bulletins and transport errors keep the last good file.
The official public host currently has an expired certificate: a narrowly scoped
fallback for public kttvnb.vn downloads is recorded in status, never set globally.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from .config import CACHE, DATA

VN = ZoneInfo("Asia/Ho_Chi_Minh")
ORIGIN = "https://kttvnb.vn"
LISTING = ORIGIN + "/index.php/thong-tin-kttv/thuy-van"
TARGET = DATA / "flood/tide_forecast.json"
STATUS = CACHE / "flood/tide_refresh_status.json"
HEADERS = {"User-Agent": "VaoDuoc/0.3 (HCMC tide bulletin refresh; minhkhoitdn@gmail.com)"}
LOG = logging.getLogger(__name__)
_refresh_lock = threading.Lock()


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(urljoin(ORIGIN, href))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def parse_pdf(content: bytes, source_url: str) -> dict:
    import pdfplumber  # optional at import time: refresh failure must never prevent server startup

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        tables = [table for page in pdf.pages for table in page.extract_tables()]
    if "ĐẶC TRƯNG THỦY TRIỀU 5 NGÀY" not in text.upper():
        raise ValueError("Not the five-day tide bulletin")
    issued = re.search(r"Tin phát lúc\s*:\s*(\d{1,2}):(\d{2})\s*giờ ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", text, re.I)
    number = re.search(r"Bản tin số\s*:\s*(\d+/\d{4})", text, re.I)
    observed = re.search(r"MỰC NƯỚC THỰC ĐO NGÀY\s*(\d{1,2})/(\d{1,2})/(\d{4})", text, re.I)
    if not all((issued, number, observed)):
        raise ValueError("Missing bulletin identity/date")
    hour, minute, day, month, year = map(int, issued.groups())
    issued_at = datetime(year, month, day, hour, minute, tzinfo=VN)
    obs_day, obs_month, obs_year = map(int, observed.groups())
    observed_date = datetime(obs_year, obs_month, obs_day, tzinfo=VN)
    if (issued_at.date() - observed_date.date()).days != 1:
        raise ValueError("Unexpected observation date")
    highs, lows, forecast_dates = [], [], set()

    def add_pairs(values, date, kind):
        if len(values) != 8:
            raise ValueError("Expected four extremum pairs")
        for i in range(0, 8, 2):
            level, when = (str(v or "").strip().replace(",", ".") for v in values[i:i + 2])
            if level.lower() in ("ct", "*", "-") and when.lower() in ("ct", "*", "-"):
                continue
            if not re.fullmatch(r"-?\d+(?:\.\d+)?", level) or not re.fullmatch(r"\d{1,2}[.:]\d{2}", when):
                raise ValueError("Unrecognised extremum")
            hh, mm = map(int, re.split(r"[.:]", when))
            if not (0 <= hh < 24 and 0 <= mm < 60 and -3 <= float(level) <= 3):
                raise ValueError("Invalid Phu An extremum")
            item = {"t": date.replace(hour=hh, minute=mm).isoformat(), "level_m": float(level), "kind": kind}
            (highs if i < 4 else lows).append(item)

    observations_found = 0
    for table in tables:
        station = None
        for row in table:
            if len(row) != 10:
                continue
            first, second = (str(v or "").replace("\n", " ").strip() for v in row[:2])
            if first:
                station = first
            if first == "Phú An" and second == "Sài Gòn":
                add_pairs(row[2:], observed_date, "observed")
                observations_found += 1
            elif station == "Phú An" and re.fullmatch(r"\d{1,2}/\d{1,2}", second):
                dd, mo = map(int, second.split("/"))
                dates = []
                for yy in (year - 1, year, year + 1):
                    try:
                        dates.append(datetime(yy, mo, dd, tzinfo=VN))
                    except ValueError:
                        pass
                date = min(dates, key=lambda d: abs((d.date() - issued_at.date()).days))
                if not 0 <= (date.date() - issued_at.date()).days <= 4 or date.date() in forecast_dates:
                    raise ValueError("Unexpected/duplicate forecast date")
                forecast_dates.add(date.date())
                add_pairs(row[2:], date, "forecast")
    expected = {issued_at.date() + timedelta(days=i) for i in range(5)}
    if observations_found != 1 or forecast_dates != expected or len(highs) < 7 or len(lows) < 7:
        raise ValueError("Incomplete Phu An table")
    alarms = {}
    for roman, key in (("I", "BD1"), ("II", "BD2"), ("III", "BD3")):
        match = re.search(r"BĐ\s*" + roman + r"\s*:\s*(\d+[.,]\d+)\s*m", text)
        if not match:
            raise ValueError("Missing alarm level")
        alarms[key] = float(match[1].replace(",", "."))
    highs.sort(key=lambda x: x["t"])
    lows.sort(key=lambda x: x["t"])
    if len({x["t"] for x in highs + lows}) != len(highs + lows):
        raise ValueError("Conflicting extremum times")
    return {"station": "Phú An (sông Sài Gòn)",
            "bulletin": f"Bản tin dự báo đặc trưng thủy triều 5 ngày, số {number[1]} — Đài KTTV Nam Bộ",
            "issued_at": issued_at.isoformat(), "source_url": source_url,
            "alarm_levels_m": alarms,
            "note": f"Đỉnh và chân triều Phú An từ bản tin chính thức {number[1]}, phát {hour:02d}:{minute:02d} ngày {day:02d}/{month:02d}/{year}. "
                    "Mực nước giữa các cực trị được nội suy cosin, không phải số đo hay dự báo ngập đường. "
                    "Ô ct không được tự thêm; ngoài phạm vi bản tin trả thiếu dữ liệu.",
            "highs": highs, "low_level_m": min(x["level_m"] for x in lows), "lows": lows}


def _get(url, status):
    if urlparse(url).hostname != "kttvnb.vn" or urlparse(url).scheme != "https":
        raise ValueError("Only official HTTPS bulletin URLs are accepted")
    try:
        response = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=False)
    except httpx.ConnectError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        status["tls_verified"] = False
        response = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=False, verify=False)
    response.raise_for_status()
    if len(response.content) > 5_000_000:
        raise ValueError("Bulletin response too large")
    return response


def refresh() -> dict:
    with _refresh_lock:
        status = {"checked_at": datetime.now(VN).isoformat(), "state": "checking", "tls_verified": True}
        try:
            listing = _get(LISTING, status).text
            articles = sorted({u for u in Links(listing).links
                               if "/thuy-van/" in u and "tphcm" in u.lower()
                               and re.search(r"/\d{4,}-", u)},
                              key=lambda u: int(re.search(r"/(\d{4,})-", u)[1]), reverse=True)
            candidates = {u for u in Links(listing).links if re.search(r"/HCMC_TVHN_\d{8}\.pdf$", u, re.I)}
            for article in articles[:3]:
                candidates.update(u for u in Links(_get(article, status).text).links
                                  if re.search(r"/HCMC_TVHN_\d{8}\.pdf$", u, re.I))
                if candidates:
                    break
            if not candidates:
                raise ValueError("No five-day Phu An attachment on official listing")
            url = max(candidates, key=lambda u: re.search(r"(\d{8})\.pdf$", u)[1])
            content = _get(url, status).content
            if not content.startswith(b"%PDF"):
                raise ValueError("Attachment is not a PDF")
            parsed = parse_pdf(content, url)
            issued = datetime.fromisoformat(parsed["issued_at"])
            if issued > datetime.now(VN) + timedelta(hours=1):
                raise ValueError("Future bulletin issue date")
            current = json.loads(TARGET.read_text()) if TARGET.exists() else {}
            current_date = datetime.fromisoformat(current["issued_at"]) if current.get("issued_at") else None
            if current_date and issued < current_date:
                raise ValueError("Older bulletin rejected")
            snapshot = CACHE / "flood" / url.rsplit("/", 1)[-1]
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(content)
            # Same issued_at can carry corrected extrema. Compare numerical content, not just the date.
            fields = ("station", "bulletin", "issued_at", "source_url", "alarm_levels_m", "highs", "lows", "low_level_m")
            changed = any(parsed.get(k) != current.get(k) for k in fields)
            if changed:
                atomic_json(TARGET, parsed)
            from . import flood
            flood.tide_meta.cache_clear()
            flood._extremes.cache_clear()
            status.update(state="updated" if changed else "current", issued_at=parsed["issued_at"],
                          source_url=url, sha256=hashlib.sha256(content).hexdigest(),
                          highs=len(parsed["highs"]), lows=len(parsed["lows"]),
                          next_check_at=(datetime.now(VN) + timedelta(hours=6)).isoformat())
        except Exception as exc:
            status.update(state="error", error=type(exc).__name__,
                          next_check_at=(datetime.now(VN) + timedelta(hours=6)).isoformat())
            LOG.warning("Tide refresh failed (%s); keeping last good bulletin", type(exc).__name__)
        try:
            atomic_json(STATUS, status)
        except OSError:
            LOG.warning("Cannot persist tide refresh status")
        return status


def start_refresher():
    stop = threading.Event()

    def run():
        while not stop.is_set():
            refresh()
            stop.wait(6 * 3600)

    thread = threading.Thread(target=run, name="tide-refresh", daemon=True)
    thread.start()
    return stop, thread
