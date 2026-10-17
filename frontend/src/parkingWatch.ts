import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Plan, type PlanRequest, type RainSpell } from './api'

const STORAGE_KEY = 'vao-duoc.parking-watch.v1'
const STORAGE_VERSION = 1
const EARTH_RADIUS_M = 6_371_000

export interface WatchSession {
  request: PlanRequest
  stop: { lat: number; lon: number }
  stopName: string
  startedAt: number
  lastCheckedAt: number | null
  alerts: string[]
  baseline: { exitFlood: string | null; leaveBeforeAt: string | null; verified: boolean }
}

interface StoredSession { version: number; session: WatchSession }

function validRain(value: unknown): value is RainSpell[] {
  return Array.isArray(value) && value.every((item) => !!item && typeof item === 'object'
    && typeof item.start === 'string' && Number.isFinite(Date.parse(item.start))
    && typeof item.end === 'string' && Number.isFinite(Date.parse(item.end)) && Number.isFinite(item.mm_per_h))
}

function validRequest(value: unknown): value is PlanRequest {
  if (!value || typeof value !== 'object') return false
  const v = value as Partial<PlanRequest>
  const origin = v.origin
  const validOrigin = origin === null || (Array.isArray(origin) && origin.length === 2
    && Number.isFinite(origin[0]) && Number.isFinite(origin[1])
    && origin[0] >= -90 && origin[0] <= 90 && origin[1] >= -180 && origin[1] <= 180)
  return Number.isFinite(v.lat) && Number.isFinite(v.lon) && v.lat! >= -90 && v.lat! <= 90 && v.lon! >= -180 && v.lon! <= 180
    && typeof v.label === 'string' && typeof v.vehicle_id === 'string' && (v.intent === 'park' || v.intent === 'pickup')
    && (v.arrive_at === null || (typeof v.arrive_at === 'string' && Number.isFinite(Date.parse(v.arrive_at))))
    && Number.isFinite(v.dwell_min) && v.dwell_min! > 0 && validRain(v.rain) && validOrigin
}

function loadSession(): WatchSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const stored = JSON.parse(raw) as Partial<StoredSession>
    const session = stored.version === STORAGE_VERSION ? stored.session : null
    if (!session || !validRequest(session.request) || !Number.isFinite(session.stop?.lat) || !Number.isFinite(session.stop?.lon)
      || typeof session.stopName !== 'string' || !Number.isFinite(session.startedAt)
      || !(session.lastCheckedAt === null || Number.isFinite(session.lastCheckedAt)) || !Array.isArray(session.alerts)
      || !session.alerts.every((x) => typeof x === 'string')
      || !session.baseline || !(session.baseline.exitFlood === null || typeof session.baseline.exitFlood === 'string')
      || !(session.baseline.leaveBeforeAt === null || typeof session.baseline.leaveBeforeAt === 'string')
      || typeof session.baseline.verified !== 'boolean') {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return session
  } catch {
    try { localStorage.removeItem(STORAGE_KEY) } catch { /* storage may be unavailable */ }
    return null
  }
}

function saveSession(session: WatchSession | null) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STORAGE_VERSION, session } satisfies StoredSession))
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* in-memory watch remains available when storage is unavailable */ }
}

function distanceMeters(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  const rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad
  const dLon = (b.lon - a.lon) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)))
}

function floodRank(status: string | null | undefined) {
  return status === 'blocked' ? 2 : status === 'risky' ? 1 : status === 'passable' ? 0 : -1
}

export function useParkingWatch({ request, plan, selectedIndex, enabled, demo }: {
  request: PlanRequest | null
  plan: Plan | null
  selectedIndex: number
  enabled: boolean
  demo: boolean
}) {
  const [session, setSession] = useState<WatchSession | null>(() => loadSession())
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [banner, setBanner] = useState('')
  const ctlRef = useRef<AbortController | null>(null)
  const seq = useRef(0)
  const sessionRef = useRef(session)
  sessionRef.current = session
  const requestRef = useRef(request)
  requestRef.current = request
  const planRef = useRef(plan)
  planRef.current = plan

  useEffect(() => { saveSession(session) }, [session])

  const selectedStop = plan?.stop_points[selectedIndex]
  const sameTrip = !session || (!!request && request.lat === session.request.lat && request.lon === session.request.lon
    && request.vehicle_id === session.request.vehicle_id && request.intent === session.request.intent
    && request.arrive_at === session.request.arrive_at && request.dwell_min === session.request.dwell_min
    && JSON.stringify(request.origin) === JSON.stringify(session.request.origin))
  const matchedSelected = !session || (!!selectedStop && distanceMeters(selectedStop, session.stop) <= 15)

  useEffect(() => {
    if (!session || !request || !sameTrip || !selectedStop || !matchedSelected) return
    if (JSON.stringify(session.request.rain) !== JSON.stringify(request.rain)) {
      setSession((current) => current ? { ...current, request: { ...current.request, rain: request.rain } } : current)
    }
  }, [session, request, sameTrip, selectedStop, matchedSelected])

  const end = useCallback(() => {
    seq.current++
    ctlRef.current?.abort()
    ctlRef.current = null
    setSession(null)
    setChecking(false)
    setError('')
    setBanner('')
  }, [])

  const requestNotifications = useCallback(async () => {
    if (!('Notification' in window)) return 'unsupported' as const
    if (Notification.permission === 'default') return Notification.requestPermission()
    return Notification.permission
  }, [])

  const start = useCallback(() => {
    if (!request || !plan || !selectedStop || !enabled || !sameTrip || !matchedSelected) return false
    setSession({
      request: { ...request }, stop: { lat: selectedStop.lat, lon: selectedStop.lon }, stopName: selectedStop.name,
      startedAt: Date.now(), lastCheckedAt: null, alerts: [],
      baseline: {
        exitFlood: selectedStop.way_out.flood?.status ?? null,
        leaveBeforeAt: plan.timing?.leave_before_at ?? null,
        verified: selectedStop.verified,
      },
    })
    setError('')
    setBanner('')
    return true
  }, [request, plan, selectedStop, enabled, sameTrip, matchedSelected])

  const check = useCallback(async () => {
    const active = sessionRef.current
    if (!active || document.visibilityState === 'hidden') return
    const seqId = ++seq.current
    ctlRef.current?.abort()
    const ctl = new AbortController()
    ctlRef.current = ctl
    setChecking(true)
    setError('')

    const latest = requestRef.current
    const currentPlan = planRef.current
    const sameContext = latest && currentPlan && latest.lat === active.request.lat && latest.lon === active.request.lon
      && latest.vehicle_id === active.request.vehicle_id && latest.intent === active.request.intent
      && latest.arrive_at === active.request.arrive_at && latest.dwell_min === active.request.dwell_min
      && JSON.stringify(latest.origin) === JSON.stringify(active.request.origin)
      && currentPlan.stop_points.some((stop) => distanceMeters(stop, active.stop) <= 15)
    const currentRequest = sameContext ? { ...active.request, rain: latest.rain } : active.request

    try {
      const next = await api.plan(currentRequest, ctl.signal)
      if (ctl.signal.aborted || seqId !== seq.current || sessionRef.current !== active) return
      const match = next.stop_points.find((stop) => distanceMeters(stop, active.stop) <= 15)
      if (!match) {
        const key = 'stop-missing'
        const message = `Không tìm thấy lại điểm dừng ${active.stopName} trong phạm vi 15 m. Hãy kiểm tra trước khi rời.`
        if (!active.alerts.includes(key)) setBanner(message)
        if (!active.alerts.includes(key) && 'Notification' in window && Notification.permission === 'granted') {
          try { new Notification('Không tìm thấy điểm dừng', { body: message }) } catch { /* in-app banner remains */ }
        }
        setSession((current) => current === active ? {
          ...current, request: currentRequest, lastCheckedAt: Date.now(),
          alerts: current.alerts.includes(key) ? current.alerts : [...current.alerts, key],
          baseline: { ...current.baseline, verified: false },
        } : current)
        return
      }

      const floodStatus = match.way_out.flood?.status ?? null
      const leaveBeforeAt = next.timing?.leave_before_at ?? null
      const currentFloodAlert = floodRank(floodStatus) > 0 ? `flood:${floodStatus}` : null
      const activeAlerts = active.alerts.filter((key) => {
        if (key === 'stop-missing') return false
        if (key.startsWith('flood:')) return key === currentFloodAlert
        if (key.startsWith('leave:')) return leaveBeforeAt != null && key === `leave:${leaveBeforeAt}`
        if (key === 'unverified') return !match.verified
        return true
      })
      const reasons: { key: string; text: string }[] = []
      if (floodRank(floodStatus) > floodRank(active.baseline.exitFlood)
        && floodRank(floodStatus) > 0) {
        reasons.push({ key: `flood:${floodStatus}`, text: `Ngập đường ra xấu hơn tại ${active.stopName}.` })
      }
      const oldLeave = active.baseline.leaveBeforeAt ? Date.parse(active.baseline.leaveBeforeAt) : NaN
      const newLeave = leaveBeforeAt ? Date.parse(leaveBeforeAt) : NaN
      if (Number.isFinite(oldLeave) && Number.isFinite(newLeave) && newLeave < oldLeave) {
        reasons.push({ key: `leave:${leaveBeforeAt}`, text: 'Giờ cần rời đi đã sớm hơn.' })
      }
      if (active.baseline.verified && !match.verified) {
        reasons.push({ key: 'unverified', text: 'Điểm dừng đã chọn hiện chưa xác minh.' })
      }

      const unseen = reasons.filter(({ key }) => !activeAlerts.includes(key))
      const stamp = Date.now()
      if (unseen.length) {
        const message = unseen.map(({ text }) => text).join(' ')
        setBanner(message)
        if ('Notification' in window && Notification.permission === 'granted') {
          try { new Notification('Cập nhật điểm đỗ', { body: message }) } catch { /* in-app banner remains available */ }
        }
      }
      setSession((current) => current === active ? {
        ...current, request: currentRequest, lastCheckedAt: stamp,
        alerts: [...activeAlerts, ...unseen.map(({ key }) => key)],
        baseline: {
          exitFlood: floodStatus, leaveBeforeAt, verified: match.verified,
        },
      } : current)
    } catch (e) {
      if (ctl.signal.aborted || seqId !== seq.current) return
      setError(e instanceof Error ? e.message : 'Không thể kiểm tra lại lúc này. Cần kết nối mạng để tiếp tục theo dõi.')
    } finally {
      if (seqId === seq.current) setChecking(false)
    }
  }, [])

  const active = !!session
  const clearBanner = useCallback(() => setBanner(''), [])

  useEffect(() => {
    if (!active) return
    const interval = window.setInterval(() => void check(), demo ? 15_000 : 5 * 60_000)
    const visible = () => { if (document.visibilityState === 'visible') void check() }
    document.addEventListener('visibilitychange', visible)
    if (document.visibilityState === 'visible') void check()
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', visible)
      seq.current++
      ctlRef.current?.abort()
      ctlRef.current = null
    }
  }, [active, check, demo])

  const lastCheckLabel = session?.lastCheckedAt ? new Date(session.lastCheckedAt).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : ''
  return {
    active, session, banner, error, checking, lastCheckLabel, start, end, check, clearBanner, requestNotifications,
    contextMatches: sameTrip && matchedSelected,
    canStart: enabled && !!selectedStop && sameTrip && matchedSelected,
  }
}
