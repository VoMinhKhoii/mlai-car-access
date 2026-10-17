"""Live, display-only Google look-up for an alley (flags: google_lookup, ai_maps_grounding).

Google Maps Platform terms: nothing here is stored, cached to disk, scored, or fed into
Evidence. It is shown to the driver with attribution. Every paid call goes through budget.spend().
"""
from __future__ import annotations

import os

import httpx

from . import budget, flags
from .ai import gemini_keys

KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
FOOD_TYPES = ["restaurant", "cafe", "coffee_shop", "bakery", "meal_takeaway", "bar", "food_court",
              "vietnamese_restaurant", "store", "convenience_store"]
NEARBY_MASK = ("places.id,places.displayName,places.primaryType,places.primaryTypeDisplayName,"
               "places.location,places.formattedAddress,places.googleMapsUri")
DETAIL_MASK = "id,displayName,rating,userRatingCount,reviews,parkingOptions,websiteUri,googleMapsUri"
KEYWORDS = ["ô tô", "oto", "xe hơi", "xe hoi", "đậu xe", "đỗ xe", "gửi xe", "chỗ để xe", "hẻm nhỏ", "hẻm sâu",
            "hẻm hẹp", "không vào được", "vào được", "ngập", "car", "parking", "alley", "narrow"]


class LookupOff(Exception):
    pass


def _require(flag: str) -> None:
    if not flags.enabled(flag):
        raise LookupOff(flag)
    if flag == "google_lookup" and not KEY:
        raise LookupOff("GOOGLE_MAPS_API_KEY")


def streetview(lat: float, lon: float) -> dict:
    """Free metadata check: is there imagery within 40 m, and when was it taken?"""
    _require("google_lookup")
    budget.spend("streetview_metadata")
    r = httpx.get("https://maps.googleapis.com/maps/api/streetview/metadata",
                  params={"location": f"{lat},{lon}", "radius": 40, "source": "outdoor", "key": KEY}, timeout=10).json()
    if r.get("status") != "OK":
        return {"available": False, "status": r.get("status")}
    loc = r["location"]
    return {"available": True, "pano_id": r["pano_id"], "date": r.get("date"), "lat": loc["lat"], "lon": loc["lng"],
            "copyright": r.get("copyright"),
            "maps_url": f"https://www.google.com/maps/@?api=1&map_action=pano&pano={r['pano_id']}"}


def streetview_image(pano_id: str, heading: float) -> bytes:
    _require("google_lookup")
    budget.spend("streetview_static")
    r = httpx.get("https://maps.googleapis.com/maps/api/streetview",
                  params={"pano": pano_id, "size": "640x400", "fov": 80, "pitch": 0, "heading": round(heading),
                          "key": KEY}, timeout=15)
    r.raise_for_status()
    return r.content


def nearby_places(lat: float, lon: float, radius: float = 80) -> list[dict]:
    _require("google_lookup")
    budget.spend("places_nearby_pro")
    r = httpx.post("https://places.googleapis.com/v1/places:searchNearby",
                   headers={"X-Goog-Api-Key": KEY, "X-Goog-FieldMask": NEARBY_MASK},
                   json={"includedTypes": FOOD_TYPES, "maxResultCount": 12, "rankPreference": "DISTANCE",
                         "languageCode": "vi",
                         "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                                            "radius": radius}}}, timeout=15)
    r.raise_for_status()
    out = []
    for p in r.json().get("places", []):
        out.append({"id": p["id"], "name": p.get("displayName", {}).get("text"),
                    "type": p.get("primaryTypeDisplayName", {}).get("text") or p.get("primaryType"),
                    "address": p.get("formattedAddress"), "lat": p["location"]["latitude"],
                    "lon": p["location"]["longitude"], "maps_url": p.get("googleMapsUri")})
    return out


def place_details(place_id: str) -> dict:
    _require("google_lookup")
    budget.spend("places_details_atmosphere")
    r = httpx.get(f"https://places.googleapis.com/v1/places/{place_id}",
                  headers={"X-Goog-Api-Key": KEY, "X-Goog-FieldMask": DETAIL_MASK},
                  params={"languageCode": "vi"}, timeout=15)
    r.raise_for_status()
    p = r.json()
    reviews = []
    for rv in p.get("reviews", []):
        text = (rv.get("text") or rv.get("originalText") or {}).get("text", "")
        low = text.lower()
        reviews.append({"text": text, "rating": rv.get("rating"),
                        "when": rv.get("relativePublishTimeDescription"),
                        "author": (rv.get("authorAttribution") or {}).get("displayName"),
                        "author_url": (rv.get("authorAttribution") or {}).get("uri"),
                        "keywords": [k for k in KEYWORDS if k in low]})
    return {"id": p.get("id"), "name": (p.get("displayName") or {}).get("text"), "rating": p.get("rating"),
            "ratings": p.get("userRatingCount"), "parking": p.get("parkingOptions"), "website": p.get("websiteUri"),
            "maps_url": p.get("googleMapsUri"), "reviews": reviews}


def ask_maps(lat: float, lon: float, alley: str) -> dict:
    """Gemini grounded on Google Maps. Display only, with Google Maps attribution right after the text."""
    _require("ai_maps_grounding")
    keys = gemini_keys()
    if not keys:
        raise LookupOff("GEMINI_API_KEY")
    budget.spend("gemini_maps_grounding")
    prompt = (f"I am driving a car to an address in {alley}, Ho Chi Minh City, Vietnam. Using Google Maps places and "
              "reviews near this alley only, answer briefly in English: (1) do reviews or place details indicate "
              "cars can enter this alley or park nearby? (2) any mention of narrow access, flooding, or where drivers "
              "park? Say 'No information available' when Maps has nothing. Do not guess.")
    body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"googleMaps": {}}],
            "toolConfig": {"retrievalConfig": {"latLng": {"latitude": lat, "longitude": lon}}}}
    last = None
    for key in keys:
        r = httpx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                       params={"key": key}, json=body, timeout=60)
        if r.status_code in (429, 403, 404, 503) or (r.status_code == 400 and "API key" in r.text):
            last = r.text[:300]
            continue
        r.raise_for_status()
        c = r.json()["candidates"][0]
        text = "".join(p.get("text", "") for p in c["content"]["parts"])
        sources = []
        for ch in (c.get("groundingMetadata") or {}).get("groundingChunks", []):
            m = ch.get("maps") or {}
            if m:
                sources.append({"title": m.get("title"), "uri": m.get("uri")})
        return {"text": text, "sources": sources, "attribution": "Google Maps"}
    raise LookupOff(f"All Gemini keys are rate-limited: {last}")
