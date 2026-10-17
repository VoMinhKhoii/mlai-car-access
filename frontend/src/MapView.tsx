import maplibregl, { type GeoJSONSource, type Map as MLMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type * as GeoJSON from 'geojson'
import { useEffect, useRef, useState } from 'react'
import { floodKnowledgeLabel, routeSourceLabel, type CameraInfo, type Corridor, type FloodLayerProperties, type ManeuverState, type Plan } from './api'
import { featurePlace, type MapContext, type MapPlace } from './mapSearch'
import { floodPresentation, floodTimeLabel } from './components/Result'

export interface LayerToggles { fit: boolean; flood: boolean; standard: boolean; cams: boolean }
export type FloodMoment = 'arrive' | 'depart'
type LL = { lat: number; lon: number }
export interface ManeuverOverlay {
  state: ManeuverState
  stop: LL
  widthLo: number | null
  widthHi: number | null
  decisive: boolean
  mirrorWidth: number
  vehicleLength: number
  bodyCenterOffset: number
  corridorWidth: number
  axis: number[][]
}
interface Props {
  styleUrl: string
  center: [number, number]
  plan: Plan | null
  selected: number
  origin: LL | null
  destination: LL | null
  toggles: LayerToggles
  floodMoment: FloodMoment
  padding: { top: number; left: number; right: number; bottom: number }
  frame: 'arrival' | 'trip'
  corridor: Corridor | null
  routeSel: number
  cams: CameraInfo[]
  maneuver: ManeuverOverlay | null
  onCameraClick: (id: string) => void
  onPick: (lat: number, lon: number, x: number, y: number) => void
  onWayClick: (wayId: number, lat: number, lon: number) => void
  onStopClick: (index: number) => void
  onFeatures: (context: MapContext) => void
  onPlaceClick: (place: MapPlace) => void
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const line = (coords?: number[][]): GeoJSON.FeatureCollection =>
  coords && coords.length > 1
    ? { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }] }
    : EMPTY

function maneuverFeatures(overlay: ManeuverOverlay | null, pose: number[] | null): GeoJSON.FeatureCollection {
  if (!overlay) return EMPTY
  const { stop, widthLo, widthHi, mirrorWidth, vehicleLength, bodyCenterOffset, corridorWidth, decisive, axis } = overlay
  const latScale = 110_540
  const lonScale = 111_320 * Math.cos(stop.lat * Math.PI / 180)
  const lastIndex = axis.length - 1
  const angle = axis.length > 1
    ? Math.atan2((axis[lastIndex][0] - axis[lastIndex - 1][0]) * lonScale, (axis[lastIndex][1] - axis[lastIndex - 1][1]) * latScale)
    : 0
  const point = (x: number, y: number): [number, number] => {
    const east = x * Math.cos(angle) + y * Math.sin(angle)
    const north = -x * Math.sin(angle) + y * Math.cos(angle)
    return [stop.lon + east / lonScale, stop.lat + north / latScale]
  }
  const length = Number.isFinite(vehicleLength) && vehicleLength > 0 ? vehicleLength : 4.5
  const low = widthLo != null && Number.isFinite(widthLo) && widthLo > 0 ? widthLo : null
  const high = widthHi != null && Number.isFinite(widthHi) && widthHi > 0 ? Math.max(widthHi, low ?? widthHi) : low
  const D = Number.isFinite(corridorWidth) && corridorWidth > 0 ? corridorWidth : 0
  const poseX = pose && Number.isFinite(pose[0]) ? pose[0] : D / 2
  const poseY = pose && Number.isFinite(pose[1]) ? pose[1] : 0
  const psi = pose && Number.isFinite(pose[2]) ? pose[2] : Math.PI / 2
  const offset = Number.isFinite(bodyCenterOffset) ? bodyCenterOffset : 0
  const x0 = poseX - D / 2 + offset * Math.cos(psi)
  const y0 = poseY + offset * Math.sin(psi)
  const reliable = decisive && low != null && low >= mirrorWidth
  const features: GeoJSON.Feature[] = []
  const lane = (w: number, boundaryKind: 'certain' | 'uncertain') => {
    const half = w / 2
    const extent = Math.max(8, Math.abs(y0) + length)
    const ring = [point(-half, -extent), point(half, -extent), point(half, extent), point(-half, extent), point(-half, -extent)]
    features.push({ type: 'Feature', properties: { kind: 'lane-fill' }, geometry: { type: 'Polygon', coordinates: [ring] } })
    for (const side of [-half, half]) {
      features.push({ type: 'Feature', properties: { kind: boundaryKind },
        geometry: { type: 'LineString', coordinates: [point(side, -extent), point(side, extent)] } })
    }
  }
  if (high != null) lane(high, low != null && high > low || !reliable ? 'uncertain' : 'certain')
  if (low != null && high != null && high > low) {
    const half = low / 2
    const extent = Math.max(8, Math.abs(y0) + length)
    for (const side of [-half, half]) {
      features.push({ type: 'Feature', properties: { kind: reliable ? 'certain' : 'uncertain' },
        geometry: { type: 'LineString', coordinates: [point(side, -extent), point(side, extent)] } })
    }
  }
  const corners = [[-length / 2, -mirrorWidth / 2], [length / 2, -mirrorWidth / 2],
    [length / 2, mirrorWidth / 2], [-length / 2, mirrorWidth / 2]].map(([dx, dy]) =>
    point(x0 + dx * Math.cos(psi) - dy * Math.sin(psi), y0 + dx * Math.sin(psi) + dy * Math.cos(psi)))
  features.push({ type: 'Feature', properties: { kind: reliable ? 'body-certain' : 'body-uncertain' },
    geometry: { type: 'Polygon', coordinates: [[...corners, corners[0]]] } })
  return { type: 'FeatureCollection', features }
}

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export function MapView(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const markers = useRef<maplibregl.Marker[]>([])
  const floodPopup = useRef<maplibregl.Popup | null>(null)
  const framed = useRef('')
  const [mapReadyTick, setMapReadyTick] = useState(0)
  const animationTimer = useRef<number | null>(null)
  const cb = useRef(p)
  cb.current = p

  useEffect(() => {
    if (!box.current) return
    const m = new maplibregl.Map({
      container: box.current, style: p.styleUrl, center: [p.center[1], p.center[0]], zoom: 14.6,
      attributionControl: { compact: true },
    })
    map.current = m
    let featureTimer: number | undefined
    const labelLayers = () => (m.getStyle().layers ?? []).filter((l) => l.type === 'symbol' && l.layout?.['text-field'] && 'source-layer' in l && typeof l.source === 'string' && m.getStyle().sources[l.source]?.type === 'vector')
    const publishFeatures = () => {
      const c = m.getCenter(), center = { lat: c.lat, lon: c.lng }, bounds = m.getBounds()
      const candidates: MapPlace[] = []
      const seen = new Set<string>()
      for (const l of labelLayers()) {
        if (!('source' in l) || typeof l.source !== 'string' || !('source-layer' in l) || !l['source-layer']) continue
        const key = `${l.source}/${l['source-layer']}`
        if (seen.has(key)) continue
        seen.add(key)
        for (const f of m.querySourceFeatures(l.source, { sourceLayer: l['source-layer'] })) {
          const place = featurePlace(f, l['source-layer'], center)
          if (place && bounds.contains([place.lon, place.lat])) candidates.push(place)
        }
      }
      cb.current.onFeatures({ center, zoom: m.getZoom(), candidates })
    }
    const scheduleFeatures = () => { window.clearTimeout(featureTimer); featureTimer = window.setTimeout(publishFeatures, 150) }
    m.on('idle', scheduleFeatures)
    m.on('moveend', scheduleFeatures)
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    m.on('load', () => {
      for (const l of m.getStyle().layers ?? []) if (l.type === 'fill-extrusion') m.setLayoutProperty(l.id, 'visibility', 'none')
      const fit = { fits: css('--fit-fits'), tight: css('--fit-tight'), no: css('--fit-no'), unknown: css('--fit-unknown'), blocked: css('--fit-blocked') }
      ;['corridor', 'flood', 'fit', 'standard', 'approach', 'route', 'wayout', 'walk', 'cams', 'maneuver'].forEach((id) => m.addSource(id, { type: 'geojson', data: EMPTY }))
      // Large-road alternatives under everything else; the chosen one is drawn like the route itself.
      m.addLayer({ id: 'corridor-alt', type: 'line', source: 'corridor', filter: ['!', ['get', 'sel']], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': css('--n-500'), 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 3, 16, 6], 'line-opacity': 0.45 } })
      m.addLayer({ id: 'flood', type: 'line', source: 'flood', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': css('--flood-risky'), 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2, 17, 9], 'line-opacity': 0.28 } })
      const notMain: maplibregl.FilterSpecification = ['!=', ['get', 'kind'], 'main']
      m.addLayer({ id: 'fit', type: 'line', source: 'fit', filter: ['all', notMain, ['!=', ['get', 'fit'], 'unknown']], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['match', ['get', 'fit'], 'fits', fit.fits, 'tight', fit.tight, 'no', fit.no, 'blocked', fit.blocked, '#999'],
          'line-width': ['interpolate', ['linear'], ['zoom'], 14, 1.4, 17, 4], 'line-opacity': ['interpolate', ['linear'], ['zoom'], 13.5, 0, 14.5, 0.9] } })
      m.addLayer({ id: 'fit-unknown', type: 'line', source: 'fit', filter: ['all', notMain, ['==', ['get', 'fit'], 'unknown']],
        paint: { 'line-color': fit.unknown, 'line-dasharray': [1.4, 1.4], 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 1, 17, 3],
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 13.5, 0, 14.5, 0.8] } })
      m.addLayer({ id: 'corridor-casing', type: 'line', source: 'corridor', filter: ['get', 'sel'], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 6, 17, 12] } })
      m.addLayer({ id: 'corridor-sel', type: 'line', source: 'corridor', filter: ['get', 'sel'], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': css('--route'), 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 3.5, 17, 7], 'line-opacity': 0.85 } })
      for (const id of ['approach', 'route']) {
        m.addLayer({ id: `${id}-casing`, type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 7, 17, 12] } })
        m.addLayer({ id, type: 'line', source: id, layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': css('--route'), 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 4, 17, 7] } })
      }
      m.addLayer({ id: 'wayout', type: 'line', source: 'wayout', layout: { 'line-cap': 'round' },
        paint: { 'line-color': css('--route'), 'line-width': 3, 'line-dasharray': [0.1, 1.6], 'line-opacity': 0.9 } })
      m.addLayer({ id: 'walk', type: 'line', source: 'walk', layout: { 'line-cap': 'round' },
        paint: { 'line-color': css('--signal'), 'line-width': 4, 'line-dasharray': [0.1, 1.5] } })
      // The reference route mostly runs on the same streets as ours: draw it on top, cased, so where it leaves ours shows.
      m.addLayer({ id: 'standard-casing', type: 'line', source: 'standard', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 5, 17, 9], 'line-opacity': 0.9 } })
      m.addLayer({ id: 'standard', type: 'line', source: 'standard', layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: { 'line-color': css('--route-standard'), 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 2.5, 17, 5], 'line-dasharray': [2, 1.5] } })
      const cam = { ok: css('--fit-fits'), un: css('--fit-tight'), jam: css('--fit-no'), water: css('--flood-risky'), none: css('--fit-unknown') }
      m.addLayer({ id: 'cams', type: 'circle', source: 'cams', minzoom: 10.5,
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['case', ['get', 'read'], 4, 2.5], 16, ['case', ['get', 'read'], 8, 5]],
          'circle-color': ['match', ['get', 'cls'], 'cam-water', cam.water, 'cam-ket_cung', cam.jam, 'cam-un_u', cam.un, 'cam-dong', css('--traffic-busy'), 'cam-thong_thoang', cam.ok, cam.none],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['case', ['get', 'read'], 2, 1] } })
      m.addLayer({ id: 'maneuver-lane-fill', type: 'fill', source: 'maneuver', filter: ['==', ['get', 'kind'], 'lane-fill'],
        paint: { 'fill-color': css('--brand-tint'), 'fill-opacity': 0.42 } })
      m.addLayer({ id: 'maneuver-lane-certain', type: 'line', source: 'maneuver', filter: ['==', ['get', 'kind'], 'certain'],
        paint: { 'line-color': css('--brand'), 'line-width': 2.5 } })
      m.addLayer({ id: 'maneuver-lane-uncertain', type: 'line', source: 'maneuver', filter: ['==', ['get', 'kind'], 'uncertain'],
        paint: { 'line-color': css('--fit-unknown'), 'line-width': 2.5, 'line-dasharray': [2, 1.5] } })
      m.addLayer({ id: 'maneuver-body-fill', type: 'fill', source: 'maneuver', filter: ['in', ['get', 'kind'], ['literal', ['body-certain', 'body-uncertain']]],
        paint: { 'fill-color': css('--brand'), 'fill-opacity': 0.82 } })
      m.addLayer({ id: 'maneuver-body-line', type: 'line', source: 'maneuver', filter: ['==', ['get', 'kind'], 'body-certain'],
        paint: { 'line-color': css('--brand'), 'line-width': 2.5 } })
      m.addLayer({ id: 'maneuver-body-dash', type: 'line', source: 'maneuver', filter: ['==', ['get', 'kind'], 'body-uncertain'],
        paint: { 'line-color': css('--brand'), 'line-width': 2.5, 'line-dasharray': [2, 1.5] } })
      ready.current = true
      setMapReadyTick((tick) => tick + 1)
      sync()
    })
    m.on('click', (e) => {
      const cam = m.queryRenderedFeatures([[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]], { layers: ['cams'] })
      if (cam.length) return cb.current.onCameraClick(String(cam[0].properties?.id))
      if (cb.current.toggles.flood && cb.current.plan) {
        const waterHit = m.queryRenderedFeatures(e.point, { layers: ['flood'] })[0]
        const feature = waterHit && cb.current.plan.layers.flood.features.find((f) => f.properties?.way_id === Number(waterHit.properties?.way_id))
        if (feature?.properties) {
          const props = feature.properties as unknown as FloodLayerProperties
          const moment = cb.current.floodMoment
          const depth = props[moment]
          const knowledge = moment === 'arrive' ? props.knowledge_arrive : props.knowledge_depart
          const reason = moment === 'arrive' ? props.reason_arrive : props.reason_depart
          const freshness = moment === 'arrive' ? props.freshness_arrive : props.freshness_depart
          const at = moment === 'arrive' ? cb.current.plan.window.arrive : cb.current.plan.window.depart
          const status = moment === 'arrive' ? props.status_arrive : props.status_depart
          const content = document.createElement('div')
          content.className = 'flood-popup'
          const title = document.createElement('b')
          title.textContent = props.name || `Đoạn đường ${props.way_id}`
          content.append(title)
          const messages = [
            `${moment === 'arrive' ? 'Lúc đến' : 'Lúc rời'}: ${floodTimeLabel(at)}.`,
            floodPresentation({ status, depth, knowledge, reason, freshness, at }).label,
            depth != null && Number.isFinite(depth.lo) && Number.isFinite(depth.hi)
              ? `Ước lượng nước ${Math.round(depth.lo * 100)}–${Math.round(depth.hi * 100)} cm.`
              : 'Chưa xác định độ sâu nước; không thể kết luận trong ngưỡng xe.',
            floodKnowledgeLabel(knowledge),
            reason,
            freshness?.source && `Nguồn: ${freshness.source}.`,
            freshness?.observed_at && `Ghi nhận: ${floodTimeLabel(freshness.observed_at)}.`,
            freshness?.valid_until && `Hiệu lực tới: ${floodTimeLabel(freshness.valid_until)}.`,
            depth?.drivers.length ? `Căn cứ: ${depth.drivers.join('; ')}.` : null,
          ]
          for (const message of messages) {
            if (!message) continue
            const paragraph = document.createElement('p')
            paragraph.textContent = message
            content.append(paragraph)
          }
          const evidence = document.createElement('button')
          evidence.type = 'button'
          evidence.className = 'btn btn-outline btn-sm'
          evidence.textContent = 'Xem bằng chứng'
          evidence.addEventListener('click', () => cb.current.onWayClick(props.way_id, e.lngLat.lat, e.lngLat.lng))
          content.append(evidence)
          floodPopup.current?.remove()
          floodPopup.current = new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setDOMContent(content).addTo(m)
          return
        }
      }
      const labels = labelLayers().map((l) => l.id)
      const features = labels.length ? m.queryRenderedFeatures([[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]], { layers: labels }) : []
      for (const f of features) {
        const place = featurePlace(f, f.sourceLayer ?? f.layer.id, { lat: e.lngLat.lat, lon: e.lngLat.lng })
        if (place) { cb.current.onPlaceClick(place); return }
      }
      const hit = m.queryRenderedFeatures(e.point, { layers: ['fit', 'fit-unknown'] })
      if (hit.length) cb.current.onWayClick(Number(hit[0].properties?.way_id), e.lngLat.lat, e.lngLat.lng)
    })
    m.on('contextmenu', (e) => cb.current.onPick(e.lngLat.lat, e.lngLat.lng, e.point.x, e.point.y))
    let press: number | undefined
    m.on('touchstart', (e) => {
      if (e.originalEvent.touches.length !== 1) return
      press = window.setTimeout(() => cb.current.onPick(e.lngLat.lat, e.lngLat.lng, e.point.x, e.point.y), 550)
    })
    for (const ev of ['touchend', 'touchmove', 'dragstart'] as const) m.on(ev, () => window.clearTimeout(press))
    for (const id of ['fit', 'fit-unknown', 'flood', 'cams']) {
      m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer' })
      m.on('mouseleave', id, () => { m.getCanvas().style.cursor = '' })
    }
    return () => {
      window.clearTimeout(featureTimer)
      if (animationTimer.current != null) window.clearInterval(animationTimer.current)
      animationTimer.current = null
      floodPopup.current?.remove()
      m.remove()
      map.current = null
      ready.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.styleUrl])

  const sync = () => {
    const m = map.current
    if (!m || !ready.current) return
    floodPopup.current?.remove()
    const { plan, selected, toggles, floodMoment, destination, origin, corridor, routeSel, cams, maneuver } = cb.current
    const set = (id: string, data: GeoJSON.FeatureCollection) => (m.getSource(id) as GeoJSONSource | undefined)?.setData(data)
    const sp = plan?.stop_points[selected]
    set('fit', plan && toggles.fit ? plan.layers.fit : EMPTY)
    set('flood', plan && toggles.flood ? plan.layers.flood : EMPTY)
    set('standard', line(toggles.standard ? plan?.standard_route?.geometry : undefined))
    // With a corridor, its chosen large-road route replaces the stop's own approach.
    set('approach', line(corridor ? undefined : sp?.approach?.geometry))
    set('corridor', corridor ? { type: 'FeatureCollection', features: corridor.routes.map((r) => ({
      type: 'Feature', properties: { id: r.id, sel: r.id === routeSel }, geometry: { type: 'LineString', coordinates: r.geometry } })) } : EMPTY)
    set('cams', toggles.cams ? { type: 'FeatureCollection', features: cams.map((c) => {
      const r = c.reading
      const read = !!r && r.state === 'ok'
      const cls = !read ? 'cam-none' : r.flooded === true || (r.depth_cm != null && r.depth_cm > 0) ? 'cam-water' : `cam-${r.traffic ?? 'none'}`
      return { type: 'Feature', properties: { id: c.id, read, cls }, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } }
    }) } : EMPTY)
    set('route', line(sp?.route_in?.geometry))
    set('wayout', line(sp?.way_out?.geometry))
    set('walk', line(sp?.walk?.geometry))
    set('maneuver', maneuverFeatures(maneuver, maneuver?.state.status === 'ready'
      ? maneuver.state.result.poses?.[0] ?? null
      : null))
    const key = floodMoment === 'arrive' ? 'status_arrive' : 'status_depart'
    const knowledgeKey = floodMoment === 'arrive' ? 'knowledge_arrive' : 'knowledge_depart'
    m.setFilter('flood', ['any', ['in', ['get', key], ['literal', ['risky', 'blocked']]], ['!=', ['get', knowledgeKey], 'known']])
    m.setPaintProperty('flood', 'line-color', ['match', ['get', key], 'blocked', css('--flood-over'), css('--flood-risky')])

    markers.current.forEach((mk) => mk.remove())
    markers.current = []
    const add = (el: HTMLElement, ll: LL, anchor: maplibregl.PositionAnchor = 'center') =>
      markers.current.push(new maplibregl.Marker({ element: el, anchor }).setLngLat([ll.lon, ll.lat]).addTo(m))
    if (origin) { const el = document.createElement('div'); el.className = 'mk-origin'; add(el, origin) }
    if (destination) {
      const el = document.createElement('div')
      el.className = 'mk-dest'
      el.innerHTML = '<svg viewBox="0 0 24 32" width="30" height="40" aria-hidden="true"><path d="M12 31s10-11.2 10-19A10 10 0 0 0 2 12c0 7.8 10 19 10 19z"/><circle cx="12" cy="12" r="4" fill="#fff"/></svg>'
      add(el, destination, 'bottom')
    }
    plan?.stop_points.forEach((s, i) => {
      if (i === selected && maneuver?.state.status === 'ready') return
      const el = document.createElement('button')
      el.type = 'button'
      el.className = `mk-stop ${i === selected ? 'on' : ''} ${s.verified ? '' : 'unverified'}`
      el.textContent = String(i + 1)
      el.setAttribute('aria-label', `Điểm dừng ${i + 1}: ${s.name}`)
      el.addEventListener('click', (ev) => { ev.stopPropagation(); cb.current.onStopClick(i) })
      add(el, s)
    })

    // Frame the whole trip once per new plan (origin → stop → destination).
    const { frame } = cb.current
    const std = toggles.standard ? plan?.standard_route?.geometry : undefined
    const sig = plan ? `${plan.destination.lat},${plan.destination.lon},${plan.origin?.lat},${frame},${frame === 'trip' ? `${corridor?.checked_at}${routeSel}` : ''},${!!std}` : ''
    if (plan && sig !== framed.current) {
      framed.current = sig
      // Arrival frame: the last stretch is the product. Trip frame: origin to destination, like any map.
      const pts: number[][] = [[plan.destination.lon, plan.destination.lat]]
      plan.stop_points.forEach((s) => pts.push([s.lon, s.lat]))
      if (sp?.route_in) pts.push(...sp.route_in.geometry)
      if (frame === 'trip') {
        if (origin) pts.push([origin.lon, origin.lat])
        if (sp?.approach && !corridor) pts.push(...sp.approach.geometry)
        const cr = corridor?.routes.find((r) => r.id === routeSel)
        if (cr) pts.push(...cr.geometry)
      }
      // Showing the reference route zooms to where it differs: its last stretch into the destination's alleys.
      if (std) pts.push(...(frame === 'trip' ? std : std.filter(([lon, lat]) => Math.hypot(lon - plan.destination.lon, lat - plan.destination.lat) < 0.006)))
      const b = pts.reduce((bb, c) => bb.extend(c as [number, number]), new maplibregl.LngLatBounds(pts[0] as [number, number], pts[0] as [number, number]))
      m.fitBounds(b, { padding: cb.current.padding, maxZoom: frame === 'trip' ? 16 : 17, duration: 900 })
    }
  }

  useEffect(sync, [p.plan, p.selected, p.toggles, p.floodMoment, p.destination, p.origin, p.frame, p.corridor, p.routeSel, p.cams, p.maneuver])
  // The dock and the inspector change how much map is free: keep what is framed inside the visible part.
  useEffect(() => {
    const m = map.current
    if (!m || !ready.current) return
    m.easeTo({ padding: p.padding, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 300 })
  }, [p.padding.bottom, p.padding.right]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const m = map.current
    const overlay = p.maneuver
    if (!m || !ready.current || !overlay || overlay.state.status !== 'ready') return
    const { result, playback } = overlay.state
    const poses = result.moves == null ? null : result.poses
    if (!poses?.length || playback === 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    if (animationTimer.current != null) window.clearInterval(animationTimer.current)
    let index = 0
    const timer = window.setInterval(() => {
      index += 1
      ;(m.getSource('maneuver') as GeoJSONSource | undefined)?.setData(maneuverFeatures(overlay, poses[Math.min(index, poses.length - 1)]))
      if (index >= poses.length - 1) {
        window.clearInterval(timer)
        animationTimer.current = null
      }
    }, 140)
    animationTimer.current = timer
    return () => {
      window.clearInterval(timer)
      if (animationTimer.current === timer) animationTimer.current = null
    }
  }, [p.maneuver, mapReadyTick])
  useEffect(() => {
    const m = map.current
    const overlay = p.maneuver
    if (!m || !ready.current || !overlay) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    m.easeTo({ center: [overlay.stop.lon, overlay.stop.lat], zoom: Math.max(m.getZoom(), 19), padding: p.padding, duration: reduced ? 0 : 240 })
  }, [p.maneuver?.state.key, mapReadyTick])

  useEffect(() => {
    const m = map.current
    if (!m || !p.destination || p.plan) return
    m.easeTo({ center: [p.destination.lon, p.destination.lat], zoom: Math.max(m.getZoom(), 15.5), duration: 700, padding: p.padding })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.destination])

  return <div ref={box} className="map" role="region" aria-label={`Bản đồ chuyến đi${p.toggles.standard && p.plan?.standard_route ? `, tuyến tham chiếu ${routeSourceLabel(p.plan.standard_route.source)}` : ''}`} />
}
