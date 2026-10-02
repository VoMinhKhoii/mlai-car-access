"""regex-v1: deterministic extractor of alley-access claims from Vietnamese listing text.

Works on accent-folded lowercase text (see common.fold, which keeps character positions aligned
so snippets can be cut from the original text). Every pattern below is written in folded form:
"hẻm xe hơi" -> "hem xe hoi", "mét" -> "met", "đầu" -> "dau".

extract(text, listing_street=None, gazetteer=None) -> dict with:
  width_m, width_at_mouth, width_text, width_mentions_m,
  access_claim ("xe_hoi"|"xe_hoi_tranh"|"ba_gac"|"xe_may"|None),
  car_to_door (True|False|None), through ("thong"|"cut"|None),
  alley_chain (list[str]), alley_chain_source ("text"|"text+listing_street"|None)
"""
from __future__ import annotations

import re

from common import fold, norm_name

EXTRACTOR = "regex-v1"

XH = r"(?:xe\s*hoi|xe\s*o\s*to|o\s*to|oto|xh)"
NUM = r"\d{1,2}(?:[.,]\d{1,2})?"

# ---------- width ----------
_FILL = (r"(?:xe\s*hoi|o\s*to|oto|xe\s*tai|nhua|be\s*tong|betong|rong|thong|truoc(?:\s*nha)?|chinh|lon|"
         r"tranh(?:\s*nhau)?|ba\s*gac|dau|cut|\d{1,2}\s*cho|:|-|,)")
_WIDTH = re.compile(
    rf"\b(?P<kw>hem|hxh|kiet|duong\s+truoc\s+nha|duong\s+hem|duong\s+vao\s+nha)"
    rf"(?P<fill>(?:\s*{_FILL}(?![a-z])){{0,4}})\s*(?:rong\s*)?(?:khoang|gan|hon|tren|toi|chi|~|la)?\s*"
    rf"(?P<num>{NUM})(?:\s*(?:-|den|toi)\s*(?P<num2>{NUM}))?\s*(?:m(?P<dec>\d)(?!\d)|met\b|m\b)"
)
# words right before the keyword that turn a width into a distance ("cách hẻm 20m", "vào hẻm 30m")
_DISTANCE_BEFORE = re.compile(r"(?:cach|vao|trong|di|sau|toi|den|ra|lo\s*gioi)\s*(?:dau\s*|mat\s*tien\s*)?$")
# "hẻm xe hơi 10m ra mặt tiền" = 10 m to the main road, not a width
_DISTANCE_AFTER = re.compile(r"^\s*(?:ra|toi|den)\s+(?:mat\s*tien|mt\b|duong|pho)")
_MOUTH_BEFORE = re.compile(r"(?:dau|mat\s*tien|mt)\s*$")


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _widths(f: str, text: str):
    out = []
    for m in _WIDTH.finditer(f):
        before = f[max(0, m.start() - 14):m.start()]
        if _DISTANCE_BEFORE.search(before) or _DISTANCE_AFTER.search(f[m.end():m.end() + 20]):
            continue
        w = _num(m.group("num"))
        if m.group("dec"):
            w = w + int(m.group("dec")) / 10          # "hẻm 3m5" = 3.5 m
        if m.group("num2"):
            w = min(w, _num(m.group("num2")))          # "hẻm 5-6m" -> conservative 5
        if not 1.0 <= w <= 15.0:
            continue
        fill = m.group("fill") or ""
        mouth = bool(_MOUTH_BEFORE.search(before)) or bool(re.search(r"\bdau\b", fill))
        front = "truoc" in fill or "truoc" in m.group("kw") or "vao nha" in m.group("kw")
        out.append({"w": round(w, 2), "mouth": mouth, "front": front,
                    "text": text[max(0, m.start() - (8 if mouth else 0)):m.end()].strip()})
    return out


# ---------- access ----------
_NEAR_BEFORE = re.compile(r"(?:cach|gan|sat|ke|ra|toi|den|thong\s*ra|buoc\s*ra|mot\s*buoc|khong\s*phai|chua)\s*(?:\d+\s*m\s*)?$")
_TO_MAIN_ROAD = r"(?:mat\s*tien|mt\b|duong|pho)"
_NEAR_AFTER = re.compile(rf"^\s*(?:\S+\s+){{0,2}}cach\b(?!\s*{_TO_MAIN_ROAD})(?!\s*(?:\S+\s+){{0,2}}(?:ra|toi|den)\s+{_TO_MAIN_ROAD})")
ACCESS_PATTERNS = {
    "xe_hoi_tranh": [rf"\b(?:hem\s+)?(?:\d\s*|hai\s*)?{XH}\s*(?:\d\s*chieu\s*)?tranh\b", r"\bhxh\s+tranh\b"],
    "xe_hoi": [r"\bhxh\b", rf"\bhem\s+(?:\d\s*)?(?:{XH}|xe\s*tai)\b",
               rf"\b{XH}\s+(?:vao|toi|den|do|dau|ngu|dung)\s+(?:tan\s+|trong\s+|truoc\s+)?(?:nha|cua)\b"],
    "ba_gac": [r"\bhem\s+(?:xe\s*)?(?:ba|3)\s*gac\b", r"\bba\s*gac\s+(?:vao|toi|den)\b"],
    "xe_may": [r"\bhem\s+(?:\d\s*)?xe\s*may\b", r"\bxe\s*may\s+tranh\b", r"\bchi\s+xe\s*may\b"],
}
_ACCESS_RX = {k: [re.compile(p) for p in v] for k, v in ACCESS_PATTERNS.items()}

_DOOR_YES = [re.compile(p) for p in (
    rf"\b{XH}\s*(?:\d{{1,2}}\s*cho\s*)?(?:vao|toi|den|do|dau|ngu|dung|quay\s*dau)\s+(?:tan\s+|trong\s+|truoc\s+|ngay\s+)*(?:nha|cua)\b",
    rf"\b(?:do|dau)\s+{XH}\s+(?:\w+\s+)?(?:truoc|trong|tan)\s+(?:nha|cua)\b",
    rf"\b(?:hem\s+{XH}|hxh)\s+(?:vao\s+|toi\s+|den\s+)(?:tan\s+)?(?:nha|cua)\b",
)]
_DOOR_NO = [re.compile(p) for p in (
    rf"\b(?:hem\s+)?{XH}\s+(?:\S+\s+){{0,2}}cach\s+(?!{_TO_MAIN_ROAD})(?:nha\s+)?(?:\w+\s+)?\d[\d.,]*+\s*+(?:met|m|can)?+(?!\s*(?:ra|toi|den)\s+{_TO_MAIN_ROAD})",
    rf"\bcach\s+(?:hem\s+{XH}|hxh)\b",
    rf"\b{XH}\s+(?:do|dau)\s+(?:o\s+)?dau\s+hem\b",
)]


def _claims(f: str) -> set[str]:
    found = set()
    for label, rxs in _ACCESS_RX.items():
        for rx in rxs:
            for m in rx.finditer(f):
                before, after = f[max(0, m.start() - 16):m.start()], f[m.end():m.end() + 45]
                if label.startswith("xe_hoi") and (_NEAR_BEFORE.search(before) or _NEAR_AFTER.search(after)):
                    continue
                if re.search(r"khong\s*(?:phai\s*)?$", before):
                    continue
                found.add(label)
    return found


def _access(claims: set[str]):
    for label in ("xe_may", "ba_gac", "xe_hoi_tranh", "xe_hoi"):   # most restrictive wins (Q4 worst case)
        if label in claims:
            return label
    return None


def _car_to_door(f: str, access):
    if access in ("xe_may", "ba_gac"):
        return False
    yes = any(rx.search(f) for rx in _DOOR_YES)
    no = any(rx.search(f) for rx in _DOOR_NO)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


# ---------- through / dead end ----------
_THONG = [re.compile(p) for p in (
    rf"\bhem\s+(?:(?:{XH}|hxh|nhua|be\s*tong|rong|{NUM}\s*m)\s+){{0,3}}thong\b(?!\s*(?:thoang|minh|tin|so|bao|qua|thuong|suot|nhat|dung))",
    r"\bhxh\s+thong\b(?!\s*(?:thoang|minh|tin))",
    r"\bthong\s+(?:ra|sang)\s+(?:duong|mat\s*tien|hem|\w+\s+\w+)",
    r"\bthong\s+(?:2|hai)\s+(?:dau|mat|duong)\b",
    r"\bthong\s+(?:tu\s*tung|cac\s*nga|nhieu\s*nga|khap\s*nga|bon\s*phia)\b",
    r"\bkhong\s+(?:phai\s+)?hem\s+cut\b",
)]
_CUT = re.compile(r"(?<!khong phai )(?<!khong )\bhem\s+cut\b|\bcuoi\s+hem\s+cut\b")


def _through(f: str):
    thong = any(rx.search(f) for rx in _THONG)
    cut = bool(_CUT.search(f))
    if thong and not cut:
        return "thong"
    if cut and not thong:
        return "cut"
    return None


# ---------- alley chain ----------
ABBREVIATIONS = {
    "xvnt": "Xô Viết Nghệ Tĩnh", "dbp": "Điện Biên Phủ", "nhc": "Nguyễn Hữu Cảnh", "cmt8": "Cách Mạng Tháng Tám",
    "pdl": "Phan Đăng Lưu", "nvd": "Nguyễn Văn Đậu", "nkkn": "Nam Kỳ Khởi Nghĩa", "ntmk": "Nguyễn Thị Minh Khai",
    "uvk": "Ung Văn Khiêm", "nvt": "Nguyễn Văn Trỗi", "pxl": "Phan Xích Long", "hvt": "Hoàng Văn Thụ",
    "lvs": "Lê Văn Sỹ",
}


class Gazetteer:
    """Folded street name -> display name, compiled into one longest-first alternation."""

    def __init__(self, names):
        self.display: dict[str, str] = {}
        for n in names:
            key = norm_name(n)
            if len(key) >= 5 and not re.match(r"^(hem|kiet|ngo|ngach)\b", key):
                self.display.setdefault(key, re.sub(r"^(Đường|Đ\.)\s+", "", n.strip()))
        for k, v in ABBREVIATIONS.items():
            self.display.setdefault(k, v)
        alts = sorted(self.display, key=len, reverse=True)
        self.rx = re.compile(r"(?:" + "|".join(re.escape(a) for a in alts) + r")(?![a-z0-9])") if alts else None


_PATH = re.compile(
    r"(?P<kw>\b(?:hem|hxh|kiet|ngo|ngach|so|nha|dc|dia\s*chi|sn)\s*(?:so\s*)?)?(?<![\d/.,])"
    r"(?P<path>\d{1,4}[a-ln-z]?(?:/\d{1,4}[a-ln-z]?){0,4})(?![\d/.,]|\s*(?:m\b|met|ty|trieu|tr\b|m2|pn|wc|tang|lau|cho))"
    r"\s*,?\s*(?:duong\s+|d\.\s*|pho\s+)?"
)


def _chain_from(path: str, street: str) -> list[str]:
    parts = path.upper().split("/")
    return [f"Hẻm {'/'.join(parts[:i])} {street}" for i in range(1, len(parts) + 1)]


def _alley_chain(f: str, listing_street: str | None, gaz: Gazetteer | None):
    listing_key = norm_name(listing_street or "")
    best = None   # (score, chain)
    for m in _PATH.finditer(f):
        path, has_kw = m.group("path"), bool(re.search(r"hem|hxh|kiet|ngo|ngach", m.group("kw") or ""))
        if "/" not in path and not has_kw:
            continue                                  # "45 XVNT" is a frontage number, not an alley
        tail = f[m.end():m.end() + 60]
        street = None
        if gaz and gaz.rx:
            sm = gaz.rx.match(tail)
            if sm:
                street = gaz.display[sm.group(0)]
        if listing_key and tail.startswith(listing_key):
            street = re.sub(r"^(Đường|Đ\.)\s+", "", listing_street.strip())
        source = "text"
        if street is None:
            if not has_kw or not listing_street:
                continue
            street, source = re.sub(r"^(Đường|Đ\.)\s+", "", listing_street.strip()), "text+listing_street"
        score = (norm_name(street) == listing_key, source == "text", path.count("/"))
        if best is None or score > best[0]:
            best = (score, _chain_from(path, street), source)
    return (best[1], best[2]) if best else ([], None)


def extract(text: str, listing_street: str | None = None, gazetteer: Gazetteer | None = None) -> dict:
    f = fold(text)
    widths = _widths(f, text)
    chosen = None
    if widths:
        front = [w for w in widths if w["front"]]
        chosen = min(front or widths, key=lambda w: w["w"])
    claims = _claims(f)
    access = _access(claims)
    chain, chain_src = _alley_chain(f, listing_street, gazetteer)
    return {
        "width_m": chosen["w"] if chosen else None,
        "width_at_mouth": bool(chosen and chosen["mouth"]),
        "width_text": chosen["text"] if chosen else None,
        "width_mentions_m": sorted({w["w"] for w in widths}),
        "access_claim": access,
        "access_claims_all": sorted(claims),
        "car_to_door": _car_to_door(f, access),
        "through": _through(f),
        "alley_chain": chain,
        "alley_chain_source": chain_src,
    }
