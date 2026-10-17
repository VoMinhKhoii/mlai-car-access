/* Liquid Glass refraction for the control layer.
   Every `.glass` surface gets an SVG displacement filter sized to its own box, so the live map bends at the rim
   the way Apple's Liquid Glass does. `backdrop-filter: url()` only renders in Chromium; elsewhere the surfaces keep
   the plain frosted look from base.css. The filter is exposed as `--lg-refract` and composed there. */

const SELECTOR = '.glass, .maplibregl-ctrl-group'
const NS = 'http://www.w3.org/2000/svg'
const MAX_AREA = 1_400_000 // px²; larger surfaces stay frosted only
const MAX_FILTERS = 64

export function refractionSupported() {
  const brands = (navigator as Navigator & { userAgentData?: { brands: { brand: string }[] } }).userAgentData?.brands
  return !!brands?.some((b) => /Chromium/i.test(b.brand))
}

/** Displacement map for a rounded rectangle: red/green push the sample inward near the rim, neutral grey inside. */
function rimMap(w: number, h: number, r: number, rim: number) {
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  const img = ctx.createImageData(w, h)
  const hx = w / 2, hy = h / 2
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const px = x + 0.5 - hx, py = y + 0.5 - hy
      const qx = Math.abs(px) - (hx - r), qy = Math.abs(py) - (hy - r)
      // signed distance to the rounded rectangle (negative inside) and its outward normal
      const ox = Math.max(qx, 0), oy = Math.max(qy, 0)
      const dist = Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0) - r
      let nx = 0, ny = 0
      if (qx > 0 && qy > 0) { const l = Math.hypot(qx, qy) || 1; nx = (qx / l) * Math.sign(px); ny = (qy / l) * Math.sign(py) }
      else if (qx > qy) nx = Math.sign(px)
      else ny = Math.sign(py)
      const depth = -dist
      const k = depth >= 0 && depth < rim ? (1 - depth / rim) ** 2 : 0
      const i = (y * w + x) * 4
      img.data[i] = 128 - nx * k * 127
      img.data[i + 1] = 128 - ny * k * 127
      img.data[i + 2] = 128
      img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL()
}

function makeFilter(id: string, w: number, h: number, r: number) {
  const short = Math.min(w, h)
  const rim = Math.max(8, Math.min(26, short / 3))
  const scale = Math.max(12, Math.min(34, short * 0.4))
  const filter = document.createElementNS(NS, 'filter')
  for (const [k, v] of Object.entries({ id, x: '0', y: '0', width: `${w}`, height: `${h}`, filterUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB' })) filter.setAttribute(k, v)
  const image = document.createElementNS(NS, 'feImage')
  for (const [k, v] of Object.entries({ href: rimMap(w, h, r, rim), x: '0', y: '0', width: `${w}`, height: `${h}`, preserveAspectRatio: 'none', result: 'rim' })) image.setAttribute(k, v)
  const displace = document.createElementNS(NS, 'feDisplacementMap')
  for (const [k, v] of Object.entries({ in: 'SourceGraphic', in2: 'rim', scale: `${scale}`, xChannelSelector: 'R', yChannelSelector: 'G' })) displace.setAttribute(k, v)
  filter.append(image, displace)
  return filter
}

/** Starts watching the page for glass surfaces; returns a cleanup. */
export function startLiquidGlass(): () => void {
  if (!refractionSupported()) return () => {}
  const quiet = window.matchMedia('(prefers-reduced-transparency: reduce)')
  if (quiet.matches) return () => {}
  document.documentElement.classList.add('lg-refract')

  const svg = document.createElementNS(NS, 'svg')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('width', '0')
  svg.setAttribute('height', '0')
  svg.style.position = 'absolute'
  document.body.append(svg)

  const filters = new Map<string, SVGFilterElement>()
  let serial = 0
  const pending = new Set<HTMLElement>()
  let timer = 0

  function filterFor(w: number, h: number, r: number) {
    const key = `${w}x${h}r${r}`
    let f = filters.get(key)
    if (f) { filters.delete(key); filters.set(key, f); return f.id } // keep the most recent at the end
    if (filters.size >= MAX_FILTERS) {
      const [oldKey, old] = filters.entries().next().value!
      filters.delete(oldKey)
      old.remove()
    }
    f = makeFilter(`lg-${++serial}`, w, h, r)
    svg.append(f)
    filters.set(key, f)
    return f.id
  }

  function apply(el: HTMLElement) {
    if (!el.isConnected) { observer.unobserve(el); return }
    // Sizes snap to 2px so a sheet that animates its height reuses filters instead of minting one per frame.
    const w = Math.round(el.offsetWidth / 2) * 2, h = Math.round(el.offsetHeight / 2) * 2
    if (!w || !h || w * h > MAX_AREA) { el.style.removeProperty('--lg-refract'); return }
    const r = Math.round(Math.min(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0, w / 2, h / 2))
    el.style.setProperty('--lg-refract', `url(#${filterFor(w, h, r)})`)
  }

  const observer = new ResizeObserver((entries) => {
    for (const e of entries) pending.add(e.target as HTMLElement)
    window.clearTimeout(timer)
    timer = window.setTimeout(() => { pending.forEach(apply); pending.clear() }, 60)
  })
  const seen = new WeakSet<Element>()
  const watch = (root: ParentNode | Element) => {
    if (root instanceof Element && root.matches(SELECTOR) && !seen.has(root)) { seen.add(root); observer.observe(root) }
    root.querySelectorAll(SELECTOR).forEach((el) => { if (!seen.has(el)) { seen.add(el); observer.observe(el) } })
  }
  const mutations = new MutationObserver((list) => {
    for (const m of list) m.addedNodes.forEach((n) => { if (n instanceof Element) watch(n) })
  })
  watch(document.body)
  mutations.observe(document.body, { childList: true, subtree: true })

  return () => {
    mutations.disconnect()
    observer.disconnect()
    window.clearTimeout(timer)
    svg.remove()
    document.documentElement.classList.remove('lg-refract')
  }
}
