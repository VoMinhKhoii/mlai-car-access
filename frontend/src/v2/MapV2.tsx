import maplibregl, { type GeoJSONSource, type Map as MLMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type * as GeoJSON from 'geojson'
import { useEffect, useRef, useState } from 'react'
import type { Plan } from '../api'
import type { MapContext } from '../mapSearch'
import { featurePlace, type MapPlace } from '../mapSearch'

type LL = { lat: number; lon: number }
interface Props {
  styleUrl: string
  center: [number, number]
  plan: Plan | null
  selected: number
  destination: LL | null
  anchor: LL | null
  anchorEl: HTMLElement
  padding: { top: number; left: number; right: number; bottom: number }
  onFeatures: (c: MapContext) => void
  onMap: (m: MLMap | null) => void
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const line = (coords?: number[][]): GeoJSON.FeatureCollection =>
  coords && coords.length > 1
    ? { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }] }
    : EMPTY

// Fit semantics only; the route uses the one accent.
const FIT = { fits: '#2f6b47', tight: '#9a6400', no: '#a3271f', blocked: '#a3271f', unknown: '#5d6872' }
const ACCENT = '#2c3620'
const INK = '#1c1c1c'

export function MapV2(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const [ready, setReady] = useState(false)
  const markers = useRef<maplibregl.Marker[]>([])
  const cutMarker = useRef<maplibregl.Marker | null>(null)
  const framed = useRef('')
  const cb = useRef(p)
  cb.current = p

  useEffect(() => {
    if (!box.current) return
    const m = new maplibregl.Map({
      container: box.current, style: p.styleUrl, center: [p.center[1], p.center[0]], zoom: 15.2,
      attributionControl: false,
    })
    map.current = m
    cb.current.onMap(m)
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.AttributionControl({ compact: true }), 'top-right')
    let featureTimer: number | undefined
    const publish = () => {
      const c = m.getCenter(), center = { lat: c.lat, lon: c.lng }, bounds = m.getBounds()
      const candidates: MapPlace[] = []
      const style = m.getStyle()
      const seen = new Set<string>()
      for (const l of style.layers ?? []) {
        if (l.type !== 'symbol' || !('source-layer' in l) || !l['source-layer'] || typeof l.source !== 'string') continue
        if (style.sources[l.source]?.type !== 'vector') continue
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
    m.on('moveend', () => { window.clearTimeout(featureTimer); featureTimer = window.setTimeout(publish, 200) })
    m.on('load', () => {
      // Quiet the base map so the alley layer reads first: no 3D, softer POI icons.
      for (const l of m.getStyle().layers ?? []) {
        if (l.type === 'fill-extrusion') m.setLayoutProperty(l.id, 'visibility', 'none')
        if (l.type === 'symbol' && l.layout?.['icon-image']) m.setPaintProperty(l.id, 'icon-opacity', 0.45)
      }
      for (const id of ['fit', 'route', 'walk']) m.addSource(id, { type: 'geojson', data: EMPTY })
      const notMain: maplibregl.FilterSpecification = ['!=', ['get', 'kind'], 'main']
      const width: maplibregl.DataDrivenPropertyValueSpecification<number> = ['interpolate', ['linear'], ['zoom'], 14, 1.6, 18, 5]
      m.addLayer({ id: 'fit-casing', type: 'line', source: 'fit', filter: ['all', notMain, ['!=', ['get', 'fit'], 'unknown']], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 3, 18, 8], 'line-opacity': 0.9 } })
      m.addLayer({ id: 'fit', type: 'line', source: 'fit', filter: ['all', notMain, ['!=', ['get', 'fit'], 'unknown']], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['match', ['get', 'fit'], 'fits', FIT.fits, 'tight', FIT.tight, 'no', FIT.no, 'blocked', FIT.blocked, FIT.unknown], 'line-width': width } })
      m.addLayer({ id: 'fit-unknown', type: 'line', source: 'fit', filter: ['all', notMain, ['==', ['get', 'fit'], 'unknown']],
        paint: { 'line-color': FIT.unknown, 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 1, 18, 3], 'line-dasharray': [2, 2], 'line-opacity': 0.55 } })
      m.addLayer({ id: 'route-casing', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 6, 18, 12] } })
      m.addLayer({ id: 'route', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ACCENT, 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 3.5, 18, 7] } })
      m.addLayer({ id: 'walk', type: 'line', source: 'walk', layout: { 'line-cap': 'round' },
        paint: { 'line-color': INK, 'line-width': 3.5, 'line-dasharray': [0.1, 1.8] } })
      setReady(true)
    })
    return () => { window.clearTimeout(featureTimer); cutMarker.current?.remove(); m.remove(); map.current = null; cb.current.onMap(null); setReady(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.styleUrl])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    const { plan, selected, destination, padding } = p
    const set = (id: string, data: GeoJSON.FeatureCollection) => (m.getSource(id) as GeoJSONSource | undefined)?.setData(data)
    const sp = plan?.stop_points[selected]
    set('fit', plan ? plan.layers.fit : EMPTY)
    set('route', line(sp?.route_in?.geometry))
    set('walk', line(sp?.walk?.geometry))
    markers.current.forEach((mk) => mk.remove())
    markers.current = []
    if (destination) {
      const el = document.createElement('div')
      el.className = 'v2-mk-dest'
      el.setAttribute('aria-hidden', 'true')
      markers.current.push(new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat([destination.lon, destination.lat]).addTo(m))
    }
    if (sp) {
      const el = document.createElement('div')
      el.className = 'v2-mk-stop'
      el.textContent = 'P'
      el.setAttribute('aria-hidden', 'true')
      markers.current.push(new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat([sp.lon, sp.lat]).addTo(m))
    }
    const sig = plan ? `${plan.destination.lat},${plan.destination.lon}` : ''
    if (plan && sig !== framed.current) {
      framed.current = sig
      const pts: [number, number][] = [[plan.destination.lon, plan.destination.lat]]
      if (sp) pts.push([sp.lon, sp.lat], ...((sp.walk.geometry ?? []) as [number, number][]))
      if (p.anchor) pts.push([p.anchor.lon, p.anchor.lat])
      const b = pts.reduce((bb, c) => bb.extend(c), new maplibregl.LngLatBounds(pts[0], pts[0]))
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      m.fitBounds(b, { padding, maxZoom: 17.2, duration: reduced ? 0 : 900 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, p.plan, p.selected, p.destination])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    if (!p.anchor) { cutMarker.current?.remove(); cutMarker.current = null; return }
    if (!cutMarker.current) cutMarker.current = new maplibregl.Marker({ element: p.anchorEl, anchor: 'bottom' })
    cutMarker.current.setLngLat([p.anchor.lon, p.anchor.lat]).addTo(m)
  }, [ready, p.anchor?.lat, p.anchor?.lon, p.anchorEl])

  useEffect(() => {
    const m = map.current
    if (!m || !ready || !p.destination || p.plan) return
    m.easeTo({ center: [p.destination.lon, p.destination.lat], zoom: Math.max(m.getZoom(), 15.5), duration: 600 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, p.destination])

  return <div ref={box} className="v2-map" role="region" aria-label="Map" />
}
