import { Waves } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type RainSpell } from '../api'
import { vn } from '../ds/ui'
import { timestamp, toLocal } from '../datetime'
import { floodTimeLabel } from './Result'

const HOURS = 30
const SNAP = 15 * 60e3
const VN = 7 * 3600e3
const hhmm = (t: number) => Number.isFinite(t) ? toLocal(new Date(t).toISOString())?.slice(11, 16) ?? '?' : '?'
function dayStart(t: number) {
  const d = new Date(t + VN)
  d.setUTCHours(0, 0, 0, 0)
  return d.getTime() - VN
}

/** The stay as a band over the tide curve and the rain bars. Drag it (or click the track) to change the arrival time.
 *  Solid curve and dots: measured at Phú An; dashed: model (±err); bars: rain per hour, measured solid, forecast pale. */
interface Props {
  arrive: string; depart: string; leaveBeforeAt?: string | null; orAfterAt?: string | null; exitFloods: boolean
  timingReason?: string | null; timingApproximate?: boolean
  station: string; rain: RainSpell[]; onChange: (iso: string) => void
}
export function TideTimeline(props: Props) {
  const a0 = timestamp(props.arrive)
  const departAt = timestamp(props.depart)
  if (a0 == null || departAt == null || departAt < a0) {
    return <p className="error-line" role="status">Cannot display tides: arrival or departure time is invalid. Select the arrival time again.</p>
  }
  return <TideChart {...props} a0={a0} departAt={departAt} />
}

function TideChart({ a0, departAt, arrive, depart, leaveBeforeAt, orAfterAt, timingReason, timingApproximate, exitFloods, station, rain, onChange }: Props & { a0: number; departAt: number }) {
  const t0 = dayStart(a0)
  const [series, setSeries] = useState<{ t: number; v: number; kind: string }[]>([])
  const [bulletin, setBulletin] = useState<{ bulletin: string; source_url: string; note: string } | null>(null)
  const [readings, setReadings] = useState<{ t: number; v: number }[]>([])
  const [latestReading, setLatestReading] = useState<{ t: number; v: number } | null>(null)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [err, setErr] = useState<number | null>(null)
  const [alarms, setAlarms] = useState<Record<string, number>>({})
  const [drag, setDrag] = useState<number | null>(null) // ms offset while dragging
  const track = useRef<HTMLDivElement>(null)
  const grab = useRef<{ x: number; a: number } | null>(null)

  useEffect(() => {
    let active = true
    setSeries([])
    setReadings([])
    setLatestReading(null)
    setLoadState('loading')
    api.tide(new Date(t0).toISOString(), HOURS).then((r) => {
      if (!active) return
      setSeries(r.series.flatMap((s) => {
        const t = timestamp(s.t)
        return t != null && Number.isFinite(s.level_m) && t >= t0 && t <= t0 + HOURS * 3600e3 ? [{ t, v: s.level_m, kind: s.kind }] : []
      }))
      setReadings((r.readings ?? []).flatMap((s) => {
        const t = timestamp(s.t)
        return t != null && Number.isFinite(s.level_m) ? [{ t, v: s.level_m }] : []
      }))
      const latestAt = r.last_reading ? timestamp(r.last_reading.t) : null
      setLatestReading(latestAt != null && r.last_reading && Number.isFinite(r.last_reading.level_m) ? { t: latestAt, v: r.last_reading.level_m } : null)
      setBulletin(r.bulletin ?? null)
      setLoadState('ready')
      setErr(r.model_err_m)
      setAlarms(Object.fromEntries(Object.entries(r.alarm_levels_m).filter(([, v]) => Number.isFinite(v))))
    }).catch(() => { if (active) { setSeries([]); setLoadState('error') } })
    return () => { active = false }
  }, [t0])

  const dwell = departAt - a0
  const a = drag ?? a0
  const span = HOURS * 3600e3
  const pct = (t: number) => Math.min(100, Math.max(0, ((t - t0) / span) * 100))
  const tAt = (clientX: number) => {
    const r = track.current!.getBoundingClientRect()
    return t0 + ((clientX - r.left) / r.width) * span
  }
  const snap = (t: number) => Math.min(t0 + span, Math.max(t0, Math.round(t / SNAP) * SNAP))
  function change(t: number) {
    if (!Number.isFinite(t) || !Number.isFinite(new Date(t).getTime())) return
    const iso = new Date(t).toISOString()
    if (timestamp(iso) != null) onChange(iso)
  }

  const vMin = Math.min(...series.map((s) => s.v), -1.5)
  const vMax = Math.max(...series.map((s) => s.v), (alarms.BD3 ?? 1.6) + 0.15)
  const y = (v: number) => 100 - ((v - vMin) / (vMax - vMin)) * 100
  const path = (pts: typeof series) => pts.map((s, i) => `${i ? 'L' : 'M'}${pct(s.t).toFixed(2)},${y(s.v).toFixed(2)}`).join('')
  const area = series.length ? `${path(series)}L${pct(series[series.length - 1].t)},100L${pct(series[0].t)},100Z` : ''
  const cut = series.findIndex((s) => s.kind === 'model')
  const measured = cut === -1 ? series : series.slice(0, cut + 1)
  const model = cut === -1 ? [] : series.slice(cut)
  const windowReadings = readings.filter((r) => r.t >= t0 && r.t <= t0 + span)
  const lastRead = windowReadings.reduce<{ t: number; v: number } | null>((last, r) => !last || r.t > last.t ? r : last, null)
  const bars = rain.filter((r) => r.mm_per_h > 0).map((r) => {
    const s = new Date(r.start).getTime()
    return { s, e: s + 3600e3, mm: r.mm_per_h, measured: !!r.measured, source: r.source ?? 'simulated' }
  }).filter((b) => b.e > t0 && b.s < t0 + span)
  const wet = bars.filter((b) => b.measured).sort((p, q) => q.s - p.s)[0]
  const peak = series.reduce<(typeof series)[number] | null>((m, s) => s.t >= a && s.t <= a + dwell && (!m || s.v > m.v) ? s : m, null)
  const lb = leaveBeforeAt ? timestamp(leaveBeforeAt) : null
  const oa = orAfterAt ? timestamp(orAfterAt) : null
  const marks = ([{ t: lb, label: 'leave earlier', side: 'before' }, { t: oa, label: 'leave later', side: 'after' }] as const)
    .filter((m): m is typeof m & { t: number } => m.t != null && m.t >= t0 && m.t <= t0 + span)

  function down(e: React.PointerEvent) {
    e.preventDefault()
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    grab.current = { x: e.clientX, a: a0 }
  }
  function move(e: React.PointerEvent) {
    if (!grab.current) return
    const r = track.current!.getBoundingClientRect()
    setDrag(snap(grab.current.a + ((e.clientX - grab.current.x) / r.width) * span))
  }
  function up() {
    if (!grab.current) return
    grab.current = null
    if (drag != null && drag !== a0) change(drag)
    setDrag(null)
  }
  function key(e: React.KeyboardEvent) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      change(snap(a0 + (e.key === 'ArrowLeft' ? -SNAP : SNAP)))
    }
  }

  return (
    <section className="timeline card" aria-label="Tide level and stay window">
      <header>
        <Waves size={15} />
        <b>Tide · {station.replace(/\s*\(.*\)/, '')}</b>
        <span className="faint tl-hint">· drag the window to change time</span>
        <span className="tl-peak num">{peak ? <>Highest available level during stay: <b>{vn(peak.v, 2)} m</b> · {floodTimeLabel(new Date(peak.t).toISOString())}
          {alarms.BD3 != null && <span className={peak.v >= alarms.BD3 ? 'over' : ''}> · alarm level 3: {vn(alarms.BD3, 1)} m</span>}</> : loadState === 'loading' ? 'Loading tide data' : 'No tide data for the stay window'}</span>
      </header>
      <p className="tl-live num">Trip: {floodTimeLabel(arrive)} to {floodTimeLabel(depart)}.</p>
      <p className="tl-live num" role="status">
        {loadState === 'loading' ? 'Loading tide data.'
          : loadState === 'error' ? 'Could not load tide data; trip comparison unavailable.'
          : lastRead
            ? <>Reading in window: {floodTimeLabel(new Date(lastRead.t).toISOString())}, <b>{vn(lastRead.v, 2)} m</b>.</>
            : 'No confirmed tide readings within the trip window.'}
      </p>
      <details className="why tl-details">
        <summary>Tide data details</summary>
        <p className="tl-live num">
          {lastRead && dayStart(lastRead.t) !== dayStart(a0) && <>Reading is from a different day; it does not confirm tides for the arrival date. </>}
          {latestReading && (!lastRead || latestReading.t !== lastRead.t) && <>Latest reading at {station}: {floodTimeLabel(new Date(latestReading.t).toISOString())}, {vn(latestReading.v, 2)} m; does not confirm tides for the trip date. </>}
          {model.length > 0 && <>Dashed: model{err != null && Number.isFinite(err) ? `, error ±${Math.round(err * 100)} cm` : ''}. </>}
          {wet && <>Measured rain {hhmm(wet.s)}–{hhmm(wet.e)}: <b>{vn(wet.mm, 1)} mm</b> ({wet.source.replace(/^(?:measured at|đo tại) /, '')}).</>}
          {!lastRead && !latestReading && loadState === 'ready' && 'No tide readings for this time.'}
        </p>
        {bulletin && series.some((p) => p.kind === 'bulletin') && <p className="tl-live" title={bulletin.note}><a href={bulletin.source_url} target="_blank" rel="noreferrer">{bulletin.bulletin}</a> · interpolated high/low tides, not road-level measurements.</p>}
        {timingReason && <p className="tl-live">{timingReason}</p>}
        {timingApproximate && <p className="tl-live">Travel windows and departure times are estimates; they do not guarantee continuous real-world conditions.</p>}
      </details>
      <div className="tl-track" ref={track} onClick={(e) => { if (e.target === e.currentTarget || (e.target as Element).tagName === 'svg' || (e.target as Element).tagName === 'path') change(snap(tAt(e.clientX))) }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="tl-water" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--flood-risky)" stopOpacity=".32" />
              <stop offset="1" stopColor="var(--flood-low)" stopOpacity=".05" />
            </linearGradient>
          </defs>
          {area && <path d={area} fill="url(#tl-water)" />}
          {bars.map((b) => (
            <rect key={b.s} x={pct(b.s)} width={Math.max(0.3, pct(b.e) - pct(b.s) - 0.25)} y={100 - Math.min(60, b.mm * 1.5)}
              height={Math.min(60, b.mm * 1.5)} className={`tl-rain ${b.measured ? 'measured' : ''}`}><title>{`${vn(b.mm, 1)} mm/h · ${b.source}`}</title></rect>
          ))}
          <path d={path(measured)} fill="none" stroke="var(--flood-risky)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
          {model.length > 0 && <path d={path(model)} fill="none" stroke="var(--flood-risky)" strokeWidth="1.6" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />}
          {Object.entries(alarms).map(([k, v]) => (
            <line key={k} x1="0" x2="100" y1={y(v)} y2={y(v)} stroke={k === 'BD3' ? 'var(--fit-no)' : 'var(--fit-tight)'} strokeOpacity=".55"
              strokeDasharray="3 3" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {windowReadings.map((r) => (
          <span key={r.t} className="tl-reading" style={{ left: `${pct(r.t)}%`, top: `${y(r.v)}%` }} title={`Measured ${floodTimeLabel(new Date(r.t).toISOString())}: ${vn(r.v, 2)} m`} />
        ))}
        {marks.map((mark) => <span key={mark.side} className="tl-line" style={{ left: `${pct(mark.t)}%` }} />)}
        <div className={`tl-band ${exitFloods ? 'floods' : ''} ${drag != null ? 'dragging' : ''}`} role="slider" tabIndex={0}
          aria-label="Stay window" aria-valuetext={`Arrive ${floodTimeLabel(new Date(a).toISOString())}, leave ${floodTimeLabel(new Date(a + dwell).toISOString())}`}
          aria-valuemin={t0} aria-valuemax={t0 + span} aria-valuenow={a}
          style={{ left: `${pct(a)}%`, width: `${Math.max(1.5, pct(a + dwell) - pct(a))}%` }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onKeyDown={key}>
          <span className="tl-in">{hhmm(a)}</span>
          <span className="tl-out">{hhmm(a + dwell)}</span>
        </div>
      </div>
      {marks.length > 0 && (
        <div className="tl-marks num" aria-hidden>
          {marks.map((mark) => <span key={mark.side} className={mark.side} style={{ left: `${pct(mark.t)}%` }} title={floodTimeLabel(new Date(mark.t).toISOString())}>{mark.label} {hhmm(mark.t)}</span>)}
        </div>
      )}
      <div className="tl-axis num" aria-hidden>
        {Array.from({ length: HOURS / 3 + 1 }, (_, i) => t0 + i * 3 * 3600e3).map((t) => (
          <span key={t} style={{ left: `${pct(t)}%` }}>{hhmm(t)}{t > t0 && dayStart(t) === t && <> · {toLocal(new Date(t).toISOString())?.slice(5, 10).split('-').reverse().join('/')}</>}</span>
        ))}
      </div>
    </section>
  )
}
