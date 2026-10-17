"""Field validation (R-11): score width and direction against real field observations.

The team measures; this script never invents, fills, or repairs a label. It refuses to score fewer than MIN_ROWS
usable measured segments or MIN_GROUPS independent normalized alley chains.

Initial split (balanced and immutable):
    python3 pipelines/eval_field.py --measurements data/field/measurements.csv \
      --make-split data/field/eval-split-v1.json

Append-only split extension (new file; the parent is never overwritten):
    python3 pipelines/eval_field.py --measurements data/field/measurements-v2.csv \
      --extend-split data/field/eval-split-v1.json --make-split data/field/eval-split-v2.json

Score:
    python3 pipelines/eval_field.py --measurements data/field/measurements.csv \
      --egress data/field/egress.csv --split data/field/eval-split-v1.json --output <report>.json

Model-only excludes every measured row before evidence indexing. Field-informed admits calibration rows but excludes
held-out ways and aliases. Only held-out rows are scored. Width truth is an uncertainty interval. Direction is the
only comparable egress dimension; turn-space and sign observations are reported as unscored/not_comparable and are
never presented as verified legal or turning claims.

Exit codes: 0 = scored gate passed or split created; 1 = scored gate failed; 2 = invalid/insufficient input; 3 = evaluation/report infrastructure failure.
"""
from __future__ import annotations

import argparse
import csv
import io
import hashlib
import json
import math
import random
import re
import os
import tempfile
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter, process_time
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evidence import EvidenceStore, OPEN_HI, _norm_alley, width_ranges  # noqa: E402
from app.storage import write_json  # noqa: E402
from app.osm import build_graph  # noqa: E402
from app.plan import compute_fit  # noqa: E402
from app.vehicles import get_profile  # noqa: E402

VN = timezone(timedelta(hours=7))
MIN_ROWS = 20
MIN_GROUPS = 20
MIN_HELD_ROWS = MIN_ROWS // 2
MIN_HELD_GROUPS = MIN_GROUPS // 2
VEHICLES = ("toyota-vios", "toyota-fortuner", "vinfast-vf-5")
MEASUREMENT_COLUMNS = (
    "osm_way_id", "alley_name", "lat", "lon", "width_m", "uncertainty_m", "bottleneck_at_m",
    "obstruction", "date", "measured_by", "note", "photo_url", "cut_count", "start_covered",
    "end_covered", "max_spacing_m", "truncated", "complete", "width_basis",
)
EGRESS_COLUMNS = ("way_id", "dimension", "observation", "observed_at", "observer", "provenance", "photo_url")
EGRESS_DIMENSIONS = ("direction", "turn_space", "sign")
EGRESS_OBSERVATIONS = {
    "direction": frozenset(("oneway_forward", "oneway_backward", "two_way", "unknown")),
    "turn_space": frozenset(("turn_space", "no_turn_space", "unknown")),
    "sign": frozenset(("sign_no_stopping", "sign_no_parking", "no_sign", "unknown")),
}


class Invalid(Exception):
    pass


def _finite(value: object, name: str, row: int, *, prefix: str = "row") -> float:
    try:
        x = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise Invalid(f"{prefix} {row}: {name} is not a number ({value!r})")
    if not math.isfinite(x):
        raise Invalid(f"{prefix} {row}: {name} is not finite")
    return x


def _text(value: object, name: str, row: int, *, prefix: str = "row") -> str:
    text = str(value or "").strip()
    if not text:
        raise Invalid(f"{prefix} {row}: {name} is required")
    return text


def _positive_int(value: object, name: str, row: int, *, prefix: str = "row") -> int:
    text = str(value or "").strip()
    if not re.fullmatch(r"[1-9]\d*", text):
        raise Invalid(f"{prefix} {row}: {name} must be a positive integer")
    return int(text)


def _boolean(value: object, name: str, row: int) -> bool:
    text = str(value or "").strip().lower()
    if text not in ("true", "false"):
        raise Invalid(f"row {row}: {name} must be true or false")
    return text == "true"


def _iso_date(value: object, name: str, row: int) -> str:
    text = _text(value, name, row)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise Invalid(f"row {row}: {name} must be an ISO date (YYYY-MM-DD)")
    return text


def _observed_at(value: object, row: int) -> str:
    text = _text(value, "observed_at", row, prefix="egress row")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise Invalid(f"egress row {row}: observed_at must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Invalid(f"egress row {row}: observed_at must include a timezone offset")
    return text


def _stable_photo_url(value: object, row: int, *, prefix: str = "row") -> str:
    text = _text(value, "photo_url", row, prefix=prefix)
    try:
        parsed = urlparse(text)
        hostname = parsed.hostname
    except ValueError:
        raise Invalid(f"{prefix} {row}: photo_url is not a valid URL")
    if (
        parsed.scheme != "https" or not hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment
    ):
        raise Invalid(
            f"{prefix} {row}: photo_url must be a stable HTTPS URL without credentials, "
            "query parameters, or a fragment"
        )
    decoded = unquote(text)
    has_email = bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", decoded))
    has_phone = bool(re.search(r"(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)", decoded))
    has_secret_path = bool(re.search(
        r"(?i)(?:^|[/_.-])(?:token|secret|password|api[-_]?key|access[-_]?key)(?:[/_.=-]|$)",
        parsed.path,
    ))
    if has_email or has_phone or has_secret_path:
        raise Invalid(f"{prefix} {row}: photo_url must not contain PII or credentials")
    return text


def _check_header(fieldnames: list[str] | None, required: tuple[str, ...], path: Path) -> None:
    fields = fieldnames or []
    if any(not isinstance(name, str) or not name.strip() for name in fields):
        raise Invalid(f"{path.name}: CSV header contains an empty column name")
    duplicates = sorted({name for name in fields if fields.count(name) > 1})
    if duplicates:
        raise Invalid(f"{path.name}: duplicate columns {duplicates}")
    missing = [name for name in required if name not in fields]
    if missing:
        raise Invalid(f"{path.name}: missing columns {missing}")


def _read_utf8(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError:
        raise Invalid(f"{description} {path}: input is not valid UTF-8")
    except OSError as exc:
        raise Invalid(f"cannot read {description} {path}: {exc}")

def group_key(alley_name: str) -> str:
    """Alias group of an alley: the main alley of its chain ("Hẻm 123/45 X" and "Hẻm 123 X" are one group)."""
    s = _norm_alley(alley_name)
    return re.sub(r"\b(\d+)(/\d+)+\b", r"\1", s)


def load_measurements(path: Path) -> list[dict]:
    rows, problems, seen = [], [], set()
    text = _read_utf8(path, "measurements")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    _check_header(reader.fieldnames, MEASUREMENT_COLUMNS, path)
    for i, raw in enumerate(reader, start=2):
        try:
            if None in raw:
                raise Invalid(f"row {i}: has more values than the CSV header")
            r = {name: str(raw.get(name) or "").strip() for name in MEASUREMENT_COLUMNS}
            way_id = _positive_int(r["osm_way_id"], "osm_way_id", i)
            if way_id in seen:
                raise Invalid(f"row {i}: duplicate osm_way_id {way_id}")
            alley_name = _text(r["alley_name"], "alley_name", i)
            group = group_key(alley_name)
            if not group:
                raise Invalid(f"row {i}: alley_name has no usable normalized alley-chain group")
            lat = _finite(r["lat"], "lat", i)
            lon = _finite(r["lon"], "lon", i)
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise Invalid(f"row {i}: lat/lon are outside valid coordinate ranges")
            width = _finite(r["width_m"], "width_m", i)
            unc = _finite(r["uncertainty_m"], "uncertainty_m", i)
            if width <= 0 or unc <= 0 or unc >= width:
                raise Invalid(
                    f"row {i}: width_m must be > 0 and 0 < uncertainty_m < width_m "
                    "(no perfect or non-physical measurement)"
                )
            bottleneck = _finite(r["bottleneck_at_m"], "bottleneck_at_m", i)
            if bottleneck < 0:
                raise Invalid(f"row {i}: bottleneck_at_m must be >= 0")
            obstruction = _text(r["obstruction"], "obstruction", i)
            measured_on = _iso_date(r["date"], "date", i)
            measured_by = _text(r["measured_by"], "measured_by", i)
            photo_url = _stable_photo_url(r["photo_url"], i)
            cut_count = _positive_int(r["cut_count"], "cut_count", i)
            start_covered = _boolean(r["start_covered"], "start_covered", i)
            end_covered = _boolean(r["end_covered"], "end_covered", i)
            max_spacing = _finite(r["max_spacing_m"], "max_spacing_m", i)
            truncated = _boolean(r["truncated"], "truncated", i)
            complete = _boolean(r["complete"], "complete", i)
            if cut_count < 2:
                raise Invalid(f"row {i}: cut_count must be >= 2 to cover both segment endpoints")
            if max_spacing <= 0 or max_spacing > 5.1:
                raise Invalid(f"row {i}: max_spacing_m must be > 0 and <= 5.1")
            if not start_covered or not end_covered or truncated or not complete:
                raise Invalid(
                    f"row {i}: coverage must include both endpoints, be untruncated, and be marked complete"
                )
            if r["width_basis"] != "measured_clear_width":
                raise Invalid(f"row {i}: width_basis must be measured_clear_width")
            rows.append({
                **r,
                "osm_way_id": way_id,
                "alley_name": alley_name,
                "lat": lat,
                "lon": lon,
                "width_m": width,
                "uncertainty_m": unc,
                "bottleneck_at_m": bottleneck,
                "obstruction": obstruction,
                "date": measured_on,
                "measured_by": measured_by,
                "photo_url": photo_url,
                "cut_count": cut_count,
                "start_covered": start_covered,
                "end_covered": end_covered,
                "max_spacing_m": max_spacing,
                "truncated": truncated,
                "complete": complete,
                "group": group,
            })
            seen.add(way_id)
        except Invalid as exc:
            problems.append(str(exc))
    if problems:
        raise Invalid("invalid measurements:\n  " + "\n  ".join(problems))
    return rows


def load_egress(path: Path | None, way_ids: set[int]) -> list[dict]:
    if path is None:
        raise Invalid("a structured --egress CSV is required")
    text = _read_utf8(path, "egress observations")
    out, problems = [], []
    seen: dict[tuple[int, str], str] = {}
    reader = csv.DictReader(io.StringIO(text, newline=""))
    _check_header(reader.fieldnames, EGRESS_COLUMNS, path)
    for i, raw in enumerate(reader, start=2):
        try:
            if None in raw:
                raise Invalid(f"egress row {i}: has more values than the CSV header")
            r = {name: str(raw.get(name) or "").strip() for name in EGRESS_COLUMNS}
            way_id = _positive_int(r["way_id"], "way_id", i, prefix="egress row")
            if way_id not in way_ids:
                raise Invalid(f"egress row {i}: way_id must be a measured way")
            dimension = _text(r["dimension"], "dimension", i, prefix="egress row")
            if dimension not in EGRESS_DIMENSIONS:
                raise Invalid(f"egress row {i}: dimension must be one of {list(EGRESS_DIMENSIONS)}")
            observation = _text(r["observation"], "observation", i, prefix="egress row")
            if observation not in EGRESS_OBSERVATIONS[dimension]:
                raise Invalid(
                    f"egress row {i}: observation {observation!r} is invalid for {dimension}; "
                    f"expected one of {sorted(EGRESS_OBSERVATIONS[dimension])}"
                )
            key = (way_id, dimension)
            previous = seen.get(key)
            if previous is not None:
                kind = "duplicate" if previous == observation else "conflicting"
                raise Invalid(
                    f"egress row {i}: {kind} {dimension} observations {previous!r} and "
                    f"{observation!r} for way {way_id}; exactly one row per dimension is allowed"
                )
            observed_at = _observed_at(r["observed_at"], i)
            observer = _text(r["observer"], "observer", i, prefix="egress row")
            provenance = _text(r["provenance"], "provenance", i, prefix="egress row")
            photo_url = _stable_photo_url(r["photo_url"], i, prefix="egress row")
            out.append({
                **r,
                "way_id": way_id,
                "dimension": dimension,
                "observation": observation,
                "observed_at": observed_at,
                "observer": observer,
                "provenance": provenance,
                "photo_url": photo_url,
            })
            seen[key] = observation
        except Invalid as exc:
            problems.append(str(exc))
    if not out:
        problems.append(f"{path.name}: at least one explicit egress observation is required")
    if problems:
        raise Invalid("invalid egress observations:\n  " + "\n  ".join(problems))
    return out


def _validate_dataset_size(rows: list[dict]) -> dict[str, list[dict]]:
    if len(rows) < MIN_ROWS:
        raise Invalid(f"need ≥{MIN_ROWS} measured segments, have {len(rows)}: collect more, do not lower the gate")
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["group"], []).append(row)
    if len(grouped) < MIN_GROUPS:
        raise Invalid(
            f"need ≥{MIN_GROUPS} independent normalized alley-chain groups, have {len(grouped)}: "
            "collect more groups; aliases cannot be treated as independent"
        )
    return grouped


def dataset_fingerprint(rows: list[dict]) -> str:
    canonical = [
        {name: row[name] for name in (*MEASUREMENT_COLUMNS, "group")}
        for row in sorted(rows, key=lambda item: item["osm_way_id"])
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _approximately_half(left: int, right: int) -> bool:
    total = left + right
    return total > 0 and min(left, right) / total >= 0.4


def _balanced_groups(grouped: dict[str, list[dict]], seed: int) -> tuple[list[str], list[str]]:
    groups = list(grouped)
    random.Random(seed).shuffle(groups)
    groups.sort(key=lambda group: len(grouped[group]), reverse=True)
    held_target = len(groups) // 2
    cal_target = len(groups) - held_target
    held: list[str] = []
    calibration: list[str] = []
    held_rows = calibration_rows = 0
    for group in groups:
        size = len(grouped[group])
        if len(held) >= held_target:
            calibration.append(group)
            calibration_rows += size
        elif len(calibration) >= cal_target:
            held.append(group)
            held_rows += size
        elif held_rows <= calibration_rows:
            held.append(group)
            held_rows += size
        else:
            calibration.append(group)
            calibration_rows += size
    if not _approximately_half(held_rows, calibration_rows):
        raise Invalid(
            f"alley groups cannot produce an approximately half split "
            f"({held_rows} held-out/{calibration_rows} calibration rows); collect more independent groups"
        )
    return held, calibration


def split_fingerprint(split: dict) -> str:
    payload = json.dumps(split, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_split(split: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(split, stream, ensure_ascii=False, indent=1)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise Invalid(f"{path} already exists: a frozen split is never overwritten") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def _print_success_line(text: str, result_code: int) -> int:
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            null_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null_fd, sys.stdout.fileno())
            finally:
                os.close(null_fd)
        except (AttributeError, OSError, ValueError):
            try:
                sys.stdout.close()
            except Exception:
                pass
    return result_code


def make_split(rows: list[dict], path: Path, seed: int) -> dict:
    if path.exists():
        raise Invalid(f"{path} already exists: a split is frozen once and never regenerated")
    grouped = _validate_dataset_size(rows)
    held, calibration = _balanced_groups(grouped, seed)
    split = {
        "format_version": 1,
        "generation": 1,
        "frozen_at": datetime.now(VN).isoformat(timespec="seconds"),
        "seed": seed,
        "measurements_sha256": dataset_fingerprint(rows),
        "heldout": {
            "groups": sorted(held),
            "way_ids": sorted(row["osm_way_id"] for group in held for row in grouped[group]),
        },
        "calibration": {
            "groups": sorted(calibration),
            "way_ids": sorted(row["osm_way_id"] for group in calibration for row in grouped[group]),
        },
    }
    check_split(rows, split)
    _write_split(split, path)
    return split


def _split_members(split: dict, side: str) -> tuple[list[int], list[str]]:
    value = split.get(side)
    if not isinstance(value, dict):
        raise Invalid(f"split {side} must be an object")
    way_ids = value.get("way_ids")
    groups = value.get("groups")
    if not isinstance(way_ids, list) or any(type(way_id) is not int or way_id <= 0 for way_id in way_ids):
        raise Invalid(f"split {side}.way_ids must be a list of positive integers")
    if not isinstance(groups, list) or any(not isinstance(group, str) or not group for group in groups):
        raise Invalid(f"split {side}.groups must be a list of nonempty strings")
    if len(way_ids) != len(set(way_ids)):
        raise Invalid(f"split {side}.way_ids contains duplicates")
    if len(groups) != len(set(groups)):
        raise Invalid(f"split {side}.groups contains duplicates")
    return way_ids, groups


def _split_generation(split: dict) -> int:
    if not isinstance(split, dict):
        raise Invalid("frozen split must be a JSON object")
    version = split.get("format_version")
    if version not in (1, 2):
        raise Invalid("split format_version must be 1 (initial) or 2 (append-only extension)")
    generation = split.get("generation", 1 if version == 1 else None)
    if type(generation) is not int or generation < 1:
        raise Invalid("split generation must be a positive integer")
    if version == 1 and generation != 1:
        raise Invalid("initial split generation must be 1")
    if version == 2:
        if generation < 2:
            raise Invalid("extended split generation must be at least 2")
        parent_generation = split.get("parent_generation")
        if type(parent_generation) is not int or parent_generation != generation - 1:
            raise Invalid("extended split parent_generation must immediately precede generation")
        for field in ("parent_split_sha256", "parent_measurements_sha256"):
            value = split.get(field)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise Invalid(f"extended split {field} must be a SHA-256 fingerprint")
    return generation


def check_split(rows: list[dict], split: dict) -> None:
    grouped = _validate_dataset_size(rows)
    generation = _split_generation(split)
    if type(split.get("seed")) is not int:
        raise Invalid("split seed must be an integer")
    frozen_at = split.get("frozen_at")
    try:
        frozen = datetime.fromisoformat(frozen_at)
    except (TypeError, ValueError):
        raise Invalid("split frozen_at must be an ISO-8601 timestamp")
    if frozen.tzinfo is None or frozen.utcoffset() is None:
        raise Invalid("split frozen_at must include a timezone offset")
    fingerprint = split.get("measurements_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise Invalid("split measurements_sha256 must be a SHA-256 fingerprint")
    if fingerprint != dataset_fingerprint(rows):
        raise Invalid("measurements do not match the frozen split fingerprint; do not alter or re-freeze inspected data")

    held_ids, held_groups = _split_members(split, "heldout")
    cal_ids, cal_groups = _split_members(split, "calibration")
    held, cal = set(held_ids), set(cal_ids)
    hg, cg = set(held_groups), set(cal_groups)
    if held & cal:
        raise Invalid(f"split leaks way ids across sides: {sorted(held & cal)[:5]}")
    if hg & cg:
        raise Invalid(f"split leaks alley groups across sides: {sorted(hg & cg)[:5]}")

    all_way_ids = {row["osm_way_id"] for row in rows}
    all_groups = set(grouped)
    if held | cal != all_way_ids:
        missing = sorted(all_way_ids - (held | cal))
        added = sorted((held | cal) - all_way_ids)
        raise Invalid(f"split way membership differs from measurements (missing={missing[:5]}, added={added[:5]})")
    if hg | cg != all_groups:
        missing = sorted(all_groups - (hg | cg))
        added = sorted((hg | cg) - all_groups)
        raise Invalid(f"split group membership differs from measurements (missing={missing[:5]}, added={added[:5]})")
    if len(hg) < MIN_HELD_GROUPS or len(held) < MIN_HELD_ROWS:
        raise Invalid(
            f"frozen split held-out side must retain ≥{MIN_HELD_GROUPS} independent groups and "
            f"≥{MIN_HELD_ROWS} ways; have {len(hg)} groups/{len(held)} ways"
        )
    if len(cg) < MIN_HELD_GROUPS or len(cal) < MIN_HELD_ROWS:
        raise Invalid(
            f"frozen split calibration side must retain ≥{MIN_HELD_GROUPS} independent groups and "
            f"≥{MIN_HELD_ROWS} ways; have {len(cg)} groups/{len(cal)} ways"
        )
    if generation == 1 and (abs(len(hg) - len(cg)) > 1 or not _approximately_half(len(held), len(cal))):
        raise Invalid(
            f"initial split is not approximately half by groups and rows "
            f"({len(hg)}/{len(cg)} groups, {len(held)}/{len(cal)} rows)"
        )
    expected_held_groups = {row["group"] for row in rows if row["osm_way_id"] in held}
    expected_cal_groups = {row["group"] for row in rows if row["osm_way_id"] in cal}
    if expected_held_groups != hg or expected_cal_groups != cg:
        raise Invalid("split groups do not exactly match the row memberships on each side")


def extend_split(
    rows: list[dict],
    parent: dict,
    path: Path,
    *,
    parent_path: Path | None = None,
) -> dict:
    if path.exists():
        raise Invalid(f"{path} already exists: write an extension to a new versioned split filename")
    if parent_path is not None and path.resolve() == parent_path.resolve():
        raise Invalid("the child split path must differ from the immutable parent split path")
    _validate_dataset_size(rows)
    parent_generation = _split_generation(parent)
    parent_held_ids, parent_held_groups = _split_members(parent, "heldout")
    parent_cal_ids, parent_cal_groups = _split_members(parent, "calibration")
    parent_ids = set(parent_held_ids) | set(parent_cal_ids)
    current_by_id = {row["osm_way_id"]: row for row in rows}
    removed = sorted(parent_ids - set(current_by_id))
    if removed:
        raise Invalid(f"cannot extend split: parent measurement rows were removed: {removed[:5]}")
    parent_rows = [current_by_id[way_id] for way_id in sorted(parent_ids)]
    try:
        check_split(parent_rows, parent)
    except Invalid as exc:
        raise Invalid(f"cannot extend malformed or altered parent split: {exc}")
    new_ids = set(current_by_id) - parent_ids
    if not new_ids:
        raise Invalid("cannot extend split without appended measurement rows")

    held_groups = set(parent_held_groups)
    calibration_groups = set(parent_cal_groups)
    held_ids = set(parent_held_ids)
    calibration_ids = set(parent_cal_ids)
    for way_id in sorted(new_ids):
        group = current_by_id[way_id]["group"]
        if group in held_groups:
            held_ids.add(way_id)
        else:
            calibration_groups.add(group)
            calibration_ids.add(way_id)
    split = {
        "format_version": 2,
        "generation": parent_generation + 1,
        "parent_generation": parent_generation,
        "parent_split_sha256": split_fingerprint(parent),
        "parent_measurements_sha256": parent["measurements_sha256"],
        "frozen_at": datetime.now(VN).isoformat(timespec="seconds"),
        "seed": parent["seed"],
        "measurements_sha256": dataset_fingerprint(rows),
        "heldout": {"groups": sorted(held_groups), "way_ids": sorted(held_ids)},
        "calibration": {"groups": sorted(calibration_groups), "way_ids": sorted(calibration_ids)},
    }
    check_split(rows, split)
    _write_split(split, path)
    return split


def load_split(path: Path | None) -> dict:
    if path is None:
        raise Invalid("a frozen --split is required (create it once with --make-split)")
    text = _read_utf8(path, "frozen split")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Invalid(f"frozen split is not valid JSON: {exc}")
    if not isinstance(value, dict):
        raise Invalid("frozen split must be a JSON object")
    return value


def truth_class(w: float, u: float, need_fit: float, need_tight: float) -> str:
    lo, hi = w - u, w + u
    if hi < need_tight:
        return "no"
    if lo >= need_fit:
        return "fits"
    if lo >= need_tight and hi < need_fit:
        return "tight"
    return "indeterminate"


def definite_false_fit(predicted: str, truth_hi: float, need_fit: float, need_tight: float) -> bool:
    if predicted == "fits":
        return truth_hi < need_fit
    if predicted == "tight":
        return truth_hi < need_tight
    return False


def _width_metrics(items: list[dict]) -> dict:
    denominator = len(items)
    informative = [item for item in items if not item["open_ended"]]
    informative_denominator = len(informative)
    overlap_count = sum(item["overlaps_truth"] is True for item in informative)
    covered_count = sum(item["covers_truth_interval"] is True for item in informative)
    gaps = [item["interval_gap_m"] for item in informative]
    return {
        "denominator": denominator,
        "informative_denominator": informative_denominator,
        "open_ended_count": denominator - informative_denominator,
        "overlap_count": overlap_count,
        "overlap_rate": round(overlap_count / informative_denominator, 3) if informative_denominator else None,
        "truth_interval_covered_count": covered_count,
        "truth_interval_coverage_rate": (
            round(covered_count / informative_denominator, 3) if informative_denominator else None
        ),
        "mean_interval_gap_m": round(sum(gaps) / informative_denominator, 3) if informative_denominator else None,
        "max_interval_gap_m": round(max(gaps), 3) if informative_denominator else None,
    }


def score(
    rows: list[dict],
    held: set[int],
    store: EvidenceStore,
    forbidden_way_ids: set[int],
    forbidden_names: set[str],
) -> dict:
    measured = lambda bounds: any(bound.tier == "Measured" for bound in bounds)  # noqa: E731
    leaked = (
        [way_id for way_id in forbidden_way_ids if measured(store.by_way.get(way_id, []))]
        + [name for name in forbidden_names if measured(store.by_name.get(name, []))]
    )
    if leaked:
        raise Invalid(f"measured labels leak into the evaluation evidence index: {leaked[:5]}")

    view = store.view()
    held_rows = [row for row in rows if row["osm_way_id"] in held]
    contexts: dict[int, tuple[object, dict] | str] = {}
    widths = []
    for row in held_rows:
        way_id = row["osm_way_id"]
        graph = build_graph(row["lat"], row["lon"])
        if way_id not in graph.ways:
            contexts[way_id] = "way not in the area graph at lat/lon"
            continue
        ranges = width_ranges(graph, view)
        if way_id not in ranges:
            contexts[way_id] = "way has no predicted width range"
            continue
        contexts[way_id] = (graph, ranges)
        width_range = ranges[way_id]
        truth_lo = row["width_m"] - row["uncertainty_m"]
        truth_hi = row["width_m"] + row["uncertainty_m"]
        open_ended = width_range.hi >= OPEN_HI
        overlaps = None if open_ended else width_range.lo <= truth_hi and truth_lo <= width_range.hi
        covers = None if open_ended else width_range.lo <= truth_lo and width_range.hi >= truth_hi
        gap = None if open_ended else max(width_range.lo - truth_hi, truth_lo - width_range.hi, 0.0)
        widths.append({
            "way_id": way_id,
            "predicted_interval_m": {
                "lo": round(width_range.lo, 3),
                "hi": None if open_ended else round(width_range.hi, 3),
                "open_ended": open_ended,
            },
            "truth_interval_m": {"lo": round(truth_lo, 3), "hi": round(truth_hi, 3)},
            "measured_width_m": row["width_m"],
            "uncertainty_m": row["uncertainty_m"],
            "open_ended": open_ended,
            "interval_gap_m": None if gap is None else round(gap, 3),
            "overlaps_truth": overlaps,
            "covers_truth_interval": covers,
            "basis": width_range.width_basis,
            "decisive": width_range.decisive_clearance,
        })

    per_vehicle = {}
    for vehicle_id in VEHICLES:
        profile = get_profile(vehicle_id)
        cells: dict[str, dict[str, int]] = {}
        false_fit_count, items = 0, []
        for row in held_rows:
            way_id = row["osm_way_id"]
            context = contexts[way_id]
            if isinstance(context, str):
                items.append({"way_id": way_id, "error": context})
                continue
            graph, ranges = context
            fit, _ = compute_fit(graph, ranges, profile)
            predicted = fit.get(way_id)
            if predicted not in ("fits", "tight", "no", "unknown"):
                raise Invalid(f"way {way_id}: planner returned invalid fit class {predicted!r}")
            truth = truth_class(
                row["width_m"], row["uncertainty_m"], profile.fits_min, profile.tight_min
            )
            cells.setdefault(predicted, {}).setdefault(truth, 0)
            cells[predicted][truth] += 1
            truth_hi = row["width_m"] + row["uncertainty_m"]
            false_fit = definite_false_fit(predicted, truth_hi, profile.fits_min, profile.tight_min)
            false_fit_count += int(false_fit)
            items.append({
                "way_id": way_id,
                "predicted": predicted,
                "truth": truth,
                "truth_interval_hi_m": round(truth_hi, 3),
                "claim_threshold_m": (
                    round(profile.fits_min, 3) if predicted == "fits"
                    else round(profile.tight_min, 3) if predicted == "tight"
                    else None
                ),
                "false_fit": false_fit,
            })
        scored = [item for item in items if "predicted" in item]
        per_vehicle[vehicle_id] = {
            "n": len(scored),
            "confusion_denominator": len(scored),
            "confusion": cells,
            "definite_false_fits": false_fit_count,
            "abstained": sum(item["predicted"] == "unknown" for item in scored),
            "items": items,
        }
    metrics = _width_metrics(widths)
    return {
        "vehicles": per_vehicle,
        "widths": widths,
        "width_interval_metrics": metrics,
    }


def egress_audit(egress: list[dict], rows: list[dict], held: set[int]) -> dict:
    by_way = {row["osm_way_id"]: row for row in rows}
    dimension_counts = {
        dimension: {
            "expected": len(held),
            "observations": 0,
            "known": 0,
            "unknown": 0,
            "agree": 0,
            "contradict": 0,
            "unscored": 0,
            "blocking_observations": 0,
        }
        for dimension in EGRESS_DIMENSIONS
    }
    out = {
        "agree": 0,
        "contradict": 0,
        "unknown": 0,
        "comparison_unknown": 0,
        "unscored": 0,
        "blocking_observations": 0,
        "dimension_counts": dimension_counts,
        "items": [],
    }
    observed_slots: set[tuple[int, str]] = set()
    direction_ways = {}
    for entry in egress:
        way_id = entry["way_id"]
        if way_id not in held:
            continue
        dimension = entry["dimension"]
        observation = entry["observation"]
        observed_slots.add((way_id, dimension))
        counts = dimension_counts[dimension]
        counts["observations"] += 1
        field_unknown = observation == "unknown"
        counts["unknown" if field_unknown else "known"] += 1
        out["unknown"] += int(field_unknown)
        blocking = observation in ("no_turn_space", "sign_no_stopping", "sign_no_parking")
        counts["blocking_observations"] += int(blocking)
        out["blocking_observations"] += int(blocking)

        if dimension != "direction":
            verdict = "unscored"
            comparability = "not_comparable"
            reason = "not_comparable: this evaluator has no corresponding model turn-space or legal-sign claim"
            counts["unscored"] += 1
            out["unscored"] += 1
        elif field_unknown:
            verdict = "unknown"
            comparability = "not_comparable"
            reason = "field direction is explicitly unknown"
        else:
            if way_id not in direction_ways:
                row = by_way[way_id]
                direction_ways[way_id] = build_graph(row["lat"], row["lon"]).ways.get(way_id)
            way = direction_ways[way_id]
            if way is None:
                verdict = "unknown"
                comparability = "not_comparable"
                reason = "measured way is absent from the local graph"
                out["comparison_unknown"] += 1
            else:
                expected = {"oneway_forward": 1, "oneway_backward": -1, "two_way": 0}[observation]
                verdict = "agree" if way.oneway == expected else "contradict"
                comparability = "comparable"
                reason = "compared with the OSM direction used by route entry/exit"
                counts[verdict] += 1
                out[verdict] += 1
        out["items"].append({
            "way_id": way_id,
            "dimension": dimension,
            "observation": observation,
            "verdict": verdict,
            "comparability": comparability,
            "reason": reason,
            "field_unknown": field_unknown,
            "blocking_observation": blocking,
            "observed_at": entry["observed_at"],
            "observer": entry["observer"],
            "provenance": entry["provenance"],
            "photo_url": entry["photo_url"],
        })

    missing_dimensions = []
    fully_covered = set()
    for way_id in sorted(held):
        missing = [dimension for dimension in EGRESS_DIMENSIONS if (way_id, dimension) not in observed_slots]
        if missing:
            missing_dimensions.append({"way_id": way_id, "dimensions": missing})
        else:
            fully_covered.add(way_id)
    expected_observations = len(held) * len(EGRESS_DIMENSIONS)
    out.update({
        "coverage_denominator": expected_observations,
        "observation_denominator": len(observed_slots),
        "covered_way_count": len(fully_covered),
        "any_covered_way_count": len({way_id for way_id, _ in observed_slots}),
        "coverage_rate": (
            round(len(observed_slots) / expected_observations, 3) if expected_observations else None
        ),
        "missing_way_ids": [item["way_id"] for item in missing_dimensions],
        "missing_dimensions": missing_dimensions,
        "unknown_way_ids": sorted({
            item["way_id"] for item in out["items"] if item["field_unknown"]
        }),
        "direction_comparison_count": (
            dimension_counts["direction"]["agree"] + dimension_counts["direction"]["contradict"]
        ),
    })
    return out


def release_gate(model_only: dict, field_informed: dict, egress: dict, held_count: int) -> dict:
    modes = (model_only, field_informed)
    vehicle_results = [vehicle for mode in modes for vehicle in mode["vehicles"].values()]
    expected_egress = held_count * len(EGRESS_DIMENSIONS)
    nonempty_denominators = (
        held_count > 0
        and bool(vehicle_results)
        and all(vehicle["confusion_denominator"] > 0 for vehicle in vehicle_results)
        and all(mode["width_interval_metrics"]["denominator"] > 0 for mode in modes)
        and egress["coverage_denominator"] == expected_egress
        and egress["observation_denominator"] > 0
    )
    complete_width_scoring = (
        held_count > 0
        and bool(vehicle_results)
        and all(vehicle["n"] == held_count for vehicle in vehicle_results)
        and all(mode["width_interval_metrics"]["denominator"] == held_count for mode in modes)
    )
    direction = egress["dimension_counts"]["direction"]
    gate = {
        "zero_definite_false_fits": bool(vehicle_results) and all(
            vehicle["definite_false_fits"] == 0 for vehicle in vehicle_results
        ),
        "no_direction_contradiction": egress["contradict"] == 0,
        "complete_egress_dimension_coverage": (
            egress["observation_denominator"] == expected_egress
            and egress["covered_way_count"] == held_count
            and not egress["missing_dimensions"]
        ),
        "known_direction_for_every_heldout_way": (
            direction["observations"] == held_count
            and direction["known"] == held_count
            and direction["unknown"] == 0
        ),
        "complete_direction_comparison": egress["direction_comparison_count"] == held_count,
        "nonempty_denominators": nonempty_denominators,
        "complete_width_scoring": complete_width_scoring,
        "shows_model_only_value": any(
            vehicle["n"] > 0 and vehicle["abstained"] < vehicle["n"]
            for vehicle in model_only["vehicles"].values()
        ),
        "unscored_turn_sign_observations": (
            egress["dimension_counts"]["turn_space"]["unscored"]
            + egress["dimension_counts"]["sign"]["unscored"]
        ),
        "descriptive_blocking_observations": egress["blocking_observations"],
    }
    criteria = (
        "zero_definite_false_fits",
        "no_direction_contradiction",
        "complete_egress_dimension_coverage",
        "known_direction_for_every_heldout_way",
        "complete_direction_comparison",
        "nonempty_denominators",
        "complete_width_scoring",
        "shows_model_only_value",
    )
    gate["passed"] = all(gate[name] for name in criteria)
    return gate




def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--measurements", type=Path, required=True, help="validated field measurements CSV")
    ap.add_argument("--egress", type=Path, help="dimensioned field egress observations CSV")
    ap.add_argument("--split", type=Path, help="frozen split to score")
    ap.add_argument(
        "--make-split",
        type=Path,
        help="new versioned split path; existing files are never overwritten",
    )
    ap.add_argument(
        "--extend-split",
        type=Path,
        metavar="PARENT_SPLIT",
        help="append-only parent split; requires --make-split with a different child filename",
    )
    ap.add_argument("--seed", type=int, default=20261012, help="initial split seed (extensions retain parent seed)")
    ap.add_argument("--output", type=Path, help="field evaluation report JSON path")
    a = ap.parse_args()
    evaluation_cpu_started = process_time()
    evaluation_wall_started = perf_counter()
    try:
        rows = load_measurements(a.measurements)
        if a.extend_split and not a.make_split:
            raise Invalid("--extend-split requires --make-split with a new versioned child filename")
        if a.make_split:
            if a.extend_split:
                parent = load_split(a.extend_split)
                split = extend_split(rows, parent, a.make_split, parent_path=a.extend_split)
                action = f"extended split generation {split['generation']}"
            else:
                split = make_split(rows, a.make_split, a.seed)
                action = "frozen initial split generation 1"
            return _print_success_line(
                f"{action}: {len(split['heldout']['way_ids'])} held-out, "
                f"{len(split['calibration']['way_ids'])} calibration → {a.make_split}",
                0,
            )
        _validate_dataset_size(rows)
        split = load_split(a.split)
        check_split(rows, split)
        held = set(split["heldout"]["way_ids"])
        all_way_ids = {row["osm_way_id"] for row in rows}
        held_names = {_norm_alley(row["alley_name"]) for row in rows if row["osm_way_id"] in held}
        all_names = {_norm_alley(row["alley_name"]) for row in rows}
        egress = load_egress(a.egress, all_way_ids)
        model_only_store = EvidenceStore.evaluation_snapshot(
            exclude_measured_way_ids=all_way_ids,
            exclude_normalized_names=all_names,
            field_file=a.measurements,
        )
        informed_store = EvidenceStore.evaluation_snapshot(
            exclude_measured_way_ids=held,
            exclude_normalized_names=held_names,
            field_file=a.measurements,
        )
        model_only = score(rows, held, model_only_store, all_way_ids, all_names)
        field_informed = score(rows, held, informed_store, held, held_names)
        audit = egress_audit(egress, rows, held)
        measurements_sha256 = dataset_fingerprint(rows)
        gate = release_gate(model_only, field_informed, audit, len(held))
        evaluation_cpu_seconds = process_time() - evaluation_cpu_started
        evaluation_wall_seconds = perf_counter() - evaluation_wall_started
        report = {
            "generated_at": datetime.now(VN).isoformat(timespec="seconds"),
            "measurements": str(a.measurements),
            "measurements_sha256": measurements_sha256,
            "split_frozen_at": split["frozen_at"],
            "split_generation": split.get("generation", 1),
            "rows": len(rows),
            "groups": len({row["group"] for row in rows}),
            "heldout": len(held),
            "split_coverage": {
                "heldout_rows": len(held),
                "heldout_groups": len(split["heldout"]["groups"]),
                "calibration_rows": len(rows) - len(held),
                "calibration_groups": len(split["calibration"]["groups"]),
                "heldout_row_share": round(len(held) / len(rows), 3) if rows else None,
            },
            "evaluation_scope": {
                "scored": ["physical_clear_width", "osm_direction"],
                "unscored": ["turn_space", "sign_and_legal_status"],
                "legal_and_turn_space_field_verified": False,
                "statement": (
                    "The release gate is limited to measurable width and OSM direction. "
                    "Turn-space and sign observations are descriptive/not_comparable and do not assert "
                    "legal or turning verification."
                ),
            },
            "latency": {
                "evaluation_command": {
                    "status": "measured",
                    "cpu_seconds": evaluation_cpu_seconds,
                    "wall_seconds": evaluation_wall_seconds,
                    "network_scope": (
                        "Local OSM graph cache is used when available; an Overpass fetch on cache miss is included "
                        "in wall_seconds but is not separated."
                    ),
                },
                "external_upstream": {
                    "status": "not_separately_instrumented",
                    "duration_seconds": None,
                },
                "background_jobs": {
                    "status": "not_scheduled_by_evaluator",
                    "duration_seconds": None,
                },
            },
            "model_only": model_only,
            "field_informed": field_informed,
            "egress": audit,
            "gate": gate,
        }
    except Invalid as exc:
        print(f"eval_field: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"eval_field: could not evaluate field data ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 3
    try:
        mo = report["model_only"]["vehicles"]
        summary = json.dumps({
            "rows": report["rows"],
            "heldout": report["heldout"],
            "scope": report["evaluation_scope"]["statement"],
            "gate": report["gate"],
            "false_fits": {key: value["definite_false_fits"] for key, value in mo.items()},
            "abstained": {key: f"{value['abstained']}/{value['n']}" for key, value in mo.items()},
        }, ensure_ascii=False)
        if a.output:
            write_json(a.output, report, indent=1)
    except Exception as exc:
        print(f"eval_field: could not write or serialize report ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 3
    return _print_success_line(summary, 0 if report["gate"]["passed"] else 1)


if __name__ == "__main__":
    sys.exit(main())
