"""Recent news about the streets around a destination (D31): Google News RSS search, filtered by Gemini.

Google News' public RSS search needs no key and returns dated headlines from Tuổi Trẻ, VnExpress, Thanh Niên…
For each named street near the destination we ask for flooding, roadworks, barriers and car bans in the last
year. Gemini keeps only items about that street in Ho Chi Minh City and labels them; without a model a keyword
filter does the same job, less precisely. Items are shown with source and date; they are not Width Evidence.
"""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx

from . import ai
from .osm import strip_accents

RSS = "https://news.google.com/rss/search?q={q}+when:365d&hl=vi&gl=VN&ceid=VN:vi"
TOPICS = '(ngập OR "triều cường" OR "thi công" OR "rào chắn" OR "cấm ô tô" OR "cấm xe" OR "sửa đường")'
HCMC = re.compile(r"tp\.?\s*hcm|tphcm|tp ho chi minh|ho chi minh|sai gon|thanh pho thu duc|binh thanh|go vap|phu nhuan|tan binh|quan \d+", re.I)
KIND = [("flood", re.compile(r"ngap|trieu cuong|nuoc dang")), ("works", re.compile(r"thi cong|rao chan|sua duong|lo coc|dao duong")),
        ("ban", re.compile(r"cam o to|cam xe|cam dung|cam do|cam luu thong"))]
PROMPT = """Dưới đây là các tiêu đề báo (đánh số). Với mỗi tiêu đề, xác định nó có nói về chính tuyến đường được nêu
ở TP.HCM hay không. Trả về JSON {"items":[{"i":số,"relevant":true|false,"kind":"flood|works|ban|other",
"depth_cm":số hoặc null,"summary":"tóm tắt ≤ 15 từ"}]}. Không suy đoán; tiêu đề về tỉnh khác là relevant=false.
"""


def _search(street: str) -> list[dict]:
    q = quote(f'"{street}" {TOPICS}')
    r = httpx.get(RSS.format(q=q), timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    out = []
    for it in re.findall(r"<item>(.*?)</item>", r.text, re.S)[:12]:
        title = html.unescape(re.search(r"<title>(.*?)</title>", it, re.S).group(1))
        link = re.search(r"<link>(.*?)</link>", it, re.S).group(1).strip()
        src = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        date = re.search(r"<pubDate>(.*?)</pubDate>", it)
        out.append({"street": street, "title": re.sub(r"\s+-\s+[^-]+$", "", title), "url": link,
                    "source": html.unescape(src.group(1)) if src else "",
                    "date": parsedate_to_datetime(date.group(1)).date().isoformat() if date else ""})
    return out


def _keyword(item: dict) -> dict | None:
    t = strip_accents(item["title"])
    if strip_accents(item["street"]) not in t:
        return None
    if not HCMC.search(t) and not HCMC.search(strip_accents(item["source"])):
        # the street name alone is ambiguous (many provinces share it); keep only HCMC-flavoured outlets
        if not re.search(r"tuoi tre|thanh nien|sggp|nguoi lao dong|vnexpress|plo|hcm", strip_accents(item["source"])):
            return None
    kind = next((k for k, rx in KIND if rx.search(t)), None)
    return {**item, "kind": kind, "depth_cm": None, "summary": item["title"]} if kind else None


def news_for(streets: list[str]) -> list[dict]:
    items, seen = [], set()
    with ThreadPoolExecutor(4) as pool:
        for batch in pool.map(lambda s: _safe(_search, s), streets):
            for it in batch or []:
                if it["url"] not in seen:
                    seen.add(it["url"])
                    items.append(it)
    if not items:
        return []
    kept = []
    if ai.provider():
        try:
            listing = "\n".join(f"{i}. [{it['street']}] {it['title']} ({it['source']}, {it['date']})" for i, it in enumerate(items))
            out = ai._call(PROMPT + listing)
            for x in out.get("items", []):
                i = x.get("i")
                if isinstance(i, int) and 0 <= i < len(items) and x.get("relevant") and x.get("kind") in ("flood", "works", "ban"):
                    kept.append({**items[i], "kind": x["kind"], "depth_cm": x.get("depth_cm"),
                                 "summary": x.get("summary") or items[i]["title"], "filter": "gemini"})
        except Exception:
            kept = []
    if not kept:
        kept = [k for k in (_keyword(it) for it in items) if k]
    return sorted(kept, key=lambda x: x["date"], reverse=True)[:12]


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return []
