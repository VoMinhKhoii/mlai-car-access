import { ChevronDown, ChevronUp, CloudRain, Ellipsis, Layers, LocateFixed, MapPin, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, poll, routeSourceLabel, type AgentPlan, type AreaBuild, type CameraInfo, type CameraReading, type Config, type Corridor, type Flag, type Intent, type ManeuverState, type Plan, type Preset, type RainSpell, type Report, type RouteSource, type Vehicle, type WayEvidence } from './api'
import { MapView, type FloodMoment, type LayerToggles, type ManeuverOverlay } from './MapView'
import { Agent } from './components/Agent'
import type { MapContext } from './mapSearch'
import { ErrorBoundary } from './ErrorBoundary'
import { Directions, type Place, type VehicleMode } from './components/Directions'
import { StandardRouteContrast, LiveStrip, NewsList, StopPhases, StopRow, Verdict, exitFloodFailure } from './components/Result'
import { VoiceReport } from './components/VoiceReport'
import { useParkingWatch } from './parkingWatch'
import { EvidencePanel } from './components/Evidence'
import { CameraPanel, CorridorCard } from './components/Corridor'
import { TideTimeline } from './components/TideTimeline'
import { Segmented, metres, minutes, useOutside } from './ds/ui'

import { fromLocal, timestamp, toLocal } from './datetime'
const DEMO_ORIGIN: Place = { lat: 10.7725, lon: 106.698, label: 'Chợ Bến Thành, Quận 1' }
const isMobile = () => window.matchMedia('(max-width: 760px)').matches

export default function App() {
  const [agentOpen, setAgentOpen] = useState(false)
  const [islandOpen, setIslandOpen] = useState(true)
  const [ask, setAsk] = useState<{ q: string; id: number } | null>(null)
  const [askDraft, setAskDraft] = useState('')
  const [dockH, setDockH] = useState(0)
  const dockRef = useRef<HTMLElement | null>(null)
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
  const [arrive, setArrive] = useState(() => toLocal(new Date().toISOString())!)
  const [rainOn, setRainOn] = useState(false)
  const [rainMm, setRainMm] = useState(45)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planTripKey, setPlanTripKey] = useState('')
  const [selected, setSelected] = useState(0)
  const [, setStopOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toggles, setToggles] = useState<LayerToggles>({ fit: true, flood: true, standard: false, cams: true })
  const [floodMoment, setFloodMoment] = useState<FloodMoment>('arrive')
  const [way, setWay] = useState<WayEvidence | null>(null)
  const [wayAt, setWayAt] = useState<[number, number]>([0, 0])
  const [build, setBuild] = useState<AreaBuild | null>(null)
  const [story, setStory] = useState('')
  const [demoScenarioId, setDemoScenarioId] = useState<string | null>(null)
  const [pick, setPick] = useState<{ lat: number; lon: number; x: number; y: number } | null>(null)
  const [menu, setMenu] = useState<'demo' | 'layers' | 'samples' | null>(null)
  const [arrived, setArrived] = useState(false)
  const [sheet, setSheet] = useState<'peek' | 'half' | 'full'>('peek')
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
  // "Đi ngay" = the next 5-minute mark when the trip was set up. It is pinned there so the clock
  // tick doesn't re-plan the trip (closing open cards, the arrival dialog and the parking watch)
  // every 5 minutes; changing the destination, vehicle, intent, stay or "Đi ngay" itself re-anchors it.
  const nowTripInputs = JSON.stringify([dest, origin, vehicleId, intent, dwell, arriveNow])
  const [nowAnchor, setNowAnchor] = useState(() => ({ key: nowTripInputs, at: now }))
  if (nowAnchor.key !== nowTripInputs) setNowAnchor({ key: nowTripInputs, at: now })
  const arriveLocal = arriveNow ? toLocal(new Date(Math.ceil(nowAnchor.at / 300e3) * 300e3).toISOString())! : arrive
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
    demo_scenario: cfg?.synthetic_demo_data ? demoScenarioId : null,
  }) : null, [dest, vehicleId, intent, arriveISO, dwell, rain, origin, demoScenarioId, cfg?.synthetic_demo_data])
  const tripKey = JSON.stringify([dest, origin, vehicleId, intent, arriveISO, intent === 'pickup' ? 15 : dwell, rain, demoScenarioId])
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
  const hasDock = !!dest
  useEffect(() => {
    const el = dockRef.current
    if (!el) { setDockH(0); return }
    const ro = new ResizeObserver(() => setDockH(Math.round(el.getBoundingClientRect().height)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [hasDock, plan])
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

  function applyAgent(p: AgentPlan) {
    const local = toLocal(p.arrive_at)
    if (!local) return
    chooseDest({ lat: p.lat, lon: p.lon, label: p.label })
    setVMode(p.vehicle_id.startsWith('class-') ? 'class' : 'model')
    if (p.vehicle_id.startsWith('class-')) setClassId(p.vehicle_id)
    else setModelId(p.vehicle_id)
    setIntent(p.intent)
    setArriveNow(false)
    setArrive(local)
    setDwell(p.dwell_min)
    setRainOn(p.rain.length > 0)
    if (p.rain[0]) setRainMm(p.rain[0].mm_per_h)
    setSelected(0)
    setSheet(isMobile() ? 'half' : 'peek')
  }

  function chooseDest(p: Place | null) {
    buildCtl.current?.abort()
    setDest(p)
    setDemoScenarioId(null)
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
    setDemoScenarioId(p.id)
    setStory(p.story)
    setMenu(null)
    setSheet(isMobile() ? 'half' : 'peek')
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
    try { setWay(await api.wayEvidence(id, lat, lon, cfg?.synthetic_demo_data ? demoScenarioId : null)) } catch { setWay(null) }
  }

  async function reviewPhoto(id: string, approve: boolean) {
    try {
      await api.reviewPhoto(id, approve)
      if (way) setWay(await api.wayEvidence(way.way_id, wayAt[0], wayAt[1], cfg?.synthetic_demo_data ? demoScenarioId : null))
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

  const inspector = !!(way || cam || agentOpen)
  const mobile = isMobile()
  const padding = mobile
    ? { top: 76, left: 16, right: 16, bottom: dockH + 16 }
    : { top: 96, left: 32, right: 88 + (inspector ? 436 : 0), bottom: dockH + 32 }

  if (!cfg) return <div className="boot">{error ? `Không kết nối được máy chủ: ${error}` : <span className="boot-mark display">Ngõ Ngách</span>}</div>

  const goongOn = cfg.goong.tiles
  const islandExpanded = islandOpen
  const stayLabel = intent === 'pickup' ? 'Đón/trả 15 phút' : `Đỗ ${minutes(dwell)}`
  const whenLabel = arriveNow ? 'Đi ngay' : `Đến ${arriveLocal.slice(11, 16)}`
  const parkingWatch = (watch.active || (plan?.intent === 'park' && selectedStop)) ? (
    <ParkingWatch watch={watch} stop={selectedStop ?? null} canArrive={!!plan && !!selectedStop}
      onArrive={() => setArrived(true)} onNotice={setNotice} />
  ) : null
  return (
    <div className={`app ${inspector ? 'has-inspector' : ''} ${dest || watch.active ? 'has-dock' : ''}`} style={{ '--dock-h': `${dockH}px` } as React.CSSProperties}>
      <ErrorBoundary label="Bản đồ">
        <MapView styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} origin={origin} destination={dest}
          toggles={toggles} floodMoment={floodMoment} padding={padding} frame={frame}
          corridor={corridor?.available ? corridor : null} routeSel={routeSel} cams={cams} maneuver={maneuverOverlay}
          onCameraClick={(id) => { setWay(null); setAgentOpen(false); openCamera(id) }}
          onPick={(lat, lon, x, y) => setPick({ lat, lon, x, y })}
          onFeatures={setMapContext} onPlaceClick={(p) => chooseDest({ lat: p.lat, lon: p.lon, label: p.name })} onWayClick={(id, lat, lon) => { setAgentOpen(false); void openEvidence(id, lat, lon) }}
          onStopClick={(i) => {
            setSelected(i)
            setSheet('full')
            requestAnimationFrame(() => document.querySelectorAll('.stop')[i]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
          }} />
      </ErrorBoundary>

      <section className={`island glass ${islandExpanded ? 'is-open' : ''}`} aria-label="Chuyến đi">
        {islandExpanded ? (
          <>
            <header className="island-head">
              <span className="wordmark display">Ngõ Ngách</span>
              <button type="button" className="btn btn-ghost btn-sm island-collapse" aria-label="Thu gọn ô chuyến đi để xem bản đồ" onClick={() => setIslandOpen(false)}>
                <ChevronUp size={16} />Thu gọn
              </button>
            </header>
            <Directions mapContext={mapContext} origin={origin} dest={dest} setOrigin={setOrigin} setDest={(p) => { chooseDest(p); if (p) setIslandOpen(false) }} locating={locating} onLocate={locate}
              vehicle={vehicle} fleet={fleet} vMode={vMode} setVMode={setVMode} classId={classId} setClassId={setClassId}
              modelId={modelId} setModelId={setModelId} vetcLinked={vetcLinked} openVetc={() => setVetcOpen(true)} unlinkVetc={() => setVetcLinked(false)}
              intent={intent} setIntent={setIntent} dwell={dwell} setDwell={setDwell}
              arrive={arriveLocal} setArrive={setArrive} arriveNow={arriveNow} setArriveNow={setArriveNow} />
            <form className="island-ask" onSubmit={(e) => {
              e.preventDefault()
              const q = askDraft.trim()
              setWay(null); setCam(null); setAgentOpen(true)
              if (q) { setAsk({ q, id: Date.now() }); setAskDraft('') }
            }}>
              <input value={askDraft} onChange={(e) => setAskDraft(e.target.value)} aria-label="Hỏi AlleyAI bằng một câu"
                placeholder="Hỏi một câu: “Fortuner tới 113/4 Võ Duy Ninh”" />
              <button type="submit" className="btn btn-sm btn-tonal">Hỏi AlleyAI</button>
            </form>
          </>
        ) : (
          <button type="button" className="island-summary" onClick={() => setIslandOpen(true)} aria-label="Sửa chuyến đi">
            <span className="wordmark display">Ngõ Ngách</span>
            <span className="island-trip">
              {origin && <span className="island-from">{origin.label.split(',')[0]}</span>}
              <span className="island-to">{dest ? dest.label.split(',')[0] : 'Chọn điểm đến'}</span>
            </span>
            <span className="island-meta">{vehicle?.label ?? 'Chưa chọn xe'} · {stayLabel} · {whenLabel}</span>
          </button>
        )}
      </section>

      <SamplesMenu presets={cfg.presets} open={menu === 'samples'} onOpen={(o) => setMenu(o ? 'samples' : null)}
        onPick={(p) => { loadPreset(p); setIslandOpen(false); setMenu(null) }} />

      <Agent origin={origin} onPlan={(p) => { applyAgent(p); setIslandOpen(false) }} open={agentOpen} setOpen={(o) => { if (o) { setWay(null); setCam(null) } setAgentOpen(o) }} mapContext={mapContext} ask={ask} />

      <nav className="rail glass" aria-label="Công cụ bản đồ">
        <LayersMenu open={menu === 'layers'} onOpen={(o) => setMenu(o ? 'layers' : null)} toggles={toggles} setToggles={setToggles}
          floodMoment={floodMoment} setFloodMoment={setFloodMoment} standardSource={plan?.standard_route?.source ?? null} />
        <button type="button" className="icon-btn raised" aria-label="Dùng vị trí hiện tại" title="Dùng vị trí hiện tại" onClick={locate}>
          <LocateFixed size={19} className={locating ? 'spin' : ''} />
        </button>
        <DemoMenu open={menu === 'demo'} onOpen={(o) => setMenu(o ? 'demo' : null)} cfg={cfg} loadPreset={loadPreset} story={story}
          rainOn={rainOn} setRainOn={setRainOn} rainMm={rainMm} setRainMm={setRainMm} setFlag={setFlag}
          onLogin={login} onLogout={logout} onApproved={() => runRef.current()} />
      </nav>

      {(dest || watch.active) && (
        <section ref={dockRef} className={`dock glass dock-${sheet}`} aria-label="Hành trình: vào, ở lại, ra">
          <button type="button" className="sheet-handle" aria-label="Thu hoặc mở bảng hành trình"
            onClick={() => setSheet((s) => (s === 'peek' ? 'half' : s === 'half' ? 'full' : 'peek'))}><i /></button>
          <div className="dock-body">
            {error && <p className="error-line">{error}</p>}
            {notice && <p className="error-line" role="status" onClick={() => setNotice('')}>{notice}</p>}
            {dest && !plan && busy && <SkeletonResult />}
            {plan && (
              <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Kết quả chuyến đi">
                <div className="dock-main">
                  <div className="dock-verdict">
                    <Verdict plan={plan} onDeparture={setDepartureAt} stale={busy || planTripKey !== tripKey} />
                    <div className="dock-bar">
                      <button type="button" className="btn btn-outline btn-sm" aria-expanded={sheet !== 'peek'}
                        onClick={() => setSheet((s) => (s === 'peek' ? 'full' : 'peek'))}>
                        {sheet !== 'peek' ? <><ChevronDown size={16} />Ẩn chi tiết</> : `Xem ${plan.stop_points.length} chỗ ${plan.intent === 'park' ? 'đỗ' : 'dừng'}: vào, ở lại, ra`}
                      </button>
                      {((plan.origin && plan.stop_points[selected]?.approach) || corridor?.available) && (
                        <Segmented label="Khung bản đồ" value={frame} onChange={setFrame}
                          options={[{ value: 'arrival', label: 'Đoạn cuối' }, { value: 'trip', label: 'Cả tuyến' }]} />
                      )}
                    </div>
                  </div>
                  <div className="dock-tide">
                    <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Biểu đồ triều">
                      <TideTimeline arrive={plan.window.arrive} depart={plan.window.depart} leaveBeforeAt={plan.timing?.leave_before_at} orAfterAt={plan.intent === 'park' ? plan.timing?.or_after_at : null}
                        timingReason={plan.timing?.reason} timingApproximate={plan.timing?.approximate} exitFloods={exitFloodFailure(plan)} station={cfg.tide.station} rain={plan.window.rain}
                        onChange={(iso) => { const local = toLocal(iso); if (local) { setArriveNow(false); setArrive(local) } }} />
                    </ErrorBoundary>
                  </div>
                </div>
                <div className="dock-detail">
                  <div className="dock-stops">
                    {origin && <CorridorCard corridor={corridor} busy={corridorBusy} selected={routeSel}
                      onSelect={(i) => { setRouteSel(i); setFrame('trip') }} onCamera={(c) => { setWay(null); setAgentOpen(false); setCam(c) }} />}
                    <h3 className="phase-title">Chỗ {plan.intent === 'park' ? 'đỗ' : 'dừng'}</h3>
                    <div className="stops">
                      {plan.stop_points.map((s, i) => (
                        <StopRow key={`${s.lat},${s.lon}`} s={s} index={i} selected={i === selected} onSelect={() => setSelected(i)} />
                      ))}
                      {!plan.stop_points.length && <p>{plan.verdict.detail}</p>}
                    </div>
                    {plan.live_crawl && <AreaStatusLine plan={plan} build={build} operator={operator} onBuild={startBuild} />}
                    {build && <LiveStrip build={build} />}
                    {plan.area_data && <NewsList items={plan.area_data.news} />}
                    {vehicle && <StandardRouteContrast plan={plan} vehicleLabel={vehicle.label} show={toggles.standard} onToggle={() => setToggles((t) => ({ ...t, standard: !t.standard }))} />}
                    <details className="why sources"><summary>Nguồn dữ liệu</summary><p>{goongOn ? 'Goong (bản đồ nền)' : 'bản đồ nền tạm'}, OpenStreetMap{plan.standard_route ? `, tuyến tham chiếu ${routeSourceLabel(plan.standard_route.source)}` : ''}, IRD 2002–2026, Đài KTTV Nam Bộ, VETC, Chợ Tốt, camera giao thông TP.HCM.</p></details>
                  </div>
                  {selectedStop && (
                    <StopPhases s={selectedStop} plan={plan} onEvidence={(id) => { setAgentOpen(false); void openEvidence(id, selectedStop.lat, selectedStop.lon) }}
                      maneuver={activeManeuver} maneuverDisabled={busy || planTripKey !== tripKey || !vehicleId}
                      onManeuver={() => void openManeuver(selected, selectedStop)} onReplay={replayManeuver} onDismiss={closeManeuver}
                      stay={parkingWatch} />
                  )}
                </div>
              </ErrorBoundary>
            )}
            {!plan && parkingWatch}
          </div>
        </section>
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
          <p>Báo cáo chỉ trở thành bằng chứng sau khi người điều hành duyệt. Không làm thay đổi kết luận phù hợp hay an toàn.</p>
          {selectedStop.kind === 'lot' || selectedStop.way_id == null
            ? <p role="status">Bãi đỗ không xác nhận xe đã vào hẻm. Chọn một điểm dừng trên đường để gửi báo cáo.</p>
            : <VoiceReport stop={selectedStop} vehicleId={plan.vehicle.id} destination={plan.destination}
              voiceEnabled={cfg.flags.some((flag) => flag.name === 'ai_voice_report' && flag.enabled)}
              onConfirm={confirmArrival} onBlockage={reportBlockage} />}
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

/** "Báo nếu nước lên": re-checks the parked stop while the tab is open. One component for both the stop and the no-plan state. */
function ParkingWatch({ watch, stop, canArrive, onArrive, onNotice }: {
  watch: ReturnType<typeof useParkingWatch>; stop: Plan['stop_points'][number] | null
  canArrive: boolean; onArrive: () => void; onNotice: (s: string) => void
}) {
  return (
    <section className="parking-watch" aria-label="Báo nếu nước lên">
      <div className="watch-heading">
        <div><strong>{watch.active ? 'Đang theo dõi nước' : 'Báo nếu nước lên'}</strong>
          <small>{watch.active ? watch.session?.stopName : 'Kiểm tra lại khi thẻ còn mở; thông báo là tùy chọn.'}</small></div>
        {watch.active
          ? <button type="button" className="btn btn-ghost btn-sm" onClick={watch.end}>Kết thúc</button>
          : <button type="button" className="btn btn-outline btn-sm" disabled={!watch.canStart} onClick={() => watch.start()}>Bắt đầu</button>}
      </div>
      {watch.active && !watch.contextMatches && <small>Theo dõi vẫn gắn với chuyến đã lưu, không phải lựa chọn hiện tại.</small>}
      {watch.active && <div className="watch-meta">
        <span>{watch.checking ? 'Đang kiểm tra…' : watch.lastCheckLabel ? `Kiểm tra lúc ${watch.lastCheckLabel}` : 'Chưa có lần kiểm tra thành công'}</span>
        <button type="button" className="link-btn" onClick={() => void watch.check()} disabled={watch.checking}>Kiểm tra ngay</button>
        {'Notification' in window && Notification.permission !== 'granted' && (
          <button type="button" className="link-btn" onClick={async () => {
            try {
              const permission = await watch.requestNotifications()
              onNotice(permission === 'granted'
                ? 'Đã bật thông báo trên thiết bị.'
                : 'Thông báo không được bật. Cảnh báo vẫn hiện trong ứng dụng khi thẻ đang mở.')
            } catch {
              onNotice('Không bật được thông báo. Cảnh báo vẫn hiện trong ứng dụng khi thẻ đang mở.')
            }
          }}>Bật thông báo</button>
        )}
      </div>}
      {!watch.active && stop && !stop.verified
        && <small>Điểm dừng chưa xác minh; theo dõi không xác nhận xe vào hoặc ra được.</small>}
      {watch.error && <p className="watch-error" role="status">
        Lỗi kiểm tra{watch.lastCheckLabel ? ` · lần gần nhất ${watch.lastCheckLabel}` : ''}: {watch.error}
      </p>}
      {watch.banner && <p className="watch-alert" role="alert">{watch.banner}
        <button type="button" className="link-btn" onClick={watch.clearBanner}>Đóng</button>
      </p>}
      {canArrive && <button type="button" className="btn btn-tonal btn-sm watch-arrive" onClick={onArrive}>Đã tới nơi: báo hẻm thế nào</button>}
    </section>
  )
}

/** Sample trips live in their own capsule on the left, so the trip island stays a single editor. */
function SamplesMenu({ presets, open, onOpen, onPick }: { presets: Preset[]; open: boolean; onOpen: (o: boolean) => void; onPick: (p: Preset) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useOutside(ref, open, () => onOpen(false))
  if (!presets.length) return null
  return (
    <div className="samples" ref={ref}>
      <button type="button" className={`samples-btn glass ${open ? 'is-open' : ''}`} aria-expanded={open} aria-controls="samples-panel" onClick={() => onOpen(!open)}>
        Chuyến mẫu <span className="samples-count num">{presets.length}</span>
      </button>
      {open && (
        <div id="samples-panel" className="popover samples-panel" role="dialog" aria-label="Chuyến mẫu">
          <p className="welcome-lede">Ngõ Ngách so bề rộng hẻm với đúng xe của bạn, xem triều lúc bạn ở lại, rồi chỉ chỗ dừng gần nhất. Thử một chuyến:</p>
          <ul className="examples">
            {presets.map((p) => (
              <li key={p.id}><button type="button" onClick={() => onPick(p)}><b>{p.label}</b><small>{p.title}</small></button></li>
            ))}
          </ul>
          <p className="faint">Hoặc nhấp chuột phải trên bản đồ để đặt điểm đi, điểm đến.</p>
        </div>
      )}
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
        <div className="popover pop-left layers" role="dialog" aria-label="Lớp bản đồ">
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

function DemoMenu({ open, onOpen, cfg, loadPreset, story, rainOn, setRainOn, rainMm, setRainMm, setFlag, onLogin, onLogout, onApproved }: {
  open: boolean; onOpen: (o: boolean) => void; cfg: Config; loadPreset: (p: Preset) => void; story: string
  rainOn: boolean; setRainOn: (b: boolean) => void; rainMm: number; setRainMm: (n: number) => void
  setFlag: (f: Flag, on: boolean) => void
  onLogin: (secret: string) => Promise<void>; onLogout: () => Promise<void>; onApproved: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [secret, setSecret] = useState('')
  const [loginError, setLoginError] = useState('')
  useOutside(ref, open, () => onOpen(false))
  const op = cfg.operator.signed_in
  return (
    <div className="tool demo" ref={ref}>
      <button type="button" className={`icon-btn raised ${open ? 'on' : ''}`} aria-label="Kịch bản demo và điều hành" title="Kịch bản demo và điều hành" aria-expanded={open} onClick={() => onOpen(!open)}>
        <Ellipsis size={19} />
      </button>
      {open && (
        <div className="popover pop-left demo-menu" role="dialog" aria-label="Kịch bản demo và điều hành">
          <h4>Kịch bản demo</h4>
          {story && <p className="scenario-story">{story}</p>}
          <ul className="examples compact">
            {cfg.presets.map((p) => <li key={p.id}><button type="button" onClick={() => loadPreset(p)}><b>{p.title}</b><small>{p.label}</small></button></li>)}
          </ul>
          <h4>Giả lập</h4>
          <label className="layer-row"><input type="checkbox" checked={rainOn} onChange={(e) => setRainOn(e.target.checked)} /><CloudRain size={15} /><span>Mưa giả định {rainOn ? `${rainMm} mm/h` : '(tắt: dùng mưa đo)'}</span></label>
          {rainOn && <input type="range" min={10} max={90} step={5} value={rainMm} onChange={(e) => setRainMm(Number(e.target.value))} aria-label="Lượng mưa" />}
          <h4>Điều hành</h4>
          {!cfg.operator.available ? (
            <p className="faint">Chức năng điều hành chưa bật trên máy chủ này.</p>
          ) : op ? (
            <div className="operator-row">
              <span>Đang đăng nhập điều hành</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout}>Đăng xuất</button>
            </div>
          ) : (
            <form className="operator-row" onSubmit={async (e) => {
              e.preventDefault()
              setLoginError('')
              try { await onLogin(secret); setSecret('') } catch (err) { setLoginError(err instanceof Error ? err.message : String(err)) }
            }}>
              <input type="password" autoComplete="current-password" aria-label="Mật khẩu điều hành" placeholder="Mật khẩu điều hành"
                value={secret} onChange={(e) => setSecret(e.target.value)} />
              <button type="submit" className="btn btn-outline btn-sm" disabled={!secret}>Đăng nhập</button>
              {loginError && <small className="error-line">{loginError}</small>}
            </form>
          )}
          {op && <ReportQueue onApproved={onApproved} />}
          <h4>Nguồn dữ liệu</h4>
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
  stop_rule: 'Quy định dừng/đỗ', photo_reading: 'AI đọc ảnh', field_measurement: 'Đo hiện trường',
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
  if (r.type === 'field_measurement') return `${p.width_m} m · ${p.method} · OSM ${p.osm_way_id} · ${p.note ?? ''}`
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
