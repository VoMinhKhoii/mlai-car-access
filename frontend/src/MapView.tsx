import maplibregl, { type GeoJSONSource, type Map as MLMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type * as GeoJSON from 'geojson'
import { useEffect, useRef } from 'react'
import { routeSourceLabel, type CameraInfo, type Corridor, type Plan } from './api'

export interface LayerToggles { fit: boolean; flood: boolean; standard: boolean; cams: boolean }
export type FloodMoment = 'arrive' | 'depart'
type LL = { lat: number; lon: number }

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
  onCameraClick: (id: string) => void
  onPick: (lat: number, lon: number, x: number, y: number) => void
  onWayClick: (wayId: number, lat: number, lon: number) => void
  onStopClick: (index: number) => void
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const line = (coords?: number[][]): GeoJSON.FeatureCollection =>
  coords && coords.length > 1
    ? { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }] }
    : EMPTY

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export function MapView(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const ready = useRef(false)
  const markers = useRef<maplibregl.Marker[]>([])
  const framed = useRef('')
  const cb = useRef(p)
  cb.current = p

  useEffect(() => {
    if (!box.current) return
    const m = new maplibregl.Map({
      container: box.current, style: p.styleUrl, center: [p.center[1], p.center[0]], zoom: 14.6,
      attributionControl: { compact: true },
    })
    map.current = m
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    m.on('load', () => {
      for (const l of m.getStyle().layers ?? []) if (l.type === 'fill-extrusion') m.setLayoutProperty(l.id, 'visibility', 'none')
      const fit = { fits: css('--fit-fits'), tight: css('--fit-tight'), no: css('--fit-no'), unknown: css('--fit-unknown'), blocked: css('--fit-blocked') }
      ;['corridor', 'flood', 'fit', 'standard', 'approach', 'route', 'wayout', 'walk', 'cams'].forEach((id) => m.addSource(id, { type: 'geojson', data: EMPTY }))
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
      m.addLayer({ id: 'standard', type: 'line', source: 'standard', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': css('--route-standard'), 'line-width': 3, 'line-dasharray': [0.1, 1.8], 'line-opacity': 0.85 } })
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
      const cam = { ok: css('--fit-fits'), un: css('--fit-tight'), jam: css('--fit-no'), water: css('--flood-risky'), none: css('--fit-unknown') }
      m.addLayer({ id: 'cams', type: 'circle', source: 'cams', minzoom: 10.5,
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['case', ['get', 'read'], 4, 2.5], 16, ['case', ['get', 'read'], 8, 5]],
          'circle-color': ['match', ['get', 'cls'], 'cam-water', cam.water, 'cam-ket_cung', cam.jam, 'cam-un_u', cam.un, 'cam-dong', css('--traffic-busy'), 'cam-thong_thoang', cam.ok, cam.none],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': ['case', ['get', 'read'], 2, 1] } })
      ready.current = true
      sync()
    })
    m.on('click', (e) => {
      const cam = m.queryRenderedFeatures([[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]], { layers: ['cams'] })
      if (cam.length) return cb.current.onCameraClick(String(cam[0].properties?.id))
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
    for (const id of ['fit', 'fit-unknown', 'cams']) {
      m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer' })
      m.on('mouseleave', id, () => { m.getCanvas().style.cursor = '' })
    }
    return () => { m.remove(); map.current = null; ready.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.styleUrl])

  const sync = () => {
    const m = map.current
    if (!m || !ready.current) return
    const { plan, selected, toggles, floodMoment, destination, origin, corridor, routeSel, cams } = cb.current
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
      const cls = !read ? 'cam-none' : r.depth_cm ? 'cam-water' : `cam-${r.traffic ?? 'none'}`
      return { type: 'Feature', properties: { id: c.id, read, cls }, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } }
    }) } : EMPTY)
    set('route', line(sp?.route_in?.geometry))
    set('wayout', line(sp?.way_out?.geometry))
    set('walk', line(sp?.walk?.geometry))
    const key = floodMoment === 'arrive' ? 'status_arrive' : 'status_depart'
    m.setFilter('flood', ['in', ['get', key], ['literal', ['risky', 'blocked']]])
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
    const sig = plan ? `${plan.destination.lat},${plan.destination.lon},${plan.origin?.lat},${frame},${frame === 'trip' ? `${corridor?.checked_at}${routeSel}` : ''}` : ''
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
      const b = pts.reduce((bb, c) => bb.extend(c as [number, number]), new maplibregl.LngLatBounds(pts[0] as [number, number], pts[0] as [number, number]))
      m.fitBounds(b, { padding: cb.current.padding, maxZoom: frame === 'trip' ? 16 : 17, duration: 900 })
    }
  }

  useEffect(sync, [p.plan, p.selected, p.toggles, p.floodMoment, p.destination, p.origin, p.frame, p.corridor, p.routeSel, p.cams])

  useEffect(() => {
    const m = map.current
    if (!m || !p.destination || p.plan) return
    m.easeTo({ center: [p.destination.lon, p.destination.lat], zoom: Math.max(m.getZoom(), 15.5), duration: 700, padding: p.padding })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.destination])

  return <div ref={box} className="map" role="region" aria-label={`Bản đồ chuyến đi${p.toggles.standard && p.plan?.standard_route ? `, tuyến tham chiếu ${routeSourceLabel(p.plan.standard_route.source)}` : ''}`} />
}
