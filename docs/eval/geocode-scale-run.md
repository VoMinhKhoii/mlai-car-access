# Goong scale recovery

Isolated detached worktree: `/Users/khoivo/Developer/mlai-geocode-wt` at `90129c1`. No results copied to the main checkout; no commit created.

Only GOONG_API_KEY_4 through _8 were eligible for this job. Keys _2, _3, _9 remain untouched for the demo; the exhausted primary key and tiles key _10 were skipped.

Calls per key: GOONG_API_KEY_4: 950, GOONG_API_KEY_5: 141, GOONG_API_KEY_6: 0, GOONG_API_KEY_7: 0, GOONG_API_KEY_8: 0.
All keys stayed within 950 requests and 5 starts/second; zero calls followed a refusal for the same key. Successful responses remain shared by query; refusal stops and budgets are scoped to the key variable.

New accepted matches by source: fire: 224, q9: 11, listing: 0.
Accepted records: 85 → 320. New accepted records touch 235 distinct ways.
Net new ways with sourced evidence: 122. Q9 historical/planned metadata remains metadata and does not gain clear-width evidence credit.

Remaining without a response: 5822; remaining eligible without a response: 0. Records rejected by preflight were retained; strict gates were not relaxed.

Precision proxy: 33/33 accepted snaps match the reference way (100%); 100 sampled records, 82 received responses, zero accepted snaps disagree. Fixed seed 4582; known fire name matches are the reference.

Validation: 33 pipeline safety tests passed. This proxy checks consistency against existing name matches, not independently measured real-world accuracy.

Machine-readable run accounting and new evidence way IDs: `docs/eval/geocode-unmatched-scale.json`. Per-key reports: `docs/eval/geocode-unmatched-key*.json`. Raw response cache, ledger and audit remain under `data/raw/geocode_unmatched/`.

## Exact output files to copy

- `/Users/khoivo/Developer/mlai-geocode-wt/backend/cache/live/declared_index.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/backend/cache/live/official_widths.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/data/processed/geocode_unmatched.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/data/official/fire_access_4582.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-unmatched.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-unmatched.md`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-unmatched-scale.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-scale-run.md`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-unmatched-key4.json`
- `/Users/khoivo/Developer/mlai-geocode-wt/docs/eval/geocode-unmatched-key5.json`

Optional pipeline implementation files: `pipelines/geocode_unmatched.py` and `pipelines/test_geocode_unmatched.py`. Resume/audit cache: copy `data/raw/geocode_unmatched/` separately if desired; never copy `.env.local`.
