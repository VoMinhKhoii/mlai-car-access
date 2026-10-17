import unittest

from app.geometry import body_center_offset, body_corners, k_turn, k_turn_path, radii
from app.vehicles import all_profiles


class ManeuverTests(unittest.TestCase):
    def test_pose_path_preserves_legacy_turn_result_and_stays_bounded(self):
        for profile in all_profiles().values():
            if profile.kind != "model":
                continue
            for width in (3.0, 8.0):
                with self.subTest(vehicle=profile.id, width=width):
                    expected = k_turn(
                        profile.body_width, profile.length, profile.wheelbase, profile.turning_radius,
                        width, T=profile.track,
                    )
                    moves, length, poses = k_turn_path(
                        profile.body_width, profile.length, profile.wheelbase, profile.turning_radius,
                        width, T=profile.track,
                    )
                    self.assertEqual((moves, length), expected)
                    self.assertLessEqual(len(poses), 120)
                    if moves is None:
                        self.assertEqual(poses, [])
                    else:
                        self.assertEqual(len(poses[0]), 3)
                        self.assertEqual(len(poses[-1]), 3)
                        self.assertNotEqual(poses[0], poses[-1])
                        self.assertTrue(all(0 <= pose[0] <= width for pose in poses))

    def test_pose_limit_must_allow_start_and_end(self):
        with self.assertRaises(ValueError):
            k_turn_path(1.8, 4.5, 2.7, 5.5, 8.0, max_poses=1)



    def test_body_center_offset_matches_the_simulated_vehicle_body_center(self):
        for profile in all_profiles().values():
            if profile.kind != "model":
                continue
            with self.subTest(vehicle=profile.id):
                g = radii(profile.body_width, profile.length, profile.wheelbase,
                          profile.turning_radius, T=profile.track)
                corners = body_corners(0, 0, 0, profile.body_width, g["FOH"], g["ROH"], profile.wheelbase)
                body_center_x = sum(x for x, _ in corners) / len(corners)
                self.assertAlmostEqual(
                    body_center_offset(profile.length, profile.wheelbase, g["FOH"], g["ROH"]),
                    body_center_x,
                )
if __name__ == "__main__":
    unittest.main()
