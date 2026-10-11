import type * as GeoJSON from 'geojson'
export type Intent = 'park' | 'pickup'
export type FitClass = 'fits' | 'tight' | 'no' | 'unknown' | 'blocked' | 'lot'
export type FloodStatus = 'passable' | 'risky' | 'blocked'
export type Legal = 'Permitted' | 'Restricted' | 'Prohibited' | 'Unverified'
export type RouteSource = 'osm' | 'goong'
export const routeSourceLabel = (source: RouteSource) => source === 'osm' ? 'OSM' : 'Goong'

export interface Flag { name: string; label: string; detail: string; enabled: boolean }
export interface Preset {
  id: string; title: string; label: string; intent: Intent; vehicle_id: string
  arrive_at: string; dwell_min: number; story: string; lat: number; lon: number
  rain?: RainSpell[]
}
export interface RainSpell { start: string; end: string; mm_per_h: number; source?: string; measured?: boolean }
export interface Config {
  map_style: string
  goong: { tiles: boolean; api: boolean }
  ai_provider: [string, string] | null
  flags: Flag[]
  tide: { station: string; bulletin: string; issued_at: string; source_url: string; alarm_levels_m: Record<string, number>; note: string }
  demo_center: [number, number]
  presets: Preset[]
  personas: { id: string; label: string; enabled: boolean; note?: string }[]
}
export interface Vehicle {
  id: string; label: string; kind: 'model' | 'class'; size_class: string; powertrain: string
  body_width: number; mirror_width: number; mirror_estimated: boolean; length: number
  turning_radius: number; turning_radius_estimated: boolean; ground_clearance: number
  safe_water_depth: number; safe_water_basis: string; members: string[]
  fits_min: number; tight_min: number; three_point_width: number; source_url: string
}
export interface Bound {
  lo: number; hi: number | null; tier: string; tier_vi: string; source: string
  detail: string; observed_on: string; url: string; ai_feature: string | null
}
export interface WidthRange {
  lo: number; hi: number | null; label: string; top_tier: string | null; review: boolean
  evidence: Bound[]; overruled: Bound[]; way_out_claims: Bound[]
}
export interface Depth { lo: number; hi: number; drivers: string[]; rain_driven: boolean; inferred: boolean }
export interface Rule { code: string; status: Legal; text: string; citation: string }
export interface StopPoint {
  rank?: number; ok: boolean; kind: 'door' | 'street' | 'lot'; name: string; lat: number; lon: number
  way_id: number | null; tier: number; verified: boolean; badges: string[]
  walk: { meters: number; minutes: number; geometry?: number[][]; wade?: { lo: number; hi: number; street: string } | null }
  route_in: { meters: number; geometry: number[][] } | null
  fit: { class: FitClass; width_range?: WidthRange; note?: string | null; needed?: { fits_min: number; tight_min: number; door_min: number } }
  way_out: { mode: string; text: string; reverse_m?: number; tight_exit?: boolean; geometry?: number[][] }
  flood: { stay: { status: FloodStatus; depth: Depth | null; at: string | null } }
  legality: { status: Legal; rules: Rule[] }
  fail_reasons: string[]; unverified_reasons: string[]
  lot: { name: string; source: string; source_label: string; address?: string } | null
  approach?: { geometry: number[][]; source: string }
  trip?: { drive_m: number; drive_min: number; walk_m: number; walk_min: number; total_min: number }
}
export interface Plan {
  destination: { lat: number; lon: number; label: string }
  vehicle: Vehicle
  intent: Intent
  window: { arrive: string; depart: string; dwell_min: number; tide_arrive: { level_m: number | null; alarm: string | null }; tide_depart: { level_m: number | null; alarm: string | null }; rain: RainSpell[] }
  verdict: { code: string; headline: string; detail: string; timing?: string }
  timing: { leave_before: string | null; or_after: string | null; if_leave_before?: { headline: string; code: string } } | null
  stop_points: StopPoint[]
  door: StopPoint | null
  standard_route: { geometry: number[][]; unfit_ways: { way_id: number; name: string; label: string; fit: string; lo: number; hi: number | null }[]; note: string; source: RouteSource; distance_m?: number; duration_s?: number } | null
  layers: { fit: GeoJSON.FeatureCollection; flood: GeoJSON.FeatureCollection }
  counts: { candidates: number; passed: number; rejected: number }
  origin: { lat: number; lon: number } | null
  area_key: string
  live_crawl: boolean
}
export interface NewsItem { street: string; title: string; summary: string; url: string; source: string; date: string; kind: 'flood' | 'works' | 'ban'; depth_cm: number | null }
export interface AreaData { key: string; listings: unknown[]; photos: ListingPhoto[]; news?: NewsItem[]; parcels?: { way_id: number; width_m: number; samples: number[] }[] }
export type StepState = 'pending' | 'running' | 'done' | 'skipped'
export interface AreaBuild {
  key: string; state: 'running' | 'done' | 'error' | 'off'; error?: string | null
  started_at?: string; finished_at?: string
  steps?: Record<'map' | 'parcels' | 'listings' | 'match' | 'news' | 'photos', { state: StepState; detail: string }>
  counts?: { fetched: number; unique: number; in_area: number; matched: number; alleys: number; photos_total: number; photos_read: number }
}
export interface ListingPhoto {
  id: string; image_url: string; way_id: number; alley: string; listing_url: string; posted_at: string
  status: 'pending' | 'approved' | 'rejected'; view?: string; width_m?: number | null; reference?: string | null
  confidence?: number | null; notes?: string; gate?: string
}
export interface WayEvidence {
  way_id: number; name: string; osm_url: string; width_range: WidthRange
  photos: ListingPhoto[]
  flood_history: { records: { street: string; year: number; date: string; cause: string; depth_max_cm: number | null; precision: string; url: string }[]; inferred_from: string }
}
export type Traffic = 'thong_thoang' | 'dong' | 'un_u' | 'ket_cung'
export interface CameraReading {
  id: string; name: string; lat: number; lon: number; image_url: string
  state: 'ok' | 'offline' | 'stale' | 'unusable' | 'no_model' | 'error' | 'not_read'
  at?: string; image_time?: string | null; frames?: number; traffic?: Traffic | 'khong_ro' | null; traffic_vi?: string
  flooded?: boolean; depth_cm?: number | null; depth_class?: string; evidence?: string; confidence?: number; model?: string
}
export interface CameraInfo { id: string; name: string; lat: number; lon: number; code: string; type: string; reading: CameraReading | null }
export interface Hotspot {
  name: string; lat: number; lon: number; along_m: number; traffic: Traffic | null; traffic_vi: string | null
  delay_min: number; depth_cm: number | null; flood_status: FloodStatus | null; at: string | null; cameras: CameraReading[]
}
export interface CorridorRoute {
  id: number; label: string; via: { name: string; lat: number; lon: number } | null; is_goong: boolean
  geometry: number[][]; distance_m: number; base_min: number; delay_min: number; eta_min: number
  status: 'ok' | 'risky' | 'blocked'; hotspots: Hotspot[]; alleys: string[]; reasons: string[]; top_reason: string | null
  flood_forecast: { street: string; at: string; status: FloodStatus; depth: Depth }[]
  cameras_on_route: number; chosen: boolean
}
export interface Corridor {
  available: boolean; reason?: string; depart_at: string; checked_at: string; live: boolean; live_note: string | null
  routes: CorridorRoute[]; summary: string; cameras_read: number; cameras_offline: number; typical_factor: number
  source: { cameras: string; routes: string }
}
export interface SearchResult { label: string; lat?: number; lon?: number; place_id?: string; source: string }

export interface PlanRequest {
  lat: number; lon: number; label: string; vehicle_id: string; intent: Intent
  /** Complete ISO timestamp with an explicit timezone, or null for now. */
  arrive_at: string | null
  dwell_min: number; rain: RainSpell[]; origin: [number, number] | null; area: AreaData | null
}
export interface ValidationIssue { loc: (string | number)[]; msg: string; type: string }
export class ApiError extends Error {
  status: number
  issues: ValidationIssue[]
  constructor(message: string, status: number, issues: ValidationIssue[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.issues = issues
  }
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText || `HTTP ${res.status}`
    let issues: ValidationIssue[] = []
    try {
      const { detail } = await res.json() as { detail?: unknown }
      if (typeof detail === 'string') msg = detail
      else if (Array.isArray(detail)) {
        issues = detail.filter((x): x is ValidationIssue => x != null && typeof x === 'object'
          && Array.isArray(x.loc) && x.loc.every((part: unknown) => typeof part === 'string' || typeof part === 'number')
          && typeof x.msg === 'string' && typeof x.type === 'string')
        if (issues.length) msg = issues.map((x) => `${x.loc.filter((part) => part !== 'body').join('.')}: ${x.msg}`).join('; ')
      }
    } catch { /* not JSON */ }
    throw new ApiError(msg, res.status, issues)
  }
  return res.json() as Promise<T>
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  config: () => fetch('/api/config').then(j<Config>),
  vehicles: () => fetch('/api/vehicles').then(j<{ classes: Vehicle[]; models: Vehicle[] }>),
  search: (q: string, near?: { lat: number; lon: number } | null, signal?: AbortSignal) => fetch(`/api/search?q=${encodeURIComponent(q)}${near ? `&lat=${near.lat}&lon=${near.lon}` : ''}`, { signal }).then(j<{ results: SearchResult[] }>),
  reverse: (lat: number, lon: number) => fetch(`/api/reverse?lat=${lat}&lon=${lon}`).then(j<{ label: string; source: string }>),
  place: (id: string, signal?: AbortSignal) => fetch(`/api/place/${encodeURIComponent(id)}`, { signal }).then(j<{ lat: number; lon: number; label: string }>),
  plan: (body: PlanRequest) => post('/api/plan', body).then(j<Plan>),
  tide: (start: string, hours = 36) =>
    fetch(`/api/tide?start=${encodeURIComponent(start)}&hours=${hours}`).then(j<{ series: { t: string; level_m: number; kind: 'measured' | 'model' | 'bulletin' }[]; alarm_levels_m: Record<string, number>; station: string; source_url: string
      readings: { t: string; level_m: number }[]; last_reading: { t: string; level_m: number } | null; model_err_m: number | null }>),
  wayEvidence: (id: number, lat: number, lon: number, area: AreaData | null) => post(`/api/evidence/way/${id}`, { lat, lon, area }).then(j<WayEvidence>),
  confirm: (body: unknown) => post('/api/confirm', body).then(j<{ ok: boolean }>),
  blockage: (body: unknown) => post('/api/blockage', body).then(j<{ ok: boolean }>),
  setFlag: (name: string, enabled: boolean) => post('/api/flags', { name, enabled }).then(j<{ flags: Flag[] }>),
  reviewPhoto: (key: string, id: string, approve: boolean) => post(`/api/photo/${id}/review`, { key, approve }).then(j<{ ok: boolean }>),
  /** Live Area Build: streamed NDJSON status lines; resolves with the area evidence from the last line. */
  async areaBuild(lat: number, lon: number, onStatus: (s: AreaBuild) => void): Promise<AreaData | null> {
    const res = await post('/api/area/build', { lat, lon })
    if (!res.ok || !res.body) throw new Error(res.statusText)
    const reader = res.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    let area: AreaData | null = null
    for (;;) {
      const { done, value } = await reader.read()
      if (value) buf += dec.decode(value, { stream: true })
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim()
        buf = buf.slice(nl + 1)
        if (!line) continue
        const msg = JSON.parse(line) as { status: AreaBuild; area?: AreaData }
        onStatus(msg.status)
        if (msg.area) area = msg.area
      }
      if (done) return area
    }
  },
  corridor: (body: { origin: number[]; destination: number[]; vehicle_id: string; depart_at: string | null; rain: RainSpell[] }) =>
    post('/api/corridor', body).then(j<Corridor>),
  cameras: () => fetch('/api/cameras').then(j<{ source: string; portal: string; reading: boolean; cameras: CameraInfo[] }>),
  readCamera: (id: string) => post(`/api/cameras/${id}/read`, {}).then(j<CameraReading>),
  aiText: (text: string, source: string) => post('/api/ai/text', { text, source }).then(j<{ items: Record<string, unknown>[] }>),
}
