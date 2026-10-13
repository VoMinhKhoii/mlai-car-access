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
  /** Booleans only: the backend never sends the secret or a session id. */
  operator: { available: boolean; signed_in: boolean }
}
export interface Vehicle {
  id: string; label: string; kind: 'model' | 'class'; size_class: string; powertrain: string
  body_width: number; mirror_width: number; mirror_estimated: boolean; length: number
  turning_radius: number; turning_radius_estimated: boolean; ground_clearance: number
  safe_water_depth: number; safe_water_basis: string; members: string[]
  fits_min: number; tight_min: number; three_point_width: number; source_url: string
}
export type WidthBasis =
  | 'measured_clear_width'
  | 'observed_clear_width'
  | 'parcel_gap_estimate'
  | 'road_width_estimate'
  | 'declared_width'
  | 'inferred'
  | 'unknown'
export interface WidthCoverage {
  cut_count: number
  start_covered: boolean
  end_covered: boolean
  max_spacing_m: number | null
  truncated: boolean
  complete: boolean
  reason: string | null
}
export interface Bound {
  lo: number; hi: number | null; tier: string; tier_vi: string; source: string
  detail: string; observed_on: string; url: string; ai_feature: string | null
  width_basis: WidthBasis; uncertainty_m: number | null; coverage: WidthCoverage | null
}
export interface WidthRange {
  lo: number; hi: number | null; label: string; top_tier: string | null; review: boolean
  evidence: Bound[]; overruled: Bound[]; way_out_claims: Bound[]
  width_basis: WidthBasis; coverage: WidthCoverage; decisive_clearance: boolean
}
export interface Depth { lo: number; hi: number; drivers: string[]; rain_driven: boolean; inferred: boolean }
export type FloodKnowledge = 'known' | 'missing_tide' | 'missing_history' | 'stale_positive_observation'
export interface FloodFreshness { observed_at?: string; valid_until?: string; source?: string }
export interface FloodCheck {
  status: FloodStatus; depth: Depth | null; knowledge: FloodKnowledge; reason: string | null
  freshness: FloodFreshness | null; at: string | null; source?: string | null
}
export interface FloodLeg extends FloodCheck { way_id: number | null; name: string; source: string | null }
export interface LegFloodCheck extends FloodCheck {
  legs: FloodLeg[]
  interval: { start: string; end: string; approximate: boolean } | null
}
export interface FloodLayerProperties {
  name: string; way_id: number
  arrive: Depth | null; depart: Depth | null
  status_arrive: FloodStatus; status_depart: FloodStatus
  knowledge_arrive: FloodKnowledge; knowledge_depart: FloodKnowledge
  reason_arrive: string | null; reason_depart: string | null
  freshness_arrive: FloodFreshness | null; freshness_depart: FloodFreshness | null
}
export const floodKnowledgeLabel = (knowledge: FloodKnowledge | undefined): string => {
  switch (knowledge) {
    case 'known': return 'Có dữ liệu cho thời điểm kiểm tra'
    case 'missing_tide': return 'Thiếu dữ liệu triều cho thời điểm kiểm tra'
    case 'missing_history': return 'Thiếu lịch sử ngập để ước lượng'
    case 'stale_positive_observation': return 'Ghi nhận ngập đã cũ; chưa có quan sát mới xác nhận nước rút'
    default: return 'Chưa đủ dữ liệu ngập'
  }
}
export interface Rule { code: string; status: Legal; text: string; citation: string }
export interface StopPoint {
  rank?: number; ok: boolean; kind: 'door' | 'street' | 'lot'; name: string; lat: number; lon: number
  way_id: number | null; tier: number; verified: boolean; badges: string[]
  walk: { meters: number; minutes: number; geometry?: number[][]
    connection?: { stop_to_walk_m: number; destination_to_walk_m: number; mapped: boolean; reason: string | null }
    wade?: { lo: number; hi: number; street: string } | null }
  route_in: { available: boolean; meters: number | null; geometry: number[][]; flood: LegFloodCheck | null } | null
  fit: { class: FitClass; width_range?: WidthRange; note?: string | null; needed?: { fits_min: number; tight_min: number; door_min: number } }
  way_out: { available: boolean; mode: string; text: string; turn_verified?: boolean; route_verified?: boolean
    reverse_m?: number; tight_exit?: boolean; geometry?: number[][]; flood: LegFloodCheck | null }
  flood: { stay: LegFloodCheck }
  legality: { status: Legal; rules: Rule[] }
  fail_reasons: string[]; unverified_reasons: string[]; failure_codes: string[]
  lot: { name: string; source: string; source_label: string; address?: string } | null
  approach?: { geometry: number[][]; source: string }
  trip?: { drive_m: number; drive_min: number; walk_m: number; walk_min: number; total_min: number }
}
export interface Plan {
  destination: { lat: number; lon: number; label: string }
  vehicle: Vehicle
  intent: Intent
  window: { arrive: string; depart: string; dwell_min: number; tide_arrive: { level_m: number | null; alarm: string | null; kind: string | null }; tide_depart: { level_m: number | null; alarm: string | null; kind: string | null }; rain: RainSpell[] }
  verdict: { code: string; headline: string; detail: string }
  timing: {
    leave_before_at: string | null; or_after_at: string | null
    reason: string | null; approximate: boolean; failure_codes: string[]
    if_leave_before?: { headline: string; code: string }
  } | null
  stop_points: StopPoint[]
  no_stop_reason?: 'missing_walk_connection' | null
  door: StopPoint | null
  standard_route: { geometry: number[][]; unfit_ways: { way_id: number; name: string; label: string; fit: string; lo: number; hi: number | null }[]; note: string; source: RouteSource; distance_m?: number; duration_s?: number } | null
  layers: { fit: GeoJSON.FeatureCollection; flood: GeoJSON.FeatureCollection }
  counts: { candidates: number; passed: number; rejected: number; dijkstra: number }
  origin: { lat: number; lon: number } | null
  area_key: string
  /** Server-owned live area evidence: why a plan may lack it (missing, stale, partial). */
  area: AreaStatus
  /** Display-only copy of the area build (news, listing photos); never sent back to the server. */
  area_data: AreaData | null
  live_crawl: boolean
}
export interface AreaStatus {
  key: string; state: 'fresh' | 'partial' | 'stale' | 'missing'; revision: number | null
  collected_at: string | null; expires_at: string | null; building: boolean; reason: string | null
}
export interface NewsItem { street: string; title: string; summary: string; url: string; source: string; date: string; kind: 'flood' | 'works' | 'ban'; depth_cm: number | null }
export interface AreaData { key: string; revision: string; news: NewsItem[]; photos: ListingPhoto[] }
export type StepState = 'pending' | 'running' | 'done' | 'skipped' | 'error'
export interface AreaBuild {
  key: string; state: 'queued' | 'running' | 'done' | 'error'; error?: string | null
  queued_at?: string; started_at?: string | null; finished_at?: string | null; revision?: number | null
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
  at?: string; image_time?: string | null; frames?: number | null; traffic?: Traffic | 'khong_ro' | null; traffic_vi?: string
  flooded?: boolean; depth_cm?: number | null; depth_class?: string; evidence?: string; confidence?: number; model?: string
}
export interface CameraInfo { id: string; name: string; lat: number; lon: number; code: string; type: string; reading: CameraReading | null }
export interface Hotspot {
  name: string; lat: number; lon: number; along_m: number; traffic: Traffic | null; traffic_vi: string | null
  delay_min: number; depth_cm: number | null; flood_status: FloodStatus | null; at: string | null; cameras: CameraReading[]
  /** read: a fresh camera reading; scheduled: in the running job; unknown: not read this time (not "clear"). */
  coverage: 'read' | 'scheduled' | 'unknown'
}
export interface CameraJob {
  id: string; state: 'queued' | 'running' | 'ready' | 'error' | 'expired' | 'interrupted'
  cameras: string[]; created_at: string; expires_at: string; finished_at: string | null; error: string | null
  readings: CameraReading[]; unread: string[]
}
export interface CorridorCameraJob {
  id: string | null; state: 'queued' | 'running' | 'busy' | 'not_scheduled'
  cameras_requested: number; cameras_scheduled: number; reason?: string | null; retry_after?: number
  dropped: { id: string; name: string; reason: string }[]
}
export interface CorridorRoute {
  id: number; label: string; via: { name: string; lat: number; lon: number } | null; is_goong: boolean
  geometry: number[][]; distance_m: number; base_min: number; delay_min: number; eta_min: number
  status: 'ok' | 'risky' | 'blocked'; hotspots: Hotspot[]; alleys: string[]; reasons: string[]
  top_reason: string | null; flood_forecast: (FloodCheck & { street: string })[]
  cameras_on_route: number; traffic_unknown: number; chosen: boolean
}
export interface Corridor {
  available: boolean; reason?: string; depart_at: string; checked_at: string; live: boolean; live_note: string | null
  routes: CorridorRoute[]; summary: string; cameras_read: number; cameras_offline: number; typical_factor: number
  camera_job: CorridorCameraJob | null
  source: { cameras: string; routes: string }
}
export interface SearchResult { label: string; lat?: number; lon?: number; place_id?: string; source: string }

export interface PlanRequest {
  lat: number; lon: number; label: string; vehicle_id: string; intent: Intent
  /** Complete ISO timestamp with an explicit timezone, or null for now. */
  arrive_at: string | null
  dwell_min: number; rain: RainSpell[]; origin: [number, number] | null
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

const post = (url: string, body: unknown, signal?: AbortSignal) =>
  fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal })

export function delay(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>()
  window.setTimeout(resolve, ms)
  return promise
}

export const api = {
  config: () => fetch('/api/config').then(j<Config>),
  vehicles: () => fetch('/api/vehicles').then(j<{ classes: Vehicle[]; models: Vehicle[] }>),
  search: (q: string, near?: { lat: number; lon: number } | null, signal?: AbortSignal) => fetch(`/api/search?q=${encodeURIComponent(q)}${near ? `&lat=${near.lat}&lon=${near.lon}` : ''}`, { signal }).then(j<{ results: SearchResult[] }>),
  reverse: (lat: number, lon: number) => fetch(`/api/reverse?lat=${lat}&lon=${lon}`).then(j<{ label: string; source: string }>),
  place: (id: string, signal?: AbortSignal) => fetch(`/api/place/${encodeURIComponent(id)}`, { signal }).then(j<{ lat: number; lon: number; label: string }>),
  plan: (body: PlanRequest, signal?: AbortSignal) => post('/api/plan', body, signal).then(j<Plan>),
  tide: (start: string, hours = 36) =>
    fetch(`/api/tide?start=${encodeURIComponent(start)}&hours=${hours}`).then(j<{ series: { t: string; level_m: number; kind: 'measured' | 'model' | 'bulletin' }[]; alarm_levels_m: Record<string, number>; station: string; source_url: string
      readings: { t: string; level_m: number }[]; last_reading: { t: string; level_m: number } | null; model_err_m: number | null }>),
  wayEvidence: (id: number, lat: number, lon: number, signal?: AbortSignal) => post(`/api/evidence/way/${id}`, { lat, lon }, signal).then(j<WayEvidence>),
  confirm: (body: { lat: number; lon: number; vehicle_id: string; result: 'in' | 'tight' | 'no'; way_ids: number[] }) =>
    post('/api/confirm', body).then(j<{ status: 'pending'; report_id: string }>),
  blockage: (body: { lat: number; lon: number; way_id: number; reason: string }) =>
    post('/api/blockage', body).then(j<{ status: 'pending'; report_id: string }>),
  setFlag: (name: string, enabled: boolean) => post('/api/flags', { name, enabled }).then(j<{ flags: Flag[] }>),
  reviewPhoto: (id: string, approve: boolean) => post(`/api/photo/${id}/review`, { approve }).then(j<{ status: string }>),
  operatorLogin: (secret: string) => post('/api/operator/login', { secret }).then(j<{ operator: boolean }>),
  operatorLogout: () => post('/api/operator/logout', {}).then(j<{ operator: boolean }>),
  reports: (status: Report['status'] | null, cursor: string | null) =>
    fetch(`/api/reports?limit=50${status ? `&status=${status}` : ''}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
      .then(j<{ items: Report[]; next_cursor: string | null; remaining: number }>),
  decideReport: (id: string, approve: boolean, revision: number) => post(`/api/reports/${id}`, { approve, revision }).then(j<Report>),
  /** Live Area Build (operator): queues a server-side build; poll `areaJob` for its progress. */
  areaBuild: (lat: number, lon: number) => post('/api/area/build', { lat, lon }).then(j<AreaBuild>),
  areaJob: (key: string, signal?: AbortSignal) => fetch(`/api/area/build/${encodeURIComponent(key)}`, { signal }).then(j<AreaBuild>),
  corridor: (body: { origin: number[]; destination: number[]; vehicle_id: string; depart_at: string | null; rain: RainSpell[] }, signal?: AbortSignal) =>
    post('/api/corridor', body, signal).then(j<Corridor>),
  cameras: () => fetch('/api/cameras').then(j<{ source: string; portal: string; reading: boolean; cameras: CameraInfo[] }>),
  readCamera: (id: string) => post(`/api/cameras/${id}/read`, {}).then(j<{ state: string; reading: CameraReading | null; job: CameraJob | null }>),
  cameraJob: (id: string, signal?: AbortSignal) => fetch(`/api/camera-jobs/${id}`, { signal }).then(j<CameraJob>),
}

export interface Report {
  report_id: string; type: 'confirmation' | 'blockage' | 'flood_report' | 'stop_rule' | 'photo_reading'
  payload: Record<string, unknown>; source: string; status: 'pending' | 'approved' | 'rejected' | 'expired'
  created_at: string; expires_at: string; reviewer: string | null; reviewed_at: string | null; revision: number
  legacy: boolean; publish_target: string | null
}

/** Poll `fetchOnce` every `everyMs` until `done` says stop, the signal aborts, the tab is hidden, or `timeoutMs`
 * passes. An abort or timeout only stops watching: it does not cancel the server job. */
export async function poll<T>(fetchOnce: (signal: AbortSignal) => Promise<T>, done: (t: T) => boolean,
  signal: AbortSignal, onUpdate: (t: T) => void, everyMs = 2000, timeoutMs = 120_000): Promise<T | null> {
  const until = Date.now() + timeoutMs
  while (!signal.aborted && Date.now() < until) {
    if (document.visibilityState === 'visible') {
      const t = await fetchOnce(signal)
      if (signal.aborted) return null
      onUpdate(t)
      if (done(t)) return t
    }
    await new Promise((r) => window.setTimeout(r, everyMs))
  }
  return null
}
