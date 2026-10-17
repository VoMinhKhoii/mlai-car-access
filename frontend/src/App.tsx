import { CloudRain, FlaskConical, Layers, MapPin, Navigation, Sparkles, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type AgentPlan, type AreaBuild, type AreaData, type Config, type Flag, type Intent, type Plan, type Preset, type RainSpell, type Vehicle, type WayEvidence } from './api'
import { MapView, type FloodMoment, type LayerToggles } from './MapView'
import type { MapContext } from './mapSearch'
import { ErrorBoundary } from './ErrorBoundary'
import { Directions, type Place, type VehicleMode } from './components/Directions'
import { GoongContrast, LiveStrip, NewsList, StopRow, Verdict } from './components/Result'
import { Agent } from './components/Agent'
import { EvidencePanel } from './components/Evidence'
import { TideTimeline } from './components/TideTimeline'
import { Segmented, useOutside, vnt } from './ds/ui'

const VN = 7 * 3600e3
const toLocal = (iso: string) => new Date(new Date(iso).getTime() + VN).toISOString().slice(0, 16)
const fromLocal = (v: string) => `${v}:00+07:00`
const DEMO_ORIGIN: Place = { lat: 10.7725, lon: 106.698, label: 'Chợ Bến Thành, Quận 1' }
const isMobile = () => window.matchMedia('(max-width: 760px)').matches

export default function App() {
  const [agentOpen, setAgentOpen] = useState(false)
  const [mapContext, setMapContext] = useState<MapContext | null>(null)
  const [cfg, setCfg] = useState<Config | null>(null)
  const [fleet, setFleet] = useState<{ classes: Vehicle[]; models: Vehicle[] }>({ classes: [], models: [] })
  const [origin, setOrigin] = useState<Place | null>(null)
  const [dest, setDest] = useState<Place | null>(null)
  const [vMode, setVMode] = useState<VehicleMode>('model')
  const [classId, setClassId] = useState('class-s')
  const [modelId, setModelId] = useState('toyota-vios')
  const [vetcLinked, setVetcLinked] = useState(false)
  const [vetcOpen, setVetcOpen] = useState(false)
  const [intent, setIntent] = useState<Intent>('park')
  const [dwell, setDwell] = useState(120)
  const [arriveNow, setArriveNow] = useState(true)
  const [arrive, setArrive] = useState(() => toLocal(new Date().toISOString()))
  const [agentRain, setAgentRain] = useState<RainSpell[] | null>(null)
  const [rainOn, setRainOn] = useState(false)
  const [rainMm, setRainMm] = useState(45)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [selected, setSelected] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toggles, setToggles] = useState<LayerToggles>({ fit: true, flood: true, goong: false })
  const [floodMoment, setFloodMoment] = useState<FloodMoment>('arrive')
  const [way, setWay] = useState<WayEvidence | null>(null)
  const [wayAt, setWayAt] = useState<[number, number]>([0, 0])
  const [build, setBuild] = useState<AreaBuild | null>(null)
  const [story, setStory] = useState('')
  const [pick, setPick] = useState<{ lat: number; lon: number; x: number; y: number } | null>(null)
  const [menu, setMenu] = useState<'demo' | 'layers' | null>(null)
  const [arrived, setArrived] = useState(false)
  const [confirmed, setConfirmed] = useState('')
  const [sheet, setSheet] = useState<'peek' | 'half' | 'full'>('half')
  const [locating, setLocating] = useState(false)
  const [frame, setFrame] = useState<'arrival' | 'trip'>('arrival')
  const [now, setNow] = useState(() => Date.now())
  const areaRef = useRef<AreaData | null>(null)
  const buildingKey = useRef('')
  const reqId = useRef(0)

  useEffect(() => {
    api.config().then(setCfg).catch((e) => setError(String(e)))
    api.vehicles().then(setFleet)
    const t = window.setInterval(() => setNow(Date.now()), 60e3)
    return () => window.clearInterval(t)
  }, [])

  const vehicleId = vMode === 'class' ? classId : vMode === 'model' ? modelId : vetcLinked ? 'toyota-fortuner' : ''
  const vehicle = useMemo(() => [...fleet.classes, ...fleet.models].find((v) => v.id === vehicleId), [fleet, vehicleId])
  // "Đi ngay" = the next 5-minute mark, so the plan only refreshes when that mark moves.
  const arriveLocal = arriveNow ? toLocal(new Date(Math.ceil(now / 300e3) * 300e3).toISOString()) : arrive
  const rain: RainSpell[] = useMemo(() => {
    if (agentRain !== null) return agentRain
    if (!rainOn) return []
    const start = new Date(new Date(fromLocal(arriveLocal)).getTime() + 30 * 60e3)
    return [{ start: start.toISOString(), end: new Date(start.getTime() + 3600e3).toISOString(), mm_per_h: rainMm }]
  }, [rainOn, rainMm, arriveLocal, agentRain])

  // One plan per committed input; newer requests always win.
  const run = useCallback(async () => {
    if (!dest || !vehicleId) return
    const id = ++reqId.current
    setBusy(true)
    setError('')
    try {
      const r = await api.plan({
        lat: dest.lat, lon: dest.lon, label: dest.label, vehicle_id: vehicleId, intent,
        arrive_at: fromLocal(arriveLocal), dwell_min: dwell, rain,
        origin: origin ? [origin.lat, origin.lon] : null, area: areaRef.current,
      })
      if (id !== reqId.current) return
      setPlan(r)
      setSelected((s) => (s < r.stop_points.length ? s : 0))
      setFloodMoment(r.timing ? 'depart' : 'arrive')
      if (r.live_crawl && areaRef.current?.key !== r.area_key && buildingKey.current !== r.area_key) startBuild(dest, r.area_key)
    } catch (e) {
      if (id === reqId.current) { setError(e instanceof Error ? e.message : String(e)); setPlan(null) }
    } finally {
      if (id === reqId.current) setBusy(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dest, origin, vehicleId, intent, dwell, arriveLocal, rain])
  const runRef = useRef(run)
  runRef.current = run

  useEffect(() => {
    const t = window.setTimeout(run, 220)
    return () => window.clearTimeout(t)
  }, [run])

  async function startBuild(d: Place, key: string) {
    buildingKey.current = key
    try {
      const a = await api.areaBuild(d.lat, d.lon, setBuild)
      if (a) { areaRef.current = a; runRef.current() }
    } catch (e) {
      setBuild({ key, state: 'error', error: e instanceof Error ? e.message : String(e) })
    } finally {
      buildingKey.current = ''
    }
  }

  function chooseDest(p: Place | null) {
    setDest(p)
    setStory('')
    setWay(null)
    if (!p) setPlan(null)
    if (p && areaRef.current && plan && Math.abs(plan.destination.lat - p.lat) > 0.01) setBuild(null)
  }

  async function locate() {
    if (!navigator.geolocation) return setOrigin(DEMO_ORIGIN)
    setLocating(true)
    navigator.geolocation.getCurrentPosition(async (pos) => {
      const { latitude: lat, longitude: lon } = pos.coords
      const r = await api.reverse(lat, lon).catch(() => ({ label: 'Vị trí của bạn' }))
      setOrigin({ lat, lon, label: r.label })
      setLocating(false)
    }, () => { setLocating(false); setOrigin(DEMO_ORIGIN) }, { enableHighAccuracy: true, timeout: 8000 })
  }

  async function pickAs(kind: 'origin' | 'dest') {
    if (!pick) return
    const { lat, lon } = pick
    setPick(null)
    const r = await api.reverse(lat, lon).catch(() => ({ label: `${lat.toFixed(5)}, ${lon.toFixed(5)}` }))
    if (kind === 'origin') setOrigin({ lat, lon, label: r.label })
    else chooseDest({ lat, lon, label: r.label })
  }

  function applyAgent(p: AgentPlan) {
    chooseDest({ lat: p.lat, lon: p.lon, label: p.label })
    areaRef.current = null
    setVMode(p.vehicle_id.startsWith('class-') ? 'class' : 'model')
    if (p.vehicle_id.startsWith('class-')) setClassId(p.vehicle_id)
    else setModelId(p.vehicle_id)
    setIntent(p.intent)
    setArriveNow(false)
    setArrive(toLocal(p.arrive_at))
    setDwell(p.dwell_min)
    setAgentRain(p.rain)
    setRainOn(p.rain.length > 0)
    if (p.rain[0]) setRainMm(p.rain[0].mm_per_h)
    setSelected(0)
    setSheet('half')
  }

  function loadPreset(p: Preset) {
    setAgentRain(null)
    const isClass = p.vehicle_id.startsWith('class-')
    setVMode(isClass ? 'class' : 'model')
    if (isClass) setClassId(p.vehicle_id)
    else setModelId(p.vehicle_id)
    setIntent(p.intent)
    setDwell(p.dwell_min)
    setArriveNow(false)
    setArrive(toLocal(p.arrive_at))
    setRainOn((p.rain ?? []).length > 0)
    if (p.rain?.[0]) setRainMm(p.rain[0].mm_per_h)
    setOrigin((o) => o ?? DEMO_ORIGIN)
    setDest({ lat: p.lat, lon: p.lon, label: p.label })
    setStory(p.story)
    setMenu(null)
    setSheet('half')
  }

  function leaveBefore(hm: string) {
    const a = new Date(fromLocal(arriveLocal)).getTime()
    const [h, m] = hm.split(':').map(Number)
    let t = new Date(fromLocal(arriveLocal.slice(0, 11) + `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)).getTime()
    if (t <= a) t += 24 * 3600e3
    setDwell(Math.max(15, Math.floor((t - a) / 60e3 / 15) * 15))
    setIntent('park')
  }

  async function openEvidence(id: number, lat: number, lon: number) {
    setWayAt([lat, lon])
    try { setWay(await api.wayEvidence(id, lat, lon, areaRef.current)) } catch { setWay(null) }
  }

  async function reviewPhoto(id: string, approve: boolean) {
    const a = areaRef.current
    if (!a) return
    areaRef.current = { ...a, photos: a.photos.map((p) => (p.id === id ? { ...p, status: approve ? 'approved' : 'rejected' } : p)) }
    api.reviewPhoto(a.key, id, approve).catch(() => { /* the browser copy is enough to re-plan */ })
    if (way) setWay(await api.wayEvidence(way.way_id, wayAt[0], wayAt[1], areaRef.current))
    runRef.current()
  }

  async function setFlag(f: Flag, on: boolean) {
    const r = await api.setFlag(f.name, on)
    setCfg((c) => (c ? { ...c, flags: r.flags } : c))
    runRef.current()
  }

  async function confirmArrival(result: 'in' | 'tight' | 'no') {
    if (!plan || !vehicle) return
    const wid = plan.door?.way_id ?? plan.stop_points[0]?.way_id
    if (!wid) return
    await api.confirm({ lat: plan.destination.lat, lon: plan.destination.lon, vehicle_id: vehicle.id, result, way_ids: [wid] })
    setConfirmed(result)
  }

  const padding = isMobile() ? { top: 190, left: 24, right: 24, bottom: 320 } : { top: 60, left: 460, right: agentOpen ? 470 : 80, bottom: 190 }

  if (!cfg) return <div className="boot">{error ? `Không kết nối được máy chủ: ${error}` : <span className="boot-mark display">Ngõ Ngách</span>}</div>

  const goongOn = cfg.goong.tiles
  return (
    <div className={`app ${way ? 'has-evidence' : ''}`}>
      <ErrorBoundary label="Bản đồ">
        <MapView styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} origin={origin} destination={dest}
          toggles={toggles} floodMoment={floodMoment} padding={padding} frame={frame}
          onPick={(lat, lon, x, y) => setPick({ lat, lon, x, y })}
          onFeatures={setMapContext} onPlaceClick={(p) => chooseDest({ lat: p.lat, lon: p.lon, label: p.name })}
          onWayClick={openEvidence}
          onStopClick={(i) => { setSelected(i); setSheet((s) => (s === 'peek' ? 'half' : s)) }} />
      </ErrorBoundary>

      <div className="side">
        <section className="card top">
          <header className="brand">
            <span className="logo" aria-hidden>NN</span>
            <span className="brand-name display">Ngõ Ngách</span>
            <span className="brand-sub">lớp hẻm cho T-Maps</span>
            <DemoMenu open={menu === 'demo'} onOpen={(o) => setMenu(o ? 'demo' : null)} cfg={cfg} loadPreset={loadPreset}
              rainOn={rainOn} setRainOn={(on) => { setAgentRain(null); setRainOn(on) }} rainMm={rainMm} setRainMm={(mm) => { setAgentRain(null); setRainMm(mm) }} setFlag={setFlag}
              canArrive={!!plan} onArrive={() => { setArrived(true); setConfirmed(''); setMenu(null) }} />
          </header>
          <Directions origin={origin} dest={dest} setOrigin={setOrigin} setDest={chooseDest} locating={locating} onLocate={locate} mapContext={mapContext}
            vehicle={vehicle} fleet={fleet} vMode={vMode} setVMode={setVMode} classId={classId} setClassId={setClassId}
            modelId={modelId} setModelId={setModelId} vetcLinked={vetcLinked} openVetc={() => setVetcOpen(true)} unlinkVetc={() => setVetcLinked(false)}
            intent={intent} setIntent={(i) => { setIntent(i); setDwell(i === 'pickup' ? 15 : 120) }} dwell={dwell} setDwell={setDwell}
            arrive={arriveLocal} setArrive={setArrive} arriveNow={arriveNow} setArriveNow={setArriveNow} />
        </section>

        <section className={`card sheet sheet-${sheet}`} aria-label="Kết quả">
          <button type="button" className="sheet-handle" aria-label="Thu/mở bảng kết quả"
            onClick={() => setSheet((s) => (s === 'peek' ? 'half' : s === 'half' ? 'full' : 'peek'))}><i /></button>
          <div className="sheet-body">
            {error && <p className="error-line">{error}</p>}
            {!dest && <Welcome presets={cfg.presets} loadPreset={loadPreset} />}
            {dest && !plan && busy && <SkeletonResult />}
            {plan && (
              <>
                {story && <p className="story">{story}</p>}
                <Verdict plan={plan} onLeaveBefore={leaveBefore} stale={busy} />
                {build && <LiveStrip build={build} />}
                {areaRef.current?.key === plan.area_key && <NewsList items={areaRef.current.news ?? []} />}
                <h3 className="section-title">{plan.stop_points.some((s) => s.legality.status === 'Restricted') ? 'Các vị trí đã kiểm tra' : `Chỗ ${plan.intent === 'park' ? 'đỗ' : 'dừng'} gợi ý`}</h3>
                <div className="stops">
                  {plan.stop_points.map((s, i) => (
                    <StopRow key={`${s.lat},${s.lon}`} s={s} plan={plan} index={i} selected={i === selected}
                      onSelect={() => setSelected(i)} onEvidence={(id) => openEvidence(id, s.lat, s.lon)} />
                  ))}
                  {!plan.stop_points.length && <p className="muted">{plan.verdict.detail}</p>}
                </div>
                {plan.door && !plan.door.ok && (
                  <details className="why">
                    <summary>Vì sao không vào tận cửa?</summary>
                    <ul>{plan.door.fail_reasons.map((r, i) => <li key={i}>{vnt(r)}</li>)}</ul>
                  </details>
                )}
                {vehicle && <GoongContrast plan={plan} vehicleLabel={vehicle.label} show={toggles.goong} onToggle={() => setToggles((t) => ({ ...t, goong: !t.goong }))} />}
                <p className="sources faint">Nguồn: {goongOn ? 'Goong (bản đồ, tìm kiếm, tuyến xe)' : 'bản đồ nền tạm'}, OpenStreetMap, IRD 2002–2026, Đài KTTV Nam Bộ, VETC, Chợ Tốt.</p>
              </>
            )}
          </div>
        </section>
      </div>

      {plan?.origin && plan.stop_points[selected]?.approach && (
        <div className="frame-toggle">
          <Segmented label="Khung bản đồ" value={frame} onChange={setFrame}
            options={[{ value: 'arrival', label: 'Đoạn cuối' }, { value: 'trip', label: 'Cả tuyến' }]} />
        </div>
      )}
      <Agent origin={origin} onPlan={applyAgent} open={agentOpen} setOpen={setAgentOpen} mapContext={mapContext} />
      <div className="map-tools">
        <LayersMenu open={menu === 'layers'} onOpen={(o) => setMenu(o ? 'layers' : null)} toggles={toggles} setToggles={setToggles}
          floodMoment={floodMoment} setFloodMoment={setFloodMoment} />
      </div>

      {plan && (
        <div className="timeline-dock">
          <TideTimeline arrive={fromLocal(arriveLocal)} depart={plan.window.depart} leaveBefore={plan.timing?.leave_before} orAfter={plan.timing?.or_after}
            exitFloods={!!plan.timing} station={cfg.tide.station} source={cfg.tide}
            onChange={(iso) => { setArriveNow(false); setArrive(toLocal(iso)) }} />
        </div>
      )}

      {way && (
        <EvidencePanel way={way} at={wayAt} onClose={() => setWay(null)} onReview={reviewPhoto}
          google={cfg.flags.some((f) => f.name === 'google_lookup' && f.enabled)}
          grounding={cfg.flags.some((f) => f.name === 'ai_maps_grounding' && f.enabled)}
          onBlockage={() => api.blockage({ way_id: way.way_id, reason: 'Vật cản tạm thời (tài xế báo)' }).then(() => runRef.current())} />
      )}

      {pick && <PickMenu pick={pick} onClose={() => setPick(null)} onPick={pickAs} />}

      {arrived && plan && (
        <div className="arrive card" role="dialog" aria-label="Xác nhận sau khi đến">
          <button type="button" className="icon-btn close" aria-label="Đóng" onClick={() => setArrived(false)}><X size={16} /></button>
          <h3 className="display">Bạn đã tới nơi. Xe vào được không?</h3>
          <p className="muted">Câu trả lời của bạn trở thành bằng chứng “Đã quan sát” cho {vehicle?.label}, giúp người đi sau.</p>
          <div className="arrive-actions">
            {([['in', 'Vào được'], ['tight', 'Hơi chật'], ['no', 'Không vào được']] as const).map(([k, l]) => (
              <button key={k} type="button" className={`btn ${confirmed === k ? 'btn-primary' : 'btn-outline'}`} onClick={() => confirmArrival(k)}>{l}</button>
            ))}
          </div>
          {confirmed && <p className="ok-line">Đã ghi nhận. Cảm ơn bạn.</p>}
        </div>
      )}

      {vetcOpen && (
        <div className="scrim" onClick={() => setVetcOpen(false)}>
          <div className="modal card" role="dialog" aria-label="Liên kết VETC" onClick={(e) => e.stopPropagation()}>
            <span className="tag brand">Mô phỏng · chưa có API VETC</span>
            <h3 className="display">Ngõ Ngách muốn đọc thông tin xe trong VETC</h3>
            <p>Chỉ để tính xe có vừa hẻm và lội nước được không:</p>
            <ul><li>Danh sách xe (biển số đã che)</li><li>Mẫu xe và số chỗ</li></ul>
            <p className="faint">Không đọc vị trí hay lịch sử qua trạm. Theo Luật Bảo vệ dữ liệu cá nhân 91/2025, bạn có thể rút lại đồng ý bất cứ lúc nào.</p>
            <div className="modal-actions">
              <button type="button" className="btn btn-ghost" onClick={() => setVetcOpen(false)}>Huỷ</button>
              <button type="button" className="btn btn-primary" onClick={() => { setVetcLinked(true); setVMode('vetc'); setVetcOpen(false) }}>Đồng ý</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Welcome({ presets, loadPreset }: { presets: Preset[]; loadPreset: (p: Preset) => void }) {
  return (
    <div className="welcome">
      <h2 className="display">Xe của bạn vào được, và ra được, không?</h2>
      <p className="muted">Nhập điểm đến. Ngõ Ngách kiểm tra bề rộng hẻm theo đúng xe của bạn, triều và ngập trong lúc bạn ở lại, luật dừng đỗ, rồi chỉ chỗ dừng gần nhất kèm quãng đi bộ.</p>
      <div className="legend-row" aria-hidden>
        <span><i style={{ background: 'var(--fit-fits)' }} />Vừa xe</span>
        <span><i style={{ background: 'var(--fit-tight)' }} />Chật</span>
        <span><i style={{ background: 'var(--fit-no)' }} />Không vừa</span>
        <span><i className="dash" />Chưa rõ</span>
      </div>
      <h3 className="section-title">Thử nhanh</h3>
      <ul className="examples">
        {presets.map((p) => (
          <li key={p.id}><button type="button" onClick={() => loadPreset(p)}><MapPin size={16} /><span><b>{p.title}</b><small>{p.label}</small></span></button></li>
        ))}
      </ul>
      <p className="faint tip">Mẹo: nhấp chuột phải (hoặc nhấn giữ) trên bản đồ để đặt điểm đi, điểm đến.</p>
    </div>
  )
}

function SkeletonResult() {
  const [slow, setSlow] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setSlow((n) => n + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  return (
    <div className="skeleton" aria-label="Đang tính">
      {slow >= 3 && (
        <p className="loading-note" aria-live="polite">
          {slow < 12 ? 'Lần đầu tới khu vực này: đang tải bản đồ hẻm từ OpenStreetMap…' : `Máy chủ bản đồ đang chậm, vẫn đang tải (${slow} giây)…`}
        </p>
      )}
      <div className="skel" style={{ height: 14, width: '30%' }} />
      <div className="skel" style={{ height: 30, width: '85%' }} />
      <div className="skel" style={{ height: 14, width: '60%' }} />
      <div className="skel" style={{ height: 72, marginTop: 12 }} />
      <div className="skel" style={{ height: 72 }} />
    </div>
  )
}

function PickMenu({ pick, onClose, onPick }: { pick: { x: number; y: number }; onClose: () => void; onPick: (k: 'origin' | 'dest') => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useOutside(ref, true, onClose)
  return (
    <div className="pick card" ref={ref} style={{ left: pick.x, top: pick.y }} role="menu">
      <button type="button" role="menuitem" onClick={() => onPick('origin')}><span className="mk-origin static" />Đặt làm điểm đi</button>
      <button type="button" role="menuitem" onClick={() => onPick('dest')}><MapPin size={16} className="dest-ico" />Đặt làm điểm đến</button>
    </div>
  )
}

function LayersMenu({ open, onOpen, toggles, setToggles, floodMoment, setFloodMoment }: {
  open: boolean; onOpen: (o: boolean) => void; toggles: LayerToggles; setToggles: (t: LayerToggles) => void
  floodMoment: FloodMoment; setFloodMoment: (m: FloodMoment) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useOutside(ref, open, () => onOpen(false))
  const row = (k: keyof LayerToggles, label: string, sw: React.ReactNode) => (
    <label className="layer-row"><input type="checkbox" checked={toggles[k]} onChange={(e) => setToggles({ ...toggles, [k]: e.target.checked })} />{sw}<span>{label}</span></label>
  )
  return (
    <div className="tool" ref={ref}>
      <button type="button" className={`icon-btn raised ${open ? 'on' : ''}`} aria-label="Lớp bản đồ" aria-expanded={open} onClick={() => onOpen(!open)}><Layers size={19} /></button>
      {open && (
        <div className="popover pop-right layers" role="dialog" aria-label="Lớp bản đồ">
          <h4>Lớp bản đồ</h4>
          {row('fit', 'Độ vừa hẻm với xe của bạn', <span className="sw-fit" />)}
          <div className="fit-key"><span><i style={{ background: 'var(--fit-fits)' }} />Vừa</span><span><i style={{ background: 'var(--fit-tight)' }} />Chật</span><span><i style={{ background: 'var(--fit-no)' }} />Không vừa</span><span><i className="dash" />Chưa rõ</span><span><i style={{ background: 'var(--fit-blocked)' }} />Bị chặn</span></div>
          {row('flood', 'Ngập so với xe của bạn', <span className="sw-flood" />)}
          {toggles.flood && <Segmented label="Thời điểm ngập" value={floodMoment} onChange={setFloodMoment} options={[{ value: 'arrive', label: 'Lúc đến' }, { value: 'depart', label: 'Lúc về' }]} />}
          {row('goong', 'Tuyến Goong thông thường', <span className="sw-goong" />)}
          <div className="line-key"><span><i className="ln-route" />Đường đi</span><span><i className="ln-walk" />Đi bộ</span><span><i className="ln-out" />Đường ra</span></div>
        </div>
      )}
    </div>
  )
}

function DemoMenu({ open, onOpen, cfg, loadPreset, rainOn, setRainOn, rainMm, setRainMm, setFlag, canArrive, onArrive }: {
  open: boolean; onOpen: (o: boolean) => void; cfg: Config; loadPreset: (p: Preset) => void
  rainOn: boolean; setRainOn: (b: boolean) => void; rainMm: number; setRainMm: (n: number) => void
  setFlag: (f: Flag, on: boolean) => void; canArrive: boolean; onArrive: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useOutside(ref, open, () => onOpen(false))
  return (
    <div className="tool demo" ref={ref}>
      <button type="button" className={`btn btn-ghost btn-sm ${open ? 'on' : ''}`} aria-expanded={open} onClick={() => onOpen(!open)}><FlaskConical size={15} />Demo</button>
      {open && (
        <div className="popover pop-right demo-menu" role="dialog" aria-label="Công cụ demo">
          <h4>Kịch bản</h4>
          <ul className="examples compact">
            {cfg.presets.map((p) => <li key={p.id}><button type="button" onClick={() => loadPreset(p)}><MapPin size={14} /><span><b>{p.title}</b><small>{p.label}</small></span></button></li>)}
          </ul>
          <h4>Giả lập</h4>
          <label className="layer-row"><input type="checkbox" checked={rainOn} onChange={(e) => setRainOn(e.target.checked)} /><CloudRain size={15} /><span>Mưa {rainOn && `${rainMm} mm/h`}</span></label>
          {rainOn && <input type="range" min={10} max={90} step={5} value={rainMm} onChange={(e) => setRainMm(Number(e.target.value))} aria-label="Lượng mưa" />}
          <button type="button" className="btn btn-outline btn-sm" disabled={!canArrive} onClick={onArrive}><Navigation size={14} />Giả lập đã tới nơi</button>
          <h4><Sparkles size={13} /> Nguồn dữ liệu và AI</h4>
          <ul className="flags">
            {cfg.flags.map((f) => (
              <li key={f.name}><label className="layer-row"><input type="checkbox" checked={f.enabled} onChange={(e) => setFlag(f, e.target.checked)} /><span><b>{f.label}</b><small>{f.detail}</small></span></label></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
