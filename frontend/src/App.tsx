import { orderStops } from './qaFixes'
import { CloudRain, FlaskConical, Layers, LogIn, LogOut, MapPin, Navigation, Sparkles, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, poll, routeSourceLabel, type AgentPlan, type AreaBuild, type CameraInfo, type CameraReading, type Config, type Corridor, type Flag, type Intent, type ManeuverState, type Plan, type PlanComparison, type Preset, type RainSpell, type Report, type RouteSource, type Vehicle, type WayEvidence } from './api'
import { MapView, type FloodMoment, type LayerToggles, type ManeuverOverlay } from './MapView'
import { Agent } from './components/Agent'
import type { MapContext } from './mapSearch'
import { ErrorBoundary } from './ErrorBoundary'
import { Directions, type Place, type VehicleMode } from './components/Directions'
import { StandardRouteContrast, LiveStrip, NewsList, StopRow, Verdict, exitFloodFailure } from './components/Result'
import { VoiceReport } from './components/VoiceReport'
import { useParkingWatch } from './parkingWatch'
import { EvidencePanel } from './components/Evidence'
import { TierLegend } from './components/Transparency'
import { CameraPanel, CorridorCard } from './components/Corridor'
import { TideTimeline } from './components/TideTimeline'
import { Segmented, metres, useOutside, vnt } from './ds/ui'

import { fromLocal, timestamp, toLocal } from './datetime'
import { planningRain } from './rain'
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
  const [arrive, setArrive] = useState(() => toLocal(new Date().toISOString())!)
  const [rainOn, setRainOn] = useState(false)
  const [rainMm, setRainMm] = useState(45)
  const [rainScenario, setRainScenario] = useState<RainSpell[] | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planTripKey, setPlanTripKey] = useState('')
  const [comparison, setComparison] = useState<{ plan: Plan; data: PlanComparison } | null>(null)
  const [selected, setSelected] = useState(0)
  const [stopOpen, setStopOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [toggles, setToggles] = useState<LayerToggles>({ fit: true, flood: true, standard: false, cams: true, evidence: false })
  const [floodMoment, setFloodMoment] = useState<FloodMoment>('arrive')
  const [way, setWay] = useState<WayEvidence | null>(null)
  const [wayAt, setWayAt] = useState<[number, number]>([0, 0])
  const [build, setBuild] = useState<AreaBuild | null>(null)
  const [story, setStory] = useState('')
  const [demoScenarioId, setDemoScenarioId] = useState<string | null>(null)
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
  // "Go now" = the next 5-minute mark, so the plan only refreshes when that mark moves.
  const arriveLocal = arriveNow ? toLocal(new Date(Math.ceil(now / 300e3) * 300e3).toISOString())! : arrive
  const arriveISO = fromLocal(arriveLocal)
  const rain = useMemo(() => planningRain(rainOn, arriveISO, rainMm, rainScenario),
    [rainOn, rainMm, arriveISO, rainScenario])
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
        setManeuver({ key, status: 'error', playback: 0, error: 'Invalid simulation data format.' })
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
      setError('Invalid arrival time. Select an arrival time to update the trip.')
      return
    }
    planCtl.current?.abort()
    const ctl = new AbortController()
    planCtl.current = ctl
    const id = ++reqId.current
    setBusy(true)
    setError('')
    try {
      const r = orderStops(await api.plan(activePlanRequest!, ctl.signal))
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
      if (e instanceof ApiError && e.status === 422) setError(`Trip has not been updated: ${message}`)
      else { setError(message); setPlan(null) }
    } finally {
      if (id === reqId.current) setBusy(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlanRequest, tripKey])
  useEffect(() => {
    if (!plan || !activePlanRequest || planTripKey !== tripKey) return
    const ctl = new AbortController()
    const vehicle_ids = [...new Set([...fleet.classes.map((v) => v.id), plan.vehicle.id])]
    api.compare({ ...activePlanRequest, vehicle_ids }, ctl.signal).then((data) => {
      if (!ctl.signal.aborted && Array.isArray(data.vehicles) && Array.isArray(data.profile)) setComparison({ plan, data })
    }).catch(() => { /* Optional endpoint: existing plan evidence remains usable. */ })
    return () => ctl.abort()
  }, [plan, activePlanRequest, planTripKey, tripKey, fleet.classes])

  function selectComparedVehicle(id: string) {
    const v = [...fleet.classes, ...fleet.models].find((item) => item.id === id)
    if (!v) return
    setVMode(v.kind)
    if (v.kind === 'class') setClassId(id)
    else setModelId(id)
  }

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
      } else setNotice('Camera could not be read; conditions remain unknown.')
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
      setError(e instanceof ApiError && e.status === 401 ? 'Sign in as an operator to collect data.' : e instanceof Error ? e.message : String(e))
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
    setRainScenario(p.rain)
    if (p.rain[0]) setRainMm(p.rain[0].mm_per_h)
    setSelected(0)
    setSheet('half')
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
      const r = await api.reverse(lat, lon).catch(() => ({ label: 'Your location' }))
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
      setError('Invalid scenario arrival time. Trip has not been updated.')
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
    setRainScenario(p.rain ?? null)
    if (p.rain?.[0]) setRainMm(p.rain[0].mm_per_h)
    setOrigin((o) => o ?? DEMO_ORIGIN)
    setDest({ lat: p.lat, lon: p.lon, label: p.label })
    setDemoScenarioId(p.id)
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
      setError('Departure time does not match the duration in minutes. Trip has not been updated.')
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
      throw new Error('Submit confirmations from a stop mapped to a road; car parks do not provide alley evidence.')
    }
    await api.confirm({
      stop_lat: selectedStop.lat, stop_lon: selectedStop.lon, vehicle_id: plan.vehicle.id, result, exit,
    })
  }

  async function reportBlockage(reason: string) {
    if (!plan || !selectedStop || selectedStop.way_id == null) throw new Error('This stop has no road ID for a blockage report.')
    await api.blockage({
      lat: plan.destination.lat, lon: plan.destination.lon, way_id: selectedStop.way_id, reason,
    })
  }

  const padding = isMobile() ? { top: 190, left: 24, right: 24, bottom: 320 } : { top: 60, left: 460, right: 80, bottom: 190 }

  if (!cfg) return <div className="boot">{error ? `Could not connect to the server: ${error}` : <span className="boot-mark display">Ngõ Ngách</span>}</div>

  const goongOn = cfg.goong.tiles
  return (
    <div className={`app ${way || cam ? 'has-evidence' : ''}`}>
      <ErrorBoundary label="Map">
        <MapView styleUrl={cfg.map_style} center={cfg.demo_center} plan={plan} selected={selected} origin={origin} destination={dest}
          toggles={toggles} floodMoment={floodMoment} padding={padding} frame={frame}
          corridor={corridor?.available ? corridor : null} routeSel={routeSel} cams={cams} maneuver={maneuverOverlay}
          onCameraClick={(id) => { setWay(null); openCamera(id) }}
          onPick={(lat, lon, x, y) => setPick({ lat, lon, x, y })}
          onFeatures={setMapContext} onPlaceClick={(p) => chooseDest({ lat: p.lat, lon: p.lon, label: p.name })} onWayClick={openEvidence}
          onStopClick={(i) => {
            setSelected(i)
            setStopOpen(false)
            setSheet((s) => (s === 'peek' ? 'half' : s))
            // A pin can select a stop that is scrolled out of the list: bring its card (header, evidence link) into view.
            requestAnimationFrame(() => document.querySelectorAll('.stop')[i]?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
          }} />
      </ErrorBoundary>

      <Agent origin={origin} onPlan={applyAgent} open={agentOpen} setOpen={setAgentOpen} mapContext={mapContext} />

      <div className="side">
        <section className="card top">
          <header className="brand">
            <span className="logo" aria-hidden>NN</span>
            <span className="brand-name display">Ngõ Ngách</span>
            <span className="brand-sub">the alley layer for T-Maps</span>
            <DemoMenu open={menu === 'demo'} onOpen={(o) => setMenu(o ? 'demo' : null)} cfg={cfg} loadPreset={loadPreset}
              rainOn={rainOn} setRainOn={setRainOn} rainMm={rainMm}
              setRainMm={(mm) => { setRainMm(mm); setRainScenario(null) }} setFlag={setFlag}
              canArrive={!!plan} onArrive={() => { setArrived(true); setMenu(null) }}
              onLogin={login} onLogout={logout} onApproved={() => runRef.current()} />
          </header>
          <Directions mapContext={mapContext} origin={origin} dest={dest} setOrigin={setOrigin} setDest={chooseDest} locating={locating} onLocate={locate}
            vehicle={vehicle} fleet={fleet} vMode={vMode} setVMode={setVMode} classId={classId} setClassId={setClassId}
            modelId={modelId} setModelId={setModelId} vetcLinked={vetcLinked} openVetc={() => setVetcOpen(true)} unlinkVetc={() => setVetcLinked(false)}
            intent={intent} setIntent={setIntent} dwell={dwell} setDwell={setDwell}
            arrive={arriveLocal} setArrive={setArrive} arriveNow={arriveNow} setArriveNow={setArriveNow} />
        </section>

        <section className={`card sheet sheet-${sheet}`} aria-label="Results">
          <button type="button" className="sheet-handle" aria-label="Collapse or expand results"
            onClick={() => setSheet((s) => (s === 'peek' ? 'half' : s === 'half' ? 'full' : 'peek'))}><i /></button>
          <div className="sheet-body">
            {error && <p className="error-line">{error}</p>}
            {notice && <p className="error-line" role="status" onClick={() => setNotice('')}>{notice}</p>}
            {!dest && <Welcome presets={cfg.presets} loadPreset={loadPreset} />}
            {dest && !plan && busy && <SkeletonResult />}
            {plan && (
              <>
                <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Trip results">
                {story && <details className="why scenario-note"><summary>Demo scenario</summary><p>{story}</p></details>}
                <Verdict plan={plan} comparison={comparison?.plan === plan ? comparison.data : null} fleet={[...fleet.classes, ...fleet.models]} onVehicle={selectComparedVehicle} onDeparture={setDepartureAt} stale={busy || planTripKey !== tripKey} />
                {origin && <CorridorCard corridor={corridor} busy={corridorBusy} selected={routeSel}
                  onSelect={(i) => { setRouteSel(i); setFrame('trip') }} onCamera={(c) => { setWay(null); setCam(c) }} />}
                {plan.live_crawl && <AreaStatusLine plan={plan} build={build} operator={operator} onBuild={startBuild} />}
                {build && <LiveStrip build={build} />}
                {plan.area_data && <NewsList items={plan.area_data.news} />}
                <h3 className="section-title">Suggested {plan.intent === 'park' ? 'parking spots' : 'stops'}</h3>
                <div className="stops">
                  {plan.stop_points.map((s, i) => (
                    <StopRow key={`${s.lat},${s.lon}`} s={s} plan={plan} index={i} selected={i === selected} open={i === selected && stopOpen}
                      comparison={i === 0 && comparison?.plan === plan ? comparison.data : null} fleet={[...fleet.classes, ...fleet.models]} onVehicle={selectComparedVehicle}
                      maneuver={i === selected ? activeManeuver : null}
                      onSelect={() => { if (i === selected) setStopOpen((o) => !o); else { setSelected(i); setStopOpen(false) } }}
                      onEvidence={(id) => openEvidence(id, s.lat, s.lon)}
                      onManeuver={() => void openManeuver(i, s)} maneuverDisabled={busy || planTripKey !== tripKey || !vehicleId}
                      onReplay={replayManeuver} onDismiss={closeManeuver} />
                  ))}
                  {!plan.stop_points.length && <p className="muted">{plan.verdict.detail}</p>}
                </div>
                {(watch.active || (plan.intent === 'park' && selectedStop)) && (
                  <section className="parking-watch" aria-label="Parking watch">
                    <div className="watch-heading">
                      <div><strong>{watch.active ? 'Watching parking spot' : 'Parking watch'}</strong>
                        <small>{watch.active ? watch.session?.stopName : 'Recheck while this tab is open'}</small></div>
                      {watch.active
                        ? <button type="button" className="btn btn-ghost btn-sm" onClick={watch.end}>End</button>
                        : <button type="button" className="btn btn-outline btn-sm" disabled={!watch.canStart} onClick={() => watch.start()}>Start</button>}
                    </div>
                    <small>Notifications are optional; alerts appear while this tab is open.</small>
                    {watch.active && !watch.contextMatches && <small>Watch is linked to the saved trip rather than the current selection.</small>}
                    {watch.active && <div className="watch-meta">
                      <span>{watch.checking ? 'Checking…' : watch.lastCheckLabel ? `Checked at ${watch.lastCheckLabel}` : 'No successful checks yet'}</span>
                      <button type="button" className="link-btn" onClick={() => void watch.check()} disabled={watch.checking}>Check now</button>
                      {'Notification' in window && Notification.permission !== 'granted' && (
                        <button type="button" className="link-btn" onClick={async () => {
                          try {
                            const permission = await watch.requestNotifications()
                            setNotice(permission === 'granted'
                              ? 'Device notifications enabled.'
                              : 'Notifications are disabled. In-app alerts appear while this tab is open.')
                          } catch {
                            setNotice('Could not enable notifications. In-app alerts appear while this tab is open.')
                          }
                        }}>Enable notifications</button>
                      )}
                    </div>}
                    {!watch.active && selectedStop && !selectedStop.verified
                      && <small>Stop is unverified; watching it does not confirm vehicle access or exit.</small>}
                    {watch.error && <p className="watch-error" role="status">
                      Check failed{watch.lastCheckLabel ? ` · last check ${watch.lastCheckLabel}` : ''}: {watch.error}
                    </p>}
                    {watch.banner && <p className="watch-alert" role="alert">{watch.banner}
                      <button type="button" className="link-btn" onClick={watch.clearBanner}>Close</button>
                    </p>}
                  </section>
                )}
                {plan.door && !plan.door.ok && (
                  <details className="why">
                    <summary>Why stop short of the door?</summary>
                    <ul>{plan.door.fail_reasons.map((r, i) => <li key={i}>{vnt(r)}</li>)}</ul>
                  </details>
                )}
                {vehicle && <StandardRouteContrast plan={plan} vehicleLabel={vehicle.label} show={toggles.standard} onToggle={() => setToggles((t) => ({ ...t, standard: !t.standard }))} />}
                <details className="why sources"><summary>Data sources</summary><p>{goongOn ? 'Goong (base map)' : 'fallback base map'}, OpenStreetMap{plan.standard_route ? `, reference route ${routeSourceLabel(plan.standard_route.source)}` : ''}, IRD 2002–2026, Southern Regional Hydro-Meteorological Centre, VETC, Chợ Tốt, HCMC traffic cameras.</p></details>
                </ErrorBoundary>
              </>
            )}
            {watch.active && !plan && <section className="parking-watch" aria-label="Parking watch">
              <div className="watch-heading">
                <div><strong>Watching parking spot</strong><small>{watch.session?.stopName}</small></div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={watch.end}>End</button>
              </div>
              <p className="watch-error">{watch.error
                ? `Check failed${watch.lastCheckLabel ? ` · last check ${watch.lastCheckLabel}` : ''}: ${watch.error}`
                : watch.banner || 'Watch by rechecking while this tab is open.'}</p>
            </section>}
          </div>
        </section>
      </div>

      {plan && ((plan.origin && plan.stop_points[selected]?.approach) || corridor?.available) && (
        <div className="frame-toggle">
          <Segmented label="Map view" value={frame} onChange={setFrame}
            options={[{ value: 'arrival', label: 'Last stretch' }, { value: 'trip', label: 'Full route' }]} />
        </div>
      )}
      <div className="map-tools">
        <LayersMenu open={menu === 'layers'} onOpen={(o) => setMenu(o ? 'layers' : null)} toggles={toggles} setToggles={setToggles}
          floodMoment={floodMoment} setFloodMoment={setFloodMoment} standardSource={plan?.standard_route?.source ?? null} />
      </div>

      {plan && (
        <div className="timeline-dock">
          <ErrorBoundary key={`${plan.window.arrive}-${plan.window.depart}`} label="Tide chart">
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
          onBlockage={() => api.blockage({ lat: wayAt[0], lon: wayAt[1], way_id: way.way_id, reason: 'Temporary blockage (driver report)' })
            .then(() => setNotice('Blockage report submitted. Operator approval is required before it affects plans.'))
            .catch((e) => setNotice(e instanceof Error ? e.message : String(e)))} />
      )}

      {pick && <PickMenu pick={pick} onClose={() => setPick(null)} onPick={pickAs} />}

      {arrived && plan && selectedStop && !busy && planTripKey === tripKey && (
        <div className="arrive card" role="dialog" aria-label="Report after arrival">
          <button type="button" className="icon-btn close" aria-label="Close" onClick={() => setArrived(false)}><X size={16} /></button>
          <h3 className="display">Have you reached the stop?</h3>
          <p className="muted">Reports become evidence after operator approval. They do not change fit or safety conclusions.</p>
          {selectedStop.kind === 'lot' || selectedStop.way_id == null
            ? <p className="muted" role="status">A car park does not confirm alley access. Choose a roadside stop to submit a report.</p>
            : <VoiceReport stop={selectedStop} vehicleId={plan.vehicle.id} destination={plan.destination}
              voiceEnabled={cfg.flags.some((flag) => flag.name === 'ai_voice_report' && flag.enabled)}
              onConfirm={confirmArrival} onBlockage={reportBlockage} />}
        </div>
      )}

      {vetcOpen && (
        <div className="scrim" onClick={() => setVetcOpen(false)}>
          <div className="modal card" role="dialog" aria-label="Connect VETC" onClick={(e) => e.stopPropagation()}>
            <span className="tag brand">Demo · VETC API unavailable</span>
            <h3 className="display">Ngõ Ngách would like to read your VETC vehicle details</h3>
            <p>To assess alley clearance and water depth for your vehicle:</p>
            <ul><li>Vehicle list (registration plates masked)</li><li>Vehicle model and seats</li></ul>
            <p className="faint">Location and toll history are not accessed. Under Luật Bảo vệ dữ liệu cá nhân 91/2025, you can withdraw consent at any time.</p>
            <div className="modal-actions">
              <button type="button" className="btn btn-ghost" onClick={() => setVetcOpen(false)}>Cancel</button>
              <button type="button" className="btn btn-primary" onClick={() => { setVetcLinked(true); setVMode('vetc'); setVetcOpen(false) }}>Allow</button>
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
      <h2 className="display">Can your car get in — and out?</h2>
      <p className="muted">Enter a destination. Ngõ Ngách checks alley clearance for your car, tides and flooding during your stay, and stopping and parking rules, then suggests the nearest stop and walk.</p>
      <div className="legend-row" aria-hidden>
        <span><i style={{ background: 'var(--fit-fits)' }} />Fits</span>
        <span><i style={{ background: 'var(--fit-tight)' }} />Tight</span>
        <span><i style={{ background: 'var(--fit-no)' }} />Does not fit</span>
        <span><i className="dash" />Unknown</span>
      </div>
      <h3 className="section-title">Try a scenario</h3>
      <ul className="examples">
        {presets.map((p) => (
          <li key={p.id}><button type="button" onClick={() => loadPreset(p)}><MapPin size={16} /><span><b>{p.title}</b><small>{p.label}</small></span></button></li>
        ))}
      </ul>
      <p className="faint tip">Tip: right-click (or press and hold) on the map to set your origin and destination.</p>
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
    <div className="skeleton" aria-label="Calculating">
      {slow >= 3 && (
        <p className="loading-note" aria-live="polite">
          {slow < 12 ? 'First visit to this area: loading alleys from OpenStreetMap…' : `Map server is slow; still loading (${slow} seconds)…`}
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
      <button type="button" role="menuitem" onClick={() => onPick('origin')}><span className="mk-origin static" />Set as origin</button>
      <button type="button" role="menuitem" onClick={() => onPick('dest')}><MapPin size={16} className="dest-ico" />Set as destination</button>
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
      <button type="button" className={`icon-btn raised ${open ? 'on' : ''}`} aria-label="Map layers" aria-expanded={open} onClick={() => onOpen(!open)}><Layers size={19} /></button>
      {open && (
        <div className="popover pop-right layers" role="dialog" aria-label="Map layers">
          <div className="layer-heading"><h4>Map layers</h4><button type="button" className="icon-btn" aria-label="Close map layers" onClick={() => onOpen(false)}><X size={16} /></button></div>
          {row('fit', 'Alley clearance for your vehicle', <span className="sw-fit" />)}
          <div className="fit-key"><span><i style={{ background: 'var(--fit-fits)' }} />Fits</span><span><i style={{ background: 'var(--fit-tight)' }} />Tight</span><span><i style={{ background: 'var(--fit-no)' }} />Does not fit</span><span><i className="dash" />Unknown</span><span><i style={{ background: 'var(--fit-blocked)' }} />Blocked</span></div>
          {row('evidence', 'Evidence strength', <span className="sw-evidence" />)}
          {toggles.evidence && <TierLegend />}
          {row('flood', 'Flooding relative to your vehicle', <span className="sw-flood" />)}
          {toggles.flood && <Segmented label="Flood time" value={floodMoment} onChange={setFloodMoment} options={[{ value: 'arrive', label: 'On arrival' }, { value: 'depart', label: 'On departure' }]} />}
          {row('standard', standardSource ? `Reference route ${routeSourceLabel(standardSource)}` : 'Reference route (no data yet)', <span className="sw-standard" />)}
          {row('cams', 'Traffic cameras (AI reads traffic and flooding)', <span className="sw-cam" />)}
          {toggles.cams && <div className="fit-key"><span><i style={{ background: 'var(--fit-fits)' }} />Free-flowing</span><span><i style={{ background: 'var(--traffic-busy)' }} />Busy</span><span><i style={{ background: 'var(--fit-tight)' }} />Congested</span><span><i style={{ background: 'var(--fit-no)' }} />Gridlocked</span><span><i style={{ background: 'var(--flood-risky)' }} />Flooding</span><span><i style={{ background: 'var(--fit-unknown)' }} />Unread</span></div>}
          <div className="line-key"><span><i className="ln-route" />Route</span><span><i className="ln-walk" />Walk</span><span><i className="ln-out" />Exit route</span></div>
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
      <button type="button" className={`btn btn-ghost btn-sm ${open ? 'on' : ''}`} aria-expanded={open} onClick={() => onOpen(!open)}>
        <FlaskConical size={15} />Demo
      </button>
      {open && (
        <div className="popover pop-right demo-menu" role="dialog" aria-label="Demo tools">
          <h4>Scenarios</h4>
          <ul className="examples compact">
            {cfg.presets.map((p) => <li key={p.id}><button type="button" onClick={() => loadPreset(p)}><MapPin size={14} /><span><b>{p.title}</b><small>{p.label}</small></span></button></li>)}
          </ul>
          <h4>Simulation</h4>
          <label className="layer-row"><input type="checkbox" checked={rainOn} onChange={(e) => setRainOn(e.target.checked)} /><CloudRain size={15} /><span>Simulated rain {rainOn ? `${rainMm} mm/h` : '(off: use measured rain)'}</span></label>
          {rainOn && <input type="range" min={10} max={90} step={5} value={rainMm} onChange={(e) => setRainMm(Number(e.target.value))} aria-label="Rainfall" />}
          <button type="button" className="btn btn-outline btn-sm" disabled={!canArrive} onClick={onArrive}><Navigation size={14} />Arrived</button>
          <h4>Operator</h4>
          {!cfg.operator.available ? (
            <p className="faint">Operator features are disabled on this server.</p>
          ) : op ? (
            <div className="operator-row">
              <span>Signed in as operator</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={onLogout}><LogOut size={14} />Sign out</button>
            </div>
          ) : (
            <form className="operator-row" onSubmit={async (e) => {
              e.preventDefault()
              setLoginError('')
              try { await onLogin(secret); setSecret('') } catch (err) { setLoginError(err instanceof Error ? err.message : String(err)) }
            }}>
              <input type="password" autoComplete="current-password" aria-label="Operator password" placeholder="Operator password"
                value={secret} onChange={(e) => setSecret(e.target.value)} />
              <button type="submit" className="btn btn-outline btn-sm" disabled={!secret}><LogIn size={14} />Sign in</button>
              {loginError && <small className="error-line">{loginError}</small>}
            </form>
          )}
          {op && <ReportQueue onApproved={onApproved} />}
          <h4><Sparkles size={13} /> Data sources and AI</h4>
          {!op && <p className="faint">Only operators can change these settings.</p>}
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
  confirmation: 'Arrival confirmation', blockage: 'Temporary blockage', flood_report: 'Flood report',
  stop_rule: 'Stopping/parking rule', photo_reading: 'AI image reading', field_measurement: 'Field measurement',
}

function reportSummary(r: Report): string {
  const p = r.payload
  if (r.type === 'confirmation') {
    const result = ({ in: 'can enter', tight: 'tight', no: 'cannot enter' } as Record<string, string>)[String(p.result)] ?? String(p.result)
    const exit = ({ through: 'exit forwards', turned: 'turn around to exit', reversed: 'reverse to exit', unknown: 'exit unknown' } as Record<string, string>)[String(p.exit)] ?? 'exit unknown'
    const ingress = Array.isArray(p.way_ids) ? p.way_ids.join(', ') : 'unknown'
    const egress = Array.isArray(p.way_out_ids)
      ? `${p.way_out_ids.slice(0, 4).join(', ')}${p.way_out_ids.length > 4 ? `, +${p.way_out_ids.length - 4}` : ''}`
      : 'unknown'
    const body = Number(p.body_width)
    const mirror = Number(p.mirror_width)
    const widthImpact = Number.isFinite(body)
      ? result === 'can enter' ? `lower bound ≥ ${metres(body + 0.2, 2)}`
        : result === 'tight' && Number.isFinite(mirror)
          ? `${metres(body + 0.1, 2)}–${metres(mirror + 0.8, 2)}`
          : result === 'cannot enter' && Number.isFinite(mirror) ? `upper bound ≤ ${metres(mirror + 0.2, 2)}` : 'width range?'
      : 'width range?'
    const location = Number.isFinite(Number(p.stop_lat)) && Number.isFinite(Number(p.stop_lon))
      ? `${Number(p.stop_lat).toFixed(5)}, ${Number(p.stop_lon).toFixed(5)}`
      : 'unknown coordinates'
    return `${p.vehicle_label}: ${result} · ${exit} · ${widthImpact} · ${location} · OSM alley ${ingress} · exit way ${egress}`
  }
  if (r.type === 'field_measurement') return `${p.width_m} m · ${p.method} · OSM ${p.osm_way_id} · ${p.note ?? ''}`
  if (r.type === 'blockage') return `${p.reason} (segment ${p.way_id}, date ${p.date})`
  if (r.type === 'flood_report') return `${p.street ?? 'unknown road'}: ${p.depth_cm ?? '?'} cm`
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
      <b>Reports awaiting review ({items.length}{cursor ? '+' : ''})</b>
      {error && <small className="error-line">{error}</small>}
      {!items.length && !error && <small className="faint">No reports awaiting review.</small>}
      <ul>
        {items.map((r) => (
          <li key={r.report_id}>
            <span><b>{REPORT_KIND[r.type]}</b>{r.legacy && ' · legacy data'}<small>{reportSummary(r)} · {r.source}</small></span>
            <span className="ph-actions">
              <button type="button" className="btn btn-tonal btn-sm" onClick={() => decide(r, true)}>Approve</button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => decide(r, false)}>Reject</button>
            </span>
          </li>
        ))}
      </ul>
      {cursor && <button type="button" className="btn btn-ghost btn-sm" onClick={() => loadMore(cursor)}>Load more</button>}
    </div>
  )
}

const AREA_STATE: Record<Plan['area']['state'], string> = {
  fresh: 'Live area data available', partial: 'Area data is missing a step',
  stale: 'Area data has expired', missing: 'No live area data yet',
}

function AreaStatusLine({ plan, build, operator, onBuild }: { plan: Plan; build: AreaBuild | null; operator: boolean; onBuild: () => void }) {
  const running = plan.area.building || build?.state === 'queued' || build?.state === 'running'
  if (plan.area.state === 'fresh' && !running) return null
  return (
    <details className="why area-status">
      <summary>{running ? 'Updating area data' : 'Area data is incomplete'}</summary>
      <p>{AREA_STATE[plan.area.state]}{plan.area.reason ? `: ${plan.area.reason.toLowerCase()}` : ''}. Plan uses static data; missing information remains unverified.</p>
      {operator
        ? <button type="button" className="link-btn" disabled={running} onClick={onBuild}>{running ? 'Collecting…' : 'Collect area data'}</button>
        : <p>An operator must collect area data.</p>}
    </details>
  )
}
