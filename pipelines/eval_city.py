"""City-wide evaluation of the Arrival Plan across HCMC (test cases spread over a 4×4 grid of urban HCMC).

For every case (a named alley, one per grid cell, seeded) the plan is computed three times:
  A. static evidence only (OSM, QĐ 4582 fire list, field/parcel CSVs)
  B. + the live area build without cadastral parcels (listings, news)
  C. + cadastral parcel widths (path into the destination cut every 5 m, usable = parcel gap − 1 m)
and the differences in door fit, Stop Points and walking distance are reported.

Run (backend deps):  cd backend && python3 ../pipelines/eval_city.py [--n 16] [--seed 7]
Output: docs/eval/city-eval.md and docs/eval/city-eval.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import flags, live, plan  # noqa: E402

ROADS = ROOT / "data" / "raw" / "overture" / "hcmc_small_roads.json"
OUT_MD = ROOT / "docs" / "eval" / "city-eval.md"
OUT_JSON = ROOT / "docs" / "eval" / "city-eval.json"
BBOX = (10.70, 106.60, 10.88, 106.80)  # urban core: s, w, n, e
VEHICLES = [("toyota-vios", "park"), ("toyota-fortuner", "park"), ("vinfast-vf-5", "pickup")]
ARRIVE = datetime.fromisoformat("2026-10-02T17:00:00+07:00")


def pick_cases(n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    side = int(n ** 0.5)
    s, w, nn, e = BBOX
    cells: dict[tuple[int, int], list] = {}
    for r in json.loads(ROADS.read_text()):
        name = r["tags"].get("name", "")
        if not name.startswith("Hẻm") or len(r["coords"]) < 3:
            continue
        lon, lat = r["coords"][len(r["coords"]) // 2]
        if not (s <= lat < nn and w <= lon < e):
            continue
        cell = (int((lat - s) / (nn - s) * side), int((lon - w) / (e - w) * side))
        cells.setdefault(cell, []).append({"name": name, "lat": lat, "lon": lon, "way_id": r["id"]})
    cases = []
    for i, cell in enumerate(sorted(cells)):
        c = rnd.choice(cells[cell])
        vid, intent = VEHICLES[i % len(VEHICLES)]
        cases.append({**c, "cell": cell, "vehicle_id": vid, "intent": intent})
    return cases[:n]


def summary(r: dict) -> dict:
    door = r.get("door") or {}
    fit = r["layers"]["fit"]["features"]
    alleys = [f for f in fit if f["properties"].get("kind") != "main"]
    known = sum(1 for f in alleys if f["properties"].get("fit") not in ("unknown",))
    return {
        "verdict": r["verdict"]["headline"],
        "code": r["verdict"]["code"],
        "door_fit": door.get("fit", {}).get("class"),
        "door_ok": door.get("ok"),
        "door_fail": (door.get("fail_reasons") or [])[:1],
        "stops": [{"name": s["name"], "kind": s["kind"], "walk_m": s["walk"]["meters"], "fit": s["fit"]["class"],
                   "verified": s["verified"]} for s in r["stop_points"]],
        "alley_fit_known_pct": round(100 * known / max(1, len(alleys)), 1),
    }


def run_case(c: dict) -> dict:
    args = (c["lat"], c["lon"], c["vehicle_id"], c["intent"], ARRIVE, 15 if c["intent"] == "pickup" else 120)
    t0 = time.time()
    a = summary(plan.plan(*args, dest_label=c["name"]))
    area = live.run_sync(c["lat"], c["lon"])
    out = {**c, "build_s": round(time.time() - t0),
           "build": {k: v["detail"] for k, v in (area or {}).get("steps", {}).items()},
           "build_error": None if area else "build failed", "A_static": a}
    if area:
        # Each variant is its own overlay with its own revision, so the width cache never mixes them.
        no_parcels = {**area, "parcels": [], "revision": f"{area['revision']}-no-parcels"}
        out["B_live"] = summary(plan.plan(*args, dest_label=c["name"], live_area=no_parcels))
        out["C_parcels"] = summary(plan.plan(*args, dest_label=c["name"], live_area=area))
        cuts = [x for p in area.get("parcels", []) for x in p["cuts"]]
        out["parcels"] = {"ways": len(area.get("parcels", [])), "cuts": len(cuts),
                          "deep_cuts": sum(len(p["cuts"]) for p in area.get("parcels", []) if p.get("deep")),
                          "narrowest_usable_m": min((x["width_m"] for x in cuts), default=None)}
    return out


def fmt_stops(s: dict) -> str:
    if not s["stops"]:
        return "—"
    return "; ".join(f"{x['name']} ({'cửa' if x['kind'] == 'door' else x['walk_m']} {'' if x['kind'] == 'door' else 'm'})".replace(" )", ")")
                     for x in s["stops"][:2])


def write(results: list[dict]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    lines = ["# City-wide evaluation", "",
             f"{len(results)} named alleys, one per cell of a 4×4 grid over urban HCMC ({BBOX}), arrival 17:00 on 2026-10-02.",
             "A = static evidence; B = + live listings and news; C = + cadastral parcel widths (5 m cuts, gap − 1 m).", "",
             "| # | Destination | Car · intent | Build | Parcel cuts (narrowest) | Door fit A→C | Stop #1 A | Stop #1 C | Changed by parcels? |",
             "|---|---|---|---|---|---|---|---|---|"]
    changed = 0
    for i, r in enumerate(results, 1):
        a, b, c = r["A_static"], r.get("B_live"), r.get("C_parcels")
        if not c:
            lines.append(f"| {i} | {r['name']} | {r['vehicle_id']} · {r['intent']} | error: {r.get('build_error')} | | | | | |")
            continue
        diff = (b["stops"][:1] != c["stops"][:1]) or (b["door_ok"] != c["door_ok"])
        changed += diff
        p = r["parcels"]
        lines.append(
            f"| {i} | {r['name']} | {r['vehicle_id']} · {r['intent']} | {r['build_s']} s | {p['cuts']} ({p['narrowest_usable_m']} m) "
            f"| {a['door_fit']}→{c['door_fit']} {'✓' if c['door_ok'] else '✗'} | {fmt_stops(a)} | {fmt_stops(c)} | {'**yes**' if diff else 'no'} |")
    known = [(r["A_static"]["alley_fit_known_pct"], r["C_parcels"]["alley_fit_known_pct"]) for r in results if r.get("C_parcels")]
    lines += ["", f"- Plans changed by parcel widths (Stop #1 or door decision, B vs C): **{changed}/{len(known)}**",
              f"- Alley segments with a fit verdict, mean: A {sum(k[0] for k in known) / max(1, len(known)):.1f} % → "
              f"C {sum(k[1] for k in known) / max(1, len(known)):.1f} %", ""]
    for i, r in enumerate(results, 1):
        if r.get("C_parcels"):
            b, c = r["B_live"], r["C_parcels"]
            lines.append(f"**{i}. {r['name']}** ({r['vehicle_id']}, {r['intent']}): B “{b['verdict']}” → C “{c['verdict']}”"
                         + (f"; door: {c['door_fail'][0]}" if c["door_fail"] else ""))
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    flags._load()
    flags._state["ai_photo_evidence"] = False  # save Gemini quota and time; photos are not what we measure here
    cases = pick_cases(a.n, a.seed)
    print(f"{len(cases)} cases", flush=True)
    done = {r["way_id"]: r for r in json.loads(OUT_JSON.read_text())} if OUT_JSON.exists() else {}
    results = []
    for i, c in enumerate(cases, 1):
        if done.get(c["way_id"], {}).get("C_parcels"):  # resume: keep finished cases
            results.append(done[c["way_id"]])
            continue
        try:
            r = run_case(c)
        except Exception as exc:  # keep going; report the failure
            r = {**c, "build_error": str(exc)[:200], "A_static": {"stops": [], "door_fit": None}}
        results.append(r)
        write(results)
        cp = r.get("C_parcels") or {}
        print(f"[{i}/{len(cases)}] {c['name']} · {c['vehicle_id']} · {r.get('build_s')} s · "
              f"{(cp.get('verdict') or r.get('build_error'))}", flush=True)
    print(f"done -> {OUT_MD}", flush=True)


if __name__ == "__main__":
    main()
