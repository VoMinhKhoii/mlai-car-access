"""R-05 tests for width provenance, bottlenecks, coverage, and held-out isolation."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.evidence import Bound, EvidenceStore, _combine, _width_metadata, width_ranges
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
            store.live["fixture"] = {
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
            store.reload()
            graph = AreaGraph(center=(10.0, 106.0), ways={
                910001: Way(910001, {"highway": "residential", "name": "Hẻm kiểm thử"}, [1, 2]),
                910002: Way(910002, {"highway": "residential", "name": "Hẻm chỉ giữa"}, [3, 4]),
            })

            with patch("app.evidence.flags.enabled", return_value=True):
                ranges = width_ranges(graph, store)
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
            ranges = width_ranges(graph, store)
            vehicle = get_profile("toyota-vios")
            fit, _ = compute_fit(graph, ranges, vehicle)

            self.assertTrue(ranges[910010].decisive_clearance)
            self.assertTrue(ranges[910010].coverage["complete"])
            self.assertEqual(fit[910010], "fits")
            self.assertTrue(_usable(fit[910010], "passable", strict=True))
            self.assertFalse(ranges[910011].decisive_clearance)
            self.assertEqual(fit[910011], "unknown")
            self.assertFalse(_usable(fit[910011], "passable", strict=True))

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
        fake_cut = lambda _line, distance, _lat, _lon: {
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
