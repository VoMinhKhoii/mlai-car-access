"""Unit tests for regex-v1.  Run:  pipelines/.venv/bin/python -m unittest pipelines/test_extract_regex.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_regex import Gazetteer, extract  # noqa: E402

GAZ = Gazetteer(["Xô Viết Nghệ Tĩnh", "Điện Biên Phủ", "Nguyễn Văn Đậu", "Huỳnh Tấn Phát", "Bạch Đằng"])


def x(text, street=None):
    return extract(text, street, GAZ)


class Width(unittest.TestCase):
    def test_variants(self):
        cases = {
            "Nhà hẻm 3,5m Huỳnh Tấn Phát": 3.5,
            "HẺM 6 MÉT thông thoáng": 6.0,
            "HXH 5m vào tận nhà": 5.0,
            "hẻm rộng 4m": 4.0,
            "hẻm xe hơi 7m": 7.0,
            "hẻm 3m5 xe ba gác": 3.5,
            "Hẻm trước nhà rộng 4.5m": 4.5,
            "hẻm 5-6m": 5.0,
            "hẽm cụt 3 mét gồm 4 căn": 3.0,
            "hẻm ô tô, 5m, quận 1": 5.0,
            "HẺM XE HƠI CHỈ 5M": 5.0,
        }
        for text, w in cases.items():
            with self.subTest(text=text):
                self.assertEqual(x(text)["width_m"], w)

    def test_not_widths(self):
        for text in ("Nhà cách hẻm xe hơi 20m", "DT ngang 4m dài 15m", "vào hẻm 30m", "hẻm 123/45 XVNT",
                     "cách đầu hẻm 10m", "hẻm xe hơi 10m ra mặt tiền", "lộ giới hẻm 1mét"):
            with self.subTest(text=text):
                self.assertIsNone(x(text)["width_m"])

    def test_mouth(self):
        self.assertTrue(x("đầu hẻm 6m, trong hẻm 3m")["width_at_mouth"] in (True, False))
        r = x("Nhà mặt tiền hẻm 8m")
        self.assertEqual(r["width_m"], 8.0)
        self.assertTrue(r["width_at_mouth"])
        self.assertTrue(x("đầu hẻm rộng 6m")["width_at_mouth"])
        self.assertFalse(x("hẻm 4m")["width_at_mouth"])

    def test_front_of_house_preferred(self):
        self.assertEqual(x("hẻm chính 8m, hẻm trước nhà 4m")["width_m"], 4.0)


class Access(unittest.TestCase):
    def test_claims(self):
        self.assertEqual(x("Bán nhà hẻm xe hơi Bình Thạnh")["access_claim"], "xe_hoi")
        self.assertEqual(x("HXH ngủ trong nhà")["access_claim"], "xe_hoi")
        self.assertEqual(x("hẻm ô tô tránh nhau")["access_claim"], "xe_hoi_tranh")
        self.assertEqual(x("hẻm 2 xe hơi tránh")["access_claim"], "xe_hoi_tranh")
        self.assertEqual(x("hẻm ba gác, cách hẻm xe hơi 10m")["access_claim"], "ba_gac")
        self.assertEqual(x("Hẻm xe máy thông thoáng")["access_claim"], "xe_may")
        self.assertIsNone(x("Nhà đẹp giá tốt")["access_claim"])
        self.assertIsNone(x("gần hẻm xe hơi")["access_claim"])
        self.assertEqual(x("Hẻm xe hơi Cách 50m ra Mặt Tiền")["access_claim"], "xe_hoi")
        self.assertEqual(x("HXH cách mặt tiền 40m")["access_claim"], "xe_hoi")
        self.assertEqual(x("HẺM 3GAC CÁCH HXH 1 CĂN")["access_claim"], "ba_gac")

    def test_car_to_door(self):
        self.assertTrue(x("xe hơi vào nhà")["car_to_door"])
        self.assertTrue(x("ô tô đỗ cửa")["car_to_door"])
        self.assertTrue(x("Hẻm xe hơi, đậu ô tô trước nhà")["car_to_door"])
        self.assertFalse(x("hẻm xe hơi cách nhà 20m")["car_to_door"])
        self.assertFalse(x("hẻm xe máy")["car_to_door"])
        self.assertIsNone(x("hẻm xe hơi")["car_to_door"])
        self.assertIsNone(x("Hẻm xe hơi Cách 50m ra Mặt Tiền")["car_to_door"])
        self.assertFalse(x("HẺM XE HƠI CÁCH 1 CĂN")["car_to_door"])

    def test_through(self):
        self.assertEqual(x("hẻm thông ra Điện Biên Phủ")["through"], "thong")
        self.assertEqual(x("HXH thông tứ tung")["through"], "thong")
        self.assertEqual(x("hẻm cụt yên tĩnh")["through"], "cut")
        self.assertIsNone(x("hẻm thông thoáng")["through"])
        self.assertEqual(x("không phải hẻm cụt")["through"], "thong")


class Chain(unittest.TestCase):
    def test_bare_address(self):
        self.assertEqual(x("Nhà 123/45 Xô Viết Nghệ Tĩnh")["alley_chain"],
                         ["Hẻm 123 Xô Viết Nghệ Tĩnh", "Hẻm 123/45 Xô Viết Nghệ Tĩnh"])

    def test_abbrev_and_keyword(self):
        self.assertEqual(x("HXH 88 NVĐ")["alley_chain"], ["Hẻm 88 Nguyễn Văn Đậu"])
        self.assertEqual(x("hẻm 12/3 xvnt")["alley_chain"], ["Hẻm 12 Xô Viết Nghệ Tĩnh", "Hẻm 12/3 Xô Viết Nghệ Tĩnh"])

    def test_listing_street_fallback(self):
        r = x("nhà hẻm 51 sạch đẹp", "Đường Bạch Đằng")
        self.assertEqual(r["alley_chain"], ["Hẻm 51 Bạch Đằng"])
        self.assertEqual(r["alley_chain_source"], "text+listing_street")

    def test_not_chain(self):
        for text in ("45 Xô Viết Nghệ Tĩnh", "giá 5/2025", "hẻm 6m Xô Viết Nghệ Tĩnh"):
            with self.subTest(text=text):
                self.assertEqual(x(text)["alley_chain"], [])


if __name__ == "__main__":
    unittest.main()
