"""Alonhadat.com.vn listings: a second Declared source for alley width (D31).

Unlike Chợ Tốt, every listing page has a structured "Đường trước nhà" (road in front of the house) field and a
property type ("Nhà trong hẻm"), so the width does not have to be parsed out of prose. Pages allowed by
robots.txt only (/nha-dat/can-ban/… and listing pages); small concurrency, cached 12 h per district.
Ads are converted to the Chợ Tốt-like shape that live._listings matches.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from .osm import strip_accents

VN_TZ = timezone(timedelta(hours=7))
BASE = "https://alonhadat.com.vn"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/128 Safari/537.36 VaoDuoc-hackathon/0.3"}
PAGES = 5          # 20 listings per page
TTL = timedelta(hours=float(os.environ.get("LISTINGS_TTL_H", "12")))


def _get(url: str) -> str:
    r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(name)).strip("-")


def district_index(cache_dir) -> dict[str, tuple[int, str]]:
    """Folded district slug ("quan-binh-thanh") → (alonhadat id, slug)."""
    path = cache_dir / "alonhadat_hcmc_districts.json"
    if path.exists():
        return {k: tuple(v) for k, v in json.loads(path.read_text()).items()}
    t = _get(f"{BASE}/can-ban-nha-dat/ho-chi-minh")
    out = {m.group(2): (int(m.group(1)), m.group(2))
           for m in re.finditer(r"/nha-dat/can-ban/nha-dat/ho-chi-minh/(\d+)/([a-z0-9-]+)\.html", t)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _detail(url: str) -> dict | None:
    t = _get(url)
    cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", t, re.S)]
    table = {cells[i]: cells[i + 1] for i in range(0, len(cells) - 1, 2)}
    street = re.search(r"itemprop='streetAddress'>(.*?)</span>", t, re.S)
    title = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
    desc = re.search(r"itemprop='description'>(.*?)</p>", t, re.S)
    date = re.search(r"itemprop='datePosted' datetime='([\d-]+)'", t)
    imgs = re.findall(r"(https?://[^\"'\s]+/files/properties/[^\"'\s]+\.(?:jpg|jpeg|png|webp))", t, re.I)
    road = re.match(r"([\d.,]+)\s*m", table.get("Đường trước nhà", ""))
    street_txt = _text(street.group(1)) if street else ""
    num = re.match(r"^\s*([\d]+[A-Za-z]?(?:/[\dA-Za-z]+)*)\s*,?\s*(.*)$", street_txt)
    return {
        "ad_id": "aln" + hashlib.sha1(url.encode()).hexdigest()[:10],
        "url": url,
        "subject": _text(title.group(1)) if title else "",
        "body": _text(desc.group(1)) if desc else "",
        "street_name": (num.group(2) if num else street_txt) or "",
        "street_number": num.group(1) if num else "",
        "kind": table.get("Loại BDS", ""),
        "road_front_m": float(road.group(1).replace(",", ".")) if road else None,
        "posted_at": date.group(1) if date else "",
        "images": list(dict.fromkeys(imgs))[:4],
        "source": "alonhadat",
    }


def pull_district(district_name: str, cache_dir, counts: dict) -> list[dict]:
    """Alley-house listings of one HCMC district (cached 12 h)."""
    idx = district_index(cache_dir)
    hit = idx.get(_slug(district_name))
    if not hit:
        return []
    aid, slug = hit
    path = cache_dir / "alonhadat" / f"{aid}.json"
    now = datetime.now(VN_TZ)
    if path.exists():
        cached = json.loads(path.read_text())
        if now - datetime.fromisoformat(cached["fetched_at"]) < TTL:
            return cached["ads"]
    urls: list[str] = []
    for page in range(1, PAGES + 1):
        suffix = "" if page == 1 else f"/trang--{page}"
        t = _get(f"{BASE}/nha-dat/can-ban/nha-dat/ho-chi-minh/{aid}/{slug}{suffix}.html")
        urls += [BASE + u for u in re.findall(r"href=['\"](/[a-z0-9-]+-\d{6,}\.html)['\"]", t)]
    urls = list(dict.fromkeys(urls))
    with ThreadPoolExecutor(4) as pool:
        ads = [a for a in pool.map(_safe_detail, urls) if a]
    counts["fetched"] = counts.get("fetched", 0) + len(ads)
    ads = [a for a in ads if "hẻm" in a["kind"].lower() or "/" in a["street_number"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": now.isoformat(), "ads": ads}, ensure_ascii=False))
    return ads


def _safe_detail(url: str) -> dict | None:
    try:
        return _detail(url)
    except Exception:
        return None
