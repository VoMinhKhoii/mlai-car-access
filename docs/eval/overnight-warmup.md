# Overnight HCMC warmup — 16–17 October 2026

The crawler runs without AI, news or photo calls. Only it writes `backend/cache/live/city_parcels.json`, using a temporary file, fsync and atomic replacement. It never writes `backend/cache/live/parcels.json`. The demo prebuild finished before the crawler started. The two build benchmarks subsequently updated the normal live build caches.

## Operation

- Crawler PID: **15721**, detached under PID 1 with `nohup` and a new process session. Current run began at **23:19:00 +07**, resuming the confirmed portal-lock cooldown. Rate observation used the prior uninterrupted run from 23:09:27 to 23:19:00 (9 min 33 s). Earlier runs verified resume and signal handling. The initial shell-background launch did not survive its launcher, so the final launch uses `subprocess.Popen(..., start_new_session=True)`.
- Log: `backend/cache/live/crawl_city.log`; console output: `backend/cache/live/crawl_city.out`.
- Resume/progress: `backend/cache/live/crawl_city_state.json`. A file lock prevents duplicate crawlers. A cached null means measured with no valid cadastral sample; transport failures are left uncached for retry.
- Stop automatically: **17 October 2026, 07:30 Asia/Ho_Chi_Minh**. The deadline watchdog saves accepted results and exits even if HTTP workers are retrying. A subprocess test verifies stopping while waiting for a prebuild.
- Stop manually from the repo root: `kill -TERM 15721`, or `kill -TERM "$(cat backend/cache/live/crawl_city.lock)"`.
- Resume in a terminal: `LISTINGS_TTL_H=48 nohup python3 -u pipelines/crawl_city.py >> backend/cache/live/crawl_city.out 2>&1 < /dev/null &`.
- Both listing sources accept `LISTINGS_TTL_H`, default 12. `.env.local` is set to 48 for this demo. The local API was reloaded to pick up the implementation and TTL.

The cadastre workers use at most three concurrent requests: three shallow measurements, each issuing its own cuts sequentially. A `Blocked` response pauses all new portal work for ten minutes. Overpass mirrors are tried sequentially in crawler mode with retries and backoff. OSM cache writes are atomic too.

## Coverage strategy and limits

There are **220 measurement cells**, about 0.012° apart, ordered from HUTECH Điện Biên Phủ outward, including HUTECH Thủ Đức. Within each cell: drivable non-main roads, alleys first, nearest first. Each pass measures 30 uncached ways before moving outward; further passes continue unfinished cells. This avoids spending the night entirely on the 3,282 eligible ways in the shared demo graph. A visited cell is only partially scanned unless `cells_done` says otherwise.

OSM uses finer 0.004° keys. A separate map warmup covers **1,731 keys**, including intervening keys, in distance order. Merely downloading the 220 measurement-center graphs would leave most arbitrary addresses with a cold OSM key. Current mean file sizes project roughly **1.2 GB** for the full finer grid. Extra map warmup stops at **1.8 GB**; the mandatory measurement-cell graphs may add a little beyond that. Initial files averaged 0.73 MB, with a maximum about 1.2 MB (the shared demo graph is 2.7 MB). Available disk at verification: 76 GiB.

City measurements remain shallow (`deep: false`). Browser/area parcel records take precedence. Existing deep scans retain precedence. When every way on the arrival path has a city lookup, a full live build reuses saved nearby widths, keeps unmeasured branches unknown, uses the existing keyword news filter, and reuses cached photos. A cached no-data path stays unknown; it is not promoted to Official evidence. Uncovered paths still collect evidence and can be slow.

## Verification

Ten offline/subprocess checks pass: atomic reload, null handling, graph filtering, browser/deep precedence, no redundant warm portal requests, retryable transport failures, polite mirror fallback, finer OSM-key coverage, cached photos/keyword news, plaintext/HTTP portal locks, and the deadline. Run `python3 pipelines/test_crawl_city.py`.

Two random non-preset alley locations were selected with seed 20261017 from already measured ways, each more than 150 m from all prebuilt destinations. All runs used `live.build(..., force=True)` so the saved-area shortcut did not explain the timing:

- **Hẻm 548 Điện Biên Phủ**, way 192512413, 10.8000326 / 106.7155079: initial warm build **107.933 s**, fixed build **1.362 s**. The initial parcel step took 35.7 s and news 71.8 s.
- **Hẻm 36 Nguyễn Gia Trí**, way 32585926, 10.8029100 / 106.7163617: initial warm build **124.917 s**, fixed build **0.893 s**. The initial parcel step took 31.4 s and news 93.0 s.

Both fixed builds finished every stage with zero portal and zero AI requests, verified by request guards. The two initial builds were allowed to use the free Gemini provider. This is a two-address result, compared with the 74–3975 s cold builds in `city-eval.md`; it is not a claim that every HCMC address is already warm. The crawler was paused during the initial benchmarks, then resumed.

Proof from the reloaded live API: `POST /api/plan` at **10.8158727 / 106.7199274**, vehicle `toyota-vios`, intent `pickup`, returned HTTP 200 in **0.741 s**. Door way **610251656** has `top_tier: Official`, `tier_vi: Số liệu chính thức`, source **Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)**. Its detail says one sampled cut, usable width **4.5 m** from a **5.5 m** parcel gap. At request time, that way had no parcel record in any area file, and **no area file existed** for key `10.816_106.720`. This proves the city cache reaches plan width evidence without an area build. An earlier independent check on way 32587999 also returned Official evidence in 0.816 s.

Machine-readable timings and the API proof are in `overnight-warmup.json`.

Chợ Tốt successfully warmed sale and rent for **all 22 districts (44 source caches)**. Alonhadat reused the Bình Thạnh cache; the other 21 district pulls returned HTTP errors. These failures are logged separately from parcel/map errors and do not stop the crawl. No bypass was attempted.

Files changed for this work: `.gitignore`, `.env.local` (TTL setting only), `backend/app/live.py`, `backend/app/parcels.py`, `backend/app/osm.py`, `backend/app/alonhadat.py`, `backend/app/news.py`, `pipelines/crawl_city.py`, `pipelines/test_crawl_city.py`, and this report with its JSON. Existing edits by other agents were preserved; no changes were made to `agent.py`, `main.py`, frontend or MCP files. No commit was created.

## Observation and projection at 23:19 +07

- **121 ways measured, 101 with cadastral data (83.5%)**; five partially visited measurement cells and zero fully completed cells.
- **9.64 ways/min** over 9 min 33 s, versus about 18/min before the lock responses began. The observation excludes the earlier deliberate benchmark pause.
- **One confirmed portal lock incident.** Before the fix, the portal returned HTTP 200 with single-quoted `The land is temporarily locked!` text. The old parser recorded 46 retryable failures rather than `Blocked`; those ways were never cached as no-data. The fixed parser recognizes this response and HTTP 403/429, abandons the rest of the locked cell until a later pass, and pauses all new portal requests for ten minutes. The saved cooldown survives a restart.
- The corrected detached crawler is **PID 15721**, paused on portal work until **23:29:00 +07**. Map warming continues independently. The incident is recorded explicitly in state/log; future automatic `Blocked` responses increment that count.
- **Conditional projection: approximately 4,800 measured ways across about 160 partially scanned cells by 07:30**, using the observed average after the current cooldown. This assumes the portal recovers. Repeated ten-minute locks can reduce this substantially; there is no defensible guarantee of city-wide cadastral coverage while the portal remains locked. Healthy pre-lock throughput alone would suggest roughly 8,000 ways, but that is too optimistic to rely on now.
- OSM at observation: **33 area files, 24.7 MB including the shared demo file**. Full 1,731-key grid extrapolation at restart: **1.14 GB**, below the 2 GB concern; extra map warming stops at 1.8 GB.
- All 44 Chợ Tốt district/type pulls succeeded. Alonhadat remains unavailable in 21 uncached districts; repeated startup attempts are logged, while the Bình Thạnh cache is usable.
