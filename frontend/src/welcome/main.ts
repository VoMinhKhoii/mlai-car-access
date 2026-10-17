import './welcome.css'
import type { Config, Vehicle } from '../api'

const $ = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)
const $$ = <T extends Element = HTMLElement>(sel: string) => Array.from(document.querySelectorAll<T>(sel))
const nf = new Intl.NumberFormat('en-US')

/* ---------- Deck: arrows, space, page keys, swipe, and #n deep links ---------- */
const slides = $$('.slide')
let at = 0

function go(n: number) {
  at = Math.max(0, Math.min(slides.length - 1, n))
  slides.forEach((s, i) => {
    s.classList.toggle('is-on', i === at)
    s.classList.toggle('is-before', i < at)
    s.setAttribute('aria-hidden', String(i !== at))
    s.inert = i !== at
  })
  $('#count')!.textContent = `${at + 1} / ${slides.length}`
  $('#bar')!.style.width = `${((at + 1) / slides.length) * 100}%`
  $<HTMLButtonElement>('#prev')!.disabled = at === 0
  $<HTMLButtonElement>('#next')!.disabled = at === slides.length - 1
  history.replaceState(null, '', `#${at + 1}`)
}

document.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const onControl = !!(e.target as Element).closest('a, button')
  if (e.key === 'ArrowRight' || e.key === 'PageDown' || (e.key === ' ' && !onControl)) { go(at + 1); e.preventDefault() }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { go(at - 1); e.preventDefault() }
  else if (e.key === 'Home') go(0)
  else if (e.key === 'End') go(slides.length - 1)
})
$('#prev')!.addEventListener('click', () => go(at - 1))
$('#next')!.addEventListener('click', () => go(at + 1))
let touchX: number | null = null
document.addEventListener('touchstart', (e) => { touchX = e.touches[0].clientX }, { passive: true })
document.addEventListener('touchend', (e) => {
  if (touchX === null) return
  const dx = e.changedTouches[0].clientX - touchX
  if (Math.abs(dx) > 60) go(at + (dx < 0 ? 1 : -1))
  touchX = null
})

/* ---------- Cross-sections: usable width, the 1 m parcel margin, and the car, to one scale ---------- */
const NS = 'http://www.w3.org/2000/svg'
let car = { body: 1.855, mirror: 2.105 } // Toyota Fortuner; replaced by /api/vehicles
const SCALE = 82 // px per metre, shared by both drawings so they compare honestly

function el(tag: string, attrs: Record<string, string | number>, text?: string) {
  const n = document.createElementNS(NS, tag)
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v))
  if (text) n.textContent = text
  return n
}

function drawSection(fig: HTMLElement) {
  const usable = Number(fig.dataset.width)
  const svg = fig.querySelector('svg')!
  svg.replaceChildren()
  const cx = 300, ground = 282
  const u = (usable * SCALE) / 2, m = 0.5 * SCALE
  svg.append(
    el('rect', { class: 'ground', x: 0, y: ground, width: 600, height: 18 }),
    el('rect', { class: 'wall', x: 0, y: 40, width: cx - u - m, height: ground - 40 }),
    el('rect', { class: 'wall', x: cx + u + m, y: 40, width: 600, height: ground - 40 }),
    el('rect', { class: 'margin', x: cx - u - m, y: 200, width: m, height: ground - 200 }),
    el('rect', { class: 'margin', x: cx + u, y: 200, width: m, height: ground - 200 }),
  )
  if (cx - u - m > 90) svg.append(el('text', { class: 'cap-label', x: 16, y: 64 }, 'parcel line'))
  // Dimension line across the usable gap
  const y = 26
  svg.append(
    el('path', { class: 'dim', d: `M${cx - u} ${y - 8} V${y + 8} M${cx - u} ${y} H${cx + u} M${cx + u} ${y - 8} V${y + 8}` }),
    el('text', { class: 'dim-label', x: cx, y: y + 30, 'text-anchor': 'middle' }, `${usable.toFixed(2)} m usable`),
  )
  // The car from behind: body, glass, lamps, wheels, mirrors
  const b = (car.body * SCALE) / 2, mr = (car.mirror * SCALE) / 2, h = 1.55 * SCALE
  const g = el('g', {})
  g.append(
    el('rect', { class: 'car-ink', x: cx - b, y: ground - h, width: 2 * b, height: h - 22, rx: 10 }),
    el('rect', { class: 'car-glass', x: cx - b * 0.8, y: ground - h + 9, width: b * 1.6, height: h * 0.27, rx: 5 }),
    el('rect', { class: 'car-lamp', x: cx - b * 0.94, y: ground - h * 0.53, width: b * 0.3, height: 8 }),
    el('rect', { class: 'car-lamp', x: cx + b * 0.64, y: ground - h * 0.53, width: b * 0.3, height: 8 }),
    el('rect', { class: 'car-ink', x: cx - b * 0.88, y: ground - 26, width: b * 0.4, height: 26, rx: 4 }),
    el('rect', { class: 'car-ink', x: cx + b * 0.48, y: ground - 26, width: b * 0.4, height: 26, rx: 4 }),
    el('rect', { class: 'car-ink', x: cx - mr, y: ground - h * 0.71, width: mr - b + 2, height: 9 }),
    el('rect', { class: 'car-ink', x: cx + b - 2, y: ground - h * 0.71, width: mr - b + 2, height: 9 }),
  )
  svg.append(g)
}
const draw = () => $$('.xs').forEach(drawSection)

/* ---------- Live counts from the engine; the printed numbers are the 17 Oct values ---------- */
async function boot() {
  try {
    const config = await fetch('/api/config').then((r) => r.json()) as Config
    const cov = (config as unknown as { coverage?: Record<string, unknown> }).coverage
    const tiers = (cov?.evidence_ways_by_strongest_tier ?? {}) as Record<string, number>
    for (const [tier, n] of Object.entries(tiers)) {
      $$(`[data-tier="${tier}"]`).forEach((e) => { if (n > 0) e.textContent = nf.format(n) })
    }
    if (typeof cov?.evidence_ways_with_sources === 'number') $$('[data-live="ways"]').forEach((e) => { e.textContent = nf.format(cov.evidence_ways_with_sources as number) })
  } catch { /* printed values stay */ }
  try {
    const v = await fetch('/api/vehicles').then((r) => r.json()) as { models: Vehicle[] }
    $$('[data-live="models"]').forEach((e) => { e.textContent = String(v.models.length) })
    const f = v.models.find((x) => x.id === 'toyota-fortuner')
    if (f) { car = { body: f.body_width, mirror: f.mirror_width }; draw() }
  } catch { /* printed dimensions stay */ }
}

draw()
go(Math.max(0, (parseInt(location.hash.slice(1), 10) || 1) - 1))
boot()
