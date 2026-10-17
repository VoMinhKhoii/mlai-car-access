"""Behavioral tests for the fail-closed field evaluator.

All measurement, egress, split, and report fixtures are synthetic test mechanics written only
inside TemporaryDirectory. They are not field evidence or acceptance results.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import eval_field as field  # noqa: E402
from app import evidence as evidence_module  # noqa: E402


def measurement(way_id: int, **overrides) -> dict[str, str]:
    row = {
        "osm_way_id": str(way_id),
        "alley_name": f"Hẻm {way_id} Test",
        "lat": "10.7800",
        "lon": "106.6900",
        "width_m": "3.0",
        "uncertainty_m": "0.1",
        "bottleneck_at_m": "8.0",
        "obstruction": "step",
        "date": "2026-10-01",
        "measured_by": "synthetic-test-operator",
        "note": "synthetic unit fixture",
        "photo_url": f"https://evidence.example.test/measurement-{way_id}.jpg",
        "cut_count": "4",
        "start_covered": "true",
        "end_covered": "true",
        "max_spacing_m": "5.0",
        "truncated": "false",
        "complete": "true",
        "width_basis": "measured_clear_width",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def egress(way_id: int, dimension: str, observation: str, **overrides) -> dict[str, str]:
    row = {
        "way_id": str(way_id),
        "dimension": dimension,
        "observation": observation,
        "observed_at": "2026-10-01T09:30:00+07:00",
        "observer": "synthetic-test-operator",
        "provenance": "synthetic test observation",
        "photo_url": f"https://evidence.example.test/egress-{way_id}-{dimension}.jpg",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def complete_egress(way_ids: list[int], *, turn: str = "turn_space", sign: str = "no_sign") -> list[dict[str, str]]:
    rows = []
    for way_id in way_ids:
        rows.extend([
            egress(way_id, "direction", "two_way"),
            egress(way_id, "turn_space", turn),
            egress(way_id, "sign", sign),
        ])
    return rows


def scored_mode(count: int, *, false_fits: int = 0, abstained: int = 0) -> dict:
    return {
        "vehicles": {
            "synthetic-car": {
                "n": count,
                "confusion_denominator": count,
                "definite_false_fits": false_fits,
                "abstained": abstained,
            }
        },
        "width_interval_metrics": {"denominator": count},
    }


class FieldFixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def write_csv(self, name: str, columns: tuple[str, ...], rows: list[dict[str, str]]) -> Path:
        path = self.root / name
        with open(path, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        return path

    def load_measurements(self, rows: list[dict[str, str]], name: str = "measurements.csv") -> list[dict]:
        return field.load_measurements(self.write_csv(name, field.MEASUREMENT_COLUMNS, rows))

    def load_egress(self, rows: list[dict[str, str]], way_ids: set[int], name: str = "egress.csv") -> list[dict]:
        return field.load_egress(self.write_csv(name, field.EGRESS_COLUMNS, rows), way_ids)


class MeasurementValidationTests(FieldFixtureTestCase):
    def test_requires_clear_width_basis_bottleneck_coverage_and_stable_photo(self) -> None:
        invalid_cases = {
            "missing-bottleneck": {"bottleneck_at_m": ""},
            "negative-bottleneck": {"bottleneck_at_m": "-0.1"},
            "missing-obstruction": {"obstruction": ""},
            "missing-photo": {"photo_url": ""},
            "non-https-photo": {"photo_url": "http://example.test/photo.jpg"},
            "credential-query": {"photo_url": "https://example.test/photo.jpg?token=secret"},
            "pii-email": {"photo_url": "https://example.test/person@example.com/photo.jpg"},
            "wrong-basis": {"width_basis": "road_width_estimate"},
            "no-start-coverage": {"start_covered": "false"},
            "no-end-coverage": {"end_covered": "false"},
            "truncated": {"truncated": "true"},
            "incomplete": {"complete": "false"},
            "sparse-cuts": {"max_spacing_m": "5.2"},
            "one-cut": {"cut_count": "1"},
            "perfect-uncertainty": {"uncertainty_m": "0"},
            "non-physical-interval": {"uncertainty_m": "3.0"},
        }
        for name, override in invalid_cases.items():
            with self.subTest(name=name):
                path = self.write_csv(f"{name}.csv", field.MEASUREMENT_COLUMNS, [measurement(1001, **override)])
                with self.assertRaises(field.Invalid):
                    field.load_measurements(path)

    def test_rejects_missing_column_duplicate_way_and_invalid_coordinates(self) -> None:
        columns = tuple(column for column in field.MEASUREMENT_COLUMNS if column != "obstruction")
        with self.assertRaisesRegex(field.Invalid, "missing columns"):
            field.load_measurements(self.write_csv("missing-column.csv", columns, [measurement(1001)]))

        duplicate = self.write_csv(
            "duplicate.csv", field.MEASUREMENT_COLUMNS, [measurement(1001), measurement(1001)]
        )
        with self.assertRaisesRegex(field.Invalid, "duplicate osm_way_id"):
            field.load_measurements(duplicate)

        coordinates = self.write_csv(
            "coordinates.csv", field.MEASUREMENT_COLUMNS, [measurement(1001, lat="91")]
        )
        with self.assertRaisesRegex(field.Invalid, "coordinate ranges"):
            field.load_measurements(coordinates)


class InputEncodingTests(FieldFixtureTestCase):
    def test_invalid_utf8_and_invalid_json_are_clear_invalid_refusals(self) -> None:
        invalid_csv = self.root / "invalid.csv"
        invalid_csv.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(field.Invalid, "not valid UTF-8"):
            field.load_measurements(invalid_csv)
        with self.assertRaisesRegex(field.Invalid, "not valid UTF-8"):
            field.load_egress(invalid_csv, {1001})

        invalid_split = self.root / "invalid-split.json"
        invalid_split.write_bytes(b"\xff")
        with self.assertRaisesRegex(field.Invalid, "not valid UTF-8"):
            field.load_split(invalid_split)

        malformed_split = self.root / "malformed-split.json"
        malformed_split.write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(field.Invalid, "not valid JSON"):
            field.load_split(malformed_split)

    def test_main_returns_refusal_without_traceback_for_invalid_utf8(self) -> None:
        invalid_csv = self.root / "invalid-measurements.csv"
        invalid_csv.write_bytes(b"\xff")
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["eval_field.py", "--measurements", str(invalid_csv)]), redirect_stderr(stderr):
            code = field.main()
        self.assertEqual(code, 2)
        self.assertIn("not valid UTF-8", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_returns_refusal_without_traceback_for_invalid_split_json(self) -> None:
        measurements_path = self.write_csv(
            "valid-measurements.csv",
            field.MEASUREMENT_COLUMNS,
            [measurement(8000 + index) for index in range(20)],
        )
        malformed_split = self.root / "malformed-split.json"
        malformed_split.write_text("{not-json", encoding="utf-8")
        stderr = io.StringIO()
        argv = [
            "eval_field.py",
            "--measurements", str(measurements_path),
            "--split", str(malformed_split),
        ]
        with patch.object(sys, "argv", argv), redirect_stderr(stderr):
            code = field.main()
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_main_distinguishes_scoring_infrastructure_failure_from_failed_gate(self) -> None:
        source_rows = [measurement(8200 + index) for index in range(20)]
        measurements_path = self.write_csv("runtime-measurements.csv", field.MEASUREMENT_COLUMNS, source_rows)
        rows = field.load_measurements(measurements_path)
        split_path = self.root / "runtime-split.json"
        field.make_split(rows, split_path, seed=53)
        egress_path = self.write_csv(
            "runtime-egress.csv",
            field.EGRESS_COLUMNS,
            complete_egress([row["osm_way_id"] for row in rows]),
        )
        report_path = self.root / "runtime-report.json"
        stderr = io.StringIO()
        argv = [
            "eval_field.py",
            "--measurements", str(measurements_path),
            "--egress", str(egress_path),
            "--split", str(split_path),
            "--output", str(report_path),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(field.EvidenceStore, "evaluation_snapshot", return_value=object()),
            patch.object(field, "score", side_effect=RuntimeError("Overpass unavailable")),
            redirect_stderr(stderr),
        ):
            result = field.main()

        self.assertEqual(result, 3)
        self.assertIn("could not evaluate field data (RuntimeError): Overpass unavailable", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse(report_path.exists())


class CliOutputTests(unittest.TestCase):
    def test_broken_pipe_does_not_override_success_or_gate_failure_codes(self) -> None:
        for result_code in (0, 1):
            with self.subTest(result_code=result_code):
                read_fd, write_fd = field.os.pipe()
                field.os.close(read_fd)
                stream = field.os.fdopen(write_fd, "w")
                try:
                    with redirect_stdout(stream):
                        self.assertEqual(field._print_success_line("one summary line", result_code), result_code)
                finally:
                    stream.close()


class EgressValidationTests(FieldFixtureTestCase):
    def test_requires_dimension_scoped_vocabulary_and_complete_provenance(self) -> None:
        with self.assertRaisesRegex(field.Invalid, "--egress"):
            field.load_egress(None, {1001})
        empty = self.write_csv("empty-egress.csv", field.EGRESS_COLUMNS, [])
        with self.assertRaisesRegex(field.Invalid, "at least one"):
            field.load_egress(empty, {1001})

        columns = tuple(column for column in field.EGRESS_COLUMNS if column != "dimension")
        with self.assertRaisesRegex(field.Invalid, "missing columns"):
            field.load_egress(
                self.write_csv("missing-dimension.csv", columns, [egress(1001, "direction", "two_way")]),
                {1001},
            )

        invalid_cases = {
            "unmeasured-way": egress(9999, "direction", "two_way"),
            "invalid-dimension": egress(1001, "legal", "no_sign"),
            "cross-dimension-observation": egress(1001, "direction", "no_sign"),
            "no-timezone": egress(1001, "direction", "two_way", observed_at="2026-10-01T09:30:00"),
            "missing-observer": egress(1001, "direction", "two_way", observer=""),
            "missing-provenance": egress(1001, "direction", "two_way", provenance=""),
            "credential-photo": egress(
                1001, "direction", "two_way", photo_url="https://example.test/photo.jpg?access_key=secret"
            ),
        }
        for name, row in invalid_cases.items():
            with self.subTest(name=name):
                with self.assertRaises(field.Invalid):
                    self.load_egress([row], {1001}, f"{name}.csv")

    def test_rejects_duplicate_or_conflicting_rows_per_way_dimension(self) -> None:
        cases = {
            "duplicate": [
                egress(1001, "direction", "two_way"),
                egress(1001, "direction", "two_way"),
            ],
            "conflicting": [
                egress(1001, "turn_space", "turn_space"),
                egress(1001, "turn_space", "no_turn_space"),
            ],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(field.Invalid, "exactly one row per dimension"):
                self.load_egress(rows, {1001}, f"{name}.csv")

    def test_unknown_is_explicit_and_scoped_to_each_dimension(self) -> None:
        rows = self.load_egress([
            egress(1001, "direction", "unknown"),
            egress(1001, "turn_space", "unknown"),
            egress(1001, "sign", "unknown"),
        ], {1001})
        self.assertEqual({row["dimension"] for row in rows}, set(field.EGRESS_DIMENSIONS))
        self.assertTrue(all(row["observation"] == "unknown" for row in rows))


class FrozenSplitTests(FieldFixtureTestCase):
    def test_initial_split_is_balanced_immutable_and_fingerprinted(self) -> None:
        rows = self.load_measurements([measurement(1000 + index) for index in range(20)])
        split_path = self.root / "eval-split-v1.json"
        split = field.make_split(rows, split_path, seed=17)

        self.assertEqual(split["generation"], 1)
        self.assertEqual(len(split["heldout"]["groups"]), 10)
        self.assertEqual(len(split["calibration"]["groups"]), 10)
        self.assertEqual(split["measurements_sha256"], field.dataset_fingerprint(rows))
        field.check_split(rows, split)

        omitted = copy.deepcopy(split)
        omitted["heldout"]["way_ids"].pop()
        with self.assertRaisesRegex(field.Invalid, "membership"):
            field.check_split(rows, omitted)
        changed = copy.deepcopy(rows)
        changed[0]["photo_url"] = "https://evidence.example.test/replaced-photo.jpg"
        with self.assertRaisesRegex(field.Invalid, "fingerprint"):
            field.check_split(changed, split)
        with self.assertRaisesRegex(field.Invalid, "already exists"):
            field.make_split(rows, split_path, seed=17)

    def test_failed_atomic_split_write_leaves_no_frozen_artifact(self) -> None:
        rows = self.load_measurements([measurement(1500 + index) for index in range(20)])
        path = self.root / "unwritten-split.json"
        with patch.object(field.os, "link", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                field.make_split(rows, path, seed=17)
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.glob(".unwritten-split.json.*.tmp")), [])

    def test_split_creation_never_clobbers_concurrent_destination(self) -> None:
        path = self.root / "preexisting-split.json"
        path.write_text("existing frozen split", encoding="utf-8")
        with self.assertRaisesRegex(field.Invalid, "never overwritten"):
            field._write_split({"format_version": 1}, path)
        self.assertEqual(path.read_text(encoding="utf-8"), "existing frozen split")


    def test_append_only_extension_preserves_parent_and_assigns_new_rows_safely(self) -> None:
        parent_rows = self.load_measurements([measurement(2000 + index) for index in range(20)], "parent.csv")
        parent_path = self.root / "eval-split-v1.json"
        parent = field.make_split(parent_rows, parent_path, seed=23)
        by_id = {row["osm_way_id"]: row for row in parent_rows}
        held_parent_id = parent["heldout"]["way_ids"][0]
        cal_parent_id = parent["calibration"]["way_ids"][0]
        appended_source = [measurement(2000 + index) for index in range(20)] + [
            measurement(3001, alley_name=by_id[held_parent_id]["alley_name"]),
            measurement(3002, alley_name=by_id[cal_parent_id]["alley_name"]),
            measurement(3003, alley_name="Hẻm 9999 Brand New Group"),
        ]
        rows = self.load_measurements(appended_source, "superset.csv")
        child_path = self.root / "eval-split-v2.json"
        child = field.extend_split(rows, parent, child_path, parent_path=parent_path)

        self.assertEqual(child["generation"], 2)
        self.assertEqual(child["parent_generation"], 1)
        self.assertEqual(child["parent_split_sha256"], field.split_fingerprint(parent))
        self.assertEqual(child["parent_measurements_sha256"], parent["measurements_sha256"])
        self.assertTrue(set(parent["heldout"]["way_ids"]).issubset(child["heldout"]["way_ids"]))
        self.assertTrue(set(parent["heldout"]["groups"]).issubset(child["heldout"]["groups"]))
        self.assertIn(3001, child["heldout"]["way_ids"])
        self.assertIn(3002, child["calibration"]["way_ids"])
        self.assertIn(3003, child["calibration"]["way_ids"])
        field.check_split(rows, child)

        unknown_assignment = copy.deepcopy(child)
        unknown_assignment["calibration"]["way_ids"].remove(3003)
        with self.assertRaisesRegex(field.Invalid, "membership"):
            field.check_split(rows, unknown_assignment)

    def test_every_split_generation_keeps_a_minimum_held_out_floor(self) -> None:
        rows = self.load_measurements([measurement(3500 + index) for index in range(20)])
        split = field.make_split(rows, self.root / "parent.json", seed=29)
        held_group = split["heldout"]["groups"][0]
        moved = [row["osm_way_id"] for row in rows if row["group"] == held_group]

        split["heldout"]["groups"].remove(held_group)
        split["calibration"]["groups"].append(held_group)
        split["heldout"]["way_ids"] = [way_id for way_id in split["heldout"]["way_ids"] if way_id not in moved]
        split["calibration"]["way_ids"].extend(moved)

        with self.assertRaisesRegex(field.Invalid, "held-out side must retain"):
            field.check_split(rows, split)

    def test_extension_rejects_removed_altered_same_or_malformed_parent_data(self) -> None:
        parent_rows = self.load_measurements([measurement(4000 + index) for index in range(20)], "parent.csv")
        parent_path = self.root / "eval-split-v1.json"
        parent = field.make_split(parent_rows, parent_path, seed=31)
        superset = self.load_measurements(
            [measurement(4000 + index) for index in range(20)] + [measurement(5001, alley_name="Hẻm 5001 New")],
            "superset.csv",
        )

        removed = [row for row in superset if row["osm_way_id"] != 4000]
        with self.assertRaisesRegex(field.Invalid, "removed"):
            field.extend_split(removed, parent, self.root / "removed.json")

        altered = copy.deepcopy(superset)
        altered[0]["width_m"] = 3.2
        with self.assertRaisesRegex(field.Invalid, "altered parent"):
            field.extend_split(altered, parent, self.root / "altered.json")

        with self.assertRaisesRegex(field.Invalid, "without appended"):
            field.extend_split(parent_rows, parent, self.root / "same-data.json")

        malformed = copy.deepcopy(parent)
        malformed["heldout"]["way_ids"].append("not-an-id")
        with self.assertRaises(field.Invalid):
            field.extend_split(superset, malformed, self.root / "malformed.json")

        with self.assertRaisesRegex(field.Invalid, "already exists"):
            field.extend_split(superset, parent, parent_path, parent_path=parent_path)

    def test_cli_extends_to_new_versioned_file_without_overwriting_parent(self) -> None:
        parent_source = [measurement(5500 + index) for index in range(20)]
        parent_rows = self.load_measurements(parent_source, "parent.csv")
        parent_path = self.root / "eval-split-v1.json"
        parent = field.make_split(parent_rows, parent_path, seed=37)
        parent_bytes = parent_path.read_bytes()
        superset_path = self.write_csv(
            "superset.csv",
            field.MEASUREMENT_COLUMNS,
            parent_source + [measurement(5599, alley_name="Hẻm 5599 New Group")],
        )
        child_path = self.root / "eval-split-v2.json"
        stdout = io.StringIO()
        argv = [
            "eval_field.py",
            "--measurements", str(superset_path),
            "--extend-split", str(parent_path),
            "--make-split", str(child_path),
        ]
        with patch.object(sys, "argv", argv), redirect_stdout(stdout):
            code = field.main()
        child = field.load_split(child_path)
        self.assertEqual(code, 0)
        self.assertEqual(child["parent_split_sha256"], field.split_fingerprint(parent))
        self.assertIn(5599, child["calibration"]["way_ids"])
        self.assertEqual(parent_path.read_bytes(), parent_bytes)
        self.assertIn("generation 2", stdout.getvalue())

    def test_refuses_twenty_rows_that_are_not_twenty_independent_groups(self) -> None:
        rows = self.load_measurements([
            measurement(6000 + index, alley_name=f"Hẻm 123/{index + 1} Test")
            for index in range(20)
        ])
        with self.assertRaisesRegex(field.Invalid, "independent normalized alley-chain groups"):
            field.make_split(rows, self.root / "split.json", seed=17)


class ScoringTests(FieldFixtureTestCase):
    def test_fit_and_tight_claims_use_their_own_thresholds(self) -> None:
        self.assertTrue(field.definite_false_fit("fits", 3.4, need_fit=3.5, need_tight=2.5))
        self.assertFalse(field.definite_false_fit("fits", 3.5, need_fit=3.5, need_tight=2.5))
        self.assertTrue(field.definite_false_fit("tight", 2.4, need_fit=3.5, need_tight=2.5))
        self.assertFalse(field.definite_false_fit("tight", 2.5, need_fit=3.5, need_tight=2.5))
        self.assertFalse(field.definite_false_fit("unknown", 1.0, need_fit=3.5, need_tight=2.5))

    def test_reports_interval_metrics_and_flags_fit_below_fit_threshold(self) -> None:
        row = self.load_measurements([measurement(1001)])[0]
        graph = SimpleNamespace(ways={1001: SimpleNamespace()})
        width_range = SimpleNamespace(lo=2.9, hi=3.2, width_basis="observed_clear_width", decisive_clearance=True)
        profile = SimpleNamespace(fits_min=3.5, tight_min=2.5)
        store = SimpleNamespace(by_way={}, by_name={}, view=lambda: object())
        with (
            patch.object(field, "VEHICLES", ("synthetic-car",)),
            patch.object(field, "build_graph", return_value=graph),
            patch.object(field, "width_ranges", return_value={1001: width_range}),
            patch.object(field, "compute_fit", return_value=({1001: "fits"}, {})),
            patch.object(field, "get_profile", return_value=profile),
        ):
            result = field.score([row], {1001}, store, set(), set())

        vehicle = result["vehicles"]["synthetic-car"]
        self.assertEqual(vehicle["confusion_denominator"], 1)
        self.assertTrue(vehicle["items"][0]["false_fit"])
        self.assertEqual(vehicle["definite_false_fits"], 1)
        self.assertEqual(result["width_interval_metrics"]["truth_interval_covered_count"], 1)

    def test_open_ended_predictions_do_not_pad_overlap_or_coverage_metrics(self) -> None:
        row = self.load_measurements([measurement(1002)])[0]
        graph = SimpleNamespace(ways={1002: SimpleNamespace()})
        width_range = SimpleNamespace(
            lo=0.5,
            hi=field.OPEN_HI,
            width_basis="unknown",
            decisive_clearance=False,
        )
        profile = SimpleNamespace(fits_min=3.5, tight_min=2.5)
        store = SimpleNamespace(by_way={}, by_name={}, view=lambda: object())
        with (
            patch.object(field, "VEHICLES", ("synthetic-car",)),
            patch.object(field, "build_graph", return_value=graph),
            patch.object(field, "width_ranges", return_value={1002: width_range}),
            patch.object(field, "compute_fit", return_value=({1002: "unknown"}, {})),
            patch.object(field, "get_profile", return_value=profile),
        ):
            result = field.score([row], {1002}, store, set(), set())

        metrics = result["width_interval_metrics"]
        self.assertEqual(metrics["denominator"], 1)
        self.assertEqual(metrics["open_ended_count"], 1)
        self.assertEqual(metrics["informative_denominator"], 0)
        self.assertIsNone(metrics["overlap_rate"])
        self.assertIsNone(metrics["truth_interval_coverage_rate"])
        self.assertIsNone(metrics["mean_interval_gap_m"])
        prediction = result["widths"][0]
        self.assertTrue(prediction["open_ended"])
        self.assertIsNone(prediction["predicted_interval_m"]["hi"])
        self.assertIsNone(prediction["covers_truth_interval"])
        self.assertIsNone(prediction["interval_gap_m"])

    def test_rejects_measured_label_leak_before_planning(self) -> None:
        row = self.load_measurements([measurement(1001)])[0]
        store = SimpleNamespace(
            by_way={1001: [SimpleNamespace(tier="Measured")]},
            by_name={},
            view=lambda: object(),
        )
        with self.assertRaisesRegex(field.Invalid, "leak"):
            field.score([row], {1001}, store, {1001}, set())


class EgressAuditAndGateTests(FieldFixtureTestCase):
    def test_requires_all_three_dimensions_but_does_not_treat_unscored_facts_as_verified(self) -> None:
        rows = self.load_measurements([measurement(1001), measurement(1002)])
        observations = self.load_egress(
            complete_egress([1001, 1002], turn="no_turn_space", sign="sign_no_stopping"),
            {1001, 1002},
        )
        graph = SimpleNamespace(ways={1001: SimpleNamespace(oneway=0), 1002: SimpleNamespace(oneway=0)})
        with patch.object(field, "build_graph", return_value=graph):
            audit = field.egress_audit(observations, rows, {1001, 1002})

        self.assertEqual(audit["agree"], 2)
        self.assertEqual(audit["unscored"], 4)
        self.assertEqual(audit["blocking_observations"], 4)
        self.assertEqual(audit["observation_denominator"], 6)
        self.assertEqual(audit["covered_way_count"], 2)
        self.assertTrue(all(
            item["verdict"] == "unscored" and item["comparability"] == "not_comparable"
            for item in audit["items"] if item["dimension"] != "direction"
        ))
        gate = field.release_gate(scored_mode(2), scored_mode(2), audit, 2)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["descriptive_blocking_observations"], 4)
        self.assertEqual(gate["unscored_turn_sign_observations"], 4)

        missing_sign = [row for row in observations if not (row["way_id"] == 1002 and row["dimension"] == "sign")]
        with patch.object(field, "build_graph", return_value=graph):
            incomplete = field.egress_audit(missing_sign, rows, {1001, 1002})
        incomplete_gate = field.release_gate(scored_mode(2), scored_mode(2), incomplete, 2)
        self.assertFalse(incomplete_gate["complete_egress_dimension_coverage"])
        self.assertFalse(incomplete_gate["passed"])

    def test_unknown_turn_and_sign_are_reported_but_only_unknown_direction_blocks(self) -> None:
        rows = self.load_measurements([measurement(1101), measurement(1102)])
        observations = self.load_egress([
            egress(1101, "direction", "two_way"),
            egress(1101, "turn_space", "unknown"),
            egress(1101, "sign", "unknown"),
            egress(1102, "direction", "two_way"),
            egress(1102, "turn_space", "unknown"),
            egress(1102, "sign", "unknown"),
        ], {1101, 1102})
        graph = SimpleNamespace(ways={1101: SimpleNamespace(oneway=0), 1102: SimpleNamespace(oneway=0)})
        with patch.object(field, "build_graph", return_value=graph):
            audit = field.egress_audit(observations, rows, {1101, 1102})
        self.assertEqual(audit["unknown"], 4)
        self.assertTrue(field.release_gate(scored_mode(2), scored_mode(2), audit, 2)["passed"])

        direction_unknown = copy.deepcopy(observations)
        direction_unknown[0]["observation"] = "unknown"
        with patch.object(field, "build_graph", return_value=graph):
            unknown_audit = field.egress_audit(direction_unknown, rows, {1101, 1102})
        gate = field.release_gate(scored_mode(2), scored_mode(2), unknown_audit, 2)
        self.assertFalse(gate["known_direction_for_every_heldout_way"])
        self.assertFalse(gate["complete_direction_comparison"])
        self.assertFalse(gate["passed"])

    def test_direction_contradiction_and_incomplete_width_scoring_fail_closed(self) -> None:
        rows = self.load_measurements([measurement(1201)])
        observations = self.load_egress(complete_egress([1201]), {1201})
        graph = SimpleNamespace(ways={1201: SimpleNamespace(oneway=1)})
        with patch.object(field, "build_graph", return_value=graph):
            audit = field.egress_audit(observations, rows, {1201})
        gate = field.release_gate(scored_mode(1), scored_mode(1), audit, 1)
        self.assertFalse(gate["no_direction_contradiction"])
        self.assertFalse(gate["passed"])

        safe_graph = SimpleNamespace(ways={1201: SimpleNamespace(oneway=0)})
        with patch.object(field, "build_graph", return_value=safe_graph):
            safe_audit = field.egress_audit(observations, rows, {1201})
        empty = scored_mode(0)
        result = field.release_gate(empty, empty, safe_audit, 1)
        self.assertFalse(result["nonempty_denominators"])
        self.assertFalse(result["complete_width_scoring"])


class MainIntegrationTests(FieldFixtureTestCase):
    def test_main_loads_real_snapshot_scores_audits_gates_and_writes_scoped_report(self) -> None:
        source_rows = [measurement(7000 + index) for index in range(20)]
        measurements_path = self.write_csv("measurements.csv", field.MEASUREMENT_COLUMNS, source_rows)
        parsed_rows = field.load_measurements(measurements_path)
        split_path = self.root / "eval-split-v1.json"
        split = field.make_split(parsed_rows, split_path, seed=41)
        egress_path = self.write_csv(
            "egress.csv",
            field.EGRESS_COLUMNS,
            complete_egress(
                [7000 + index for index in range(20)],
                turn="no_turn_space",
                sign="sign_no_parking",
            ),
        )
        report_path = self.root / "reports" / "field-validation.json"
        all_ids = {7000 + index for index in range(20)}
        graph = SimpleNamespace(ways={way_id: SimpleNamespace(oneway=0) for way_id in all_ids})
        ranges = {
            way_id: SimpleNamespace(
                lo=2.9,
                hi=3.1,
                width_basis="observed_clear_width",
                decisive_clearance=True,
            )
            for way_id in all_ids
        }
        profile = SimpleNamespace(fits_min=2.5, tight_min=2.0)

        stdout = io.StringIO()
        argv = [
            "eval_field.py",
            "--measurements", str(measurements_path),
            "--egress", str(egress_path),
            "--split", str(split_path),
            "--output", str(report_path),
        ]
        evidence_files = {
            "LISTINGS_FILE": self.root / "listings.json",
            "GAPS_FILE": self.root / "gaps.json",
            "FIRE_FILE": self.root / "fire.json",
            "PARCEL_FILE": self.root / "parcels.csv",
            "CONFIRM_FILE": self.root / "confirmations.jsonl",
        }
        with (
            patch.object(sys, "argv", argv),
            patch.object(field, "VEHICLES", ("synthetic-car",)),
            patch.object(field, "build_graph", return_value=graph),
            patch.object(field, "width_ranges", return_value=ranges),
            patch.object(field, "compute_fit", side_effect=lambda g, wrs, p: ({way_id: "fits" for way_id in g.ways}, {})),
            patch.object(field, "get_profile", return_value=profile),
            patch.object(evidence_module.flags, "enabled", return_value=True),
            patch.multiple(evidence_module, **evidence_files),
            redirect_stdout(stdout),
        ):
            code = field.main()
            failed_report_path = self.root / "reports" / "failed-gate.json"
            argv[-1] = str(failed_report_path)
            with patch.object(sys, "argv", argv), patch.object(
                field, "release_gate", return_value={"passed": False}
            ):
                failed_gate_code = field.main()

            infrastructure_report = self.root / "reports" / "unwritable-report.json"
            argv[-1] = str(infrastructure_report)
            stderr = io.StringIO()
            with patch.object(sys, "argv", argv), patch.object(
                field, "write_json", side_effect=OSError("disk full")
            ), redirect_stderr(stderr):
                write_failure_code = field.main()

        self.assertEqual(code, 0)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        held_count = len(split["heldout"]["way_ids"])
        self.assertEqual(report["rows"], 20)
        self.assertEqual(report["heldout"], held_count)
        self.assertEqual(report["split_coverage"]["heldout_rows"], held_count)
        self.assertEqual(report["split_coverage"]["calibration_rows"], 20 - held_count)
        self.assertEqual(report["split_coverage"]["heldout_groups"], 10)
        self.assertEqual(report["split_coverage"]["calibration_groups"], 10)
        self.assertEqual(report["split_coverage"]["heldout_row_share"], 0.5)
        self.assertEqual(report["split_generation"], 1)
        self.assertTrue(report["gate"]["passed"])
        self.assertTrue(report["gate"]["complete_egress_dimension_coverage"])
        self.assertEqual(report["egress"]["agree"], held_count)
        self.assertEqual(report["egress"]["unscored"], held_count * 2)
        self.assertEqual(report["egress"]["blocking_observations"], held_count * 2)
        self.assertEqual(report["model_only"]["vehicles"]["synthetic-car"]["confusion_denominator"], held_count)
        latency = report["latency"]
        self.assertEqual(latency["evaluation_command"]["status"], "measured")
        self.assertGreaterEqual(latency["evaluation_command"]["cpu_seconds"], 0.0)
        self.assertGreaterEqual(latency["evaluation_command"]["wall_seconds"], 0.0)
        self.assertIn("cache miss", latency["evaluation_command"]["network_scope"])
        self.assertEqual(
            latency["external_upstream"],
            {"status": "not_separately_instrumented", "duration_seconds": None},
        )
        self.assertEqual(
            latency["background_jobs"],
            {"status": "not_scheduled_by_evaluator", "duration_seconds": None},
        )
        self.assertNotIn("external_upstream", report["gate"])
        self.assertNotIn("background_jobs", report["gate"])
        self.assertEqual(report["evaluation_scope"]["scored"], ["physical_clear_width", "osm_direction"])
        self.assertEqual(report["evaluation_scope"]["unscored"], ["turn_space", "sign_and_legal_status"])
        self.assertFalse(report["evaluation_scope"]["legal_and_turn_space_field_verified"])
        self.assertIn("limited to measurable width and OSM direction", report["evaluation_scope"]["statement"])
        self.assertIn('"passed": true', stdout.getvalue())
        self.assertEqual(failed_gate_code, 1)
        self.assertTrue(failed_report_path.is_file())
        self.assertFalse(json.loads(failed_report_path.read_text(encoding="utf-8"))["gate"]["passed"])
        self.assertEqual(write_failure_code, 3)
        self.assertIn("could not write or serialize report (OSError): disk full", stderr.getvalue())
        self.assertFalse(infrastructure_report.exists())


if __name__ == "__main__":
    unittest.main()
