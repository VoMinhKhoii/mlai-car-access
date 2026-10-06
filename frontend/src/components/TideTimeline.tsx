import { Waves } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type RainSpell } from '../api'
import { vn } from '../ds/ui'

const HOURS = 30
const SNAP = 15 * 60e3
const VN = 7 * 3600e3
const hhmm = (t: number) => new Date(t + VN).toISOString().slice(11, 16)
function dayStart(iso: string) {
  const d = new Date(new Date(iso).getTime() + VN)
  d.setUTCHours(0, 0, 0, 0)
  return d.getTime() - VN
}
const atHHMM = (t0: number, s: string, after: number) => {
  const [h, m] = s.split(':').map(Number)
  let t = t0 + (h * 60 + m) * 60e3
  while (t < after - 6 * 3600e3) t += 24 * 3600e3
  return t
}

/** The stay as a band over the tide curve and the rain bars. Drag it (or click the track) to change the arrival time.
 *  Solid curve and dots: measured at Phú An; dashed: model (±err); bars: rain per hour, measured solid, forecast pale. */
export function TideTimeline({ arrive, depart, leaveBefore, orAfter, exitFloods, station, rain, onChange }: {
  arrive: string; depart: string; leaveBefore?: string | null; orAfter?: string | null; exitFloods: boolean
  station: string; rain: RainSpell[]; onChange: (iso: string) => void
}) {
  const t0 = dayStart(arrive)
  const [series, setSeries] = useState<{ t: number; v: number; kind: string }[]>([])
  const [readings, setReadings] = useState<{ t: number; v: number }[]>([])
  const [err, setErr] = useState<number | null>(null)
  const [alarms, setAlarms] = useState<Record<string, number>>({})
  const [drag, setDrag] = useState<number | null>(null) // ms offset while dragging
  const track = useRef<HTMLDivElement>(null)
  const grab = useRef<{ x: number; a: number } | null>(null)

  useEffect(() => {
    api.tide(new Date(t0).toISOString(), HOURS).then((r) => {
      setSeries(r.series.map((s) => ({ t: new Date(s.t).getTime(), v: s.level_m, kind: s.kind })))
      setReadings((r.readings ?? []).map((s) => ({ t: new Date(s.t).getTime(), v: s.level_m })))
      setErr(r.model_err_m)
      setAlarms(r.alarm_levels_m)
    }).catch(() => setSeries([]))
  }, [t0])

  const a0 = new Date(arrive).getTime()
  const dwell = new Date(depart).getTime() - a0
  const a = drag ?? a0
  const span = HOURS * 3600e3
  const pct = (t: number) => Math.min(100, Math.max(0, ((t - t0) / span) * 100))
  const tAt = (clientX: number) => {
    const r = track.current!.getBoundingClientRect()
    return t0 + ((clientX - r.left) / r.width) * span
  }
  const snap = (t: number) => Math.round(t / SNAP) * SNAP

  if (!series.length) return null
  const vMin = Math.min(...series.map((s) => s.v), -1.5)
  const vMax = Math.max(...series.map((s) => s.v), (alarms.BD3 ?? 1.6) + 0.15)
  const y = (v: number) => 100 - ((v - vMin) / (vMax - vMin)) * 100
  const path = (pts: typeof series) => pts.map((s, i) => `${i ? 'L' : 'M'}${pct(s.t).toFixed(2)},${y(s.v).toFixed(2)}`).join('')
  const curve = path(series)
  const area = `${curve}L${pct(series[series.length - 1].t)},100L${pct(series[0].t)},100Z`
  const cut = series.findIndex((s) => s.kind === 'model')
  const measured = cut === -1 ? series : series.slice(0, cut + 1)
  const model = cut === -1 ? [] : series.slice(cut)
  const lastRead = readings.length ? readings[readings.length - 1] : null
  const bars = rain.filter((r) => r.mm_per_h > 0).map((r) => {
    const s = new Date(r.start).getTime()
    return { s, e: s + 3600e3, mm: r.mm_per_h, measured: !!r.measured, source: r.source ?? 'giả định' }
  }).filter((b) => b.e > t0 && b.s < t0 + span)
  const wet = bars.filter((b) => b.measured).sort((p, q) => q.s - p.s)[0]
  const peak = series.reduce((m, s) => (s.t >= a && s.t <= a + dwell && s.v > m.v ? s : m), { t: a, v: -9 })
  const lb = leaveBefore ? atHHMM(t0, leaveBefore, a0) : null
  const oa = orAfter ? atHHMM(t0, orAfter, a0) : null

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
    if (drag != null && drag !== a0) onChange(new Date(drag).toISOString())
    setDrag(null)
  }
  function key(e: React.KeyboardEvent) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      onChange(new Date(a0 + (e.key === 'ArrowLeft' ? -SNAP : SNAP)).toISOString())
    }
  }

  return (
    <section className="timeline card" aria-label="Mực nước triều và thời gian ở lại">
      <header>
        <Waves size={15} />
        <b>Triều · {station.replace(/\s*\(.*\)/, '')}</b>
        <span className="faint tl-hint">· kéo khung để đổi giờ</span>
        <span className="tl-peak num">Đỉnh trong lúc ở: <b>{vn(peak.v, 2)} m</b> lúc {hhmm(peak.t)}
          {alarms.BD3 != null && <span className={peak.v >= alarms.BD3 ? 'over' : ''}> · báo động 3: {vn(alarms.BD3, 1)} m</span>}</span>
      </header>
      <p className="tl-live num">
        {lastRead ? <>Số đo mới nhất {hhmm(lastRead.t)} {new Date(lastRead.t + VN).toISOString().slice(8, 10).replace(/^0/, '')}/{Number(new Date(lastRead.t + VN).toISOString().slice(5, 7))}: <b>{vn(lastRead.v, 2)} m</b>{model.length > 0 && err != null && <> · nét đứt: mô hình ±{Math.round(err * 100)} cm</>}</>
          : <>Không lấy được số đo, theo bản tin triều</>}
        {wet && <> · Mưa đo {hhmm(wet.s).slice(0, 2)}–{hhmm(wet.e).slice(0, 2)}h: <b>{vn(wet.mm, 1)} mm</b> ({wet.source.replace(/^đo tại /, '')})</>}
      </p>
      <div className="tl-track" ref={track} onClick={(e) => { if (e.target === e.currentTarget || (e.target as Element).tagName === 'svg' || (e.target as Element).tagName === 'path') onChange(new Date(snap(tAt(e.clientX))).toISOString()) }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="tl-water" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--flood-risky)" stopOpacity=".32" />
              <stop offset="1" stopColor="var(--flood-low)" stopOpacity=".05" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#tl-water)" />
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
        {readings.filter((r) => r.t >= t0 && r.t <= t0 + span).map((r) => (
          <span key={r.t} className="tl-reading" style={{ left: `${pct(r.t)}%`, top: `${y(r.v)}%` }} title={`Đo ${hhmm(r.t)}: ${vn(r.v, 2)} m`} />
        ))}
        {lb && <span className="tl-line" style={{ left: `${pct(lb)}%` }} />}
        {oa && <span className="tl-line" style={{ left: `${pct(oa)}%` }} />}
        <div className={`tl-band ${exitFloods ? 'floods' : ''} ${drag != null ? 'dragging' : ''}`} role="slider" tabIndex={0}
          aria-label="Thời gian ở lại" aria-valuetext={`Đến ${hhmm(a)}, rời ${hhmm(a + dwell)}`}
          aria-valuemin={t0} aria-valuemax={t0 + span} aria-valuenow={a}
          style={{ left: `${pct(a)}%`, width: `${Math.max(1.5, pct(a + dwell) - pct(a))}%` }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onKeyDown={key}>
          <span className="tl-in">{hhmm(a)}</span>
          <span className="tl-out">{hhmm(a + dwell)}</span>
        </div>
      </div>
      {(lb || oa) && (
        <div className="tl-marks num" aria-hidden>
          {lb && <span className="before" style={{ left: `${pct(lb)}%` }}>rời trước {leaveBefore}</span>}
          {oa && <span className="after" style={{ left: `${pct(oa)}%` }}>hoặc sau {orAfter}</span>}
        </div>
      )}
      <div className="tl-axis num" aria-hidden>
        {Array.from({ length: HOURS / 3 + 1 }, (_, i) => t0 + i * 3 * 3600e3).map((t) => (
          <span key={t} style={{ left: `${pct(t)}%` }}>{hhmm(t).slice(0, 2)}h</span>
        ))}
      </div>
    </section>
  )
}
