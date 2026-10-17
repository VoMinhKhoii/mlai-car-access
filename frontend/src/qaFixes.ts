import type { Plan, SearchResult, StopPoint, WidthProfileSegment } from './api'
import { normalizeName } from './mapSearch.ts'

export const negativeAccess = (s: StopPoint) => ['no', 'blocked'].includes(s.fit.class) || s.estimate?.answer === 'no'
export function orderStops(plan: Plan): Plan {
  const eligible = plan.stop_points.filter((s) => !negativeAccess(s))
  const stops = eligible.length ? eligible.concat(plan.stop_points.filter(negativeAccess)) : []
  // A reordered recommendation must keep the width profile tied to its own route.
  const verdict = stops[0] !== plan.stop_points[0] ? { ...plan.verdict, profile: stops[0]?.profile } : plan.verdict
  return { ...plan, verdict, stop_points: stops }
}
export const stopLocation = (s: StopPoint) => s.kind === 'door' || /^at the door$/i.test(s.name) ? 'at the door' : `at ${s.name}`
export const hasSamples = (s: WidthProfileSegment) => (s.sample_count ?? 0) > 0
export const profileTier = (s: WidthProfileSegment) => !hasSamples(s) && s.tier !== 'No data' && s.tier != null ? 'Inferred' : s.tier
export const profileBasis = (s: WidthProfileSegment) => !hasSamples(s) ? /osm/i.test(s.source ?? '') ? 'assumed from OSM tag, not measured' : 'inferred, not measured' : s.tier ?? 'Inferred'

/** Server geocoder points win over viewport-dependent tile label vertices. */
export function canonicalSuggestions(remote: SearchResult[], local: SearchResult[]): SearchResult[] {
  const label = (p: SearchResult) => normalizeName(p.label.split(',')[0])
  const distance = (a: SearchResult, b: SearchResult) => a.lat == null || b.lat == null || a.lon == null || b.lon == null ? Infinity : Math.hypot((a.lat - b.lat) * 111320, (a.lon - b.lon) * 109350)
  const result: SearchResult[] = []
  for (const p of [...remote, ...local.slice().sort((a, b) => (a.lat ?? 0) - (b.lat ?? 0) || (a.lon ?? 0) - (b.lon ?? 0))]) {
    if (!result.some((x) => label(x) === label(p) && (distance(x, p) <= 150 || x.place_id && x.place_id === p.place_id))) result.push(p)
  }
  return result.slice(0, 6).map((p) => ({ ...p, subtitle: result.filter((x) => label(x) === label(p)).length > 1 ? `${p.source} · ${p.lat != null ? `${p.lat.toFixed(5)}, ${p.lon!.toFixed(5)}` : p.label.split(',').slice(1).join(',') || p.place_id}` : p.source }))
}
