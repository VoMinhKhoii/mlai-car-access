# Engine / Agent A handoff

English engine fields now come directly from plan.py and evidence.py; street names and legal citations remain verbatim. `estimate.stop_width` and `fit.width_range.sampled_estimate` expose the door samples separately from the route bottleneck and strict bounds.

The requested English boundary regression `test_agent_compact_preserves_actual_caveats_and_never_invents_portal_disclaimer` now asserts `Basis:`, the supplied `Exit unverified` caveat, and the English legality/flood/manoeuvre caveats. It rejects any invented portal, entrance or cadastral disclaimer. The fixture now supplies the planner's real unknown-flood shape, `flood={"stay":{"status":"unknown","depth":null}}`, rather than an empty object missing `stay`. Actual supplied caveats remain unchanged by compaction. Agent B did not edit agent.py.

Separate legacy edge case for Agent A: passing a compact stop with `flood=None` directly to `agent.grounded_answer` still reaches `stop.get('flood', {}).get('depth')` and raises `AttributeError`. The actual engine emits a `stay` object even for unknown flood evidence; this is a missing/legacy-payload guard, not a reason to alter engine safety checks. The suggested guard is `(stop.get("flood") or {}).get("depth")`. No production workaround was added by Agent B.

Final verification counts and logs are in [engine-stress.md](engine-stress.md). Earlier migration logs were captured during simultaneous English edits and are superseded by `engine-stress-backend-final-tests.txt`.


Frontend follow-up (outside Agent B ownership): `Result.tsx` and `Evidence.tsx` still format strict `width_range.lo/hi`; they do not yet read `sampled_estimate`. The strict Ministop range therefore remains 0–5.86 m in those existing width labels. For the estimate display, wire `sampled_estimate.lo/hi` (5.26–5.86 m), identify it as sampled/unverified, and retain the strict range and `verified` semantics for clearance decisions. The English basis and separate `estimate.stop_width` already carry the correct door sample.
