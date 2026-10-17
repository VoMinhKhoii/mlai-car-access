import { StrictMode, useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDown, ArrowUpRight, Camera, Check, CheckCircle2, ChevronLeft, CloudUpload, LocateFixed, LockKeyhole, MapPin, Navigation, Ruler, WifiOff } from 'lucide-react'
import { ArrivalConfirmation } from './ArrivalConfirmation'
import { ApiError, api, pending, readStored, savePending, store, submissionId } from './storage'
import type { Pending } from './storage'
import './field.css'
import { Crowd } from './Crowd'
import { Review } from './Review'
import { Stage } from './Stage'

type Place = { lat: number; lon: number; accuracy_m?: number }
type Campus = Place & { id: string; name: string; official_address: string }
type Vehicle = { id: string; label: string }
type Way = Place & { way_id: number; name: string; lo: number; hi: number | null; top_tier: string | null; review: boolean; thresholds_straddled: string[]; plan_requests: number }
type Recent = { submission_id: string; osm_way_id: string; width_m: string; tier: string; measured_by: string; date: string }
type Bootstrap = { campuses: Campus[]; vehicles: Vehicle[] }
const DEFAULT = { lat: 10.801617, lon: 106.714455 }
const format = (n: number) => n.toLocaleString('en-GB', { maximumFractionDigits: 2 })
const distance = (a: Place, b: Place) => Math.hypot((a.lat-b.lat)*110574, (a.lon-b.lon)*109400)
const mapLink = (p: Place) => `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=19/${p.lat}/${p.lon}`
function why(w: Way) {
  if (w.review) return 'Sources conflict. A field check is needed.'
  if (w.thresholds_straddled.length) return `Cannot yet determine vehicle fit for ${w.thresholds_straddled.map(x => ({ vf3: 'VF 3', sedan: 'sedan', suv: 'SUV' })[x] || x).join(', ')}.`
  return w.top_tier === 'Measured' ? 'Measured; recheck if conditions change.' : 'No clear-width measurement at the narrowest point.'
}

function FieldApp() {
  const [token, setToken] = useState(() => readStored('ngo-field-token', ''))
  const [tokenDraft, setTokenDraft] = useState('')
  const [unlocked, setUnlocked] = useState(false)
  const [boot, setBoot] = useState<Bootstrap>(() => readStored('ngo-field-bootstrap', { campuses: [], vehicles: [] }))
  const [center, setCenter] = useState<Place>(DEFAULT)
  const [gps, setGps] = useState<Place | null>(null)
  const [ways, setWays] = useState<Way[]>(() => readStored('ngo-field-ways', []))
  const [selected, setSelected] = useState<Way | null>(null)
  const [wayId, setWayId] = useState('')
  const [position, setPosition] = useState<Place | null>(null)
  const [positionKind, setPositionKind] = useState('')
  const [tab, setTab] = useState<'measure' | 'arrival'>('measure')
  const [method, setMethod] = useState('tape')
  const [turn, setTurn] = useState('unknown')
  const [measurer, setMeasurer] = useState(() => readStored('ngo-field-measurer', ''))
  const [photo, setPhoto] = useState<{ data: string; name: string; size: number } | null>(null)
  const [items, setItems] = useState<Pending[]>(pending)
  const [recent, setRecent] = useState<Recent[]>([])
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [vehicleId, setVehicleId] = useState('toyota-vios')
  const [allWays, setAllWays] = useState(false)
  const syncing = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const formSection = useRef<HTMLElement>(null)
  const alive = useRef(true)

  const loadRecent = useCallback(async () => {
    try { const r = await api<{ items: Recent[] }>('/api/field/recent', token); setRecent(r.items) } catch { /* Preserve last view offline. */ }
  }, [token])

  useEffect(() => {
    if (!token) return
    let current = true
    api<Bootstrap>('/api/field/bootstrap', token).then(data => {
      if (!current) return
      setBoot(data); store('ngo-field-bootstrap', data); setUnlocked(true); setError('')
    }).catch(e => {
      if (!current) return
      if (!(e instanceof ApiError) && boot.campuses.length) { setUnlocked(true); setStatus('Offline mode. Measurements will be queued for retry.') }
      else setError(e.message)
    })
    return () => { current = false }
  // Cached bootstrap is intentionally read only on initial load.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    if (!unlocked) return
    let current = true
    const d = .018
    const bbox = `${center.lon-d},${center.lat-d},${center.lon+d},${center.lat+d}`
    setLoading(true)
    api<{ items: Way[]; available: boolean }>(`/api/field/queue?limit=60&bbox=${bbox}`, token).then(data => {
      if (!current) return
      if (!data.available) throw new Error('Evidence store is unavailable on the server.')
      const sorted = data.items.sort((a,b) => distance(a,center)-distance(b,center))
      setWays(sorted); store('ngo-field-ways', sorted)
      setSelected(s => s && sorted.some(w => w.way_id === s.way_id) ? s : sorted[0] || null)
      if (!gps) setWayId(String(sorted[0]?.way_id || ''))
      setError('')
    }).catch(e => { if (current) setError(`${e.message} The last saved list remains available.`) }).finally(() => { if (current) setLoading(false) })
    void loadRecent()
    return () => { current = false }
  }, [center, token, unlocked, loadRecent, gps])

  const retry = useCallback(async () => {
    if (syncing.current || !token || !navigator.onLine) return
    syncing.current = true
    try {
      for (const entry of pending()) {
        try {
          await api(entry.endpoint, token, entry.body)
          const remaining = pending().filter(x => x.id !== entry.id)
          if (!savePending(remaining)) { setError('Submitted but device storage could not be updated. The record ID makes retrying safe.'); break }
          setItems(remaining)
        } catch (e) {
          const message = e instanceof Error ? e.message : 'Could not connect.'
          const remaining = pending().map(x => x.id === entry.id ? { ...x, error: message } : x)
          savePending(remaining); setItems(remaining)
          if (!(e instanceof ApiError) || e.status === 401 || e.status >= 500) break
        }
      }
      void loadRecent()
    } finally { syncing.current = false }
  }, [token, loadRecent])

  useEffect(() => {
    alive.current = true
    function network() { setOnline(navigator.onLine); if (navigator.onLine) void retry() }
    window.addEventListener('online', network); window.addEventListener('offline', network)
    const timer = setInterval(() => void retry(), 30000)
    if (unlocked) void retry()
    return () => { alive.current = false; window.removeEventListener('online', network); window.removeEventListener('offline', network); clearInterval(timer) }
  }, [retry, unlocked])

  useEffect(() => {
    if ('serviceWorker' in navigator && import.meta.env.PROD) {
      navigator.serviceWorker.register('/field-sw.js', { scope: '/field' }).then(() => {
        void navigator.serviceWorker.ready.then(() => { if (alive.current) setStatus('Page is ready to reopen offline.') })
      }).catch(() => setStatus('Could not save the page offline. Keep this tab open during fieldwork.'))
    }
  }, [])

  async function send(endpoint: string, body: Record<string, unknown>) {
    const id = String(body.submission_id)
    const entry: Pending = { id, endpoint, body }
    const durable = savePending([...pending(), entry])
    if (durable) setItems(pending())
    try {
      await api(endpoint, token, body)
      if (durable) {
        const remaining = pending().filter(x => x.id !== id)
        savePending(remaining); setItems(remaining)
      }
      void loadRecent()
      return 'Submitted and added to evidence. Thank you!'
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Connection lost.'
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![401,408,429].includes(e.status)) {
        if (durable) { const remaining = pending().filter(x => x.id !== id); savePending(remaining); setItems(remaining) }
        throw e
      }
      if (!durable) throw new Error(`Not submitted or saved: device storage is full or blocked. Keep the form open, choose a smaller photo and retry. ${message}`)
      const updated = pending().map(x => x.id === id ? { ...x, error: message } : x)
      savePending(updated); setItems(updated)
      return `Saved on device, awaiting retry. ${message}`
    }
  }

  function locate() {
    setStatus('Getting precise GPS…'); setError('')
    if (!navigator.geolocation) { setError('Browser does not support GPS. Enter coordinates at the measurement location.'); return }
    navigator.geolocation.getCurrentPosition(async ({ coords }) => {
      const p = { lat: coords.latitude, lon: coords.longitude, accuracy_m: Math.round(coords.accuracy) }
      setGps(p); setCenter(p); setPosition(p); setPositionKind('Phone GPS')
      setStatus(`GPS captured, accuracy about ${Math.round(coords.accuracy)} m. Check the road segment before measuring.`)
      try {
        const data = await api<{ items: { way_id: number; name: string; distance_m: number }[] }>(`/api/field/snap?lat=${p.lat}&lon=${p.lon}`, token)
        if (data.items[0]) { setWayId(String(data.items[0].way_id)); setStatus(`GPS near ${data.items[0].name} (${data.items[0].distance_m} m). Way ID filled in; please check it.`) }
      } catch (e) { setError(e instanceof Error ? e.message : 'Could not match GPS to a road.') }
    }, () => { setError('Could not get GPS. Allow location in Safari/Chrome and use HTTPS, or enter coordinates at the measurement point.') }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 15000 })
  }

  async function choosePhoto(file?: File) {
    if (!file) { setPhoto(null); return }
    if (file.size > 8*1024*1024) { setError('Photo must be at most 8 MB. Choose another photo; retain the original with GPS if available.'); return }
    try {
      const data = await new Promise<string>((resolve,reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = reject; r.readAsDataURL(file) })
      setPhoto({ data, name: file.name, size: file.size }); setError('')
    } catch { setError('Could not read photo. Select the original photo again.') }
  }

  async function submitMeasurement(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault(); setError(''); setStatus('')
    if (!position) { setError('Get GPS or enter actual measurement coordinates before submitting.'); return }
    const values = new FormData(e.currentTarget)
    const num = (key: string) => values.get(key) ? Number(String(values.get(key)).replace(',', '.')) : null
    const width = num('width_m')
    if (width === null || !Number.isFinite(width) || width<.5 || width>15) { setError('Width must be between 0.5 and 15 m.'); return }
    if (!Number.isInteger(Number(wayId)) || Number(wayId)<=0) { setError('Way ID must be a positive integer.'); return }
    const body = { submission_id: submissionId(), measured_at: new Date().toISOString(), way_id: Number(wayId), width_m: width, method, measured_by: measurer.trim(), ...position,
      position_note: String(values.get('position_note') || ''), note: String(values.get('note') || ''), obstructions: values.getAll('obstructions'),
      turn_space: turn, turn_width_m: turn === 'yes' ? num('turn_width_m') : null, turn_length_m: turn === 'yes' ? num('turn_length_m') : null,
      coverage_complete: values.get('coverage_complete') === 'on', photo_base64: photo?.data || null }
    setSaving(true)
    try {
      const message = await send('/api/field/measure', body)
      store('ngo-field-measurer', measurer); setStatus(message)
      form.current?.reset(); setPhoto(null); setTurn('unknown'); setMethod('tape')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save measurement.') }
    finally { setSaving(false) }
  }

  const vehicle = boot.vehicles.find(v => v.id === vehicleId) || boot.vehicles[0]
  const arrivalPosition = position || gps
  return <div className="field-shell">
    <header className="field-header"><a href="/field" className="field-brand"><span className="field-mark">n.</span><span>Ngõ Ngách<small>FIELD KIT</small></span></a><span className={`connection ${online ? '' : 'offline'}`}>{online ? <span className="live-dot" /> : <WifiOff size={15} />}{online ? 'Online' : 'Offline'}</span></header>
    {!unlocked ? <main className="unlock"><div className="lock-symbol"><LockKeyhole size={28} /></div><p className="eyebrow">FOR FIELD TEAMS</p><h1>Every measurement,<br />one less guess.</h1><p>Measure the usable alley clearance. Record the source, location and time for the team.</p><form onSubmit={e => { e.preventDefault(); const value = tokenDraft.trim(); store('ngo-field-token', value); setToken(value); if (value === token) api<Bootstrap>('/api/field/bootstrap', value).then(data => { setBoot(data); setUnlocked(true); setError('') }).catch(e => setError(e.message)) }}><label>Team code<input type="password" autoComplete="current-password" value={tokenDraft} onChange={e => setTokenDraft(e.target.value)} required placeholder="Enter the shared FIELD_TOKEN" /></label><button className="primary" type="submit">Open field kit <ArrowUpRight size={19} /></button></form><p className="hint">This device remembers the code. Use your own phone and change the code after fieldwork.</p>{error && <p className="notice error" role="alert">{error}</p>}</main> : <main>
      <div className="intro"><p className="eyebrow">FROM ESTIMATES TO MEASUREMENTS</p><h1>Measure an alley today.</h1><p>Measure the narrowest point. Record the usable vehicle clearance.</p></div>
      <nav className="field-tabs" aria-label="Tasks"><button className={tab==='measure' ? 'active' : ''} onClick={() => setTab('measure')}><Ruler size={18} /> Measure width</button><button className={tab==='arrival' ? 'active' : ''} onClick={() => setTab('arrival')}><CheckCircle2 size={18} /> Arrived</button></nav>
      {(error || status) && <div className={`notice ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>{error || status}<button type="button" onClick={() => { setError(''); setStatus('') }} aria-label="Dismiss notification">×</button></div>}
      <section className="location-block" aria-label="Choose area"><button type="button" className="gps-button" onClick={locate}><LocateFixed size={20} /> Use my GPS <ArrowUpRight size={17} /></button><label className="campus-label">Or choose a HUTECH campus<select aria-label="HUTECH campus" defaultValue="" onChange={e => { const c=boot.campuses.find(x=>x.id===e.target.value); if(c) { setCenter(c); setAllWays(false) } }}><option value="" disabled>Điện Biên Phủ · 475A</option>{boot.campuses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><p className="hint">Choose a campus to find alleys. Capture GPS at the measurement location.</p></section>
      {tab==='measure' && <>
        <section className="next-section" aria-labelledby="next-title"><div className="section-heading"><div><p className="eyebrow">01 / CHOOSE A SEGMENT</p><h2 id="next-title">Where to measure next?</h2></div><span className="count">{ways.length} segments</span></div><p className="hint">Near your selected location, prioritised by the evidence queue.</p>
          {loading && <p role="status">Finding segments to measure…</p>}
          {!loading && !ways.length && <p className="notice">No segments in this area. Choose another campus or get GPS and retry.</p>}
          <ol className="way-list">{ways.slice(0, allWays ? 12 : 3).map((w,i) => <li key={w.way_id} className={selected?.way_id===w.way_id ? 'selected' : ''}>
            <button type="button" className="way-select" onClick={() => { setSelected(w); setWayId(String(w.way_id)) }} aria-pressed={selected?.way_id===w.way_id}><span className="way-index">{selected?.way_id===w.way_id ? <Check size={18} /> : String(i+1).padStart(2,'0')}</span><span className="way-content"><strong>{w.name || `Unnamed segment · ${w.way_id}`}</strong><span className="range">{format(w.lo)}–{w.hi===null ? '?' : format(w.hi)} m <span>· {w.top_tier || 'No source yet'}</span></span><small>{why(w)}</small></span></button>
            <a className="pin-link" href={mapLink(w)} target="_blank" rel="noreferrer" aria-label={`Open ${w.name || w.way_id} pin on map`}><MapPin size={16} /> {Math.round(distance(center,w))} m <ArrowUpRight size={14} /></a>
          </li>)}</ol>
          {ways.length>3 && <button type="button" className="text-button" onClick={() => setAllWays(!allWays)}>{allWays ? 'Collapse list' : 'Show more segments to measure'} <ArrowDown size={16} /></button>}
          {selected && <button type="button" className="primary" onClick={() => formSection.current?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })}>Measure selected segment <Ruler size={18} /></button>}
        </section>
        <section className="measurement-section" ref={formSection}><div className="section-heading"><div><p className="eyebrow">02 / RECORD MEASUREMENT</p><h2>Usable vehicle clearance</h2></div><Ruler size={24} /></div>
          <form ref={form} onSubmit={e => void submitMeasurement(e)}>
            <label>Way ID <input name="way_id" inputMode="numeric" value={wayId} onChange={e=>setWayId(e.target.value)} required /><small>Matched from GPS or the selected segment. Editable.</small></label>
            <fieldset><legend>Method</legend><div className="method-options">{([['tape','Tape measure'],['lidar','LiDAR'],['pacing','Pacing']] as const).map(([value,label]) => <label key={value} className={method===value ? 'chosen' : ''}><input type="radio" name="method" checked={method===value} onChange={()=>setMethod(value)} />{label}</label>)}</div><p className="tier-line">{method==='pacing' ? 'Observed · Pacing is an observation, uncertainty ±0.5 m.' : 'Measured · Actual measurement, uncertainty ±0.1 m.'}</p></fieldset>
            <label className="width-label">Narrowest clear width<div className="width-input"><input name="width_m" type="text" maxLength={6} inputMode="decimal" placeholder="2.40" required aria-describedby="width-help" /><span>m</span></div><small id="width-help">0.5–15 m. Exclude steps, plant pots and current obstructions.</small></label>
            <label className="check-row"><input type="checkbox" name="coverage_complete" /><span>I checked this entire segment and measured its narrowest point.<small>Do not select if you measured only one location. A single sample does not certify the whole alley.</small></span></label>
            <div className="position-heading"><h3>Location along alley</h3><button type="button" className="text-button" onClick={locate}><LocateFixed size={17} /> Get GPS</button></div>
            <p className="hint">{positionKind || 'No measurement location. Get GPS or enter actual coordinates.'}{position?.accuracy_m!==undefined ? ` · Accuracy ±${position.accuracy_m} m` : ''}</p>
            <div className="two-columns"><label>Latitude<input type="number" step="any" value={position?.lat ?? ''} required onChange={e => { setPosition({ lat:Number(e.target.value),lon:position?.lon ?? center.lon }); setPositionKind('Manually entered coordinates') }} placeholder="10.8016" /></label><label>Longitude<input type="number" step="any" value={position?.lon ?? ''} required onChange={e => { setPosition({lat:position?.lat ?? center.lat,lon:Number(e.target.value)}); setPositionKind('Manually entered coordinates') }} placeholder="106.7145" /></label></div>
            <label>Recognisable landmark<input name="position_note" maxLength={500} placeholder="Example: narrowest point, outside number 12" /></label>
            <fieldset><legend>Obstructions at measurement time</legend>{([['steps','Steps / entrance ramp'],['motorbikes','Parked motorbikes'],['stall','Market stall']] as const).map(([value,label]) => <label className="check-row" key={value}><input type="checkbox" name="obstructions" value={value} />{label}</label>)}</fieldset>
            <label>Turning space at the end of the alley?<select value={turn} onChange={e=>setTurn(e.target.value)}><option value="unknown">Not checked</option><option value="yes">Open space available</option><option value="no">No</option></select><small>Records current conditions; does not confirm a particular vehicle can turn.</small></label>
            {turn==='yes' && <div className="two-columns"><label>Width (m)<input name="turn_width_m" type="number" min="0.5" max="100" step="0.01" inputMode="decimal" /></label><label>Length (m)<input name="turn_length_m" type="number" min="0.5" max="100" step="0.01" inputMode="decimal" /></label></div>}
            <label className="photo-input"><Camera size={22} /><span><strong>{photo ? photo.name : 'Add field photo'}</strong><small>{photo ? `${(photo.size/1024/1024).toFixed(1)} MB · Original photo preserved` : 'Original photo up to 8 MB; retain EXIF GPS if available. No faces needed.'}</small></span><input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" onChange={e=>void choosePhoto(e.target.files?.[0])} /></label>
            {photo && <button type="button" className="text-button" onClick={()=>setPhoto(null)}>Remove selected photo</button>}
            <label>Measured by<input name="measured_by" autoComplete="name" value={measurer} onChange={e=>setMeasurer(e.target.value)} maxLength={100} required placeholder="Your name" /></label>
            <label>Additional notes (optional)<textarea name="note" maxLength={1000} rows={2} placeholder="Permanent or temporary obstructions, direction…" /></label>
            <div className="safety-note"><Navigation size={18} /><p>Stand somewhere safe, out of traffic. Ask residents for permission when measuring near homes.</p></div>
            <button className="primary" type="submit" disabled={saving}>{saving ? 'Saving measurement…' : 'Save field measurement'} <CloudUpload size={20} /></button>
          </form>
        </section>
      </>}
      {tab==='arrival' && <section className="arrival-section"><p className="eyebrow">RECORD ONLY SEGMENTS YOU TRAVELLED</p><label>Vehicle model<select value={vehicleId} onChange={e=>setVehicleId(e.target.value)}>{boot.vehicles.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}</select></label><label>Way ID of travelled segment<input inputMode="numeric" value={wayId} onChange={e=>setWayId(e.target.value)} /></label>{vehicle ? <ArrivalConfirmation key={`${vehicle.id}-${wayId}`} vehicle={vehicle} lat={arrivalPosition?.lat ?? center.lat} lon={arrivalPosition?.lon ?? center.lon} wayIds={Number(wayId)>0 ? [Number(wayId)] : []} disabled={!arrivalPosition || !Number.isInteger(Number(wayId)) || Number(wayId)<=0} submit={body=>send('/api/field/confirm',body)} /> : null}{!arrivalPosition && <p className="notice">Get GPS above and select a Way ID to confirm arrival.</p>}</section>}
      <section className="pending-section"><div className="section-heading"><h2>Pending submission <span className="count">{items.length}</span></h2><button type="button" className="text-button" onClick={()=>void retry()}>Retry <CloudUpload size={17} /></button></div><p className="hint">{items.length ? 'Saved on your phone. Retries when online, every 30 seconds and on page open.' : 'Measurements are saved on your device before submission. Keep the page open if saving fails.'}</p>{items.map(item=><div className="pending-item" key={item.id}><strong>{item.endpoint.includes('measure') ? `Measured ${String(item.body.width_m)} m` : 'Arrival confirmation'} · Way {String(item.body.way_id || (item.body.way_ids as number[])?.[0])}</strong><p>{item.error || 'Waiting for connection'}</p><button type="button" className="text-button" onClick={()=>{ const next=pending().filter(x=>x.id!==item.id); if(savePending(next)) setItems(next) }}>Remove queued submission</button></div>)}</section>
      <section className="recent-section"><p className="eyebrow">RECENT TEAM CONTRIBUTIONS</p><h2>Recent measurements</h2>{recent.length ? <ul>{recent.slice(0,5).map((r,i)=><li key={r.submission_id || i}><Ruler size={18} /><div><strong>{r.width_m} m <span>· {r.tier}</span></strong><small>Way {r.osm_way_id} · {r.measured_by}<br />{new Date(r.date).toLocaleString('en-GB')}</small></div></li>)}</ul> : <p className="hint">No measurements yet. Record the first segment of this field trip.</p>}</section>
      <footer><span>Ngõ Ngách · Measure on site, record the source.</span><button type="button" onClick={()=>{ store('ngo-field-token',''); setToken(''); setTokenDraft(''); setUnlocked(false) }}><ChevronLeft size={15} /> Change team code</button></footer>
    </main>}
  </div>
}

const page = location.pathname === '/field/review' ? <Review /> : location.pathname === '/field/qr' ? <Stage /> : new URLSearchParams(location.search).get('crowd') === '1' ? <Crowd /> : <FieldApp />
createRoot(document.getElementById('root')!).render(<StrictMode>{page}</StrictMode>)
