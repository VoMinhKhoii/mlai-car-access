# Research 06: Vehicle profiles, water depth, alley geometry

Collected 2026-09-28 by a research agent. Data: `../../data/vehicles/vn_car_profiles.csv` (34 models, source URL per row), `geometry.py` (formulas as code), `_geometry_out.txt` (results per model). The agent's search budget ran out before every gap could be filled.

## Best sellers 2025 (VAMA + VinFast + Hyundai Thành Công, total 604,134) [reported]
1. VF 3 – 44,585
2. VF 5 – 43,913
3. Limo Green – 27,127
4. VF 6 – 23,291
5. Xpander – 19,891
6. Ranger – 18,692
7. CX-5 – 17,262
8. Xforce – 15,254
9. Yaris Cross – 14,601
10. Vios – 13,424

August 2026 is still led by VF 3, VF 5, Limo Green and VF 6. Sources: https://oto.com.vn/thi-truong-o-to/top-10-xe-ban-chay-nhat-nam-2025-articleid-p9v1iiy, https://thanhnien.vn/10-o-to-ban-chay-nhat-viet-nam-nam-2025-o-to-dien-vinfast-ap-dao-185260113213157679.htm

## Ranges (cars, excluding vans and trucks)

| Measure | Range | Notes |
|---|---|---|
| Body width | 1.595 (Morning) – 2.065 m (VF 9 Plus) | median 1.83 m |
| Width incl. mirrors | 1.748 (VF 3) – 2.254 m (VF 9) | only 8 models publish it; mirrors add 0.07–0.41 m |
| Length | 3.19 – 5.36 m | |
| Min turning radius | 4.5 (VF 3) – 7.33 m (VF 9) | median 5.35 m; no maker says whether it's measured at tyre, kerb or body |
| Ground clearance | 133 (Vios) – 279 mm (Fortuner) | |
| Vans (Transit, Solati) | 2.04–2.07 m body; 2.474 m Transit with mirrors; 2.49–2.76 m tall | |

Gaps and conflicts:
- **Turning radius not published:** Grand i10, Accent, C-Class, Territory, H150.
- **Estimated radius:** Limo Green and VF 8 (2026) use 5.34 m, the agent's estimate from the steering angle in the manual, not a published figure.
- **Conflicting figures:**
  - C-Class width appears as 1,820 and 1,890 mm.
  - VF 7 height appears as 1,590 and 1,636 mm; its clearance as 184 and 190 mm.

## Safe water depth
- **Published wading depths** [documented]:
  - Ranger and Everest: 800 mm at a steady 7 km/h (Ford AU).
  - Fortuner: 700 mm, for the AU 2.8 diesel only. The VN 2.7 petrol has no published figure.
  - Hilux 700 mm, D-Max 800 mm.
  - Hyundai, Kia, Honda, Mazda and Mercedes publish nothing.
- **VinFast** (every VN owner manual) [documented]:
  - Water must not exceed ground clearance.
  - Drive under 10 km/h, and never stop or reverse in water.
  - Door-sill water can reach the high-voltage system.
  - Flood damage isn't covered by warranty.
  - IP67 on the battery is a still-water lab rating and doesn't make the car a boat.
- **Toyota VN:** don't enter water deeper than 25 cm (about half the wheel), and never restart a stalled engine [documented] https://www.toyota.com.vn/tin-tuc/thong-tin-bo-tro/thuy-kich-39236
- **Moving water:** 30 cm carries most cars away; 60 cm carries SUVs (US NWS) [documented].
- **Thủy kích (hydrolock) insurance:**
  - Excluded from standard physical-damage cover. The PVI add-on costs 0.1% of car value a year, with a 10% or 2M VND deductible, and pays nothing if the engine was restarted [documented] https://online.pvi.com.vn/kien-thuc/bao-hiem-thuy-kich-la-gi
  - Tasco Insurance's page doesn't mention thủy kích.
- **Air-intake height:** no maker publishes it.

## Geometry references
- **QCVN 06:2022/BXD + Amendment 1:2023 (fire safety):**
  - Fire-truck road ≥3.5 m wide, ≥4.5 m clear height.
  - A dead end >46 m needs a turnaround: triangle with 7 m sides, 12 m square, 10 m diameter circle, or 5 × 20 m rectangle.
- **TCVN 13592:2022 (urban roads):**
  - Design car 5.79 × 2.13 m, turning radius 7.26 m outer / 4.39 m inner.
  - Dead-end turnarounds: circle of 10 m radius, or 10 × 20 m; L, T and Y shapes allowed for small alleys.
  - Kerb radius ≥3 m in residential areas.
- **TCVN 4054:2005:** car parking space 2.5 × 5.0 m.
- **Draft QCVN 07-11:2025/BXD (parking; status unverified):**
  - Space ≥2.3 × 5.0 m (5.4 m parallel); motorbike space 0.75 × 2.0 m.
  - Clearances: 0.6 m car to car, 0.6 m car to wall, 0.3 m car to column.
  - One-way lane ≥4 m.
- **Motorbikes** [documented]: Vision 1,925 × 686 mm; Wave Alpha 1,914 × 688 mm; SH160i 2,090 × 739 mm.

## Formulas (in `geometry.py`)
Units are metres. W = body width; c = clearance per side (default 0.3). Idealised full-lock model.
1. **Pass through:** Clear Width ≥ W_mirror + 2c. Add 0.69–0.74 m for motorbikes parked along one side, or about 2.0 m if parked nose-in.
2. **Get out of the car:** Clear Width ≥ W + c + 0.6 (about 0.9 m per door is comfortable).
3. **Turning radii:**
   - Rear-axle radius: Rr = √(R² − WB²) − T/2, where R is the published radius, WB the wheelbase and T the track (default W − 0.28).
   - Inner body: r_in = Rr − W/2.
   - Front swing: r_out = √((Rr + W/2)² + (WB + FOH)²), where FOH is front overhang (default 0.45 × (L − WB)).
   - Tail swing: r_tail = √((Rr + W/2)² + ROH²), where ROH is rear overhang (default 0.55 × (L − WB)).
4. **Turn into an alley in one move** (street width A, alley width B, each net of 2c):
   - Let y = r_tail − A.
   - If y ≥ 0: B ≥ r_out − √(r_in² − y²), which needs y ≤ r_in.
   - If y < 0: B ≥ max(Rr + W/2, √(r_out² − y²)) − r_in.
   - Checked against a brute-force sweep of the vehicle outline (±0.08 m).
5. **U-turn in one go:** width ≥ r_out + r_tail + 2c.
6. **Turn around at a dead end:** hard lower bound √(L² + W²) + 2c. 3-point and 5-point minimums come from a simulation.

The model assumes instant full lock, so real drivers need more room. Validate with the field measurements.

## Proposed Size Classes (worst case per limit, c = 0.3)
"est" = body width + 0.25 m where mirror width isn't published.

| Class | Models | Width incl. mirrors | Max R | Min wading | Alley to turn in from 4 / 6 m street | U-turn | 3-point |
|---|---|---|---|---|---|---|---|
| XS | VF 3, Morning, i10 | 1.93 (est) | 4.7 | 175 mm | 3.3 / 2.9 | 9.9 | 6.2 |
| S | Vios, City, Accent, Mazda3, VF 5/6, Yaris Cross, Creta, Seltos, Xforce, Corolla Cross, Xpander, CX-5 | 2.10 (est) | 5.5 | 160 mm | 4.1 / 3.5 | 11.7 | 7.5 |
| M | Camry, C-Class, VF 7/8, Limo Green, Territory, Innova Cross, Fortuner, Santa Fe, Everest | 2.21 | 6.2 | 170 mm | 4.5 / 3.7 | 13.0 | 8.0 |
| L | VF 9, Carnival, Ranger, H150, QKR | 2.26 (est) | 7.33 | 175 mm | 5.3 / 4.0 | 15.3 | 9.1 |
| XL | Transit, Solati | 2.47 | 6.7 | none published (250 mm Toyota VN guidance) | 5.3 / 4.4 | 13.9 | 9.1 |

- The Min wading column uses VinFast's "water no higher than ground clearance" rule. For ICE cars with no published figure, cap at 250 mm (Toyota VN). The lowest clearance in S is 133 mm (Vios).
- A Fortuner or Ranger only gets its 700–800 mm wading figure when the exact Vehicle Model is chosen. That's the payoff of the precise path.

## VETC and registration
- **Toll groups** (Decree 130/2024, Circular 32/2024) are based on seats and payload, not size. Group 1 covers everything from a VF 3 to a Fortuner to a 1.5 t truck [documented].
- **ETC accounts** (Decree 119/2024) hold plate, VIN, seats, payload and type. No brand, model or dimensions. Data goes to third parties only with consent or an authority request.
- **Registration certificate:** has brand and model code.
- **Inspection certificate:** has overall dimensions ("kích thước bao"). Electronic certificates have been available via VNeID since 2026-03-01 [reported].
- **Privacy:**
  - Personal Data Protection Law 91/2025 and Decree 356/2025 are in force from 2026-01-01; Decree 13/2023 is repealed.
  - A plate number is basic personal data; location from positioning services is sensitive.
  - Consent must be explicit and per purpose.

## Open questions
- Is QCVN 06:2022 still current under the 2024 fire law? Has the draft QCVN 07-11:2025 been issued? What replaces HCMC's alley-width rule?
- Measure water against ground clearance or the door sill?
- Validate the turn-in widths against real alleys.
