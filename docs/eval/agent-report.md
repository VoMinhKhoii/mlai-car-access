# Agent demo verification, 16/10/2026

Implemented the in-app Trợ lý Vào Được, NDJSON agent API, shared compact engine tools, opt-in paid fallback with a persistent $3 cap, and dependency-free MCP bridge. No commit was made. Backend is running on port 8787 with `AGENT_ALLOW_PAID=0`; `frontend/dist` was rebuilt.

The original prebuild finished all five destinations without being interrupted or run concurrently. `backend/cache/live/areas/demo.json` has 79 parcel records and 6 cached destinations.

The expected Fortuner versus VF 3 contrast does **not** occur with the current engine and completed cache. Both return `nearby`, Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh, 53 m / 1 minute walking. At the door, the lower clear width is 5.49 m; the engine requires 7.84 m for Fortuner and 5.85 m for VF 3 to turn there. The computed reverse distance is 224 m for both, exceeding the 60 m rejection cutoff. This is the engine's way-out check, not a missing parcel cache or a hallucinated vehicle difference. Diagnostic details: `agent-exit-diagnosis.json`.

The tide bulletin does not cover October 16/17. The agent says the tide/flood situation is unverified for these dates. The MCP tide test on September 29 returns five extrema over 36 hours and the official alarm thresholds.

## Final live answers (verbatim)

### Fortuner

Xe Fortuner không nên vào tận cửa Hẻm 220/9 Xô Viết Nghệ Tĩnh do chưa có đường ra phù hợp lúc rời đi. Theo dữ liệu thửa đất hai bên hẻm từ cổng Thông tin quy hoạch TP.HCM, bạn nên đỗ xe tại Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh rồi đi bộ khoảng 53 m (tầm 1 phút) vào điểm đến. Lưu ý, hiện chưa có dự báo triều cho thời gian này nên chưa xác minh được ngập.

Tool calls:

```json
[
  {
    "name": "tim_dia_diem",
    "args": {
      "query": "Hẻm 220/9 Xô Viết Nghệ Tĩnh"
    }
  },
  {
    "name": "lap_ke_hoach",
    "args": {
      "label": "Hẻm 220/9 Xô Viết Nghệ Tĩnh",
      "intent": "park",
      "arrive_at": "2026-10-16T17:00:00+07:00",
      "dwell_min": 120,
      "vehicle_id": "toyota-fortuner",
      "lon": 106.7123911,
      "lat": 10.7992432
    }
  }
]
```

### VF 3 follow-up

Xe VinFast VF 3 cũng không nên vào tận cửa Hẻm 220/9 Xô Viết Nghệ Tĩnh do chưa có đường ra phù hợp lúc rời đi. Theo dữ liệu thửa đất hai bên hẻm từ cổng Thông tin quy hoạch TP.HCM, phương án tốt nhất vẫn là đỗ tại Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh và đi bộ khoảng 53 m (tầm 1 phút). Ngoài ra, hiện chưa có dự báo triều cho thời gian này nên chưa xác minh được tình trạng ngập.

Tool calls:

```json
[
  {
    "name": "lap_ke_hoach",
    "args": {
      "lon": 106.7123911,
      "arrive_at": "2026-10-16T17:00:00+07:00",
      "intent": "park",
      "label": "Hẻm 220/9 Xô Viết Nghệ Tĩnh",
      "vehicle_id": "vinfast-vf-3",
      "lat": 10.7992432,
      "dwell_min": 120
    }
  }
]
```

The request reused the Fortuner `done.contents` unchanged. Destination, 17:00 +07:00 arrival and 120-minute park window are identical; vehicle changes to `vinfast-vf-3`. Gemini thoughtSignature parts remain intact.

### Blind baseline, tools:false

Hẻm 220 Xô Viết Nghệ Tĩnh khá hẹp và thời điểm 17h là giờ cao điểm, xe Fortuner chắc chắn không thể đỗ trong hẻm. Lựa chọn an toàn và thuận tiện nhất là bạn gửi xe tại **bãi hầm Pearl Plaza** (561A Điện Biên Phủ, cách đó khoảng 1 km) rồi gọi Grab vào hẻm. Ngoài ra, bạn có thể hỏi gửi tại các bãi xe ô tô tư nhân quanh khu vực đường Nguyễn Văn Lạc hoặc gần ngã tư Hàng Xanh.

Tool calls:

```json
[]
```

## Spend

Agent testing made **41 free HTTP generation attempts** (including key/quota retries), **0 paid calls**, **$0.000000 paid spend**. No real paid-key test was made. These counters exclude the prebuild already running before this task.

```json
{
  "spent_usd": 0.0,
  "free_calls": 41,
  "paid_calls": 0,
  "reservations": {},
  "limit_usd": 3.0,
  "reserved_usd": 0,
  "paid_enabled": false
}
```

## MCP tools/list output

```json
{
  "tools": [
    {
      "name": "tim_dia_diem",
      "description": "Tìm địa chỉ/hẻm ở TP.HCM. Trả tối đa 3 điểm đã có tọa độ.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string"
          }
        },
        "required": [
          "query"
        ]
      }
    },
    {
      "name": "lap_ke_hoach",
      "description": "Kiểm tra xe vào và ra, bề rộng có nguồn, ngập, luật dừng đỗ, chỗ dừng và quãng đi bộ.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "lat": {
            "type": "number"
          },
          "lon": {
            "type": "number"
          },
          "label": {
            "type": "string"
          },
          "vehicle_id": {
            "type": "string"
          },
          "arrive_at": {
            "type": "string",
            "description": "ISO datetime +07:00"
          },
          "dwell_min": {
            "type": "integer"
          },
          "intent": {
            "type": "string",
            "enum": [
              "park",
              "pickup"
            ]
          },
          "rain_mm_per_h": {
            "type": "number"
          }
        },
        "required": [
          "lat",
          "lon",
          "label",
          "vehicle_id",
          "arrive_at",
          "dwell_min",
          "intent"
        ]
      }
    },
    {
      "name": "muc_trieu",
      "description": "Các đỉnh/chân triều và báo động, tối đa 36 giờ; không phải dự báo ngoài thời gian bản tin.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "start": {
            "type": "string"
          },
          "hours": {
            "type": "integer",
            "maximum": 36
          }
        },
        "required": [
          "start"
        ]
      }
    }
  ]
}
```

## MCP tools/call lap_ke_hoach result

```json
{
  "destination": {
    "lat": 10.7992432,
    "lon": 106.7123911,
    "label": "Hẻm 220/9 Xô Viết Nghệ Tĩnh"
  },
  "vehicle": {
    "id": "toyota-fortuner",
    "label": "Toyota Fortuner",
    "mirror_width": 2.105
  },
  "window": {
    "arrive": "2026-10-17T17:00:00+07:00",
    "depart": "2026-10-17T19:00:00+07:00",
    "dwell_min": 120,
    "tide_arrive": {
      "level_m": null,
      "alarm": null
    },
    "tide_depart": {
      "level_m": null,
      "alarm": null
    },
    "rain": []
  },
  "tide_note": "Chưa có dự báo triều cho thời gian này; chưa xác minh được ngập.",
  "verdict": {
    "code": "nearby",
    "headline": "Đỗ tại Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh, đi bộ 53 m (~1 phút)",
    "detail": "Xe không nên vào tận cửa"
  },
  "timing": null,
  "stop_points": [
    {
      "name": "Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh",
      "kind": "street",
      "walk": {
        "meters": 53,
        "minutes": 1
      },
      "fit": "fits",
      "width": {
        "lo": 7.75,
        "hi": 8.05,
        "label": "Đường phố",
        "top_tier": "Official",
        "source": "Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)",
        "detail": "Khoảng cách hai thửa đất đối diện trừ 1 m (đo 1 mặt cắt): hẹp nhất 7,8 m (thửa cách nhau 8,8 m)"
      },
      "way_out": "Lùi 8 m rồi quay đầu tại ngã ba",
      "flood": {
        "status": "passable",
        "depth": null,
        "at": null
      },
      "legality": {
        "status": "Permitted",
        "rule": {
          "code": "no-rule",
          "status": "Permitted",
          "text": "Không có quy định cấm dừng/đỗ được biết tại vị trí này",
          "citation": "Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4"
        }
      },
      "lot": null,
      "fail_reasons": []
    },
    {
      "name": "Hẻm 502 Điện Biên Phủ",
      "kind": "street",
      "walk": {
        "meters": 339,
        "minutes": 5
      },
      "fit": "fits",
      "width": {
        "lo": 6.48,
        "hi": 6.78,
        "label": "Đường phố",
        "top_tier": "Official",
        "source": "Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)",
        "detail": "Khoảng cách hai thửa đất đối diện trừ 1 m (đo 1 mặt cắt): hẹp nhất 6,5 m (thửa cách nhau 7,5 m)"
      },
      "way_out": "Phải lùi 42 m (quá giới hạn 30 m) mới quay đầu được",
      "flood": {
        "status": "passable",
        "depth": null,
        "at": null
      },
      "legality": {
        "status": "Permitted",
        "rule": {
          "code": "no-rule",
          "status": "Permitted",
          "text": "Không có quy định cấm dừng/đỗ được biết tại vị trí này",
          "citation": "Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4"
        }
      },
      "lot": null,
      "fail_reasons": []
    },
    {
      "name": "Nhánh cạnh Xô Viết Nghệ Tĩnh",
      "kind": "street",
      "walk": {
        "meters": 129,
        "minutes": 2
      },
      "fit": "fits",
      "width": {
        "lo": 4.74,
        "hi": 6.01,
        "label": "Ô tô tránh",
        "top_tier": "Official",
        "source": "Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)",
        "detail": "Khoảng cách hai thửa đất đối diện trừ 1 m (đo 2 mặt cắt): hẹp nhất 4,7 m (thửa cách nhau 5,7 m)"
      },
      "way_out": "Phải lùi 53 m (quá giới hạn 30 m) mới quay đầu được",
      "flood": {
        "status": "passable",
        "depth": null,
        "at": null
      },
      "legality": {
        "status": "Unverified",
        "rule": {
          "code": "lane-unknown",
          "status": "Unverified",
          "text": "Chưa đủ bằng chứng hẻm rộng hơn 5.5 m (đủ hai làn xe)",
          "citation": "Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4"
        }
      },
      "lot": null,
      "fail_reasons": []
    }
  ],
  "door": {
    "name": "Trước cửa nhà",
    "kind": "door",
    "walk": {
      "meters": 0,
      "minutes": 0
    },
    "fit": "fits",
    "width": {
      "lo": 5.49,
      "hi": 5.79,
      "label": "Ô tô tránh",
      "top_tier": "Official",
      "source": "Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)",
      "detail": "Khoảng cách hai thửa đất đối diện trừ 1 m (đo 1 mặt cắt): hẹp nhất 5,5 m (thửa cách nhau 6,5 m)"
    },
    "way_out": "Không có đường ra phù hợp lúc rời đi (hẻm cụt hoặc ngập lúc về)",
    "flood": {
      "status": "passable",
      "depth": null,
      "at": null
    },
    "legality": {
      "status": "Unverified",
      "rule": {
        "code": "lane-unknown",
        "status": "Unverified",
        "text": "Chưa đủ bằng chứng hẻm rộng hơn 5.5 m (đủ hai làn xe)",
        "citation": "Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4"
      }
    },
    "lot": null,
    "fail_reasons": [
      "Không có đường ra phù hợp lúc rời đi (hẻm cụt hoặc ngập lúc về)"
    ]
  },
  "standard_route": {
    "unfit_ways": [
      {
        "way_id": 192512284,
        "name": "Nhánh cạnh Xô Viết Nghệ Tĩnh",
        "label": "Hẻm xe hơi",
        "fit": "unknown",
        "lo": 2.2,
        "hi": 3.89
      }
    ]
  }
}
```

## Verification

- `PYTHONPATH=backend AGENT_ALLOW_PAID=0 python3 -m unittest discover -s backend/tests -v`: six tests pass. Signed parts survive the next call and follow-up; baseline has no tools or paid permission; six tool rounds are enforced; free key rotation passes 429/403/503; paid usage includes thought tokens; next-call budget guard refuses overspend; missing tide coverage is counted.
- `cd frontend && npm run build`: TypeScript + Vite pass, final dist rebuilt. Existing large-chunk warning remains.
- `npm run lint`: exits 0; only existing warnings in ds/ui, Directions and Result. No Agent warnings.
- `git diff --check`: passes.
- JSON-RPC initialize, notifications/initialized, tools/list, tools/call and ping tested through stdin/stdout. Additional tests cover tide, invalid vehicle, unknown method and malformed JSON.
- Real browser: baseline bubble plus live trace, Fortuner plan, VF 3 follow-up changing the vehicle selector, and VF 5 pickup plan all work. VF 5 chooses Xô Viết Nghệ Tĩnh with 109 m / 2 minute walk. No app error was shown.
- Mobile at 390×844: assistant is a bottom sheet; no horizontal overflow. The mic button is visible on supporting browsers. Physical microphone transcription was not tested.
- Paid fallback uses file locking plus persisted reservations across processes. Conservative prices: $1/M input and $6/M candidates + thought output. The next request reserves UTF-8 input bytes plus overhead and its entire output allowance. Ambiguous paid network failures retain the ceiling as spend. Real paid access stays disabled for this test session.

## Screenshots

- `docs/eval/agent-mid-run.png`: actual panel while generating.
- `docs/eval/agent-mid-run-latest.png`: latest pickup run while generating.
- `docs/eval/agent-map-updated.png`: Fortuner plan and tool trace after map update.
- `docs/eval/agent-vf3-map.png`: VF 3 chat follow-up and changed vehicle selector.
- `docs/eval/agent-mobile.png`: 390 px bottom sheet after follow-up.
- `docs/eval/agent-pickup-map.png`: final panel layout with the destination and stops visible between panels.

## Implementation files

- `backend/app/agent.py`: three engine tools, compact summary shared with MCP, fixed Gemini model, signed history, NDJSON loop, neutral blind baseline.
- `backend/app/agent_budget.py`: persisted paid usage and reservation guard, free attempt counters.
- `backend/app/main.py`: `/api/agent`, `/api/agent/tools`, `/api/agent/tool/{name}`, extended `/api/budget`.
- `backend/tests/test_agent.py`: six offline contract/guard tests, no real Gemini calls.
- `frontend/src/components/Agent.tsx`: chat, live tool steps, suggestions, comparison, speech input, errors and follow-up history.
- `frontend/src/components/Agent.css`: existing design tokens, reduced motion and mobile sheet.
- `frontend/src/api.ts`: typed NDJSON streaming helper.
- `frontend/src/App.tsx`: assistant entry point, exact plan callback, rain/dwell state, space for the panel in map bounds.
- `mcp/vaoduoc_mcp.py`: standard-library MCP stdio bridge.
- `mcp/README.md`: startup, Claude Desktop / Claude Code config, budget switch.
- `frontend/dist`: generated final build (ignored by git).
- `docs/eval/agent-*`: request/response logs, MCP outputs, screenshots, diagnostics and this report.

The pre-existing edits and ongoing work in other files were outside this implementation. No dependency versions were changed. `npm ci` installed the lockfile dependencies; npm reported two existing dependency advisories. The mock paid guard is tested, but real paid billing and physical speech recognition were intentionally not exercised.

