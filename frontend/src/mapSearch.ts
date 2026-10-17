import type { Feature, Geometry } from 'geojson'

export interface MapPlace { name: string; lat: number; lon: number; layer: string }
export interface MapContext { center: { lat: number; lon: number }; zoom: number; candidates: MapPlace[] }

export const normalizeName = (text: string) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[đĐ]/g, 'd').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const generic = new Set(['cong', 'ty', 'cp', 'tnhh', 'co', 'phan', 'quan', 'hem', 'duong', 'so'])
const tokens = (text: string) => [...new Set(normalizeName(text).split(' ').filter((t) => t && !generic.has(t)))]

/** Exact tokens, never edit-distance similarity (Vương Phạm is not Sư phạm). */
export function matchMapPlaces(query: string, places: MapPlace[], center: MapContext['center'], limit = 20, inMessage = false): MapPlace[] {
  const wanted = tokens(query)
  if (!wanted.length) return []
  return places.map((p) => {
    const name = tokens(p.name)
    const found = Math.max(...p.name.split(/[,;|\n]/).map((part) => wanted.filter((t) => tokens(part).includes(t)).length))
    const coverage = found / wanted.length
    const mentioned = inMessage && name.length >= 2 && name.every((t) => wanted.includes(t))
    const distance = (p.lat - center.lat) ** 2 + ((p.lon - center.lon) * Math.cos(center.lat * Math.PI / 180)) ** 2
    return { p, coverage, distance, ok: coverage >= .7 || mentioned }
  }).filter((r) => r.ok).sort((a, b) => b.coverage - a.coverage || a.distance - b.distance)
    .filter((r, i, all) => all.findIndex((x) => normalizeName(x.p.name) === normalizeName(r.p.name) && Math.abs(x.p.lat - r.p.lat) < .0001 && Math.abs(x.p.lon - r.p.lon) < .0001) === i)
    .slice(0, limit).map((r) => r.p)
}

/** Tile line labels use the nearest vertex to the current centre; POIs keep their exact point. */
export function featurePlace(feature: Pick<Feature<Geometry>, 'properties' | 'geometry'>, layer: string, center: MapContext['center']): MapPlace | null {
  const props = feature.properties ?? {}
  const name = props.name ?? props['name:vi'] ?? props.name_vi ?? props.st_name ?? props.name_vn ?? props.name_en ?? props['name:en'] ?? props.city_name ?? props.name1 ?? props.ref
  if (typeof name !== 'string' || !name.trim()) return null
  const g = feature.geometry
  const points = g.type === 'Point' ? [g.coordinates] : g.type === 'MultiPoint' || g.type === 'LineString' ? g.coordinates : g.type === 'MultiLineString' || g.type === 'Polygon' ? g.coordinates.flat() : []
  const coordinate = points.reduce<number[] | null>((best, c) => !best || (c[0] - center.lon) ** 2 + (c[1] - center.lat) ** 2 < (best[0] - center.lon) ** 2 + (best[1] - center.lat) ** 2 ? c : best, null)
  if (!coordinate || !Number.isFinite(coordinate[0]) || !Number.isFinite(coordinate[1])) return null
  return { name, lon: coordinate[0], lat: coordinate[1], layer }
}
