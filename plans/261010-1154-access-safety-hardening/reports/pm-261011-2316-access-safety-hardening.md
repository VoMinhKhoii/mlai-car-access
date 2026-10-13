## Progress report — access-safety-hardening (2026-10-13)

### Status

| Plan | Status | Progress | Next gate |
|---|---|---:|---|
| Vào Được: safety, evidence trust và demo reliability | In progress | 4/5 phases; 11/13 items (84%) | Complete R-11/R-12 release evidence |

### Sync-back

- Phases 1–4 complete: R-01–R-10 checked, evidence linked.
- Phase 5 in progress: 1/3 checklist items complete.
- Full sweep: no checkbox correction needed. Phase frontmatter/table reconciled to checklist evidence.
- Earlier implementation commits pushed: `a64c393`, `5516d12`. Review-driven runtime/evaluator/docs hardening is currently uncommitted; no new commit or push made.

### Latest local checks

- Backend: 129 passed, 0 failed.
- Field evaluator mechanics: 26 passed, 0 failed; real header-only input correctly refuses with exit 2.
- Frontend: TypeScript and build pass; lint 0 errors/14 warnings; JS chunk warning above 500 kB.
- The isolated desktop/mobile browser capture predates final runtime/corridor changes; it is partial local evidence, not production/field proof.

### Blockers

| Gate | State | Owner | Unblock / done |
|---|---|---|---|
| R-11 field validation | Blocked >1 session | Field team | ≥20 genuine surveyed ways + ≥20 independent alley-chain groups; structured dimensioned egress observations/photos; frozen grouped split; real field evaluation passes |
| R-12 live/hosted/release | Open/blocked | Release/operator team | Live Goong + AI; HTTPS backend origin and trusted proxy; hosted persistence/rollback; full browser matrix and physical-device proof |

### Risks

| Risk | State | Mitigation |
|---|---|---|
| Local/stub coverage mistaken for live proof | Open | Keep R-12 open; report live paths as not exercised |
| Header-only field data mistaken for calibration | Open | Evaluator rejects <20 rows; keep R-11 open |
| Final independent review | Partially blocked | Main agent: latest successful review found no Critical/High blocker; final refresh failed provider usage limit, so newest minor changes lack independent review |
| Stale plan status | Resolved | Phase statuses/table now match 4/5 and 11/13 |

### Docs impact

- Local authority docs updated for HTTPS proxy-header trust, matched-version rollback/cache invalidation, camera one-frame uncertainty, dimensioned egress, append-only splits and evaluator exit codes.
- Phase 5 hosting/restart documentation is complete; real production rollback and hosted-origin behavior remain unverified.

### Next actions

1. **Field team:** collect/validate R-11 dataset + egress audit. Done = evaluator accepts real >=20-row grouped split and emits nonempty field metrics.
2. **Release/operator team:** supply live credentials/backend origin and execute remaining R-12 paths. Done = live Goong/AI + hosted production evidence recorded.
3. **Main agent:** retain plan `in-progress`; ask whether to commit/push the uncommitted local remediation after the user reviews the status. Final code-review refresh could not run due provider limits.

### Unresolved questions

- None beyond missing field data, live credentials and production backend origin.
