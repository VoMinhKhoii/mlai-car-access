import { ArrowUpDown, Car, Clock, Crosshair, MapPin, ParkingSquare, Search, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api, matchVisiblePlaces, type Intent, type SearchResult, type Vehicle } from '../api'
import { ChipMenu, Segmented, metres, vn } from '../ds/ui'
import { type MapContext } from '../mapSearch'
import { fromLocal } from '../datetime'

export interface Place { lat: number; lon: number; label: string }
export type VehicleMode = 'class' | 'model' | 'vetc'

/** One place input with Goong/OSM autocomplete. */
function PlaceField({ kind, value, onPick, placeholder, extra, near, mapContext }: {
  kind: 'origin' | 'dest'; value: Place | null; onPick: (p: Place | null) => void; placeholder: string; extra?: React.ReactNode
  mapContext?: MapContext | null
  near?: { lat: number; lon: number } | null
}) {
  const [q, setQ] = useState<string | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [active, setActive] = useState(-1)
  const [status, setStatus] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const timer = useRef<number | undefined>(undefined)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  const text = q ?? value?.label ?? ''
  const expanded = results.length > 0

  const cancel = useCallback(() => {
    generation.current++
    window.clearTimeout(timer.current)
    controller.current?.abort()
    controller.current = null
  }, [])
  const dismiss = useCallback(() => {
    cancel()
    setResults([])
    setActive(-1)
    setStatus('idle')
    setQ(null)
  }, [cancel])
  useEffect(() => () => cancel(), [cancel])
  useEffect(() => { dismiss() }, [value, dismiss]) // external place changes also invalidate pending detail
  useEffect(() => {
    if (active >= 0) document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active, id])

  function type(v: string) {
    cancel()
    setQ(v)
    setResults([])
    setActive(-1)
    setStatus('idle')
    if (v.trim().length < 2) return
    const gen = generation.current
    const request = new AbortController()
    controller.current = request
    const local: SearchResult[] = mapContext ? matchVisiblePlaces(v, mapContext.candidates, mapContext.center, 6)
      .map((p) => ({ label: p.name, lat: p.lat, lon: p.lon, source: 'On the map' })) : []
    setResults(local)
    setStatus(local.length ? 'idle' : 'loading')
    setMessage('Finding places…')
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.search(v, kind === 'dest' ? mapContext?.center ?? near : near, request.signal)
        if (gen !== generation.current || request.signal.aborted) return
        const remote = r.results.filter((p) => !local.some((x) => x.label === p.label && p.lat != null && p.lon != null && Math.abs(x.lat! - p.lat) < .0002 && Math.abs(x.lon! - p.lon) < .0002))
        setResults([...local, ...remote].slice(0, 6))
        setStatus((local.length + r.results.length) ? 'idle' : 'empty')
        setMessage('Could not find that place. Try a street name or tap the map.')
      } catch {
        if (gen !== generation.current || request.signal.aborted) return
        setResults(local)
        setStatus(local.length ? 'idle' : 'error')
        setMessage('Search is unavailable. Choose a map result or try again.')
      }
    }, 250)
  }
  async function pick(r: SearchResult) {
    cancel()
    const gen = generation.current
    const request = new AbortController()
    controller.current = request
    setResults([])
    setActive(-1)
    setQ(r.label)
    setStatus('loading')
    setMessage('Getting the location…')
    input.current?.focus()
    try {
      let place: Place | null = r.lat != null && r.lon != null ? { lat: r.lat, lon: r.lon, label: r.label } : null
      if (!place && r.place_id) place = await api.place(r.place_id, request.signal)
      if (gen !== generation.current || request.signal.aborted) return
      if (!place) throw new Error('Location unavailable')
      setStatus('idle')
      setQ(null)
      onPick(place)
    } catch {
      if (gen !== generation.current || request.signal.aborted) return
      setStatus('error')
      setMessage('Could not get that location. Search and select again; your previous destination is still selected.')
    }
  }
  function key(e: React.KeyboardEvent<HTMLInputElement>) {
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && results.length) {
      e.preventDefault()
      setActive((a) => e.key === 'ArrowDown' ? (a + 1) % results.length : (a < 0 ? results.length - 1 : (a - 1 + results.length) % results.length))
    } else if (e.key === 'Enter' && active >= 0 && expanded) {
      e.preventDefault()
      void pick(results[active])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      dismiss()
    }
  }

  return (
    <div className="place">
      <span className={`place-mark ${kind}`} aria-hidden>{kind === 'dest' ? <MapPin size={16} strokeWidth={2.4} /> : <i />}</span>
      <div className="field">
        <input ref={input} value={text} placeholder={placeholder} aria-label={kind === 'origin' ? 'Starting point' : 'Destination'}
          role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={`${id}-list`}
          aria-activedescendant={expanded && active >= 0 ? `${id}-${active}` : undefined} aria-describedby={`${id}-status`} aria-busy={status === 'loading'}
          onChange={(e) => type(e.target.value)} onFocus={(e) => e.target.select()}
          onKeyDown={key} onBlur={dismiss} />
        {text && <button type="button" className="icon-btn sm" aria-label="Clear" onPointerDown={(e) => e.preventDefault()}
          onClick={() => { dismiss(); setQ(''); onPick(null); input.current?.focus() }}><X size={15} /></button>}
        {extra}
      </div>
      <ul id={`${id}-list`} className="results card" role="listbox" aria-label={kind === 'origin' ? 'Starting point suggestions' : 'Destination suggestions'} hidden={!expanded}>
        {results.map((r, i) => (
          <li key={r.place_id ?? `${r.label}-${i}`} id={`${id}-${i}`} role="option" aria-selected={active === i}
            onPointerDown={(e) => e.preventDefault()} onClick={() => void pick(r)} onPointerMove={() => setActive(i)}>
            <Search size={15} /><span>{r.label}<small>{r.source}</small></span>
          </li>
        ))}
      </ul>
      <div id={`${id}-status`} aria-live="polite" className={status === 'idle' ? 'sr-only' : `results card search-status ${status === 'error' ? 'error-line' : 'note'}`}>
        {status !== 'idle' ? message : expanded ? `${results.length} suggestions. Use arrow keys and Enter to select.` : ''}
      </div>
    </div>
  )
}

export function Directions(p: {
  mapContext: MapContext | null
  origin: Place | null; dest: Place | null; setOrigin: (x: Place | null) => void; setDest: (x: Place | null) => void
  locating: boolean; onLocate: () => void
  vehicle?: Vehicle; fleet: { classes: Vehicle[]; models: Vehicle[] }
  vMode: VehicleMode; setVMode: (m: VehicleMode) => void; classId: string; setClassId: (s: string) => void
  modelId: string; setModelId: (s: string) => void; vetcLinked: boolean; openVetc: () => void; unlinkVetc: () => void
  intent: Intent; setIntent: (i: Intent) => void; dwell: number; setDwell: (n: number) => void
  arrive: string; setArrive: (s: string) => void; arriveNow: boolean; setArriveNow: (b: boolean) => void
}) {
  const v = p.vehicle
  const today = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10)
  const timeLabel = p.arriveNow ? 'Leave now' : `Arrive ${p.arrive.slice(11, 16)}${p.arrive.slice(0, 10) === today ? '' : ` ${Number(p.arrive.slice(8, 10))}/${Number(p.arrive.slice(5, 7))}`}`
  const shortTimeLabel = p.arriveNow ? 'Now' : `${p.arrive.slice(11, 16)}${p.arrive.slice(0, 10) === today ? '' : ` ${Number(p.arrive.slice(8, 10))}/${Number(p.arrive.slice(5, 7))}`}`
  const shortDwell = p.dwell % 60 === 0 ? `${p.dwell / 60}h` : `${p.dwell}′`
  return (
    <div className="directions">
      <div className="places">
        <PlaceField kind="origin" value={p.origin} onPick={p.setOrigin} near={p.dest ?? p.origin} placeholder="Starting point or your location"
          extra={<button type="button" className="icon-btn sm" aria-label="Use current location" title="Use current location" onClick={p.onLocate}>
            <Crosshair size={16} className={p.locating ? 'spin' : ''} /></button>} />
        <PlaceField mapContext={p.mapContext} kind="dest" value={p.dest} onPick={p.setDest} near={p.origin ?? p.dest} placeholder="Destination, address or alley…" />
        <span className="places-rail" aria-hidden />
        <button type="button" className="icon-btn swap" aria-label="Swap start and destination" onClick={() => { const o = p.origin; p.setOrigin(p.dest); p.setDest(o) }}>
          <ArrowUpDown size={16} />
        </button>
      </div>

      <div className="chips">
        <ChipMenu icon={<Car size={15} />} label={v ? shortName(v) : 'Choose car'}>
          {() => (
            <div className="menu vehicle-menu">
              <Segmented label="Choose vehicle by" value={p.vMode} onChange={p.setVMode}
                options={[{ value: 'class', label: 'Size class' }, { value: 'model', label: 'Model' }, { value: 'vetc', label: 'From VETC' }]} />
              {p.vMode === 'class' && (
                <select className="select" value={p.classId} onChange={(e) => p.setClassId(e.target.value)} aria-label="Size class">
                  {p.fleet.classes.map((c) => <option key={c.id} value={c.id}>{vehicleLabel(c)}</option>)}
                </select>
              )}
              {p.vMode === 'model' && (
                <select className="select" value={p.modelId} onChange={(e) => p.setModelId(e.target.value)} aria-label="Model">
                  {p.fleet.models.map((c) => <option key={c.id} value={c.id}>{vehicleLabel(c)}</option>)}
                </select>
              )}
              {p.vMode === 'vetc' && (p.vetcLinked
                ? <p className="vetc-row"><span className="tag brand">Demo</span> 51K-***.68 · Toyota Fortuner <button type="button" className="btn btn-ghost btn-sm" onClick={p.unlinkVetc}>Unlink</button></p>
                : <button type="button" className="btn btn-tonal" onClick={p.openVetc}>Link VETC account</button>)}
              {v && (
                <dl className="specs">
                  <div><dt>Width with mirrors</dt><dd>{metres(v.mirror_width, 2)}{v.mirror_estimated ? '*' : ''}</dd></div>
                  <div><dt>Turning radius</dt><dd>{metres(v.turning_radius)}</dd></div>
                  <div><dt>Water depth limit</dt><dd>{Math.round(v.safe_water_depth * 100)} cm</dd></div>
                  <div><dt>Three-point turn</dt><dd>≥ {metres(v.three_point_width)}</dd></div>
                </dl>
              )}
              {v?.kind === 'class' && <p className="note">Uses a conservative envelope for the largest vehicles in this class. Choose a model for a closer estimate.</p>}
              {v?.mirror_estimated && <p className="note">* Not published by the manufacturer: body width plus 0.25 m.</p>}
            </div>
          )}
        </ChipMenu>

        <ChipMenu icon={p.intent === 'park' ? <ParkingSquare size={15} /> : <UserRound size={15} />}
          label={p.intent === 'park'
            ? <><span className="chip-full">Parking · {minutes(p.dwell)}</span><span className="chip-compact">Park · {shortDwell}</span></>
            : <><span className="chip-full">Pickup/drop-off · 15-minute check</span><span className="chip-compact">Pickup · 15 min</span></>}>
          {() => (
            <div className="menu">
              <Segmented label="Trip purpose" value={p.intent} onChange={p.setIntent}
                options={[{ value: 'park', label: 'Parking' }, { value: 'pickup', label: 'Pickup/drop-off' }]} />
              {p.intent === 'park' ? (
                <label className="menu-row">Stay for
                  <select className="select" value={p.dwell} onChange={(e) => p.setDwell(Number(e.target.value))}>
                    {[...new Set([30, 60, 120, 180, 240, p.dwell])].sort((a, b) => a - b).map((d) => <option key={d} value={d}>{minutes(d)}</option>)}
                  </select>
                </label>
              ) : <p className="note">The planning window is 15 minutes. This is not a legal stopping allowance; check signs and local restrictions.</p>}
            </div>
          )}
        </ChipMenu>

        <ChipMenu icon={<Clock size={15} />} label={<><span className="chip-full">{timeLabel}</span><span className="chip-compact">{shortTimeLabel}</span></>} align="right">
          {(close) => <TimeMenu arrive={p.arrive} arriveNow={p.arriveNow} close={close}
            onCommit={(value, now) => { p.setArrive(value); p.setArriveNow(now) }} />}
        </ChipMenu>
      </div>
    </div>
  )
}

function TimeMenu({ arrive, arriveNow, close, onCommit }: {
  arrive: string; arriveNow: boolean; close: () => void; onCommit: (value: string, now: boolean) => void
}) {
  const [draft, setDraft] = useState(arrive)
  const [now, setNow] = useState(arriveNow)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  function validate() {
    const valid = now || (!!fromLocal(draft) && !!input.current?.validity.valid)
    setError(valid ? '' : 'Enter a valid arrival date and time (Vietnam time, UTC+07:00). Your previous time is still selected.')
    return valid
  }
  function commit() {
    if (!validate()) {
      input.current?.focus()
      return
    }
    onCommit(now ? arrive : draft, now)
    close()
  }
  return (
    <div className="menu">
      <Segmented label="Time" value={now ? 'now' : 'at'} onChange={(x) => { setNow(x === 'now'); setError('') }}
        options={[{ value: 'now', label: 'Leave now' }, { value: 'at', label: 'Set arrival time' }]} />
      {!now && <>
        <label htmlFor={`${id}-arrival`} className="note">Arrival in Vietnam (UTC+07:00)</label>
        <input ref={input} id={`${id}-arrival`} className="input" type="datetime-local" required value={draft}
          onChange={(e) => setDraft(e.target.value)} onBlur={validate} aria-invalid={!!error} aria-describedby={`${id}-error`} />
      </>}
      <p id={`${id}-error`} className="error-line" aria-live="polite">{error}</p>
      <button type="button" className="btn btn-primary btn-sm" onClick={commit}>Done</button>
    </div>
  )
}

const minutes = (n: number) => n % 60 === 0 ? `${n / 60} ${n === 60 ? 'hour' : 'hours'}` : `${n} min`
const classLabels: Record<string, string> = { XS: 'Small car', S: 'B/C sedan or crossover', M: '7-seat SUV/MPV or D sedan', L: 'Large car or pickup', XL: '16-seat van or minibus' }
const vehicleLabel = (v: Vehicle) => v.kind === 'class' ? `${v.size_class} · ${classLabels[v.size_class] ?? 'Size class'}` : v.label

function shortName(v: Vehicle) {
  if (v.kind === 'class') return vehicleLabel(v)
  return v.label
}

export const fmtWidth = (lo: number, hi: number | null) => (hi == null ? `≥ ${vn(lo)} m` : `${vn(lo)}–${vn(hi)} m`)
