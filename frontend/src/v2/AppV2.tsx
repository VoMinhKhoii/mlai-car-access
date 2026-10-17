import { useEffect, useMemo, useRef, useState } from 'react'
import type { Map as MLMap } from 'maplibre-gl'
import { createPortal } from 'react-dom'
import { api, type AgentPlan, type Config, type Plan, type PlanRequest, type Preset, type SearchResult, type Vehicle } from '../api'
import type { MapContext } from '../mapSearch'
import { Agent } from '../components/Agent'
import { MapV2 } from './MapV2'
import { CrossSection } from './CrossSection'
import { answer, m2, narrowestCut, stopLine, tierWord, wayOut } from './derive'
import './v2.css'

type Place = { lat: number; lon: number; label: string }
const FONT_HREF = 'https://fonts.googleapis.com/css2?family=Stack+Sans+Headline:wght@300&family=Stack+Sans+Text:wght@400;500&display=swap'
const SWITCH = [{ id: 'toyota-fortuner', label: 'Fortuner' }, { id: 'vinfast-vf-3', label: 'VF 3' }]
const DEFAULT_VEHICLE = 'toyota-fortuner'

function useMedia(q: string) {
  const [on, setOn] = useState(() => window.matchMedia(q).matches)
  useEffect(() => {
    const mq = window.matchMedia(q)
    const f = () => setOn(mq.matches)
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [q])
  return on
}

export default function AppV2() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [models, setModels] = useState<Vehicle[]>([])
  const [dest, setDest] = useState<Place | null>(null)
  const [vehicleId, setVehicleId] = useState(DEFAULT_VEHICLE)
  const [dwell, setDwell] = useState(90)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [selected, setSelected] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [agentOpen, setAgentOpen] = useState(false)
  const [mapContext, setMapContext] = useState<MapContext | null>(null)
  const [details, setDetails] = useState(false)
  const phone = useMedia('(max-width: 720px)')
  const [xsOpen, setXsOpen] = useState(!phone)
  const [anchorEl] = useState(() => { const el = document.createElement('div'); el.className = 'v2-anchor'; return el })
  const mapRef = useRef<MLMap | null>(null)
  const planCtl = useRef<AbortController | null>(null)
  const askRef = useRef<HTMLButtonElement>(null)
  const extra = useRef<{ arrive_at: string | null; intent: PlanRequest['intent'] }>({ arrive_at: null, intent: 'park' })

  useEffect(() => {
    if (!document.querySelector(`link[href="${FONT_HREF}"]`)) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = FONT_HREF; document.head.append(l)
    }
    document.title = 'Ngõ Ngách'
    api.config().then((c) => {
      setCfg(c)
      const first = c.presets[0]
      if (first) { setDwell(first.dwell_min); setDest({ lat: first.lat, lon: first.lon, label: first.label }) }
    }).catch(() => setError('Could not reach the server.'))
    api.vehicles().then((v) => setModels(v.models)).catch(() => {})
  }, [])

  useEffect(() => { setXsOpen(!phone) }, [phone])

  useEffect(() => {
    if (!dest) return
    planCtl.current?.abort()
    const ctl = new AbortController()
    planCtl.current = ctl
    setLoading(true); setError('')
    api.plan({ lat: dest.lat, lon: dest.lon, label: dest.label, vehicle_id: vehicleId, intent: extra.current.intent,
      arrive_at: extra.current.arrive_at, dwell_min: dwell, rain: [], origin: null }, ctl.signal)
      .then((p) => { setPlan(p); setSelected(0) })
      .catch((e) => { if (!ctl.signal.aborted) setError(e instanceof Error && e.message ? 'Could not check this place.' : 'Could not check this place.') })
      .finally(() => { if (planCtl.current === ctl) setLoading(false) })
    return () => ctl.abort()
  }, [dest, vehicleId, dwell])

  const choose = (p: Place) => { extra.current = { arrive_at: null, intent: 'park' }; setDest(p) }
  function applyAgent(p: AgentPlan) {
    extra.current = { arrive_at: p.arrive_at || null, intent: p.intent }
    setVehicleId(p.vehicle_id); setDwell(p.dwell_min); setDest({ lat: p.lat, lon: p.lon, label: p.label })
  }

  const vehicle = models.find((v) => v.id === vehicleId) ?? (plan?.vehicle.id === vehicleId ? plan.vehicle : null) ?? plan?.vehicle ?? null
  const stop = plan?.stop_points[selected]
  const cut = useMemo(() => plan ? narrowestCut(plan, selected) : null, [plan, selected])
  const ans = plan ? answer(plan, stop) : null
  const out = stop ? wayOut(stop) : null

  // Opening the cross-section on a small screen: pan just enough that the whole card sits in the free map area.
  function revealCard() {
    window.setTimeout(() => {
      const m = mapRef.current
      if (!m) return
      const r = anchorEl.getBoundingClientRect()
      const top = (document.querySelector('.v2-search')?.getBoundingClientRect().bottom ?? 0) + 12
      const bottom = (phone ? document.querySelector('.v2-verdict')?.getBoundingClientRect().top ?? innerHeight : innerHeight) - 12
      const dx = r.left < 16 ? r.left - 16 : r.right > innerWidth - 16 ? r.right - innerWidth + 16 : 0
      const dy = r.top < top ? r.top - top : r.bottom > bottom ? r.bottom - bottom : 0
      if (dx || dy) m.panBy([dx, dy], { duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 320 })
    }, 30)
  }

  const prevAgent = useRef(agentOpen)
  useEffect(() => { if (prevAgent.current && !agentOpen) askRef.current?.focus(); prevAgent.current = agentOpen }, [agentOpen])

  const padding = phone ? { top: 300, left: 40, right: 40, bottom: 330 } : { top: 420, left: 460, right: 120, bottom: 120 }
  const support = plan && stop && cut?.lo != null
    ? `Narrowest cut ${m2(cut.lo)}${cut.wayName ? ` on ${cut.wayName}` : ''}. ${stopLine(stop)}.`
    : plan && stop ? `${stopLine(stop)}. Width not measured on this route.`
      : plan ? 'No stop within walking distance for this car.' : ''

  return <div className="v2">
    {cfg && <MapV2 styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} destination={dest}
      anchor={cut ? { lat: cut.lat, lon: cut.lon } : null} anchorEl={anchorEl} padding={padding} onFeatures={setMapContext} onMap={(m) => { mapRef.current = m }} />}
    {cut && vehicle && createPortal(<div className="v2-anchor-inner">
      <CrossSection cut={cut} body={vehicle.body_width} mirror={vehicle.mirror_width} vehicleName={vehicle.label}
        expanded={xsOpen} onToggle={() => { if (!xsOpen) revealCard(); setXsOpen(!xsOpen) }} />
      <span className="v2-stem" aria-hidden="true" />
    </div>, anchorEl)}

    <Search presets={cfg?.presets ?? []} near={dest} onChoose={choose} />

    <section className="v2-verdict" aria-label="Answer">
      <div className="v2-seg" role="radiogroup" aria-label="Car">
        {SWITCH.map((s) => {
          const on = vehicleId === s.id
          return <button key={s.id} type="button" role="radio" aria-checked={on} tabIndex={on || !SWITCH.some((x) => x.id === vehicleId) ? 0 : -1}
            className={on ? 'on' : ''} onClick={() => setVehicleId(s.id)}
            onKeyDown={(e) => {
              if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
                e.preventDefault()
                const next = SWITCH[(SWITCH.findIndex((x) => x.id === s.id) + 1) % SWITCH.length]
                setVehicleId(next.id)
                ;(e.currentTarget.parentElement?.querySelector(`[data-id="${next.id}"]`) as HTMLButtonElement | null)?.focus()
              }
            }} data-id={s.id}>{s.label}</button>
        })}
      </div>

      <div className="v2-answer" aria-live="polite" aria-busy={loading}>
        {error && !loading ? <p className="v2-error" role="alert">{error} <button type="button" className="v2-link" onClick={() => dest && setDest({ ...dest })}>Try again</button></p> : null}
        {ans ? <>
          <p className="v2-status">{loading ? 'Checking…' : vehicle ? `${vehicle.label}, mirrors ${vehicle.mirror_width.toFixed(2)} m` : ''}</p>
          <h1 key={`${ans.word}${plan?.vehicle.id}`} className={`v2-word tone-${ans.tone} v2-xfade`}>{ans.word}</h1>
          <p className="v2-support">{support}</p>
        </> : <p className="v2-status">{loading ? 'Checking…' : error ? '' : 'Search for a destination.'}</p>}
      </div>

      {plan && stop && out && <dl className="v2-facts">
        <div><dt>Evidence</dt><dd>{cut?.tier ?? tierWord(stop.fit.width_range?.top_tier)}</dd></div>
        <div><dt>Parking</dt><dd>{stop.legality.status}</dd></div>
        <div><dt>Way out</dt><dd>{out.value}</dd>{out.note && <dd className="v2-note">{out.note}</dd>}</div>
      </dl>}

      <div className="v2-actions">
      {plan && <button type="button" className="v2-link v2-details-toggle" aria-expanded={details} aria-controls="v2-details" onClick={() => setDetails((d) => !d)}>
        {details ? 'Fewer details' : `Details, ${plan.stop_points.length} ${plan.stop_points.length === 1 ? 'stop' : 'stops'}`}
      </button>}
      <button ref={askRef} type="button" className="v2-ask" aria-expanded={agentOpen} aria-controls="agent-panel" onClick={() => setAgentOpen((o) => !o)}>Ask AlleyAI</button>
      </div>
      {plan && details && <div id="v2-details" className="v2-details">
        <ul className="v2-stops" aria-label="Stops">
          {plan.stop_points.map((s, i) => {
            const a = answer(plan, s)
            return <li key={i}><button type="button" aria-pressed={i === selected} className={i === selected ? 'on' : ''} onClick={() => setSelected(i)}>
              <span className="v2-stop-name">{s.kind === 'door' ? 'At the door' : s.name}</span>
              <span className={`v2-stop-fit tone-${a.tone}`}>{i === 0 ? a.word : fitWord(s.fit.class)}</span>
              <span className="v2-num v2-stop-walk">{Math.round(s.walk.meters)} m walk</span>
            </button></li>
          })}
        </ul>
        <label className="v2-select">
          <span>More vehicles</span>
          <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            {!models.some((v) => v.id === vehicleId) && <option value={vehicleId}>{vehicle?.label ?? vehicleId}</option>}
            {models.map((v) => <option key={v.id} value={v.id}>{v.label}, {v.mirror_width.toFixed(2)} m mirrors</option>)}
          </select>
        </label>
      </div>}
    </section>

    <div className={`v2-agent ${agentOpen ? 'open' : ''}`}>
      <Agent origin={null} onPlan={applyAgent} open={agentOpen} setOpen={setAgentOpen} mapContext={mapContext} />
    </div>
  </div>
}

const fitWord = (c: string) => ({ fits: 'Fits', tight: 'Tight', no: "Won't fit", blocked: "Won't fit", lot: 'Lot' } as Record<string, string>)[c] ?? 'Not verified'

function Search({ presets, near, onChoose }: { presets: Preset[]; near: Place | null; onChoose: (p: Place) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [active, setActive] = useState(-1)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const text = q.trim()
    if (text.length < 2) { setResults([]); setBusy(false); return }
    const ctl = new AbortController()
    setBusy(true)
    const t = window.setTimeout(() => {
      api.search(text, near, ctl.signal).then((r) => { setResults(r.results.slice(0, 6)); setActive(-1); setMsg('') })
        .catch(() => { if (!ctl.signal.aborted) setMsg('Search is unavailable right now.') })
        .finally(() => { if (!ctl.signal.aborted) setBusy(false) })
    }, 250)
    return () => { window.clearTimeout(t); ctl.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const showPresets = q.trim().length < 2
  const items: { key: string; label: string; pick: () => Promise<Place | null> }[] = showPresets
    ? presets.map((p) => ({ key: p.id, label: p.label, pick: async () => ({ lat: p.lat, lon: p.lon, label: p.label }) }))
    : results.map((r, i) => ({ key: `${i}-${r.label}`, label: r.label, pick: async () =>
        r.lat != null && r.lon != null ? { lat: r.lat, lon: r.lon, label: r.label } : r.place_id ? api.place(r.place_id) : null }))

  async function pick(i: number) {
    const it = items[i]
    if (!it) return
    try {
      const p = await it.pick()
      if (!p) return setMsg('That place has no location.')
      setQ(p.label); setOpen(false); setActive(-1); onChoose(p)
    } catch { setMsg('Could not open that place.') }
  }

  const expanded = open && (items.length > 0 || !!msg)
  return <div className="v2-search" ref={wrap} onBlur={(e) => { if (!wrap.current?.contains(e.relatedTarget as Node)) setOpen(false) }}>
    <p className="v2-wordmark">Ngõ Ngách</p>
    <input className="v2-input" type="text" role="combobox" aria-label="Destination" placeholder="Where are you driving to?"
      aria-expanded={expanded} aria-controls="v2-listbox" aria-autocomplete="list"
      aria-activedescendant={expanded && active >= 0 ? `v2-opt-${active}` : undefined}
      value={q} onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true) }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(items.length - 1, a + 1)) }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
        else if (e.key === 'Enter') { e.preventDefault(); void pick(active >= 0 ? active : 0) }
        else if (e.key === 'Escape') { if (open) { e.preventDefault(); setOpen(false) } else setQ('') }
      }} />
    {expanded && <div className="v2-pop">
      {showPresets && items.length > 0 && <p className="v2-pop-label" id="v2-presets-label">Try a real alley</p>}
      <ul id="v2-listbox" role="listbox" aria-label={showPresets ? 'Try a real alley' : 'Places'}>
        {items.map((it, i) => <li key={it.key} id={`v2-opt-${i}`} role="option" aria-selected={i === active}
          className={i === active ? 'active' : ''} onMouseDown={(e) => e.preventDefault()} onClick={() => void pick(i)}
          onMouseEnter={() => setActive(i)}>{it.label}</li>)}
      </ul>
      {(msg || (busy && !items.length)) && <p className="v2-pop-msg" role="status">{msg || 'Searching…'}</p>}
    </div>}
  </div>
}
