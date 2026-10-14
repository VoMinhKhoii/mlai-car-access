import { CloudRain, FlaskConical, Layers, LogIn, LogOut, MapPin, Navigation, Sparkles, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, poll, routeSourceLabel, type AreaBuild, type CameraInfo, type CameraReading, type Config, type Corridor, type Flag, type Intent, type ManeuverState, type Plan, type Preset, type RainSpell, type Report, type RouteSource, type Vehicle, type WayEvidence } from './api'
import { MapView, type FloodMoment, type LayerToggles, type ManeuverOverlay } from './MapView'
import { ErrorBoundary } from './ErrorBoundary'
import { Directions, type Place, type VehicleMode } from './components/Directions'
import { StandardRouteContrast, LiveStrip, NewsList, StopRow, Verdict, exitFloodFailure } from './components/Result'
import { VoiceReport } from './components/VoiceReport'
import { useParkingWatch } from './parkingWatch'
import { EvidencePanel } from './components/Evidence'
import { CameraPanel, CorridorCard } from './components/Corridor'
import { TideTimeline } from './components/TideTimeline'
import { Segmented, metres, useOutside, vnt } from './ds/ui'

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
  const [stopOpen, setStopOpen] = useState(false)
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
  const [sheet, setSheet] = useState<'peek' | 'half' | 'full'>('half')
  const [locating, setLocating] = useState(false)
  const [frame, setFrame] = useState<'arrival' | 'trip'>('arrival')
  const [now, setNow] = useState(() => Date.now())
  const [corridor, setCorridor] = useState<Corridor | null>(null)
  const [corridorBusy, setCorridorBusy] = useState(false)
  const [routeSel, setRouteSel] = useState(0)
  const [cams, setCams] = useState<CameraInfo[]>([])
  const [maneuver, setManeuver] = useState<ManeuverState | null>(null)
  const [cam, setCam] = useState<CameraReading | null>(null)
  const [notice, setNotice] = useState('')
  const planCtl = useRef<AbortController | null>(null)
  const buildCtl = useRef<AbortController | null>(null)
  const camCtl = useRef<AbortController | null>(null)
  const maneuverCtl = useRef<AbortController | null>(null)
  const maneuverKeyRef = useRef('')
  const reqId = useRef(0)
  const operator = cfg?.operator.signed_in ?? false
  const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

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
  const activePlanRequest = useMemo(() => dest && vehicleId ? ({
    lat: dest.lat, lon: dest.lon, label: dest.label, vehicle_id: vehicleId, intent,
    arrive_at: arriveISO, dwell_min: intent === 'pickup' ? 15 : dwell, rain,
    origin: origin ? [origin.lat, origin.lon] as [number, number] : null,
  }) : null, [dest, vehicleId, intent, arriveISO, dwell, rain, origin])
  const tripKey = JSON.stringify([dest, origin, vehicleId, intent, arriveISO, intent === 'pickup' ? 15 : dwell, rain])
  const activeManeuverKey = `${tripKey}:${selected}:${vehicleId}`
  useEffect(() => {
    if (maneuver?.key === activeManeuverKey) return
    maneuverCtl.current?.abort()
    maneuverCtl.current = null
    maneuverKeyRef.current = ''
    setManeuver(null)
  }, [activeManeuverKey, maneuver])

  function closeManeuver() {
    maneuverCtl.current?.abort()
    maneuverCtl.current = null
    maneuverKeyRef.current = ''
    setManeuver(null)
  }

  async function openManeuver(index: number, stop: Plan['stop_points'][number]) {
    if (!plan || planTripKey !== tripKey || busy || !vehicleId) return
    const key = `${tripKey}:${index}:${vehicleId}`
    if (maneuver?.key === key && maneuver.status !== 'error') {
      closeManeuver()
      return
    }
    maneuverCtl.current?.abort()
    maneuverKeyRef.current = key
    setSelected(index)
    setManeuver({ key, status: 'loading', playback: 0 })
    const width = stop.fit.width_range?.lo
    if (width == null || !Number.isFinite(width) || width <= 0) {
      setManeuver({ key, status: 'unavailable', playback: 0, reason: 'missing-width' })
      return
    }
    if (width < 1.5 || width > 15) {
      setManeuver({ key, status: 'unavailable', playback: 0, reason: 'out-of-range' })
      return
    }
    const ctl = new AbortController()
    maneuverCtl.current = ctl
    try {
      const result = await api.maneuver(vehicleId, width, ctl.signal)
      if (ctl.signal.aborted || maneuverKeyRef.current !== key) return
      const validPoses = Array.isArray(result.poses) && result.poses.length > 0
        && result.poses.length <= 120
        && result.poses.every((pose) => Array.isArray(pose) && pose.length === 3
          && pose.every((value) => Number.isFinite(value)))
      if (result.frame !== 'corridor' || result.vehicle_id !== vehicleId || (result.poses != null && !validPoses)) {
        setManeuver({ key, status: 'error', playback: 0, error: 'Dữ liệu mô phỏng không đúng định dạng.' })
        return
      }
      setManeuver({ key, status: 'ready', playback: 0, result })
    } catch (e) {
      if (ctl.signal.aborted || maneuverKeyRef.current !== key) return
      setManeuver({ key, status: 'error', playback: 0, error: e instanceof Error ? e.message : String(e) })
    }
  }

  function replayManeuver() {
    setManeuver((state) => state?.status === 'ready'
      ? { ...state, playback: state.playback + 1 }
      : state)
  }

  const selectedStop = plan?.stop_points[selected]
  const watch = useParkingWatch({
    request: activePlanRequest, plan, selectedIndex: selected, enabled: !!plan && planTripKey === tripKey && !busy && intent === 'park',
    demo: new URLSearchParams(window.location.search).get('demo') === '1',
  })
  const activeManeuver = maneuver?.key === activeManeuverKey ? maneuver : null
  const activeManeuverResult = activeManeuver?.status === 'ready' ? activeManeuver.result : null
  const maneuverOverlay = useMemo<ManeuverOverlay | null>(() => activeManeuver && selectedStop && plan ? {
    state: activeManeuver,
    stop: { lat: selectedStop.lat, lon: selectedStop.lon },
    widthLo: selectedStop.fit.width_range?.lo ?? null,
    widthHi: selectedStop.fit.width_range?.hi ?? null,
    decisive: !!selectedStop.fit.width_range?.decisive_clearance
      && (selectedStop.fit.width_range?.evidence.length ?? 0) > 0,
    mirrorWidth: activeManeuverResult?.vehicle_mirror_width_m ?? plan.vehicle.mirror_width,
    vehicleLength: activeManeuverResult?.vehicle_length_m ?? plan.vehicle.length,
    bodyCenterOffset: activeManeuverResult?.body_center_offset_m ?? 0,
    corridorWidth: activeManeuverResult?.width_m ?? selectedStop.fit.width_range?.lo ?? 0,
    axis: selectedStop.route_in?.geometry ?? [],
  } : null, [activeManeuver, activeManeuverResult, selectedStop, plan])

  // One plan per committed input; a newer request aborts the older one, so an old answer can never undo a new trip.
  const run = useCallback(async () => {
    if (!dest || !vehicleId) return
    if (!arriveISO) {
      setError('Giờ đến không hợp lệ. Chuyến đi chưa cập nhật; hãy chọn lại giờ đến.')
      return
    }
    planCtl.current?.abort()
    const ctl = new AbortController()
    planCtl.current = ctl
    const id = ++reqId.current
    setBusy(true)
    setError('')
    try {
      const r = await api.plan(activePlanRequest!, ctl.signal)
      if (id !== reqId.current) return
      maneuverCtl.current?.abort()
      maneuverCtl.current = null
      maneuverKeyRef.current = ''
      setManeuver(null)
      setStopOpen(false)
      setPlan(r)
      setPlanTripKey(tripKey)
      setSelected((s) => (s < r.stop_points.length ? s : 0))
      setFloodMoment(exitFloodFailure(r) ? 'depart' : 'arrive')
    } catch (e) {
      if (isAbort(e) || id !== reqId.current) return
      const message = e instanceof Error ? e.message : String(e)
      if (e instanceof ApiError && e.status === 422) setError(`Chuyến đi chưa cập nhật: ${message}`)
      else { setError(message); setPlan(null) }
    } finally {
      if (id === reqId.current) setBusy(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlanRequest, tripKey])
  const runRef = useRef(run)
  runRef.current = run

  useEffect(() => {
    const t = window.setTimeout(run, 220)
    return () => window.clearTimeout(t)
  }, [run])
  useEffect(() => () => { planCtl.current?.abort(); buildCtl.current?.abort(); camCtl.current?.abort(); maneuverCtl.current?.abort() }, [])

  // Large-road route choice: answered at once from the forecast and cached camera readings. When the backend queued
  // a camera job (operator only), watch it and ask again once it is ready. Any input change aborts all of this.
  useEffect(() => {
    if (!origin || !dest || !vehicleId || !arriveISO) { setCorridor(null); return }
    const ctl = new AbortController()
    const body = { origin: [origin.lat, origin.lon], destination: [dest.lat, dest.lon], vehicle_id: vehicleId,
      depart_at: arriveNow ? null : arriveISO, rain }
    const show = (c: Corridor) => {
      setCorridor(c)
      setRouteSel(c.routes?.find((r) => r.chosen)?.id ?? 0)
      const seen = new Map(c.routes?.flatMap((r) => r.hotspots.flatMap((h) => h.cameras)).filter((x) => x.state !== 'not_read').map((x) => [x.id, x]))
      if (seen.size) setCams((cs) => cs.map((x) => (seen.has(x.id) ? { ...x, reading: seen.get(x.id)! } : x)))
    }
    const t = window.setTimeout(async () => {
      setCorridorBusy(true)
      try {
        const c = await api.corridor(body, ctl.signal)
        show(c)
        const jid = c.camera_job?.id
        if (jid) {
          const job = await poll((s) => api.cameraJob(jid, s), (j) => !['queued', 'running'].includes(j.state), ctl.signal, () => {})
          if (job && job.state === 'ready') show(await api.corridor(body, ctl.signal))
        }
      } catch (e) {
        if (!isAbort(e)) setCorridor(null)
      } finally {
        if (!ctl.signal.aborted) setCorridorBusy(false)
      }
    }, 400)
    return () => { window.clearTimeout(t); ctl.abort() }
  }, [origin, dest, vehicleId, arriveNow, arriveISO, rain])

  function openCamera(id: string) {
    const c = cams.find((x) => x.id === id)
    if (c) setCam(c.reading ?? { id: c.id, name: c.name, lat: c.lat, lon: c.lon, image_url: `/api/cameras/${c.id}.jpg`, state: 'not_read' })
  }

  async function readCamera(id: string) {
    camCtl.current?.abort()
    const ctl = new AbortController()
    camCtl.current = ctl
    try {
      const r = await api.readCamera(id)
      let reading = r.reading
      if (!reading && r.job) {
        const job = await poll((s) => api.cameraJob(r.job!.id, s), (j) => !['queued', 'running'].includes(j.state), ctl.signal, () => {})
        reading = job?.readings.find((x) => x.id === id) ?? null
      }
      if (ctl.signal.aborted) return
      if (reading) {
        setCam(reading)
        setCams((cs) => cs.map((x) => (x.id === id ? { ...x, reading } : x)))
      } else setNotice('Chưa đọc được camera này; kết quả vẫn là “chưa rõ”, không phải đường thông.')
    } catch (e) {
      if (!isAbort(e)) setNotice(e instanceof Error ? e.message : String(e))
    }
  }

  // Live Area Build (operator): the server runs it; the page only watches the job and re-plans when it is published.
  const watchBuild = useCallback(async (key: string, first?: AreaBuild) => {
    buildCtl.current?.abort()
    const ctl = new AbortController()
    buildCtl.current = ctl
    if (first) setBuild(first)
    try {
      const job = await poll((s) => api.areaJob(key, s), (j) => j.state === 'done' || j.state === 'error', ctl.signal,
        (j) => { if (!ctl.signal.aborted) setBuild(j) }, 2000, 330_000)
      if (job?.state === 'done' && !ctl.signal.aborted) runRef.current()
    } catch (e) {
      if (!isAbort(e)) setBuild((b) => (b ? { ...b, state: 'error', error: e instanceof Error ? e.message : String(e) } : b))
    }
  }, [])

  async function startBuild() {
    if (!plan) return
    try {
      const job = await api.areaBuild(plan.destination.lat, plan.destination.lon)
      watchBuild(job.key, job)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? 'Cần đăng nhập điều hành để thu thập dữ liệu.' : e instanceof Error ? e.message : String(e))
    }
  }

  // A build already running on the server (started by any operator) is watched again after a reload.
  useEffect(() => {
    if (operator && plan?.area.building) watchBuild(plan.area.key)
  }, [operator, plan?.area.building, plan?.area.key, watchBuild])

  function chooseDest(p: Place | null) {
    buildCtl.current?.abort()
    setDest(p)
    setStory('')
    setWay(null)
    setBuild(null)
    if (!p) { planCtl.current?.abort(); setPlan(null) }
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
    try { setWay(await api.wayEvidence(id, lat, lon)) } catch { setWay(null) }
  }

  async function reviewPhoto(id: string, approve: boolean) {
    try {
      await api.reviewPhoto(id, approve)
      if (way) setWay(await api.wayEvidence(way.way_id, wayAt[0], wayAt[1]))
      runRef.current()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    }
  }

  async function setFlag(f: Flag, on: boolean) {
    try {
      const r = await api.setFlag(f.name, on)
      setCfg((c) => (c ? { ...c, flags: r.flags } : c))
      runRef.current()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))  // the switch keeps its real state
    }
  }

  async function login(secret: string) {
    await api.operatorLogin(secret)
    setCfg(await api.config())
  }

  async function logout() {
    await api.operatorLogout().catch(() => {})
    setCfg(await api.config())
  }

  async function confirmArrival(result: 'in' | 'tight' | 'no', exit: 'through' | 'turned' | 'reversed' | 'unknown') {
    if (!plan || !selectedStop || selectedStop.kind === 'lot' || selectedStop.way_id == null) {
      throw new Error('Chỉ gửi xác nhận từ điểm dừng được ánh xạ lên đường; bãi đỗ không tạo bằng chứng hẻm.')
    }
    await api.confirm({
      stop_lat: selectedStop.lat, stop_lon: selectedStop.lon, vehicle_id: plan.vehicle.id, result, exit,
    })
  }

  async function reportBlockage(reason: string) {
    if (!plan || !selectedStop || selectedStop.way_id == null) throw new Error('Điểm dừng này chưa có mã đường để gửi báo cáo vật cản.')
    await api.blockage({
      lat: plan.destination.lat, lon: plan.destination.lon, way_id: selectedStop.way_id, reason,
    })
  }

  const padding = isMobile() ? { top: 190, left: 24, right: 24, bottom: 320 } : { top: 60, left: 460, right: 80, bottom: 190 }

  if (!cfg) return <div className="boot">{error ? `Không kết nối được máy chủ: ${error}` : <span className="boot-mark display">Vào Được</span>}</div>

  const goongOn = cfg.goong.tiles
  return (
    <div className={`app ${way || cam ? 'has-evidence' : ''}`}>
      <ErrorBoundary label="Bản đồ">
        <MapView styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} origin={origin} destination={dest}
          toggles={toggles} floodMoment={floodMoment} padding={padding} frame={frame}
          corridor={corridor?.available ? corridor : null} routeSel={routeSel} cams={cams} maneuver={maneuverOverlay}
          onCameraClick={(id) => { setWay(null); openCamera(id) }}
          onPick={(lat, lon, x, y) => setPick({ lat, lon, x, y })}
          onWayClick={openEvidence}
          onStopClick={(i) => {
            setSelected(i)
            setStopOpen(false)
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
              canArrive={!!plan} onArrive={() => { setArrived(true); setMenu(null) }}
              onLogin={login} onLogout={logout} onApproved={() => runRef.current()} />
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
            {notice && <p className="error-line" role="status" onClick={() => setNotice('')}>{notice}</p>}
            {!dest && <Welcome presets={cfg.presets} loadPreset={loadPreset} />}
            {dest && !plan && busy && <SkeletonResult />}
            {plan && (
              <>
                <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Kết quả chuyến đi">
                {story && <details className="why scenario-note"><summary>Kịch bản demo</summary><p>{story}</p></details>}
                <Verdict plan={plan} onDeparture={setDepartureAt} stale={busy || planTripKey !== tripKey} />
                {origin && <CorridorCard corridor={corridor} busy={corridorBusy} selected={routeSel}
                  onSelect={(i) => { setRouteSel(i); setFrame('trip') }} onCamera={(c) => { setWay(null); setCam(c) }} />}
                {plan.live_crawl && <AreaStatusLine plan={plan} build={build} operator={operator} onBuild={startBuild} />}
                {build && <LiveStrip build={build} />}
                {plan.area_data && <NewsList items={plan.area_data.news} />}
                <h3 className="section-title">Chỗ {plan.intent === 'park' ? 'đỗ' : 'dừng'} gợi ý</h3>
                <div className="stops">
                  {plan.stop_points.map((s, i) => (
                    <StopRow key={`${s.lat},${s.lon}`} s={s} plan={plan} index={i} selected={i === selected} open={i === selected && stopOpen}
                      maneuver={i === selected ? activeManeuver : null}
                      onSelect={() => { if (i === selected) setStopOpen((o) => !o); else { setSelected(i); setStopOpen(false) } }}
                      onEvidence={(id) => openEvidence(id, s.lat, s.lon)}
                      onManeuver={() => void openManeuver(i, s)} maneuverDisabled={busy || planTripKey !== tripKey || !vehicleId}
                      onReplay={replayManeuver} onDismiss={closeManeuver} />
                  ))}
                  {!plan.stop_points.length && <p className="muted">{plan.verdict.detail}</p>}
                </div>
                {(watch.active || (plan.intent === 'park' && selectedStop)) && (
                  <section className="parking-watch" aria-label="Theo dõi điểm đỗ">
                    <div className="watch-heading">
                      <div><strong>{watch.active ? 'Đang theo dõi điểm đỗ' : 'Theo dõi điểm đỗ'}</strong>
                        <small>{watch.active ? watch.session?.stopName : 'Kiểm tra lại khi thẻ đang mở'}</small></div>
                      {watch.active
                        ? <button type="button" className="btn btn-ghost btn-sm" onClick={watch.end}>Kết thúc</button>
                        : <button type="button" className="btn btn-outline btn-sm" disabled={!watch.canStart} onClick={() => watch.start()}>Bắt đầu</button>}
                    </div>
                    <small>Thông báo là tùy chọn; cảnh báo vẫn hiện khi thẻ còn mở.</small>
                    {watch.active && !watch.contextMatches && <small>Theo dõi vẫn gắn với chuyến đã lưu, không phải lựa chọn hiện tại.</small>}
                    {watch.active && <div className="watch-meta">
                      <span>{watch.checking ? 'Đang kiểm tra…' : watch.lastCheckLabel ? `Kiểm tra lúc ${watch.lastCheckLabel}` : 'Chưa có lần kiểm tra thành công'}</span>
                      <button type="button" className="link-btn" onClick={() => void watch.check()} disabled={watch.checking}>Kiểm tra ngay</button>
                      {'Notification' in window && Notification.permission !== 'granted' && (
                        <button type="button" className="link-btn" onClick={async () => {
                          try {
                            const permission = await watch.requestNotifications()
                            setNotice(permission === 'granted'
                              ? 'Đã bật thông báo trên thiết bị.'
                              : 'Thông báo không được bật. Cảnh báo vẫn hiện trong ứng dụng khi thẻ đang mở.')
                          } catch {
                            setNotice('Không bật được thông báo. Cảnh báo vẫn hiện trong ứng dụng khi thẻ đang mở.')
                          }
                        }}>Bật thông báo</button>
                      )}
                    </div>}
                    {!watch.active && selectedStop && !selectedStop.verified
                      && <small>Điểm dừng chưa xác minh; theo dõi không xác nhận xe vào hoặc ra được.</small>}
                    {watch.error && <p className="watch-error" role="status">
                      Lỗi kiểm tra{watch.lastCheckLabel ? ` · lần gần nhất ${watch.lastCheckLabel}` : ''}: {watch.error}
                    </p>}
                    {watch.banner && <p className="watch-alert" role="alert">{watch.banner}
                      <button type="button" className="link-btn" onClick={watch.clearBanner}>Đóng</button>
                    </p>}
                  </section>
                )}
                {plan.door && !plan.door.ok && (
                  <details className="why">
                    <summary>Vì sao không vào tận cửa?</summary>
                    <ul>{plan.door.fail_reasons.map((r, i) => <li key={i}>{vnt(r)}</li>)}</ul>
                  </details>
                )}
                {vehicle && <StandardRouteContrast plan={plan} vehicleLabel={vehicle.label} show={toggles.standard} onToggle={() => setToggles((t) => ({ ...t, standard: !t.standard }))} />}
                <details className="why sources"><summary>Nguồn dữ liệu</summary><p>{goongOn ? 'Goong (bản đồ nền)' : 'bản đồ nền tạm'}, OpenStreetMap{plan.standard_route ? `, tuyến tham chiếu ${routeSourceLabel(plan.standard_route.source)}` : ''}, IRD 2002–2026, Đài KTTV Nam Bộ, VETC, Chợ Tốt, camera giao thông TP.HCM.</p></details>
                </ErrorBoundary>
              </>
            )}
            {watch.active && !plan && <section className="parking-watch" aria-label="Theo dõi điểm đỗ">
              <div className="watch-heading">
                <div><strong>Đang theo dõi điểm đỗ</strong><small>{watch.session?.stopName}</small></div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={watch.end}>Kết thúc</button>
              </div>
              <p className="watch-error">{watch.error
                ? `Lỗi kiểm tra${watch.lastCheckLabel ? ` · lần gần nhất ${watch.lastCheckLabel}` : ''}: ${watch.error}`
                : watch.banner || 'Theo dõi bằng cách kiểm tra lại khi thẻ đang mở.'}</p>
            </section>}
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
        <CameraPanel key={cam.id} cam={cam} canRead={operator && cfg.flags.some((f) => f.name === 'ai_camera_flood' && f.enabled)}
          onClose={() => setCam(null)} onRead={readCamera} />
      )}

      {way && (
        <EvidencePanel way={way} at={wayAt} onClose={() => setWay(null)} onReview={reviewPhoto} canReview={operator}
          google={operator && cfg.flags.some((f) => f.name === 'google_lookup' && f.enabled)}
          grounding={operator && cfg.flags.some((f) => f.name === 'ai_maps_grounding' && f.enabled)}
          onBlockage={() => api.blockage({ lat: wayAt[0], lon: wayAt[1], way_id: way.way_id, reason: 'Vật cản tạm thời (tài xế báo)' })
            .then(() => setNotice('Đã gửi báo cáo vật cản. Báo cáo chờ người điều hành duyệt trước khi ảnh hưởng tới kế hoạch.'))
            .catch((e) => setNotice(e instanceof Error ? e.message : String(e)))} />
      )}

      {pick && <PickMenu pick={pick} onClose={() => setPick(null)} onPick={pickAs} />}

      {arrived && plan && selectedStop && !busy && planTripKey === tripKey && (
        <div className="arrive card" role="dialog" aria-label="Báo cáo sau khi đến">
          <button type="button" className="icon-btn close" aria-label="Đóng" onClick={() => setArrived(false)}><X size={16} /></button>
          <h3 className="display">Bạn đã tới điểm dừng?</h3>
          <p className="muted">Báo cáo chỉ trở thành bằng chứng sau khi người điều hành duyệt. Không làm thay đổi kết luận phù hợp hay an toàn.</p>
          {selectedStop.kind === 'lot' || selectedStop.way_id == null
            ? <p className="muted" role="status">Bãi đỗ không xác nhận xe đã vào hẻm. Chọn một điểm dừng trên đường để gửi báo cáo.</p>
            : <VoiceReport stop={selectedStop} vehicleId={plan.vehicle.id} destination={plan.destination}
              voiceEnabled={cfg.flags.some((flag) => flag.name === 'ai_voice_report' && flag.enabled)}
              onConfirm={confirmArrival} onBlockage={reportBlockage} />}
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

function DemoMenu({ open, onOpen, cfg, loadPreset, rainOn, setRainOn, rainMm, setRainMm, setFlag, canArrive, onArrive, onLogin, onLogout, onApproved }: {
  open: boolean; onOpen: (o: boolean) => void; cfg: Config; loadPreset: (p: Preset) => void
  rainOn: boolean; setRainOn: (b: boolean) => void; rainMm: number; setRainMm: (n: number) => void
  setFlag: (f: Flag, on: boolean) => void; canArrive: boolean; onArrive: () => void
  onLogin: (secret: string) => Promise<void>; onLogout: () => Promise<void>; onApproved: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [secret, setSecret] = useState('')
  const [loginError, setLoginError] = useState('')
  useOutside(ref, open, () => onOpen(false))
  const op = cfg.operator.signed_in
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
          <h4>Điều hành</h4>
          {!cfg.operator.available ? (
            <p className="faint">Chức năng điều hành chưa bật trên máy chủ này.</p>
          ) : op ? (
            <div className="operator-row">
              <span>Đang đăng nhập điều hành</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout}><LogOut size={14} />Đăng xuất</button>
            </div>
          ) : (
            <form className="operator-row" onSubmit={async (e) => {
              e.preventDefault()
              setLoginError('')
              try { await onLogin(secret); setSecret('') } catch (err) { setLoginError(err instanceof Error ? err.message : String(err)) }
            }}>
              <input type="password" autoComplete="current-password" aria-label="Mật khẩu điều hành" placeholder="Mật khẩu điều hành"
                value={secret} onChange={(e) => setSecret(e.target.value)} />
              <button type="submit" className="btn btn-outline btn-sm" disabled={!secret}><LogIn size={14} />Đăng nhập</button>
              {loginError && <small className="error-line">{loginError}</small>}
            </form>
          )}
          {op && <ReportQueue onApproved={onApproved} />}
          <h4><Sparkles size={13} /> Nguồn dữ liệu và AI</h4>
          {!op && <p className="faint">Chỉ người điều hành mới bật/tắt được.</p>}
          <ul className="flags">
            {cfg.flags.map((f) => (
              <li key={f.name}><label className="layer-row"><input type="checkbox" checked={f.enabled} disabled={!op} onChange={(e) => setFlag(f, e.target.checked)} /><span><b>{f.label}</b><small>{f.detail}</small></span></label></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

const REPORT_KIND: Record<Report['type'], string> = {
  confirmation: 'Xác nhận sau khi đến', blockage: 'Vật cản tạm thời', flood_report: 'Báo ngập',
  stop_rule: 'Quy định dừng/đỗ', photo_reading: 'AI đọc ảnh',
}

function reportSummary(r: Report): string {
  const p = r.payload
  if (r.type === 'confirmation') {
    const result = ({ in: 'vào được', tight: 'chật', no: 'không vào được' } as Record<string, string>)[String(p.result)] ?? String(p.result)
    const exit = ({ through: 'đi thẳng ra', turned: 'quay đầu ra', reversed: 'lùi ra', unknown: 'chưa rõ cách ra' } as Record<string, string>)[String(p.exit)] ?? 'chưa rõ cách ra'
    const ingress = Array.isArray(p.way_ids) ? p.way_ids.join(', ') : 'không rõ'
    const egress = Array.isArray(p.way_out_ids)
      ? `${p.way_out_ids.slice(0, 4).join(', ')}${p.way_out_ids.length > 4 ? `, +${p.way_out_ids.length - 4}` : ''}`
      : 'không rõ'
    const body = Number(p.body_width)
    const mirror = Number(p.mirror_width)
    const widthImpact = Number.isFinite(body)
      ? result === 'vào được' ? `cận dưới ≥ ${metres(body + 0.2, 2)}`
        : result === 'chật' && Number.isFinite(mirror)
          ? `${metres(body + 0.1, 2)}–${metres(mirror + 0.8, 2)}`
          : result === 'không vào được' && Number.isFinite(mirror) ? `cận trên ≤ ${metres(mirror + 0.2, 2)}` : 'khoảng bề rộng?'
      : 'khoảng bề rộng?'
    const location = Number.isFinite(Number(p.stop_lat)) && Number.isFinite(Number(p.stop_lon))
      ? `${Number(p.stop_lat).toFixed(5)}, ${Number(p.stop_lon).toFixed(5)}`
      : 'tọa độ không rõ'
    return `${p.vehicle_label}: ${result} · ${exit} · ${widthImpact} · ${location} · hẻm OSM ${ingress} · way ra ${egress}`
  }
  if (r.type === 'blockage') return `${p.reason} (đoạn ${p.way_id}, ngày ${p.date})`
  if (r.type === 'flood_report') return `${p.street ?? 'không rõ đường'}: ${p.depth_cm ?? '?'} cm`
  return String(p.street ?? p.type ?? p.notes ?? '')
}

function ReportQueue({ onApproved }: { onApproved: () => void }) {
  const [items, setItems] = useState<Report[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    api.reports('pending', null)
      .then((page) => { if (live) { setItems(page.items); setCursor(page.next_cursor) } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    return () => { live = false }
  }, [])
  async function loadMore(from: string) {
    try {
      const page = await api.reports('pending', from)
      setItems((xs) => [...xs, ...page.items])
      setCursor(page.next_cursor)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function decide(r: Report, approve: boolean) {
    try {
      await api.decideReport(r.report_id, approve, r.revision)
      setItems((xs) => xs.filter((x) => x.report_id !== r.report_id))
      if (approve) onApproved()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div className="report-queue">
      <b>Báo cáo chờ duyệt ({items.length}{cursor ? '+' : ''})</b>
      {error && <small className="error-line">{error}</small>}
      {!items.length && !error && <small className="faint">Không có báo cáo nào chờ duyệt.</small>}
      <ul>
        {items.map((r) => (
          <li key={r.report_id}>
            <span><b>{REPORT_KIND[r.type]}</b>{r.legacy && ' · dữ liệu cũ'}<small>{reportSummary(r)} · {r.source}</small></span>
            <span className="ph-actions">
              <button type="button" className="btn btn-tonal btn-sm" onClick={() => decide(r, true)}>Duyệt</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => decide(r, false)}>Bỏ</button>
            </span>
          </li>
        ))}
      </ul>
      {cursor && <button type="button" className="btn btn-ghost btn-sm" onClick={() => loadMore(cursor)}>Tải thêm</button>}
    </div>
  )
}

const AREA_STATE: Record<Plan['area']['state'], string> = {
  fresh: 'Đã có dữ liệu trực tiếp cho khu vực', partial: 'Dữ liệu khu vực thiếu một bước',
  stale: 'Dữ liệu khu vực đã quá hạn', missing: 'Chưa có dữ liệu trực tiếp cho khu vực',
}

function AreaStatusLine({ plan, build, operator, onBuild }: { plan: Plan; build: AreaBuild | null; operator: boolean; onBuild: () => void }) {
  const running = plan.area.building || build?.state === 'queued' || build?.state === 'running'
  if (plan.area.state === 'fresh' && !running) return null
  return (
    <details className="why area-status">
      <summary>{running ? 'Đang cập nhật dữ liệu khu vực' : 'Dữ liệu khu vực chưa đầy đủ'}</summary>
      <p>{AREA_STATE[plan.area.state]}{plan.area.reason ? `: ${plan.area.reason.toLowerCase()}` : ''}. Kế hoạch dùng dữ liệu tĩnh; phần thiếu vẫn được ghi là chưa xác minh.</p>
      {operator
        ? <button type="button" className="link-btn" disabled={running} onClick={onBuild}>{running ? 'Đang thu thập…' : 'Thu thập dữ liệu khu vực'}</button>
        : <p>Cần người điều hành thu thập dữ liệu khu vực.</p>}
    </details>
  )
}
