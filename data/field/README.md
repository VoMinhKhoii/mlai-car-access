# Field measurements (Evidence Tier: Measured)

Fill `measurements.csv` during the Bình Thạnh field trip. One row per measured alley segment.

- `osm_way_id`: from the app's evidence panel ("OSM way"), or leave blank and fill `alley_name`.
- `alley_name`: as signed, e.g. `Hẻm 123/45 Xô Viết Nghệ Tĩnh`.
- `width_m`: the **narrowest usable width** along the segment (Clear Width), wall to wall or step to step, not at the mouth.
- `date`, `measured_by`, `note` (e.g. "xe máy đậu một bên sau 18h"), `photo_url`.

The backend reloads evidence on start and through `POST /api/evidence/reload`.
