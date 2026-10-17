# Parked night prototypes

The active application uses the safety engine, immutable evidence views, operator
review, bounded jobs, structured confirmation and voice reports from
`origin/fix/collapsible-result-cards` (`339e643`). See
[`docs/eval/merge-report-2026-10-17.md`](../../../docs/eval/merge-report-2026-10-17.md).

`night_engine/` preserves the previous night implementation for comparison. Its
package refuses import unless `ENABLE_NIGHT_ENGINE=1`; setting that variable does
not replace the production planner or register any routes. Do not mount it in the
demo. Port additional behavior into the canonical modules with safety tests.

The earlier field/crowd kit remains in `field_routes.py`, `field_server.py` and
the frontend field entry point. Its API routes require
`ENABLE_NIGHT_FIELD_KIT=1`, off by default. The main app never mounts those routes.
QR/crowd intake and the earlier arrival prompt await integration with canonical
pending reports and operator approval. The product's field intake and driver
confirmation are active.

The unfinished `width_samples.py` outlier filter and its evidence adapter remain
available for diagnostics; the production width-combination path does not call
that adapter. Map-feature search was retained in MapView/Directions and compiles.

Default pytest runs explicitly skip 77 legacy prototype contract cases. Set
`RUN_NIGHT_ENGINE_TESTS=1` or `RUN_NIGHT_FIELD_TESTS=1` only while migrating those
contracts. These switches do not enable either prototype in the application.
