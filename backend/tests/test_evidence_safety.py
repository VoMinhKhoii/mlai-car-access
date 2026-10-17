"""R-05 tests for width provenance, bottlenecks, coverage, and held-out isolation."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.evidence import (SYNTHETIC_DEMO_TIER, SYNTHETIC_DEMO_WIDTH_BASIS, Bound, EvidenceIndex, EvidenceStore,
                          _combine, _width_metadata, width_ranges)
from app.legality import supports_legal_lane_count
from app.osm import AreaGraph, Way
from app.parcels import measure
from app.plan import _usable, compute_fit
from app.vehicles import get_profile


HEADER = (
    "osm_way_id,alley_name,width_m,date,measured_by,note,photo_url,width_basis,uncertainty_m,"
    "cut_count,start_covered,end_covered,max_spacing_m,truncated,complete\n"
)
COMPLETE = {
    "cut_count": 5, "start_covered": True, "end_covered": True,
    "max_spacing_m": 5.0, "truncated": False, "complete": True, "reason": None,
}

class EvidenceSafetyTests(unittest.TestCase):
    def _store(self, path: Path) -> EvidenceStore:
        return EvidenceStore.evaluation_snapshot(field_file=path)

    def test_narrowest_live_cut_survives_and_parcel_gap_never_authorizes_fit(self):
        with TemporaryDirectory() as directory:
            field = Path(directory) / "measurements.csv"
            field.write_text(HEADER, encoding="utf-8")
            store = self._store(field)
            widths = [1.5, 4.0, 4.0, 4.0, 4.0]
            area = {
                "listings": [], "photos": [],
                "parcels": [
                    {
                        "way_id": 910001,
                        "samples": widths,
                        "cuts": [
                            {"at_m": index * 5, "gap_m": width + 1.0, "width_m": width}
                            for index, width in enumerate(widths)
                        ],
                        "segment_length_m": 20.0,
                        "truncated": False,
                        "deep": True,
                    },
                    {
                        "way_id": 910002,
                        "samples": [4.0, 4.0],
                        "cuts": [
                            {"at_m": 10.0, "gap_m": 5.0, "width_m": 4.0},
                            {"at_m": 15.0, "gap_m": 5.0, "width_m": 4.0},
                        ],
                        "segment_length_m": 30.0,
                        "truncated": False,
                        "deep": False,
                    },
                ],
            }
            view = store.view(area)  # the build is an overlay: the shared snapshot is never mutated
            graph = AreaGraph(center=(10.0, 106.0), ways={
                910001: Way(910001, {"highway": "residential", "name": "Hẻm kiểm thử"}, [1, 2]),
                910002: Way(910002, {"highway": "residential", "name": "Hẻm chỉ giữa"}, [3, 4]),
            })

            with patch("app.evidence.flags.enabled", return_value=True):
                ranges = width_ranges(graph, view)
            width = ranges[910001]
            parcel_bound = next(bound for bound in width.evidence if bound.width_basis == "parcel_gap_estimate")
            self.assertEqual(parcel_bound.lo, 1.5)
            self.assertEqual(parcel_bound.hi, 1.5)
            self.assertTrue(parcel_bound.coverage["complete"])
            self.assertFalse(width.coverage["complete"])
            self.assertFalse(width.decisive_clearance)
            fit, _ = compute_fit(graph, ranges, get_profile("toyota-vios"))
            self.assertNotEqual(fit[910001], "fits")
            self.assertFalse(_usable(fit[910001], "passable", strict=True))
            interior = ranges[910002]
            self.assertFalse(interior.coverage["start_covered"])
            self.assertFalse(interior.coverage["end_covered"])
            self.assertFalse(interior.decisive_clearance)
            interior_fit, _ = compute_fit(graph, ranges, get_profile("toyota-vios"))
            self.assertEqual(interior_fit[910002], "unknown")
            self.assertFalse(_usable(interior_fit[910002], "passable", strict=True))

    def test_only_complete_measured_clear_width_can_authorize_strict_fit(self):
        with TemporaryDirectory() as directory:
            field = Path(directory) / "measurements.csv"
            field.write_text(
                HEADER
                + "910010,,6.0,2026-10-01,test,complete,,measured_clear_width,0.1,5,true,true,5,false,true\n"
                + "910011,,6.0,2026-10-01,test,sparse,,measured_clear_width,0.1,,,,,,\n",
                encoding="utf-8",
            )
            store = self._store(field)
            graph = AreaGraph(center=(10.0, 106.0), ways={
                910010: Way(910010, {"highway": "residential", "name": "Hẻm đo đủ"}, [1, 2]),
                910011: Way(910011, {"highway": "residential", "name": "Hẻm đo thưa"}, [3, 4]),
            })
            ranges = width_ranges(graph, store.view())
            vehicle = get_profile("toyota-vios")
            fit, _ = compute_fit(graph, ranges, vehicle)

            self.assertTrue(ranges[910010].decisive_clearance)
            self.assertTrue(ranges[910010].coverage["complete"])
            self.assertEqual(fit[910010], "fits")
            self.assertTrue(_usable(fit[910010], "passable", strict=True))
            self.assertFalse(ranges[910011].decisive_clearance)
            self.assertEqual(fit[910011], "unknown")
            self.assertFalse(_usable(fit[910011], "passable", strict=True))
            claims = {
                way_id: replace(
                    width,
                    way_out_claims=[Bound(0.0, 40.0, "Observed", "Xác nhận sau khi đến", "quay đầu")],
                )
                for way_id, width in ranges.items()
            }
            fit_with_exit_claims, _ = compute_fit(graph, claims, vehicle)
            self.assertEqual(fit_with_exit_claims, fit)

    def test_synthetic_fixture_never_enters_the_measured_tier(self):
        fixture = Path(__file__).parent / "fixtures" / "synthetic_demo_measurements.csv"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                "LISTINGS_FILE": root / "listings.json",
                "GAPS_FILE": root / "gaps.json",
                "FIRE_FILE": root / "fire.json",
                "PARCEL_FILE": root / "parcels.csv",
                "CONFIRM_FILE": root / "confirmations.jsonl",
                "BLOCKAGE_FILE": root / "blockages.jsonl",
            }
            with patch.multiple("app.evidence", **sources):
                normal = EvidenceStore(_field_file=fixture)
                self.assertFalse(any(bound.tier in ("Measured", "Synthetic")
                                     for bound in normal.by_way.get(544982029, [])))

                graph = AreaGraph(center=(10.0, 106.0), ways={
                    544982029: Way(544982029, {"highway": "residential", "name": "Hẻm demo"}, [1, 2]),
                })
                demo = EvidenceStore(_field_file=root / "empty.csv")
                ranges = width_ranges(graph, demo.view(synthetic_demo_file=fixture))
                synthetic_bound = next(
                    bound for bound in ranges[544982029].evidence
                    if bound.width_basis == SYNTHETIC_DEMO_WIDTH_BASIS
                )
                self.assertEqual(synthetic_bound.tier, SYNTHETIC_DEMO_TIER)
                self.assertEqual(synthetic_bound.source, "Synthetic demo fixture")
                self.assertEqual(synthetic_bound.to_json()["tier_vi"], "Synthetic demo")
                self.assertIn("SYNTHETIC DEMO ONLY", synthetic_bound.detail)
                self.assertTrue(ranges[544982029].decisive_clearance)
                self.assertFalse(supports_legal_lane_count(ranges[544982029]))
                self.assertTrue(
                    supports_legal_lane_count(replace(ranges[544982029], width_basis="measured_clear_width"))
                )
                fit, _ = compute_fit(graph, ranges, get_profile("toyota-vios"))
                self.assertEqual(fit[544982029], "fits")

    def test_measured_width_is_not_narrowed_by_synthetic_fixture(self):
        measured = Bound(5.8, 6.4, "Measured", "Field survey", "Measured clear width")
        synthetic = Bound(
            6.1, 6.3, SYNTHETIC_DEMO_TIER, "Synthetic demo fixture", "Demo coverage",
            width_basis=SYNTHETIC_DEMO_WIDTH_BASIS,
        )
        lo, hi, top, review, overruled, active = _combine([synthetic, measured])
        self.assertEqual((lo, hi, top, review), (5.8, 6.4, "Measured", False))
        self.assertEqual(overruled, [synthetic])
        self.assertEqual(active, [measured])

    def test_synthetic_demo_scenario_is_bound_to_target_location_and_way(self):
        from types import SimpleNamespace
        from app.main import _synthetic_demo_input

        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.csv"
            fixture.write_text("fixture")
            scenario = "cafe-ngo-tat-to"
            target = {
                "lat": 10.7896558,
                "lon": 106.7155889,
                "max_distance_m": 200.0,
                "way_ids": frozenset({544982029, 609967096, 165400090}),
            }
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                synthetic_demo_data=True,
                synthetic_demo_scenarios={scenario: target},
                synthetic_demo_fixture_file=str(fixture),
            )))
            self.assertEqual(
                _synthetic_demo_input(request, scenario, target["lat"], target["lon"], 544982029),
                (scenario, fixture),
            )
            self.assertEqual(
                _synthetic_demo_input(request, scenario, target["lat"] + 0.00135, target["lon"], 165400090),
                (scenario, fixture),
            )
            self.assertEqual(
                _synthetic_demo_input(request, scenario, 10.7931975, 106.7169399, 544982029),
                (None, None),
            )
            self.assertEqual(
                _synthetic_demo_input(request, scenario, target["lat"], target["lon"], 193085696),
                (None, None),
            )

    def test_class_confirmation_uses_narrowest_member_body_width_and_exit_claim_is_not_width(self):
        with TemporaryDirectory() as directory:
            confirmations = Path(directory) / "confirmations.jsonl"
            confirmations.write_text(
                json.dumps({
                    "date": "2026-10-14", "vehicle_id": "class-l", "vehicle_label": "L",
                    "body_width": 2.065, "mirror_width": 2.315, "result": "in",
                    "way_ids": [920001], "way_out_ids": [920002], "exit": "turned",
                }) + "\n",
                encoding="utf-8",
            )
            index = EvidenceIndex()
            with patch("app.evidence.CONFIRM_FILE", confirmations):
                index._load_confirmations()

            width = index.by_way[920001][0]
            self.assertAlmostEqual(width.lo, 1.94)
            self.assertEqual(width.width_basis, "unknown")
            exit_claim = index.way_out_by_way[920002][0]
            self.assertEqual(exit_claim.tier, "Observed")
            self.assertEqual(exit_claim.width_basis, "unknown")
            self.assertIn("turn around and exit", exit_claim.detail)

    def test_legacy_confirmation_without_exit_fields_still_loads(self):
        with TemporaryDirectory() as directory:
            confirmations = Path(directory) / "confirmations.jsonl"
            confirmations.write_text(
                json.dumps({
                    "date": "2026-10-14", "vehicle_id": "toyota-vios", "vehicle_label": "Vios",
                    "body_width": 1.735, "mirror_width": 1.925, "result": "in", "way_ids": [920003],
                }) + "\n",
                encoding="utf-8",
            )
            index = EvidenceIndex()
            with patch("app.evidence.CONFIRM_FILE", confirmations):
                index._load_confirmations()

            self.assertIn(920003, index.by_way)
            self.assertNotIn(920003, index.way_out_by_way)

    def test_evaluation_snapshot_excludes_measured_rows_before_way_and_name_indexing(self):
        with TemporaryDirectory() as directory:
            field = Path(directory) / "measurements.csv"
            field.write_text(
                HEADER
                + "910020,,4.0,2026-10-01,test,held out by id,,,,,,,\n"
                + "910021,Hẻm 42 Nguyễn,4.0,2026-10-01,test,held out by name,,,,,,,\n"
                + "910022,Hẻm 43 Nguyễn,4.0,2026-10-01,test,retained by id,,,,,,,\n"
                + ",Hẻm 42 Nguyễn,4.0,2026-10-01,test,held out name-only,,,,,,,\n"
                + ",Hẻm 43 Nguyễn,4.0,2026-10-01,test,retained name-only,,,,,,,\n",
                encoding="utf-8",
            )
            snapshot = EvidenceStore.evaluation_snapshot(
                exclude_measured_way_ids={910020},
                exclude_normalized_names={"Hẻm 42 Nguyễn"},
                field_file=field,
            )

            self.assertNotIn(910020, snapshot.by_way)
            self.assertNotIn(910021, snapshot.by_way)
            self.assertIn(910022, snapshot.by_way)
            self.assertNotIn("hem 42 nguyen", snapshot.by_name)
            self.assertIn("hem 43 nguyen", snapshot.by_name)


    def test_deep_measurement_includes_both_endpoints_and_marks_cut_cap(self):
        coordinates = [(10.0, 106.0), (10.00018, 106.0)]
        fake_cut = lambda _line, distance, _lat, _lon, _deadline=None: {
            "at_m": round(distance, 1), "gap_m": 3.0, "width_m": 2.0,
        }
        with patch("app.parcels._cut_at", side_effect=fake_cut):
            complete = measure(coordinates, step=5.0, max_cuts=60)
        self.assertEqual(complete["cuts"][0]["at_m"], 0.0)
        self.assertEqual(complete["cuts"][-1]["at_m"], complete["segment_length_m"])
        self.assertFalse(complete["truncated"])
        self.assertLessEqual(complete["max_spacing_m"], 5.1)

        with patch("app.parcels._cut_at", side_effect=fake_cut):
            truncated = measure(coordinates, step=5.0, max_cuts=3)
        positions = [cut["at_m"] for cut in truncated["cuts"]]
        self.assertEqual(len(positions), 3)
        self.assertEqual(positions[0], 0.0)
        self.assertAlmostEqual(positions[1], truncated["segment_length_m"] / 2, delta=0.2)
        self.assertAlmostEqual(positions[2], truncated["segment_length_m"], delta=0.2)
        self.assertTrue(truncated["truncated"])

    def test_cross_tier_conflict_demotes_even_a_complete_measurement(self):
        measured = Bound(4.0, 5.0, "Measured", "Thước", "đo đủ",
                         width_basis="measured_clear_width", uncertainty_m=0.1, coverage=COMPLETE)
        declared = Bound(1.0, 3.0, "Declared", "Tin rao", "khai báo hẹp")
        lo, hi, _, review, overruled, active = _combine([measured, declared])
        basis, coverage, decisive = _width_metadata(active, review)

        self.assertEqual((lo, hi), (4.0, 5.0))
        self.assertTrue(review)
        self.assertEqual(overruled, [declared])
        self.assertEqual(basis, "measured_clear_width")
        self.assertTrue(coverage["complete"])
        self.assertFalse(decisive)


if __name__ == "__main__":
    unittest.main()
