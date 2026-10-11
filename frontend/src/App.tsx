import { CloudRain, FlaskConical, Layers, MapPin, Navigation, Sparkles, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, routeSourceLabel, type AreaBuild, type AreaData, type CameraInfo, type CameraReading, type Config, type Corridor, type Flag, type Intent, type Plan, type Preset, type RainSpell, type RouteSource, type Vehicle, type WayEvidence } from './api'
import { MapView, type FloodMoment, type LayerToggles } from './MapView'
import { ErrorBoundary } from './ErrorBoundary'
import { Directions, type Place, type VehicleMode } from './components/Directions'
import { StandardRouteContrast, LiveStrip, NewsList, StopRow, Verdict, exitFloodFailure } from './components/Result'
import { EvidencePanel } from './components/Evidence'
import { CameraPanel, CorridorCard } from './components/Corridor'
import { TideTimeline } from './components/TideTimeline'
import { Segmented, useOutside, vnt } from './ds/ui'

import { fromLocal, timestamp, toLocal } from './datetime'
const DEMO_ORIGIN: Place = { lat: 10.7725, lon: 106.698, label: 'Chợ Bến Thành, Quận 1' }
const isMobile = () => window.matchMedia('(max-width: 760px)').matches

export default function App() {
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
  const [arrive, setArrive] = useState(() => toLocal(new Date().toISOString())!)
  const [rainOn, setRainOn] = useState(false)
  const [rainMm, setRainMm] = useState(45)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planTripKey, setPlanTripKey] = useState('')
  const [selected, setSelected] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toggles, setToggles] = useState<LayerToggles>({ fit: true, flood: true, standard: false, cams: true })
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
  const [corridor, setCorridor] = useState<Corridor | null>(null)
  const [corridorBusy, setCorridorBusy] = useState(false)
  const [routeSel, setRouteSel] = useState(0)
  const [cams, setCams] = useState<CameraInfo[]>([])
  const [cam, setCam] = useState<CameraReading | null>(null)
  const corridorReq = useRef(0)
  const areaRef = useRef<AreaData | null>(null)
  const buildingKey = useRef('')
  const buildGen = useRef(0)  // bumped by parcel switches: a build started before the switch is stale
  const reqId = useRef(0)

  useEffect(() => {
    api.config().then(setCfg).catch((e) => setError(String(e)))
    api.vehicles().then(setFleet)
    api.cameras().then((r) => setCams(r.cameras)).catch(() => { /* the camera layer is optional */ })
    const t = window.setInterval(() => setNow(Date.now()), 60e3)
    return () => window.clearInterval(t)
  }, [])

  const vehicleId = vMode === 'class' ? classId : vMode === 'model' ? modelId : vetcLinked ? 'toyota-fortuner' : ''
  const vehicle = useMemo(() => [...fleet.classes, ...fleet.models].find((v) => v.id === vehicleId), [fleet, vehicleId])
  // "Đi ngay" = the next 5-minute mark, so the plan only refreshes when that mark moves.
  const arriveLocal = arriveNow ? toLocal(new Date(Math.ceil(now / 300e3) * 300e3).toISOString())! : arrive
  const arriveISO = fromLocal(arriveLocal)
  const rain: RainSpell[] = useMemo(() => {
    if (!rainOn || !arriveISO) return []
    const at = timestamp(arriveISO)
    if (at == null) return []
    const start = new Date(at + 30 * 60e3)
    return [{ start: start.toISOString(), end: new Date(start.getTime() + 3600e3).toISOString(), mm_per_h: rainMm }]
  }, [rainOn, rainMm, arriveISO])
  const tripKey = JSON.stringify([dest, origin, vehicleId, intent, arriveISO, intent === 'pickup' ? 15 : dwell, rain])

  // One plan per committed input; newer requests always win.
  const run = useCallback(async () => {
    if (!dest || !vehicleId) return
    if (!arriveISO) {
      setError('Giờ đến không hợp lệ. Chuyến đi chưa cập nhật; hãy chọn lại giờ đến.')
      return
    }
    const id = ++reqId.current
    setBusy(true)
    setError('')
    try {
      const r = await api.plan({
        lat: dest.lat, lon: dest.lon, label: dest.label, vehicle_id: vehicleId, intent,
        arrive_at: arriveISO, dwell_min: intent === 'pickup' ? 15 : dwell, rain,
        origin: origin ? [origin.lat, origin.lon] : null, area: areaRef.current,
      })
      if (id !== reqId.current) return
      setPlan(r)
      setPlanTripKey(tripKey)
      setSelected((s) => (s < r.stop_points.length ? s : 0))
      setFloodMoment(exitFloodFailure(r) ? 'depart' : 'arrive')
      if (r.live_crawl && areaRef.current?.key !== r.area_key && buildingKey.current !== r.area_key) startBuild(dest, r.area_key)
    } catch (e) {
      if (id === reqId.current) {
        const message = e instanceof Error ? e.message : String(e)
        if (e instanceof ApiError && e.status === 422) setError(`Chuyến đi chưa cập nhật: ${message}`)
        else { setError(message); setPlan(null) }
      }
    } finally {
      if (id === reqId.current) setBusy(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dest, origin, vehicleId, intent, dwell, arriveISO, rain, tripKey])
  const runRef = useRef(run)
  runRef.current = run

  useEffect(() => {
    const t = window.setTimeout(run, 220)
    return () => window.clearTimeout(t)
  }, [run])

  // Large-road route choice (cameras + flood forecast), separate from the plan because reading cameras takes ~30 s.
  useEffect(() => {
    if (!origin || !dest || !vehicleId || !arriveISO) { setCorridor(null); return }
    const id = ++corridorReq.current
    const t = window.setTimeout(async () => {
      setCorridorBusy(true)
      try {
        const c = await api.corridor({ origin: [origin.lat, origin.lon], destination: [dest.lat, dest.lon], vehicle_id: vehicleId,
          depart_at: arriveNow ? null : arriveISO, rain })
        if (id !== corridorReq.current) return
        setCorridor(c)
        setRouteSel(c.routes?.find((r) => r.chosen)?.id ?? 0)
        const seen = new Map(c.routes?.flatMap((r) => r.hotspots.flatMap((h) => h.cameras)).filter((x) => x.state !== 'not_read').map((x) => [x.id, x]))
        if (seen.size) setCams((cs) => cs.map((x) => (seen.has(x.id) ? { ...x, reading: seen.get(x.id)! } : x)))
      } catch {
        if (id === corridorReq.current) setCorridor(null)
      } finally {
        if (id === corridorReq.current) setCorridorBusy(false)
      }
    }, 400)
    return () => window.clearTimeout(t)
  }, [origin, dest, vehicleId, arriveNow, arriveISO, rain])

  function openCamera(id: string) {
    const c = cams.find((x) => x.id === id)
    if (c) setCam(c.reading ?? { id: c.id, name: c.name, lat: c.lat, lon: c.lon, image_url: `/api/cameras/${c.id}.jpg`, state: 'not_read' })
  }

  async function readCamera(id: string) {
    const r = await api.readCamera(id)
    setCam(r)
    setCams((cs) => cs.map((x) => (x.id === id ? { ...x, reading: r } : x)))
  }

  async function startBuild(d: Place, key: string) {
    buildingKey.current = key
    const gen = buildGen.current
    try {
      const a = await api.areaBuild(d.lat, d.lon, setBuild)
      if (a && gen === buildGen.current) { areaRef.current = a; runRef.current() }
    } catch (e) {
      setBuild({ key, state: 'error', error: e instanceof Error ? e.message : String(e) })
    } finally {
      buildingKey.current = ''
      if (gen !== buildGen.current) runRef.current()  // the settings changed mid-build: plan again, which rebuilds
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

  function loadPreset(p: Preset) {
    const local = toLocal(p.arrive_at)
    if (!local) {
      setError('Giờ đến trong kịch bản không hợp lệ. Chuyến đi chưa cập nhật.')
      return
    }
    const isClass = p.vehicle_id.startsWith('class-')
    setVMode(isClass ? 'class' : 'model')
    if (isClass) setClassId(p.vehicle_id)
    else setModelId(p.vehicle_id)
    setIntent(p.intent)
    setDwell(p.dwell_min)
    setArriveNow(false)
    setArrive(local)
    setRainOn((p.rain ?? []).length > 0)
    if (p.rain?.[0]) setRainMm(p.rain[0].mm_per_h)
    setOrigin((o) => o ?? DEMO_ORIGIN)
    setDest({ lat: p.lat, lon: p.lon, label: p.label })
    setStory(p.story)
    setMenu(null)
    setSheet('half')
  }

  function setDepartureAt(iso: string) {
    if (!plan || busy || planTripKey !== tripKey || plan.intent !== 'park' || intent !== 'park') return
    if (iso !== plan.timing?.leave_before_at && iso !== plan.timing?.or_after_at) return
    const a = timestamp(plan.window.arrive)
    const t = timestamp(iso)
    const local = toLocal(plan.window.arrive)
    if (a == null || t == null || !local || t <= a) return
    const duration = (t - a) / 60e3
    if (!Number.isInteger(duration)) {
      setError('Giờ rời không khớp thời lượng theo phút. Chuyến đi chưa cập nhật.')
      return
    }
    // Pin "now" to the evaluated arrival before changing dwell, including departures on another day.
    setArriveNow(false)
    setArrive(local)
    setDwell(duration)
  }

  async function openEvidence(id: number, lat: number, lon: number) {
    setCam(null)
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
    // Parcel widths are measured in the area build: re-run it so the switch takes effect here, not only in new areas.
    if (f.name === 'parcel_widths' || f.name === 'parcel_deep_scan') { buildGen.current++; areaRef.current = null; setBuild(null) }
    runRef.current()
  }

  async function confirmArrival(result: 'in' | 'tight' | 'no') {
    if (!plan || !vehicle) return
    const wid = plan.door?.way_id ?? plan.stop_points[0]?.way_id
    if (!wid) return
    await api.confirm({ lat: plan.destination.lat, lon: plan.destination.lon, vehicle_id: vehicle.id, result, way_ids: [wid] })
    setConfirmed(result)
  }

  const padding = isMobile() ? { top: 190, left: 24, right: 24, bottom: 320 } : { top: 60, left: 460, right: 80, bottom: 190 }

  if (!cfg) return <div className="boot">{error ? `Không kết nối được máy chủ: ${error}` : <span className="boot-mark display">Vào Được</span>}</div>

  const goongOn = cfg.goong.tiles
  return (
    <div className={`app ${way || cam ? 'has-evidence' : ''}`}>
      <ErrorBoundary label="Bản đồ">
        <MapView styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} origin={origin} destination={dest}
          toggles={toggles} floodMoment={floodMoment} padding={padding} frame={frame}
          corridor={corridor?.available ? corridor : null} routeSel={routeSel} cams={cams}
          onCameraClick={(id) => { setWay(null); openCamera(id) }}
          onPick={(lat, lon, x, y) => setPick({ lat, lon, x, y })}
          onWayClick={openEvidence}
          onStopClick={(i) => {
            setSelected(i)
            setSheet((s) => (s === 'peek' ? 'half' : s))
            // A pin can select a stop that is scrolled out of the list: bring its card (header, evidence link) into view.
            requestAnimationFrame(() => document.querySelectorAll('.stop')[i]?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
          }} />
      </ErrorBoundary>

      <div className="side">
        <section className="card top">
          <header className="brand">
            <span className="logo" aria-hidden>VĐ</span>
            <span className="brand-name display">Vào Được</span>
            <span className="brand-sub">lớp hẻm cho T-Maps</span>
            <DemoMenu open={menu === 'demo'} onOpen={(o) => setMenu(o ? 'demo' : null)} cfg={cfg} loadPreset={loadPreset}
              rainOn={rainOn} setRainOn={setRainOn} rainMm={rainMm} setRainMm={setRainMm} setFlag={setFlag}
              canArrive={!!plan} onArrive={() => { setArrived(true); setConfirmed(''); setMenu(null) }} />
          </header>
          <Directions origin={origin} dest={dest} setOrigin={setOrigin} setDest={chooseDest} locating={locating} onLocate={locate}
            vehicle={vehicle} fleet={fleet} vMode={vMode} setVMode={setVMode} classId={classId} setClassId={setClassId}
            modelId={modelId} setModelId={setModelId} vetcLinked={vetcLinked} openVetc={() => setVetcOpen(true)} unlinkVetc={() => setVetcLinked(false)}
            intent={intent} setIntent={setIntent} dwell={dwell} setDwell={setDwell}
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
                <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Kết quả chuyến đi">
                {story && <p className="story">{story}</p>}
                <Verdict plan={plan} onDeparture={setDepartureAt} stale={busy || planTripKey !== tripKey} />
                {origin && <CorridorCard corridor={corridor} busy={corridorBusy} selected={routeSel}
                  onSelect={(i) => { setRouteSel(i); setFrame('trip') }} onCamera={(c) => { setWay(null); setCam(c) }} />}
                {build && <LiveStrip build={build} />}
                {areaRef.current?.key === plan.area_key && <NewsList items={areaRef.current.news ?? []} />}
                <h3 className="section-title">Chỗ {plan.intent === 'park' ? 'đỗ' : 'dừng'} gợi ý</h3>
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
                {vehicle && <StandardRouteContrast plan={plan} vehicleLabel={vehicle.label} show={toggles.standard} onToggle={() => setToggles((t) => ({ ...t, standard: !t.standard }))} />}
                <p className="sources faint">Nguồn: {goongOn ? 'Goong (bản đồ nền)' : 'bản đồ nền tạm'}, OpenStreetMap{plan.standard_route ? `, tuyến tham chiếu ${routeSourceLabel(plan.standard_route.source)}` : ''}, IRD 2002–2026, Đài KTTV Nam Bộ, VETC, Chợ Tốt, camera giao thông TP.HCM.</p>
                </ErrorBoundary>
              </>
            )}
          </div>
        </section>
      </div>

      {plan && ((plan.origin && plan.stop_points[selected]?.approach) || corridor?.available) && (
        <div className="frame-toggle">
          <Segmented label="Khung bản đồ" value={frame} onChange={setFrame}
            options={[{ value: 'arrival', label: 'Đoạn cuối' }, { value: 'trip', label: 'Cả tuyến' }]} />
        </div>
      )}
      <div className="map-tools">
        <LayersMenu open={menu === 'layers'} onOpen={(o) => setMenu(o ? 'layers' : null)} toggles={toggles} setToggles={setToggles}
          floodMoment={floodMoment} setFloodMoment={setFloodMoment} standardSource={plan?.standard_route?.source ?? null} />
      </div>

      {plan && (
        <div className="timeline-dock">
          <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Biểu đồ triều">
            <TideTimeline arrive={plan.window.arrive} depart={plan.window.depart} leaveBeforeAt={plan.timing?.leave_before_at} orAfterAt={plan.intent === 'park' ? plan.timing?.or_after_at : null}
              timingReason={plan.timing?.reason} timingApproximate={plan.timing?.approximate} exitFloods={exitFloodFailure(plan)} station={cfg.tide.station} rain={plan.window.rain}
              onChange={(iso) => { const local = toLocal(iso); if (local) { setArriveNow(false); setArrive(local) } }} />
          </ErrorBoundary>
        </div>
      )}

      {cam && !way && (
        <CameraPanel key={cam.id} cam={cam} canRead={cfg.flags.some((f) => f.name === 'ai_camera_flood' && f.enabled)}
          onClose={() => setCam(null)} onRead={readCamera} />
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
            <h3 className="display">Vào Được muốn đọc thông tin xe trong VETC</h3>
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
      <p className="muted">Nhập điểm đến. Vào Được kiểm tra bề rộng hẻm theo đúng xe của bạn, triều và ngập trong lúc bạn ở lại, luật dừng đỗ, rồi chỉ chỗ dừng gần nhất kèm quãng đi bộ.</p>
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

function LayersMenu({ open, onOpen, toggles, setToggles, floodMoment, setFloodMoment, standardSource }: {
  open: boolean; onOpen: (o: boolean) => void; toggles: LayerToggles; setToggles: (t: LayerToggles) => void
  floodMoment: FloodMoment; setFloodMoment: (m: FloodMoment) => void; standardSource: RouteSource | null
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
          {row('standard', standardSource ? `Tuyến tham chiếu ${routeSourceLabel(standardSource)}` : 'Tuyến tham chiếu (chưa có dữ liệu)', <span className="sw-standard" />)}
          {row('cams', 'Camera giao thông (AI đọc kẹt xe, ngập)', <span className="sw-cam" />)}
          {toggles.cams && <div className="fit-key"><span><i style={{ background: 'var(--fit-fits)' }} />Thông thoáng</span><span><i style={{ background: 'var(--traffic-busy)' }} />Đông</span><span><i style={{ background: 'var(--fit-tight)' }} />Ùn ứ</span><span><i style={{ background: 'var(--fit-no)' }} />Kẹt cứng</span><span><i style={{ background: 'var(--flood-risky)' }} />Ngập</span><span><i style={{ background: 'var(--fit-unknown)' }} />Chưa đọc</span></div>}
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
          <label className="layer-row"><input type="checkbox" checked={rainOn} onChange={(e) => setRainOn(e.target.checked)} /><CloudRain size={15} /><span>Mưa giả định {rainOn ? `${rainMm} mm/h` : '(tắt: dùng mưa đo)'}</span></label>
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
