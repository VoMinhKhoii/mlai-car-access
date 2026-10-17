import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import './welcome.css'
import type { Config, Plan, Vehicle } from '../api'

document.documentElement.classList.add('js')
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)
const $$ = <T extends Element = HTMLElement>(sel: string) => Array.from(document.querySelectorAll<T>(sel))
const m2 = (n: number) => n.toFixed(2)
const nf = new Intl.NumberFormat('en-US')

/* ---------- Real data: three alleys from the live engine, two cars ---------- */
interface Alley { id: string; name: string; lat: number; lon: number; width: number; hi: number | null; tier: string; wayId: number | null }
// Fallbacks are the values the live engine returned on 17 Oct 2026; replaced by fresh /api/plan answers on load.
const alleys: Record<string, Alley> = {
  '356': { id: '356', name: 'Hẻm 356 Xô Viết Nghệ Tĩnh', lat: 10.8034189, lon: 106.711972, width: 2.2, hi: 4.5, tier: 'Observed', wayId: 1330786038 },
  '160': { id: '160', name: 'Hẻm 160 Ngô Tất Tố', lat: 10.7896558, lon: 106.7155889, width: 2.5, hi: 15, tier: 'Observed', wayId: 544982029 },
  '220': { id: '220', name: 'Hẻm 220/9 Xô Viết Nghệ Tĩnh', lat: 10.7992432, lon: 106.7123911, width: 5.49, hi: 5.49, tier: 'Inferred', wayId: 32584409 },
}
type Car = Pick<Vehicle, 'id' | 'label' | 'body_width' | 'mirror_width' | 'fits_min' | 'tight_min'>
const cars: Record<string, Car> = {
  'toyota-fortuner': { id: 'toyota-fortuner', label: 'Toyota Fortuner', body_width: 1.855, mirror_width: 2.105, fits_min: 3.41, tight_min: 2.31 },
  'vinfast-vf-3': { id: 'vinfast-vf-3', label: 'VinFast VF 3', body_width: 1.679, mirror_width: 1.748, fits_min: 3.05, tight_min: 1.95 },
}
let carId = 'toyota-fortuner'
let alleyId = '356'
const plans = new Map<string, Plan>()

/* ---------- The car between the walls ---------- */
const SCALE = 100 // px per metre in the 600 x 300 drawing
const answerOf = (w: number, c: Car) => (w >= c.fits_min ? 'Fits' : w >= c.tight_min ? 'Tight' : "Won't fit")

function drawFit(animate = true) {
  const a = alleys[alleyId]; const c = cars[carId]
  const gap = a.width * SCALE
  const set = (sel: string, t: string) => { const el = $<SVGGraphicsElement>(sel); if (el) el.style.transform = t }
  set('#wall-l', `translateX(${-gap / 2}px)`)
  set('#wall-r', `translateX(${gap / 2}px)`)
  set('#car-body', `scaleX(${c.body_width})`)
  const arm = Math.max(0.06, (c.mirror_width - c.body_width) / 2 + 0.03)
  set('#mirror-l', `translateX(${-c.mirror_width / 2}px) scaleX(${arm})`)
  set('#mirror-r', `translateX(${c.mirror_width / 2 - arm}px) scaleX(${arm})`)
  const label = $('#gap-label'); if (label) label.textContent = `${m2(a.width)} m`

  const spare = (a.width - c.mirror_width) / 2
  const answer = answerOf(a.width, c)
  $('#fit')?.classList.toggle('is-clash', answer === "Won't fit")
  const word = $('#fit-word')!
  const numbers = $('#fit-numbers')!
  const text = `${m2(a.width)} m clear (${a.tier}), mirrors ${m2(c.mirror_width)} m, ${spare >= 0 ? `${(spare * 100).toFixed(1)} cm spare each side` : `${(-spare * 100).toFixed(1)} cm too wide each side`}`
  const swap = () => { word.textContent = answer; numbers.textContent = text; word.classList.remove('is-out') }
  if (animate && !reduce && word.textContent !== answer) { word.classList.add('is-out'); window.setTimeout(swap, 200) } else swap()

  const spec = (id: string, v: string) => { const el = $(id); if (el) el.textContent = v }
  spec('#spec-name', c.label); spec('#spec-body', `${m2(c.body_width)} m`); spec('#spec-mirror', `${m2(c.mirror_width)} m`); spec('#spec-fits', `${m2(c.fits_min)} m`)
}

$$<HTMLButtonElement>('[data-vehicle]').forEach((b) => b.addEventListener('click', () => {
  carId = b.dataset.vehicle!
  $$<HTMLButtonElement>('[data-vehicle]').forEach((x) => x.setAttribute('aria-checked', String(x === b)))
  drawFit(); paintMap()
}))
// Arrow keys move within the radio group, as a native radio group would.
$('.fit .seg')?.addEventListener('keydown', (e) => {
  const k = (e as KeyboardEvent).key
  if (k !== 'ArrowLeft' && k !== 'ArrowRight') return
  const btns = $$<HTMLButtonElement>('[data-vehicle]')
  const i = btns.findIndex((x) => x.getAttribute('aria-checked') === 'true')
  const next = btns[(i + (k === 'ArrowRight' ? 1 : btns.length - 1)) % btns.length]
  next.focus(); next.click(); e.preventDefault()
})
const select = $<HTMLSelectElement>('#alley-select')!
select.addEventListener('change', () => chooseAlley(select.value))

/* ---------- Live map (Goong tiles through the app's own config) ---------- */
let map: maplibregl.Map | null = null
const FIT_COLOURS = { room: '#2f6b3a', tight: '#a86a00', no: '#a3271f', unknown: '#6b747a' }

function fitExpression(c: Car): maplibregl.ExpressionSpecification {
  return ['case',
    ['!', ['has', 'lo']], FIT_COLOURS.unknown,
    ['>=', ['coalesce', ['get', 'lo'], 0], c.fits_min], FIT_COLOURS.room,
    ['>=', ['coalesce', ['get', 'lo'], 0], c.tight_min], FIT_COLOURS.tight,
    FIT_COLOURS.no]
}
function paintMap() {
  if (!map?.getLayer('fit')) return
  map.setPaintProperty('fit', 'line-color', fitExpression(cars[carId]))
}

async function planFor(id: string): Promise<Plan | null> {
  if (plans.has(id)) return plans.get(id)!
  const a = alleys[id]
  try {
    const res = await fetch('/api/plan', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ lat: a.lat, lon: a.lon, label: a.name, vehicle_id: 'toyota-fortuner', intent: 'park', arrive_at: null, dwell_min: 90, rain: [], origin: null }) })
    if (!res.ok) return null
    const plan = await res.json() as Plan
    plans.set(id, plan)
    return plan
  } catch { return null }
}

function showFacts(id: string, plan: Plan | null) {
  const a = alleys[id]
  $('#mf-width')!.textContent = `${m2(a.width)} m`
  $('#mf-tier')!.textContent = a.tier
  if (plan) $('#mf-count')!.textContent = nf.format(plan.layers.fit.features.length)
  const open = $<HTMLAnchorElement>('#map-open'); if (open) open.href = `/?ui=v2&q=${encodeURIComponent(a.name)}`
  const measure = $<HTMLInputElement>('#measure input[name=alley]'); if (measure) measure.value = a.name
}

async function chooseAlley(id: string) {
  alleyId = id
  select.value = id
  $$<HTMLButtonElement>('[data-alley]').forEach((x) => x.setAttribute('aria-selected', String(x.dataset.alley === id)))
  drawFit()
  showFacts(id, plans.get(id) ?? null)
  const a = alleys[id]
  map?.flyTo({ center: [a.lon, a.lat], zoom: 16.4, duration: reduce ? 0 : 1400, essential: true })
  const plan = await planFor(id)
  if (alleyId !== id) return
  showFacts(id, plan)
  const src = map?.getSource('fit') as maplibregl.GeoJSONSource | undefined
  if (plan && src) src.setData(plan.layers.fit)
  const sel = map?.getSource('sel') as maplibregl.GeoJSONSource | undefined
  if (plan && sel) sel.setData({ type: 'FeatureCollection', features: plan.layers.fit.features.filter((f) => f.properties?.way_id === a.wayId) })
}

$$<HTMLButtonElement>('[data-alley]').forEach((b) => b.addEventListener('click', () => chooseAlley(b.dataset.alley!)))

async function boot() {
  let config: Config | null = null
  try { config = await fetch('/api/config').then((r) => r.json()) as Config } catch { /* fallback copy stays */ }
  const cov = (config as unknown as { coverage?: Record<string, unknown> } | null)?.coverage
  if (cov) {
    const tiers = (cov.evidence_ways_by_strongest_tier ?? {}) as Record<string, number>
    const fill = (k: string, v: unknown) => { if (typeof v === 'number') $$(`[data-live="${k}"]`).forEach((el) => { el.textContent = nf.format(v) }) }
    fill('ways', cov.evidence_ways_with_sources)
    fill('observed', tiers.Observed); fill('declared', tiers.Declared); fill('inferred', tiers.Inferred)
  }
  fetch('/api/vehicles').then((r) => r.json() as Promise<{ models: Vehicle[]; classes: Vehicle[] }>).then((v) => {
    for (const id of Object.keys(cars)) { const live = v.models.find((x) => x.id === id); if (live) cars[id] = live }
    $$('[data-live="models"]').forEach((el) => { el.textContent = String(v.models.length) })
    $$('[data-live="classes"]').forEach((el) => { el.textContent = String(v.classes.length) })
    drawFit(false); paintMap()
  }).catch(() => { /* fallback dimensions stay */ })

  // Refresh the three alleys' widths from the live engine (first stop on each is the alley itself).
  for (const id of Object.keys(alleys)) {
    planFor(id).then((plan) => {
      const stop = plan?.stop_points.find((s) => s.way_id === alleys[id].wayId && s.fit.width_range && s.fit.width_range.lo > 0)
      const wr = stop?.fit.width_range
      if (wr) { alleys[id] = { ...alleys[id], width: wr.lo, hi: wr.hi, tier: wr.top_tier ?? alleys[id].tier } }
      if (id === alleyId) { drawFit(false); showFacts(id, plan) }
    })
  }

  if (config?.map_style) {
    const a = alleys[alleyId]
    map = new maplibregl.Map({ container: 'goong-map', style: config.map_style, center: [a.lon, a.lat], zoom: 16.2,
      attributionControl: { compact: true }, cooperativeGestures: true })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.on('load', async () => {
      map!.addSource('fit', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map!.addSource('sel', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map!.addLayer({ id: 'sel-casing', type: 'line', source: 'sel', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#1c1c1c', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 8, 18, 18] } })
      map!.addLayer({ id: 'fit', type: 'line', source: 'fit', layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': fitExpression(cars[carId]), 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 2.5, 18, 9] } })
      map!.on('mouseenter', 'fit', () => { map!.getCanvas().style.cursor = 'pointer' })
      map!.on('mouseleave', 'fit', () => { map!.getCanvas().style.cursor = '' })
      map!.on('click', 'fit', (e) => {
        const p = e.features?.[0]?.properties as { name?: string; lo?: number; hi?: number; top_tier?: string } | undefined
        if (!p) return
        const width = typeof p.lo === 'number' ? `${m2(p.lo)}${p.hi && p.hi !== p.lo ? ` to ${m2(p.hi)}` : ''} m` : 'no width on record'
        new maplibregl.Popup({ closeButton: false, offset: 8 }).setLngLat(e.lngLat)
          .setHTML(`<strong>${(p.name ?? 'Unnamed hẻm').replace(/</g, '&lt;')}</strong><br>${width}${p.top_tier ? `, ${p.top_tier}` : ''}`).addTo(map!)
      })
      await chooseAlley(alleyId)
    })
  }
  drawTide(config)
}

/* ---------- Tide tile: the next 36 hours from the official bulletin ---------- */
async function drawTide(config: Config | null) {
  try {
    const start = new Date(); start.setMinutes(0, 0, 0)
    const iso = new Date(start.getTime() + 7 * 3600e3).toISOString().slice(0, 19) + '+07:00'
    const t = await fetch(`/api/tide?start=${encodeURIComponent(iso)}&hours=36`).then((r) => r.json()) as { series: { t: string; level_m: number }[]; alarm_levels_m: Record<string, number>; station: string }
    if (!t.series?.length) return
    const bd1 = t.alarm_levels_m?.BD1 ?? 1.4
    const lo = -2, hi = 2
    const y = (v: number) => 160 - ((v - lo) / (hi - lo)) * 160
    const d = t.series.map((p, i) => `${i ? 'L' : 'M'}${((i / (t.series.length - 1)) * 400).toFixed(1)} ${y(p.level_m).toFixed(1)}`).join(' ')
    $('#tide-path')?.setAttribute('d', d)
    $('#tide-svg .tide-alarm')?.setAttribute('height', String(y(bd1)))
    const peak = Math.max(...t.series.map((p) => p.level_m))
    $('#tide-peak')!.textContent = `peak ${peak.toFixed(2)} m`
    $('#tide-bd1')!.textContent = bd1.toFixed(1)
    if (t.station || config?.tide?.station) $('#tide-station')!.textContent = 'Phú An, Saigon River'
  } catch { /* the drawn placeholder curve stays, labelled as the station */ }
}

/* ---------- Evidence accordion ---------- */
const tiers = $$('.tier')
tiers.forEach((tier) => {
  const btn = tier.querySelector<HTMLButtonElement>('.tier-name')!
  btn.addEventListener('click', () => {
    tiers.forEach((t) => {
      const open = t === tier
      t.classList.toggle('is-open', open)
      t.querySelector('.tier-name')!.setAttribute('aria-expanded', String(open))
    })
  })
})

/* ---------- Hero photograph: slow crossfade, paused when hidden ---------- */
const frames = $$<HTMLImageElement>('.hero-photo .xfade')
if (!reduce && frames.length > 1) {
  let i = 0
  window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    frames[i].classList.remove('is-on')
    i = (i + 1) % frames.length
    frames[i].classList.add('is-on')
  }, 5600)
}

/* ---------- Entrances: each section's parts, staggered ---------- */
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue
    const el = e.target as HTMLElement
    el.classList.add('is-in')
    io.unobserve(el)
  }
}, { rootMargin: '0px 0px -8% 0px' })
$$('section, .footer').forEach((sec) => {
  sec.querySelectorAll<HTMLElement>('.reveal').forEach((el, i) => { el.style.setProperty('--d', `${i * 80}ms`); io.observe(el) })
})

drawFit(false)
boot()
