# Camera route choice at rush hour: 5 Oct 2026

**Covered:** the morning peak only, 07:07–07:52, four checks 15 min apart on three trips. The evening run (16:00–19:30) did not happen: the sampler was stopped at 13:54 because it shared the free Gemini quota (20 requests per key per day for 3.5 Flash) with the preview being reviewed. Raw data is in `data/raw/camera_samples/2026-10-05/` (not committed). The automatic table is in `camera-sampler.md`.

## Labels vs the photos

Fifteen saved frames were checked by eye against the AI label, chosen to cover every jam that drove a route decision and the roads that matter most (Cầu Sài Gòn, Hàng Xanh, Điện Biên Phủ, Phạm Văn Đồng).

| Camera, time | AI | The frame |
|---|---|---|
| Đinh Bộ Lĩnh – Bạch Đằng 2, 07:23 | kẹt cứng | packed to the horizon ✓ |
| BX Miền Đông – Đinh Bộ Lĩnh 1, 07:08 | ùn ứ | packed ✓ |
| Phạm Văn Đồng – Lê Quang Định 2, 07:37 / 07:52 | kẹt cứng | one carriageway packed, the other empty ✓ |
| Phạm Văn Đồng – Phan Văn Trị 1, 07:22 | ùn ứ | dense ✓ |
| Điện Biên Phủ – Nguyễn Bỉnh Khiêm, 07:53 | ùn ứ | roundabout full ✓ |
| Cầu Sài Gòn 9, 07:23 | đông | busy, moving ✓ |
| Cầu Sài Gòn (10), 07:08 | thông thoáng | ✓ |
| Điện Biên Phủ – Nguyễn Gia Trí, 07:37 | đông | ✓ |
| Điện Biên Phủ – Nguyễn Hữu Cảnh, 07:08 | đông | ✓ |
| Hàng Xanh 8, 07:52 | thông thoáng | ✓ |
| Đinh Bộ Lĩnh – Bạch Đằng 2, 07:52 | đông | ✓ |
| BX Miền Đông – Đinh Bộ Lĩnh 1, 07:23 | thông thoáng | ✓ (borderline đông) |
| Xô Viết Nghệ Tĩnh – Phan Văn Hân, 07:07 | ùn ứ | moving lanes: đông (one level high) |
| Hàng Xanh 1, 07:23 | thông thoáng | busy junction: đông (one level low) |

13 of 15 agree, the 2 misses are one level each and in opposite directions: no systematic labelling error. No flooding was seen (dry morning), so the flood labels were not tested at rush hour.

## What the decisions did

- **Old rule (worst camera of a group), as it ran:** Vạn Phúc City → Quận 1 alternated between Goong's route and the Điện Biên Phủ route (07:07 ĐBP, 07:22 ĐBP, 07:37 Goong, 07:52 ĐBP) because single cameras flip within 15 min (Bạch Đằng 2: đông → kẹt cứng → đông → đông). The other two trips never changed route.
- **Current rule (median of a group), replayed on the same saved readings:** one switch, at 07:07 (BX Miền Đông packed, verified; ~11 min saved), then Goong's route.
- **Miss of the current rule:** at 07:22 Bạch Đằng 2 was genuinely gridlocked (frame checked), but its group read {kẹt cứng, đông, thông thoáng} (Bạch Đằng 3 and Hàng Xanh 1, a different junction ~300 m away), so the median said đông and the real jam was not counted.

## Other findings

- The Hàng Xanh 3 and 5 feeds print a clock 5–6 min behind the reading time, consistently. Inside the 10-min stale limit, but those feeds lag.
- Direction is not modelled: a jam on one carriageway (Phạm Văn Đồng – Lê Quang Định 2) also counts against trips in the free direction.

## Not changed, and what would fix it

The median vs worst trade-off is real: the median absorbs a red-light queue on one camera (the 11:06 Bạch Đằng 3 case) and also hides a real jam seen by one camera. A 13-second pair cannot tell the two apart; persistence can (a jam survives a full signal cycle, ~60–90 s). Options, best first:
1. Persistence: a third frame ~60 s later only for cameras that read ùn ứ / kẹt cứng (adds ~60 s to a route check), or reuse the same camera's reading from the last ~15 min.
2. Group only cameras at the same junction (~150 m instead of 400 m), so a separate junction cannot outvote a jam.
3. Run the sampler through an evening peak (16:00–19:30) before tuning: it costs ~100–200 Gemini calls, so ideally with a billed key.
