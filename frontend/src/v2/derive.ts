import type { Estimate, Plan, StopPoint } from '../api'

/** English presentation derived only from codes and numbers; backend sentences are Vietnamese. */
export type Tone = 'fits' | 'tight' | 'no' | 'unknown'
export interface Limiting { value_m: number; tier: string; way_id: number | null; way_name: string | null }
type VerdictX = Plan['verdict'] & { estimate?: Estimate & { limiting_width?: Limiting | null } }

export const verdictOf = (plan: Plan) => plan.verdict as VerdictX

export const m2 = (v: number) => `${v.toFixed(2)} m`

export function answer(plan: Plan, stop: StopPoint | undefined): { word: string; tone: Tone } {
  if (!stop || plan.verdict.code === 'none') return { word: 'No stop', tone: 'no' }
  switch (stop.fit.class) {
    case 'fits': return { word: 'Fits', tone: 'fits' }
    case 'tight': return { word: 'Tight', tone: 'tight' }
    case 'no': case 'blocked': return { word: "Won't fit", tone: 'no' }
    case 'lot': return { word: 'Use a lot', tone: 'fits' }
  }
  const est = verdictOf(plan).estimate?.answer
  if (est === 'fits') return { word: 'Likely fits', tone: 'fits' }
  if (est === 'tight') return { word: 'Likely tight', tone: 'tight' }
  if (est === 'no') return { word: "Likely won't fit", tone: 'no' }
  return { word: 'Not verified', tone: 'unknown' }
}

const TIERS = ['Measured', 'Official', 'Observed', 'Declared', 'Inferred']
export function tierWord(tier: string | null | undefined): string {
  const t = (tier ?? '').toLowerCase()
  return TIERS.find((x) => t.startsWith(x.toLowerCase())) ?? 'Unknown'
}

export function wayOut(stop: StopPoint): { value: string; note: string | null } {
  const w = stop.way_out
  const note = w.route_verified ? null : 'Not driven yet'
  switch (w.mode) {
    case 'through': return { value: 'Drive out forward', note }
    case 'turn_here': return { value: 'Turn around here', note }
    case 'reverse': return { value: `Reverse ${Math.round(w.reverse_m ?? 0)} m`, note }
    case 'lot': return { value: 'Exit from the lot', note: null }
    default: return { value: 'No way out found', note: null }
  }
}

export function stopLine(stop: StopPoint): string {
  const walk = Math.round(stop.walk.meters)
  if (stop.kind === 'door' && walk === 0) return 'Park at the door'
  if (stop.kind === 'lot') return `Park at ${stop.lot?.name ?? 'a lot'}, walk ${walk} m`
  return `Park on ${stop.name}, walk ${walk} m`
}

export interface Cut { lo: number | null; hi: number | null; tier: string; wayName: string | null; lat: number; lon: number }

/** The narrowest cut: the plan's limiting width for the best stop, located at the midpoint of its way. */
export function narrowestCut(plan: Plan, selected: number): Cut | null {
  const stop = plan.stop_points[selected]
  const lim = selected === 0 ? verdictOf(plan).estimate?.limiting_width ?? null : null
  const wr = stop?.fit.width_range
  const wayId = lim?.way_id ?? stop?.way_id ?? null
  const feature = wayId == null ? undefined : plan.layers.fit.features.find((f) => f.properties?.way_id === wayId)
  let at: [number, number] | null = null
  if (feature?.geometry.type === 'LineString') at = midpoint(feature.geometry.coordinates)
  if (!at && stop) at = [stop.lon, stop.lat]
  if (!at) return null
  if (lim) {
    const sameWay = stop && stop.way_id === lim.way_id && wr?.hi != null && wr.hi > lim.value_m
    return { lo: lim.value_m, hi: sameWay ? wr!.hi : null, tier: tierWord(lim.tier), wayName: lim.way_name, lat: at[1], lon: at[0] }
  }
  return { lo: wr?.lo ?? null, hi: wr?.hi != null && wr.hi > (wr.lo ?? 0) ? wr.hi : null, tier: tierWord(wr?.top_tier), wayName: stop?.name ?? null, lat: at[1], lon: at[0] }
}

function midpoint(coords: number[][]): [number, number] | null {
  if (!coords.length) return null
  const seg: number[] = []
  let total = 0
  for (let i = 1; i < coords.length; i++) {
    const d = Math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1])
    seg.push(d); total += d
  }
  let half = total / 2
  for (let i = 0; i < seg.length; i++) {
    if (half <= seg[i] && seg[i] > 0) {
      const t = half / seg[i]
      return [coords[i][0] + t * (coords[i + 1][0] - coords[i][0]), coords[i][1] + t * (coords[i + 1][1] - coords[i][1])]
    }
    half -= seg[i]
  }
  return [coords[0][0], coords[0][1]]
}
