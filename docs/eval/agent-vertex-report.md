# Vertex paid routing fix — 2026-10-17

Implemented, uncommitted. The endpoint and shared daily-quota cooldown are fixed. The paid plain smoke succeeded; the paid function-calling smoke failed before returning usage metadata. Live Vertex multi-turn signature acceptance is **not proven**. No key values were printed or written into these artifacts.

## Changes

- `backend/app/agent.py`: paid fallback uses Vertex express mode; `AGENT_PAID_ENDPOINT` optionally supplies the complete endpoint URL. Free keys remain on AI Studio. Exhausted daily quota stops key rotation immediately, and the local free-call ceiling permits paid fallback instead of bypassing it.
- `backend/app/agent_budget.py`: shared, locked daily-project cooldown until next Pacific midnight (`America/Los_Angeles`, including DST). Tracks thinking tokens separately as well as including them in output charges. The hard $3 cap, reservations, and full-reservation charge for ambiguous failures remain intact.
- `backend/app/ai.py`: the generic free-key rotation also observes and sets this same project cooldown.
- `backend/tests/test_agent_vertex.py`: eight offline tests covering routing, opt-in, daily versus transient errors, skipping the other eleven keys, persistence/reset/DST, fallback, and exact signed function-call parts through HTTP requests and subsequent conversation turns.
- `mcp/README.md`: corrects paid endpoint and quota documentation.
- This report and `agent-vertex-smoke.json`: reproducible observations and verbatim answers.

Existing signed function-call parts were already retained exactly by the agent loop; the new HTTP-boundary tests verify this for the Vertex route. No signature bypass was added.

## Validation

`PYTHONPATH=backend:. python3 -m pytest backend/tests pipelines/test_*.py -q`

**121 passed, 49 subtests passed**, four dependency/deprecation warnings. Backend-only run: 46 passed, 28 subtests passed. No commits. The listener on 8787 was not restarted or stopped.

Google's express-mode endpoint reference confirms the global publisher-model route without project/location path segments: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/express-mode/api-reference>. The free quota documentation states project-scoped quotas and Pacific-midnight daily reset: <https://ai.google.dev/gemini-api/docs/rate-limits>.

## Paid smoke and accounting

Two paid generate attempts were made, with no retry. AI Studio keys were excluded only in the temporary paid smoke harness so the test exercised paid fallback. The configured paid key authenticated successfully using the `x-goog-api-key` header; no credential was placed in the URL.

1. Plain `gemini-3.5-flash` inference succeeded. Answer, verbatim: `Vertex OK.` Ledger charge: **$0.000522**.

Real usage metadata:

```json
{
  "promptTokenCount": 6,
  "candidatesTokenCount": 3,
  "totalTokenCount": 63,
  "trafficType": "ON_DEMAND",
  "promptTokensDetails": [
    {
      "modality": "TEXT",
      "tokenCount": 6
    }
  ],
  "candidatesTokensDetails": [
    {
      "modality": "TEXT",
      "tokenCount": 3
    }
  ],
  "thoughtsTokenCount": 54
}
```

2. The Fortuner function-call smoke used HTTP `/api/agent` on 8788 with `AGENT_ALLOW_PAID=1`. Its disposable harness scheduled the real geocoder before the paid request, supplied a short instruction, forced the real `lap_ke_hoach` declaration, and capped output at 256 tokens. The planned final answers used the existing deterministic `grounded_answer`; this was deliberately a bounded harness, **not the ordinary model-synthesized-answer loop**. Free Vertex `countTokens` returned 284 input tokens. The paid generation failed without usable response/usage metadata; the HTTP stream ended in an error before a plan call was emitted. It returned no signed parts and no answer. The VF 3 paid turn was not run.

The ledger conservatively charged the failed attempt's entire reservation, **$0.010818**, including its input-byte allowance and 4,096-token safety margin. Ledger total for this task: **$0.011340**, no outstanding reservations. The preflight token-based estimate for that failed attempt was $0.002730 at the output ceiling, but actual billed usage cannot be established without provider metadata; this is not an invoice. The ledger exceeded the requested one-cent smoke amount because of the ambiguous-failure charge, so no further paid attempt was made. Historical paid-attempt count: 1 → 3; this task added exactly 2 attempts.

The failed `/api/agent` error, verbatim:

> Nguồn dữ liệu tạm gián đoạn. Bạn có thể thử lại.

## Normal API fallback answers (paid disabled)

After the failed smoke, the temporary harness was stopped and replaced by the normal app on 8788, with paid disabled and an absolute free-call ceiling of 186. These are real engine-backed conservative fallback responses, **not paid-model answers**. Both returned HTTP 200 and ended with `done`.

Fortuner request: `Tôi lái Fortuner tới Hẻm 113/4 Võ Duy Ninh, Bình Thạnh, lúc 19:00 ngày 2026-10-17, đỗ 120 phút. Vào được không?`

Answer, verbatim:

```
Chưa đủ bằng chứng để khẳng định
Đường Võ Duy Ninh; đi bộ 35 m; nguồn: OSM phân loại đường.
Hẻm 75 Nguyễn Hữu Cảnh; đi bộ 58 m; nguồn: OSM phân loại đường.
Bằng chứng có thể chỉ là suy luận; chưa xác minh cổng địa chính hoặc khoảng thông thủy tại chỗ. Không coi thiếu dữ liệu là an toàn.
```

Follow-up using the returned conversation contents: `Còn xe VF 3 của vợ tôi?`

Answer, verbatim:

```
Chưa đủ bằng chứng để khẳng định
Đường Võ Duy Ninh; đi bộ 35 m; nguồn: OSM phân loại đường.
Hẻm 75 Nguyễn Hữu Cảnh; đi bộ 58 m; nguồn: OSM phân loại đường.
Bằng chứng có thể chỉ là suy luận; chưa xác minh cổng địa chính hoặc khoảng thông thủy tại chỗ. Không coi thiếu dữ liệu là an toàn.
```

The second plan used `vinfast-vf-3` and retained the exact coordinates (10.792106, 106.716661), address, `2026-10-17T19:00:00+07:00`, 120 minutes, and parking intent.

A separate tiny free-key probe returned HTTP 200 with prompt=4, candidate=1, total=5 tokens. Thus the free project was not marked exhausted merely because an earlier report said so. Live daily-quota exhaustion was not reproduced during this task; the cooldown behavior is verified offline.

## Demo-day start

The app loads existing credentials from `.env.local` automatically; no shell sourcing or key literals are needed. Run the following when the owner of 8787 is ready to replace that server (this command was **not** run on 8787 during this task):

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=1 \
AGENT_PAID_LIMIT_USD=3.00 \
AGENT_FREE_CALL_LIMIT=0 \
AGENT_FREE_MODEL=gemini-2.5-flash \
AGENT_PAID_ENDPOINT=https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.5-flash:generateContent \
PYTHONPATH=backend python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

`AGENT_FREE_CALL_LIMIT=0` removes the old absolute evaluation ceiling. `AGENT_PAID_ENDPOINT` is optional because this exact Vertex route is the default. The paid cap remains $3 cumulative across processes and restarts, including the $0.011340 conservatively recorded by this smoke; keep the existing ledger. A daily quota cooldown automatically expires at the next Pacific midnight.

The normal review server left on 8788 has paid access disabled; its free-call ceiling intentionally keeps review traffic on the conservative fallback. It is not the demo-day configuration.
