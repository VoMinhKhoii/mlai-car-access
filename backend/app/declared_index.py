"""Atomic, mtime-reloaded city listing index. Read-only; no network/credentials.

Listing bounds remain Declared. Measured/Official widths exclude this product
entirely, including apparently compatible claims. An advertising disagreement
keeps the hull and REVIEW; generic OSM priors cannot conceal its uncertainty.
"""
from __future__ import annotations

import json
import math
import threading

from .config import CACHE

PATH = CACHE / "live/declared_index.json"
_lock = threading.RLock()
_stamp, _data = None, {}


def snapshot():
    global _stamp, _data
    with _lock:
        try:
            st = PATH.stat()
        except FileNotFoundError:
            _stamp, _data = None, {}
            return _stamp, _data
        stamp = st.st_mtime_ns, st.st_size
        if stamp != _stamp:
            try:
                data = json.loads(PATH.read_text())
                if data.get("schema_version") != 1 or data.get("tier") != "Declared" or not isinstance(data.get("ways"), dict):
                    raise ValueError("Unsupported Declared product")
                for wid, r in data["ways"].items():
                    lo, hi = r.get("lo"), r.get("hi")
                    if not str(wid).isdigit() or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lo, hi)) or not .5 <= lo <= hi <= 40:
                        raise ValueError("Invalid Declared bounds")
            except (OSError, ValueError, TypeError, AttributeError):
                return _stamp, _data  # retain last good product, retry the replacement later
            _stamp, _data = stamp, data
        return _stamp, _data


def refresh(store):
    stamp, _ = snapshot()
    if stamp != getattr(store, "_declared_stamp", None):
        store.reload()


def load_into(store):
    # Import lazily to avoid an evidence ↔ product module cycle.
    from .evidence import Bound
    store._declared_stamp, product = snapshot()
    for wid, r in product.get("ways", {}).items():
        claims = r.get("claims", [])
        b = Bound(r["lo"], r["hi"], "Declared", "HCMC listings (alley address chain)",
                  f"{r.get('independent_listings', 0)} estimated independent listings / {r.get('n_listings', 0)} listings; "
                  f"agreement {r.get('agreement', 0):.0%}. Union of declared ranges; "
                  "listing width is an upper bound, not measured clear width. "
                  + ("Conflicting declarations: review required." if r.get("review") else "Not measured on site.")
                  + (' ' + '; '.join(dict.fromkeys(c['provenance'] for c in claims if c.get('provenance')))
                     if any(c.get('provenance') for c in claims) else ''),
                  observed_on=r.get("last_posted", ""), url=claims[0].get("url", "") if claims else "",
                  feature="ai_listings")
        b._city_declared = True
        store._add(b, wid)
    for wid, r in product.get("fire_supplemental", {}).items():
        store._add(Bound(r["lo"], r["hi"], "Declared", r["source"], r["detail"],
                         observed_on=r.get("observed_on", ""), url=r.get("url", "")), wid)


def prepare(way_id, bounds):
    """Return active bounds, overruled bounds and an explicit disagreement flag."""
    city = [b for b in bounds if getattr(b, "_city_declared", False)]
    if not city:
        return bounds, [], False
    if any(b.tier in ("Measured", "Official") for b in bounds):
        return [b for b in bounds if b not in city], city, False
    _, product = snapshot()
    review = bool(product.get("ways", {}).get(str(way_id), {}).get("review"))
    ignored = [b for b in bounds if b not in city and
               ((b.tier == "Declared" and (b.feature == "ai_listings" or review)) or
                (b.tier == "Inferred" and b.source in ("OSM road class", "OSM lane count", "OSM phân loại đường", "OSM số làn xe")))]
    return [b for b in bounds if b not in ignored], ignored, review
