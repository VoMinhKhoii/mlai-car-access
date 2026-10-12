# Field measurements (Evidence Tier: Measured)

Add one row per physical field-measured OSM way segment. Use the existing CSV header; the backend reads columns by name.

- `osm_way_id`: from the app's evidence panel ("OSM way"), or leave blank and fill `alley_name`.
- `alley_name`: as signed, e.g. `Hẻm 123/45 Xô Viết Nghệ Tĩnh`.
- `width_m`: narrowest observed physical clear width along the entire segment, not a cadastral gap or entrance-only width.
- `uncertainty_m`: finite measurement uncertainty in metres.
- `cut_count`, `start_covered`, `end_covered`, `max_spacing_m`, `truncated`, `complete`: coverage summary for the same measured segment. Mark `complete=true` only when both endpoints and the full segment were measured at spacing no greater than 5.1 m and sampling was not truncated.
- `width_basis`: `measured_clear_width` for a physical clear-width measurement. Incomplete coverage remains useful for review, but cannot authorize strict fit.
- `date`, `measured_by`, `note`, `photo_url`.

Parcel geometry is an inferred gap estimate, not a physical clear-width measurement. See `backend/app/evidence.py` for the executable evidence contract.

The backend reloads evidence on start and through `POST /api/evidence/reload`.
