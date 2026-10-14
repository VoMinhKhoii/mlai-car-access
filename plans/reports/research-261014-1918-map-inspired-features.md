---
type: research
date: 2026-10-14 19:18 (+07)
branch: fix/collapsible-result-cards @ 38beedf
topic: Ý tưởng UI + feature cho Vào Được, tham khảo map lớn 2025–2026
searches: 5/5
---

# Research Report: Ý tưởng "wow" cho Vào Được từ các map lớn

## Executive Summary
Các map lớn 2025–2026 đều đi một hướng: **AI hiểu câu hỏi tự nhiên** (Google Ask Maps, Mapbox MapGPT), **xem trước bằng hình 3D** (Google Immersive Navigation, Mapbox 3D Lanes), **báo cáo bằng giọng nói** (Waze Conversational Reporting), **hướng dẫn lúc đến nơi** (Google arrival guidance: lối vào, bãi đỗ, lưu chỗ đỗ), **nhớ thói quen người dùng** (Apple Visited Places, Preferred Routes) và **ảnh đường phố crowdsource** (Grab KartaCam/KartaView).

Không map nào trả lời câu hỏi lõi của Vào Được: *xe tôi có vào, đỗ và ra khỏi hẻm này không, vào giờ đó*. Lợi thế của repo: đã có mô phỏng quay đầu (`geometry.k_turn`, `body_corners`), mức bằng chứng, dự báo ngập theo giờ rời. Ý tưởng "wow" nhất là **biến các con số đó thành hình**: cho người dùng *thấy* thân xe của họ trong bề rộng hẻm và đường quay đầu, giống Immersive Navigation nhưng cho hẻm.

Ràng buộc giữ nguyên: mọi tính năng mới chỉ hiển thị/thu bằng chứng, không tự đổi `strict`, `decisive_clearance`, `turn_verified`.

## Research Methodology
- Sources: 5 search, ~30 nguồn (blog Google, TechCrunch, 9to5Google, Mapbox, Grab, Apple/MacRumors, Edaily).
- Khoảng thời gian: 2022 (KartaCam) → 03/2026 (Ask Maps, Immersive Navigation).
- Từ khóa: Google Maps Gemini/Ask Maps/Immersive Navigation/Know before you go; Apple Maps iOS 26; Waze conversational reporting; Mapbox 3D Lanes/MapGPT; GrabMaps KartaCam; Naver/Kakao.
- Repo đã đối chiếu: `geometry.py`, `vehicles.py`, `plan.py`, `evidence.py`, `MapView.tsx`, `Result.tsx`, `Directions.tsx`, `App.tsx`.

## Key Findings

### 1. Map lớn đang làm gì (2025–2026)
| Map | Tính năng | Nguồn |
|---|---|---|
| Google | Ask Maps (Gemini, hỏi câu phức tạp), Immersive Navigation (3D, chi tiết làn, giọng nói tự nhiên) — 03/2026 | [blog.google](https://blog.google/products-and-platforms/products/maps/ask-maps-immersive-navigation/), [TechCrunch](https://techcrunch.com/2026/03/12/google-maps-is-getting-an-ai-ask-maps-feature-and-upgraded-immersive-navigation/) |
| Google | "Know before you go": mẹo tóm tắt (lối vào, đỗ xe); dự đoán số trạm sạc trống khi đến — 11/2025 | [9to5Google](https://9to5google.com/2025/11/19/google-maps-review-nicknames/), [TechCrunch](https://techcrunch.com/2025/11/19/google-maps-adds-gemini-powered-tips-section-ev-charger-availability-predictions-and-more/) |
| Google | Arrival guidance: tô sáng lối vào, gợi ý bãi đỗ, nhắc lưu chỗ đỗ, đi bộ từ xe tới cửa | [blog.google](https://blog.google/products/maps/gemini-google-maps-navigation-updates/) |
| Google | Navigation with Gemini: hỏi/báo giao thông bằng hội thoại khi lái — 11/2025 | [blog.google](https://blog.google/products-and-platforms/products/maps/gemini-navigation-global), [9to5Google](https://9to5google.com/2025/11/05/google-maps-gemini-navigation/) |
| Waze | Conversational Reporting: nói tự nhiên, Gemini phân loại, hỏi lại khi thiếu thông tin — 10/2025 | [9to5Google](https://9to5google.com/2025/10/06/waze-conversational-reporting-voice-command-feature/) |
| Apple | Visited Places (nhật ký nơi đã đến), Preferred Routes (nhớ tuyến quen, cảnh báo sự cố) — iOS 26 | [Gadget Hacks](https://apple.gadgethacks.com/news/apple-maps-visited-places-in-ios-26-what-it-does-and-how-it-works/) |
| Mapbox | 3D Lanes, hiển thị xe/người quanh xe, điểm đến có "arrival points" tới lối vào/bãi đỗ; MapGPT | [Mapbox CES 2025](https://www.mapbox.com/blog/mapbox-at-ces-2025-driving-the-future-of-navigation), [3D Lanes](https://www.mapbox.com/blog/never-miss-a-turn-again-with-mapbox-3d-lanes) |
| Grab | KartaCam gắn mũ/kính lái xe để thu ảnh đường; KartaDashCam xác thực sự cố ≤10 phút; KartaView ảnh đường mở | [Grab KartaCam 2](https://www.grab.com/sg/inside-grab/stories/kartacam-2-grab-new-map-making-camera-launch), [GrabMaps 2025](https://grabmaps.grab.com/resources/2025-year-in-review-building-the-map-that-moves-southeast-asia-and-beyond), [KartaView](https://kartaview.org/landing) |
| Naver | CCTV thời gian thực trong dẫn đường; dẫn đường đi bộ bằng giọng nói — 06/2026 | [Naver Map](https://app.map.naver.com/), [Edaily](https://en.edaily.co.kr/news/eda202606195159/) |

### 2. Repo đã có gì để tận dụng
- `geometry.k_turn` mô phỏng quay đầu nhiều điểm bằng `body_corners` từng tư thế; hiện chỉ trả `(moves, length)` — **quỹ đạo bị bỏ đi**.
- `geometry.min_alley_for_turn_in` tính bề rộng tối thiểu để rẽ vào một nhịp.
- `Directions.tsx:188` chỉ hiện số "Quay đầu 3 điểm ≥ x m".
- `MapView.tsx:59` đang **tắt** mọi lớp `fill-extrusion` (3D tòa nhà).
- Dự báo ngập theo giờ rời (`timing.or_after_at`, `way_out.flood`) đã có.
- `/api/confirm`, `/api/blockage` + `reports.submit` + operator review đã có.

## Comparative Analysis — ý tưởng xếp theo wow / công sức

| # | Ý tưởng | Lấy cảm hứng từ | Wow | Công sức | Hook trong repo |
|---|---|---|---|---|---|
| 1 | **Bóng xe trên hẻm + mô phỏng quay đầu** | Immersive Navigation, Mapbox 3D Lanes | Rất cao | Trung bình | `k_turn`, `body_corners`, `MapView` |
| 2 | **Cảnh báo giờ về** cho xe đang đỗ | Apple Preferred Routes, Google EV prediction | Cao | Thấp–TB | flood depart, `live_hydro` |
| 3 | **Hỏi Vào Được** bằng câu tự nhiên | Ask Maps, MapGPT | Cao | TB | `ai._call`, `PlanRequest` |
| 4 | **Báo hẻm bằng giọng nói** | Waze Conversational Reporting | Cao | TB | `/api/blockage`, `/api/confirm`, `ai._gate` |
| 5 | **Lưu ý khi đến** (thẻ tóm tắt) | Know before you go | TB | Thấp | `checks`, `unverified_reasons` |
| 6 | **Hẻm quen của tôi** | Apple Visited Places | TB | Thấp | `/api/confirm`, localStorage |
| 7 | **Quay clip khi vào hẻm** (dashcam điện thoại) | Grab KartaCam | Cao | Cao | pipeline CV, review |

### Chi tiết

**1. Bóng xe trên hẻm + mô phỏng quay đầu (đề xuất làm demo chính).**
- Trên map, vẽ hình chữ nhật thân xe **đúng tỉ lệ** (từ `body_width`, `length`, gương) đặt trong dải bề rộng hẻm `lo..hi` tại điểm hẹp nhất. Người dùng nhìn là hiểu "còn 20 cm mỗi bên".
- Ở điểm dừng/nút quay đầu: animation các tư thế từ `k_turn` (cần trả về danh sách pose thay vì chỉ đếm) — "quay 3 nhịp, cần 7,2 m chiều dài".
- Ở đầu hẻm: cung rẽ vào từ `min_alley_for_turn_in`.
- Bắt buộc ghi rõ: *mô phỏng trên bề rộng thấp nhất đã biết, hành lang thẳng; chưa phải bằng chứng*. Nếu `decisive_clearance=false` → vẽ dải bề rộng dạng nét đứt/mờ.
- Rủi ro: hình đẹp tạo cảm giác chắc chắn giả. Giảm bằng cách luôn vẽ theo `lo` (xấu nhất) và nhãn tier.

**2. Cảnh báo giờ về.**
- Sau khi người dùng chọn điểm dừng và "Tôi đã đỗ ở đây", lưu (stop, giờ rời dự kiến). Định kỳ chạy lại check ngập đường ra; nếu `way_out.flood` chuyển `risky/blocked` → thông báo "Đường ra dự kiến ngập lúc 18:10, nên rời trước 17:40".
- Đây là câu chuyện mạnh nhất cho người dùng TP.HCM mùa triều cường. Cần Web Push hoặc PWA notification.

**3. Hỏi Vào Được.**
- Câu: "Fortuner, 6 giờ chiều nay mưa to, vào 123/4 Xô Viết Nghệ Tĩnh đỗ 2 tiếng được không?" → LLM chỉ **điền** `PlanRequest` (vehicle_id, lat/lon qua search, arrive/depart, rain); planner deterministic trả kết quả; LLM tóm tắt **chỉ từ** `checks` + nguồn.
- Không để LLM tự kết luận vào được/không — cùng nguyên tắc `ai._gate` "model extracts, never publishes".

**4. Báo hẻm bằng giọng nói.**
- "Đầu hẻm có xe ba gác đậu chắn" / "vào được nhưng phải gập gương" → LLM phân loại thành `blockage` hoặc `confirm(result=tight)` + câu hỏi tiếp nếu thiếu (Waze cũng hỏi lại). Vẫn qua `reports.submit` + duyệt.
- Kết hợp đề xuất trước: thêm câu hỏi "ra bằng cách nào" → `way_out_claims`.

**5. Lưu ý khi đến.** Thẻ 3–4 dòng sinh **deterministic** từ dữ liệu sẵn: đoạn hẹp nhất, cách ra (lùi bao nhiêu m), giờ ngập, đỗ ở đâu + đi bộ. Hợp với thẻ đã gập ở commit `38beedf`: thẻ này là thứ luôn hiện.

**6. Hẻm quen của tôi.** Lưu local (không gửi server) các hẻm đã xác nhận "vào được" với xe đang chọn → badge "Bạn đã vào hẻm này 3 lần bằng Vios". Chỉ cá nhân, không thành bằng chứng chung trừ khi người dùng gửi confirm.

**7. Quay clip khi vào hẻm.** Tài xế bật camera điện thoại khi vào hẻm (giống KartaCam). Từ clip: xe có trong hẻm (cận dưới bề rộng), vật cản, cả việc ra được. Công sức cao nhất; để sau.

## Implementation Recommendations

### Quick start (thứ tự đề xuất)
1. **#1 Bóng xe + quay đầu**: backend trả pose list từ `k_turn`; endpoint `/api/vehicles/{id}/maneuver?width=`; layer GeoJSON polygon trong `MapView`. Demo mạnh nhất cho hackathon.
2. **#5 Lưu ý khi đến**: rẻ, làm cùng lúc.
3. **#2 Cảnh báo giờ về**: PWA + job kiểm tra lại.
4. **#3/#4**: dùng chung một lớp "LLM điền form, không kết luận".

### Code sketch (#1)
```python
# geometry.py — k_turn hiện chỉ đếm; thêm bản trả quỹ đạo
def k_turn_path(W, L, WB, R, D, c=0.3, **kw) -> list[tuple[float, float, float]] | None:
    """Same simulation as k_turn, returning (x, y, psi) per step for display."""
```
```ts
// MapView: mỗi pose -> polygon body_corners chiếu về lat/lon quanh nút quay đầu
m.addSource('maneuver', { type: 'geojson', data: EMPTY })
m.addLayer({ id: 'maneuver-body', type: 'fill', source: 'maneuver',
  paint: { 'fill-color': css('--brand'), 'fill-opacity': ['get', 'alpha'] } })
```

### Common Pitfalls
- Hình đẹp ≠ bằng chứng: luôn vẽ theo bề rộng thấp nhất và gắn tier.
- LLM không được viết kết luận an toàn; chỉ điền form và tóm tắt.
- Street View không dùng được làm dữ liệu (flag `google_lookup` của repo + điều khoản Google).
- Bật lại `fill-extrusion` 3D tòa nhà: đẹp nhưng nặng mobile và OSM VN thiếu chiều cao nhà → không ưu tiên.

## Resources & References
- Google Ask Maps + Immersive Navigation: https://blog.google/products-and-platforms/products/maps/ask-maps-immersive-navigation/
- Google Know before you go / EV prediction: https://techcrunch.com/2025/11/19/google-maps-adds-gemini-powered-tips-section-ev-charger-availability-predictions-and-more/
- Google arrival guidance: https://blog.google/products/maps/gemini-google-maps-navigation-updates/
- Waze Conversational Reporting: https://9to5google.com/2025/10/06/waze-conversational-reporting-voice-command-feature/
- Apple Maps iOS 26: https://apple.gadgethacks.com/news/apple-maps-visited-places-in-ios-26-what-it-does-and-how-it-works/
- Mapbox 3D Lanes: https://www.mapbox.com/blog/never-miss-a-turn-again-with-mapbox-3d-lanes
- GrabMaps 2025 / KartaCam: https://grabmaps.grab.com/resources/2025-year-in-review-building-the-map-that-moves-southeast-asia-and-beyond , https://www.grab.com/sg/inside-grab/stories/kartacam-2-grab-new-map-making-camera-launch
- KartaView: https://kartaview.org/landing
- Naver walking voice nav: https://en.edaily.co.kr/news/eda202606195159/

## Next Steps
1. Chọn 1–2 ý tưởng để lên plan (`ak-plan`).
2. Nếu chọn #1: kiểm tra `k_turn` có đủ thông tin pose để dựng lại (đọc `geometry.py:67-106`).
3. Nếu chọn #2: kiểm tra frontend đã là PWA chưa (service worker).

## Unresolved Questions
- Giấy phép ảnh KartaView có cho phép trích xuất dữ liệu làm bằng chứng không — chưa kiểm (hết ngân sách tìm kiếm).
- Naver/Kakao có cảnh báo hẻm hẹp cho ô tô không — search không ra bằng chứng.
- Hackathon chấm UI demo hay độ đúng dữ liệu nhiều hơn — ảnh hưởng thứ tự #1 vs #2.
