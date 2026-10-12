"""Field validation (R-11): score width and egress predictions against real field measurements.

The team measures; this script never invents, fills or repairs a label. It refuses to score fewer than MIN_ROWS
usable measured segments.

  1. Freeze a split once, from the real measurements (group-disjoint: the same alley chain never appears on both sides):
       python3 pipelines/eval_field.py --measurements data/field/measurements.csv --make-split data/field/eval-split.json
     Commit the split before looking at any result. It is never regenerated over an existing file.
  2. Score:
       python3 pipelines/eval_field.py --measurements data/field/measurements.csv --egress data/field/egress.csv \
         --split data/field/eval-split.json --output plans/<plan>/reports/field-validation.json

Two modes are reported separately:
  * model_only: every measured row (held-out and calibration) is removed from the evidence index before indexing, so
    the plan reasons only from OSM, listings, parcels and the other sources.
  * field_informed: calibration rows are evidence, held-out rows are not.
Only held-out segments are scored in both modes.

Truth is an interval: measured clear width ± stated uncertainty. A predicted "fits"/"tight" whose whole truth interval
lies below the vehicle's need is a definite false fit; an interval that straddles the need is indeterminate and is not
counted as correct. "unknown" is abstention: it is safe, but if everything is unknown the tool has shown no value.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evidence import EvidenceStore, _norm_alley, width_ranges  # noqa: E402
from app.osm import build_graph  # noqa: E402
from app.plan import compute_fit  # noqa: E402
from app.vehicles import get_profile  # noqa: E402

VN = timezone(timedelta(hours=7))
MIN_ROWS = 20
VEHICLES = ("toyota-vios", "toyota-fortuner", "vinfast-vf-5")
REQUIRED = ("osm_way_id", "alley_name", "lat", "lon", "width_m", "uncertainty_m", "date", "measured_by")
EGRESS_OBSERVATIONS = {"turn_space", "no_turn_space", "oneway_forward", "oneway_backward", "two_way",
                       "sign_no_stopping", "sign_no_parking", "no_sign", "unknown"}


class Invalid(Exception):
    pass


def _finite(value: str, name: str, row: int) -> float:
    try:
        x = float(str(value).replace(",", "."))
    except ValueError:
        raise Invalid(f"row {row}: {name} is not a number ({value!r})")
    if not math.isfinite(x):
        raise Invalid(f"row {row}: {name} is not finite")
    return x


def group_key(alley_name: str) -> str:
    """Alias group of an alley: the main alley of its chain ("Hẻm 123/45 X" and "Hẻm 123 X" are one group)."""
    s = _norm_alley(alley_name)
    return re.sub(r"\b(\d+)(/\d+)+\b", r"\1", s)


def load_measurements(path: Path) -> list[dict]:
    rows, problems, seen = [], [], set()
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise Invalid(f"{path.name}: missing columns {missing}")
        for i, r in enumerate(reader, start=2):
            try:
                if not (r.get("osm_way_id") or "").strip().isdigit():
                    raise Invalid(f"row {i}: osm_way_id is required for evaluation")
                way_id = int(r["osm_way_id"])
                if way_id in seen:
                    raise Invalid(f"row {i}: duplicate osm_way_id {way_id}")
                width = _finite(r["width_m"], "width_m", i)
                unc = _finite(r["uncertainty_m"], "uncertainty_m", i)
                if width <= 0 or unc <= 0:
                    raise Invalid(f"row {i}: width_m and uncertainty_m must be > 0 (no perfect measurement)")
                if not r["alley_name"].strip() or not r["date"].strip() or not r["measured_by"].strip():
                    raise Invalid(f"row {i}: alley_name, date and measured_by are required")
                rows.append({**r, "osm_way_id": way_id, "width_m": width, "uncertainty_m": unc,
                             "lat": _finite(r["lat"], "lat", i), "lon": _finite(r["lon"], "lon", i),
                             "group": group_key(r["alley_name"])})
                seen.add(way_id)
            except Invalid as exc:
                problems.append(str(exc))
    if problems:
        raise Invalid("invalid measurements:\n  " + "\n  ".join(problems))
    return rows


def load_egress(path: Path | None, way_ids: set[int]) -> list[dict]:
    if path is None or not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            obs = (r.get("observation") or "").strip()
            if obs not in EGRESS_OBSERVATIONS:
                raise Invalid(f"egress row {i}: observation must be one of {sorted(EGRESS_OBSERVATIONS)}")
            if not (r.get("way_id") or "").isdigit() or int(r["way_id"]) not in way_ids:
                raise Invalid(f"egress row {i}: way_id must be a measured way")
            out.append({**r, "way_id": int(r["way_id"])})
    return out


def make_split(rows: list[dict], path: Path, seed: int) -> dict:
    if path.exists():
        raise Invalid(f"{path} already exists: a split is frozen once and never regenerated")
    groups = sorted({r["group"] for r in rows})
    if len(rows) < MIN_ROWS:
        raise Invalid(f"need ≥{MIN_ROWS} measured segments, have {len(rows)}: collect more, do not lower the gate")
    if len(groups) < 2:
        raise Invalid("need at least two alley groups to split")
    random.Random(seed).shuffle(groups)
    held, cal, held_n = [], [], 0
    for g in groups:  # fill the held-out half by whole groups, so no alias crosses the split
        if held_n < len(rows) / 2:
            held.append(g)
            held_n += sum(1 for r in rows if r["group"] == g)
        else:
            cal.append(g)
    split = {"frozen_at": datetime.now(VN).isoformat(timespec="seconds"), "seed": seed,
             "measurements_sha1": hashlib.sha1(json.dumps([r["osm_way_id"] for r in rows]).encode()).hexdigest(),
             "heldout": {"groups": sorted(held), "way_ids": sorted(r["osm_way_id"] for r in rows if r["group"] in held)},
             "calibration": {"groups": sorted(cal), "way_ids": sorted(r["osm_way_id"] for r in rows if r["group"] in cal)}}
    path.write_text(json.dumps(split, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return split


def check_split(rows: list[dict], split: dict) -> None:
    held, cal = set(split["heldout"]["way_ids"]), set(split["calibration"]["way_ids"])
    if held & cal:
        raise Invalid(f"split leaks way ids across sides: {sorted(held & cal)[:5]}")
    hg, cg = set(split["heldout"]["groups"]), set(split["calibration"]["groups"])
    if hg & cg:
        raise Invalid(f"split leaks alley groups across sides: {sorted(hg & cg)[:5]}")
    for r in rows:
        side = "heldout" if r["osm_way_id"] in held else "calibration" if r["osm_way_id"] in cal else None
        if side is None:
            raise Invalid(f"way {r['osm_way_id']} is not in the frozen split (re-freezing is not allowed)")
        if r["group"] not in split[side]["groups"]:
            raise Invalid(f"way {r['osm_way_id']}: its alley group {r['group']!r} is on the other side of the split")


def truth_class(w: float, u: float, need_fit: float, need_tight: float) -> str:
    lo, hi = w - u, w + u
    if hi < need_tight:
        return "no"
    if lo >= need_fit:
        return "fits"
    if lo >= need_tight and hi < need_fit:
        return "tight"
    return "indeterminate"


def score(rows: list[dict], held: set[int], store: EvidenceStore, label_names: set[str]) -> dict:
    # No held-out label may be reachable from the evidence the plan reasons from.
    measured = lambda bounds: any(b.tier == "Measured" for b in bounds)  # noqa: E731
    leaked = ([w for w in held if measured(store.by_way.get(w, []))]
              + [n for n in label_names if measured(store.by_name.get(n, []))])
    if leaked:
        raise Invalid(f"held-out labels leak into the evidence index: {leaked[:5]}")
    view = store.view()
    per_vehicle = {}
    widths = []
    for vid in VEHICLES:
        p = get_profile(vid)
        cells: dict[str, dict[str, int]] = {}
        definite_false_fit, items = 0, []
        for r in (x for x in rows if x["osm_way_id"] in held):
            g = build_graph(r["lat"], r["lon"])
            if r["osm_way_id"] not in g.ways:
                items.append({"way_id": r["osm_way_id"], "error": "way not in the area graph at lat/lon"})
                continue
            wrs = width_ranges(g, view)
            fit, _ = compute_fit(g, wrs, p)
            pred = fit[r["osm_way_id"]]
            truth = truth_class(r["width_m"], r["uncertainty_m"], p.fits_min, p.tight_min)
            cells.setdefault(pred, {}).setdefault(truth, 0)
            cells[pred][truth] += 1
            false_fit = pred in ("fits", "tight") and truth == "no"
            definite_false_fit += false_fit
            items.append({"way_id": r["osm_way_id"], "predicted": pred, "truth": truth, "false_fit": false_fit})
            if vid == VEHICLES[0]:
                wr = wrs[r["osm_way_id"]]
                inside = wr.lo <= r["width_m"] + r["uncertainty_m"] and r["width_m"] - r["uncertainty_m"] <= wr.hi
                widths.append({"way_id": r["osm_way_id"], "lo": round(wr.lo, 2), "hi": min(round(wr.hi, 2), 40),
                               "truth": r["width_m"], "unc": r["uncertainty_m"], "overlaps_truth": inside,
                               "basis": wr.width_basis, "decisive": wr.decisive_clearance})
        scored = [x for x in items if "predicted" in x]
        per_vehicle[vid] = {"n": len(scored), "confusion": cells, "definite_false_fits": definite_false_fit,
                            "abstained": sum(1 for x in scored if x["predicted"] == "unknown"),
                            "items": items}
    return {"vehicles": per_vehicle, "widths": widths,
            "width_overlap_rate": round(sum(w["overlaps_truth"] for w in widths) / len(widths), 3) if widths else None}


def egress_audit(egress: list[dict], rows: list[dict], held: set[int]) -> dict:
    by_way = {r["osm_way_id"]: r for r in rows}
    out = {"agree": 0, "contradict": 0, "unknown": 0, "items": []}
    for e in egress:
        if e["way_id"] not in held:
            continue
        r = by_way[e["way_id"]]
        way = build_graph(r["lat"], r["lon"]).ways.get(e["way_id"])
        obs, verdict = e["observation"], "unknown"
        if way is not None and obs in ("oneway_forward", "oneway_backward", "two_way"):
            expected = {"oneway_forward": 1, "oneway_backward": -1, "two_way": 0}[obs]
            verdict = "agree" if way.oneway == expected else "contradict"
        # The planner never claims a verified turn or a verified sign, so those observations can only expose
        # unknowns, not contradict a claim.
        out[verdict] += 1
        out["items"].append({"way_id": e["way_id"], "observation": obs, "verdict": verdict})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--measurements", type=Path, required=True)
    ap.add_argument("--egress", type=Path)
    ap.add_argument("--split", type=Path)
    ap.add_argument("--make-split", type=Path)
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()
    try:
        rows = load_measurements(a.measurements)
        if a.make_split:
            split = make_split(rows, a.make_split, a.seed)
            print(f"frozen split: {len(split['heldout']['way_ids'])} held-out, "
                  f"{len(split['calibration']['way_ids'])} calibration → {a.make_split}")
            return 0
        if len(rows) < MIN_ROWS:
            raise Invalid(f"need ≥{MIN_ROWS} measured segments, have {len(rows)}: collect more, do not lower the gate")
        if not a.split or not a.split.exists():
            raise Invalid("a frozen --split is required (create it once with --make-split)")
        split = json.loads(a.split.read_text(encoding="utf-8"))
        check_split(rows, split)
        held = set(split["heldout"]["way_ids"])
        held_names = {_norm_alley(r["alley_name"]) for r in rows if r["osm_way_id"] in held}
        all_names = {_norm_alley(r["alley_name"]) for r in rows}
        egress = load_egress(a.egress, {r["osm_way_id"] for r in rows})
        model_only = EvidenceStore.evaluation_snapshot(
            exclude_measured_way_ids={r["osm_way_id"] for r in rows}, exclude_normalized_names=all_names,
            field_file=a.measurements)
        informed = EvidenceStore.evaluation_snapshot(
            exclude_measured_way_ids=held, exclude_normalized_names=held_names, field_file=a.measurements)
        report = {
            "generated_at": datetime.now(VN).isoformat(timespec="seconds"),
            "measurements": str(a.measurements), "split_frozen_at": split["frozen_at"],
            "rows": len(rows), "heldout": len(held),
            "model_only": score(rows, held, model_only, held_names),
            "field_informed": score(rows, held, informed, held_names),
            "egress": egress_audit(egress, rows, held),
        }
        mo = report["model_only"]["vehicles"]
        report["gate"] = {
            "zero_definite_false_fits": all(v["definite_false_fits"] == 0 for v in mo.values()),
            "no_wrong_way_contradiction": report["egress"]["contradict"] == 0,
            "shows_value": any(v["abstained"] < v["n"] for v in mo.values()),
        }
        report["gate"]["passed"] = all(report["gate"].values())
    except Invalid as exc:
        print(f"eval_field: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"rows": report["rows"], "heldout": report["heldout"], "gate": report["gate"],
                      "false_fits": {k: v["definite_false_fits"] for k, v in mo.items()},
                      "abstained": {k: f"{v['abstained']}/{v['n']}" for k, v in mo.items()}}, ensure_ascii=False))
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
