import { Cctv, ChevronDown, Droplets, ExternalLink, LoaderCircle, RefreshCw, Route, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { CameraReading, Corridor, CorridorRoute, Hotspot, Traffic } from '../api'
import { Tag, distance, minutes, type Tone } from '../ds/ui'
import { FloodEvidenceDetail, floodPresentation, floodTimeLabel } from './Result'

const PORTAL = 'https://giaothong.hochiminhcity.gov.vn/Map.aspx'
const TRAFFIC_TONE: Record<Traffic, Tone> = { thong_thoang: 'ok', dong: 'muted', un_u: 'warn', ket_cung: 'bad' }
// Short chip text for scanning; the full, hedged meaning stays in the chip's tooltip and the route detail.
const STATUS = {
  ok: { tone: 'ok', label: 'No flooding observed', full: 'Within vehicle limits at points with data' },
  risky: { tone: 'warn', label: 'Possible flooding', full: 'Possible flooding on route' },
  blocked: { tone: 'bad', label: 'Deep flooding', full: 'Flooding exceeds vehicle limits' },
  unknown: { tone: 'muted', label: 'Missing flood data', full: 'Insufficient route flood data' },
} as const
const SHOWN = 3  // best route plus two alternatives; the rest behind "Show more"

/* ---------- which large road to take ---------- */

export function CorridorCard({ corridor, busy, selected, onSelect, onCamera }: {
  corridor: Corridor | null; busy: boolean; selected: number; onSelect: (id: number) => void; onCamera: (c: CameraReading) => void
}) {
  // The selected route stays drawn on the map; its detail starts folded and a click on it toggles the detail.
  const [collapsed, setCollapsed] = useState(true)
  const [all, setAll] = useState(false)
  if (!corridor) {
    return busy ? (
      <section className="corridor">
        <header><LoaderCircle size={15} className="spin" /><span><b>Main-road routes</b> · calculating…</span></header>
      </section>
    ) : null
  }
  if (!corridor.available) return null
  const best = corridor.routes.find((r) => r.chosen) ?? corridor.routes[0]
  const shown = all ? corridor.routes : corridor.routes.filter((r, i) => i < SHOWN || r.id === selected)
  const hidden = corridor.routes.length - shown.length
  // Only worth reading when the advice departs from Goong's own pick or nothing is safe.
  const why = best && (!best.is_goong || best.status === 'blocked') ? corridor.summary : null
  return (
    <section className={`corridor ${busy ? 'is-stale' : ''}`} aria-live="polite">
      <header>
        {busy ? <LoaderCircle size={15} className="spin" /> : <Route size={15} />}
        <span><b>Main-road routes</b> · {corridor.live ? `camera ${floodTimeLabel(corridor.checked_at)}` : 'forecast'}</span>
      </header>
      {why && <p className="corridor-sum">{why}</p>}
      <ol className="corr-list">
        {shown.map((r) => (
          <li key={r.id}>
            <RouteRow r={r} best={best} live={corridor.live} selected={r.id === selected} open={r.id === selected && !collapsed}
              onSelect={() => { if (r.id === selected) setCollapsed((c) => !c); else { setCollapsed(false); onSelect(r.id) } }} />
            {r.id === selected && !collapsed && <RouteDetail r={r} live={corridor.live} onCamera={onCamera} />}
          </li>
        ))}
      </ol>
      {hidden > 0 && <button type="button" className="link-btn corr-more" onClick={() => setAll(true)}>Show {hidden} more routes</button>}
      <CameraJobNote job={corridor.camera_job} busy={busy} />
      <details className="corridor-src faint">
        <summary>Sources and limitations</summary>
        {corridor.live_note && <p>{corridor.live_note}</p>}
        <p>
          {corridor.live ? `${corridor.cameras_read} cameras read, ${corridor.cameras_offline} offline. ` : ''}
          Camera <a href={PORTAL} target="_blank" rel="noreferrer">HCMC Traffic Portal</a>, Gemini reads up to 2 frames about 13 seconds apart; a single frame supports flood observation only, not traffic assessment. Routes by Goong; flooding based on tides, rain and IRD history.
        </p>
      </details>
    </section>
  )
}

/** "qua A, B, C" → the streets; an alternative is named by the first street the best route doesn't use. */
const streets = (label: string) => label.replace(/^qua\s+/, '').split(/,\s*/)
function shortName(r: CorridorRoute, best: CorridorRoute | undefined) {
  if (!best || r.id === best.id) return r.label
  const own = streets(best.label)
  const diff = streets(r.label).find((x) => !own.includes(x))
  return diff ? `qua ${diff}` : r.label
}

function routeStatus(r: CorridorRoute) {
  const unknownCoverage = !r.flood_forecast.length || r.flood_forecast.some((f) => f.knowledge !== 'known')
  return r.status === 'blocked' ? STATUS.blocked : unknownCoverage ? STATUS.unknown : STATUS[r.status]
}

function CameraJobNote({ job, busy }: { job: Corridor['camera_job']; busy: boolean }) {
  if (!job || !job.cameras_requested) return null
  const reading = job.id && busy
  return (
    <p className="faint corridor-note">
      {reading ? <><LoaderCircle size={12} className="spin" /> Reading {job.cameras_scheduled} cameras; routes will be recalculated when complete. </> : null}
      {job.state === 'not_scheduled' && `${job.cameras_requested} cameras unread. ${job.reason ?? ''} `}
      {job.state === 'busy' && `${job.reason}, try again in ${job.retry_after ?? 30} seconds. `}
      {job.dropped.length > 0 && `${job.dropped.length} cameras skipped this round; those segments remain unknown.`}
    </p>
  )
}

function RouteRow({ r, best, live, selected, open, onSelect }: {
  r: CorridorRoute; best: CorridorRoute | undefined; live: boolean; selected: boolean; open: boolean; onSelect: () => void
}) {
  const jam = r.hotspots.filter((h) => h.traffic === 'ket_cung' || h.traffic === 'un_u').length
  const st = routeStatus(r)
  const isBest = r.chosen
  const delta = best && !isBest ? r.eta_min - best.eta_min : 0
  return (
    <button type="button" className={`corr-row ${selected ? 'is-selected' : ''} ${open ? 'is-expanded' : ''} ${isBest ? 'is-best' : ''}`} onClick={onSelect} aria-expanded={open}>
      <span className="corr-main">
        {isBest && <span className="corr-best">Recommended</span>}
        <span className="corr-name">{shortName(r, best)}</span>
        <span className="corr-tags">
          <span title={st.full}><Tag tone={st.tone} icon={<Droplets size={13} />}>{st.label}</Tag></span>
          {jam > 0 && <Tag tone="bad" icon={<Cctv size={13} />}>{jam} congestion points</Tag>}
          {live && r.traffic_unknown > 0 && <span title={`${r.traffic_unknown} segments without camera confirmation of free-flowing traffic`}><Tag tone="muted" icon={<Cctv size={13} />}>{r.traffic_unknown} unknown segments</Tag></span>}
          {r.alleys.length > 0 && <Tag tone="warn">Via alleys</Tag>}
          {isBest && r.is_goong && <Tag tone="muted">Goong</Tag>}
        </span>
      </span>
      <span className="corr-time">
        {isBest || !best
          ? <><span className="display num">{minutes(r.eta_min)}</span><small>{distance(r.distance_m)}{r.delay_min > 0 ? ` · +${r.delay_min} min delay` : ''}</small></>
          : <span className={`corr-delta num ${delta > 0 ? 'slower' : ''}`}>{delta > 0 ? `+${delta} min` : delta < 0 ? `${delta} min` : 'Same time'}</span>}
      </span>
      <ChevronDown size={15} className="chev" />
    </button>
  )
}

function RouteDetail({ r, live, onCamera }: { r: CorridorRoute; live: boolean; onCamera: (c: CameraReading) => void }) {
  const notable = (h: Hotspot) => h.traffic === 'un_u' || h.traffic === 'ket_cung' || (h.depth_cm != null && h.depth_cm > 0) || h.flood_status === 'blocked'
  const calm = r.hotspots.filter((h) => !notable(h) && h.traffic)
  return (
    <div className="corr-detail">
      {(!r.chosen || r.delay_min > 0) && <p className="corr-full">{r.label} · {minutes(r.eta_min)} · {distance(r.distance_m)}{r.delay_min > 0 ? ` (free-flowing ${minutes(r.base_min)}, +${r.delay_min} min delay)` : ''}</p>}
      {r.reasons.length > 0 && <ul className="corr-reasons">{r.reasons.map((x, i) => <li key={i}><TriangleAlert size={13} />{x}</li>)}</ul>}
      {r.flood_forecast.length ? <ul className="corr-forecast">{r.flood_forecast.map((f, i) => (
        <li key={`${f.street}-${f.at}-${i}`}>
          <b>{f.street}</b> <Tag tone={floodPresentation(f).tone}>{floodPresentation(f).label}</Tag>
          <FloodEvidenceDetail check={f} />
        </li>
      ))}</ul> : <p className="faint">No flood forecasts for route segments; cannot confirm conditions are within vehicle limits.</p>}
      {live && (
        <ul className="corr-cams">
          {r.hotspots.map((h) => {
            const cam = h.cameras.find((c) => c.state === 'ok') ?? h.cameras[0]
            return (
              <li key={`${h.name}${h.along_m}`}>
                <button type="button" onClick={() => cam && onCamera(cam)}>
                  <i className={`cam-dot ${camClass(cam)}`} />
                  <span>{h.name}</span>
                  <small>{h.depth_cm ? `flooding ~${h.depth_cm} cm` : h.traffic_vi ?? cam?.traffic_vi ?? (h.coverage === 'scheduled' ? 'reading' : h.coverage === 'unknown' && cam?.state === 'not_read' ? 'unknown' : STATE_VI[cam?.state ?? 'not_read'])}</small>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {live && calm.length > 0 && !r.reasons.length && <p className="faint">{calm.length} camera points show free-flowing or busy but moving traffic.</p>}
      <p className="faint corr-caveat">Forecasts use the time each road is traversed; they do not confirm the full route or alley entry and exit.</p>
    </div>
  )
}

const STATE_VI: Record<CameraReading['state'], string> = {
  ok: 'read', offline: 'offline', stale: 'stale image', unusable: 'unusable image', no_model: 'AI unavailable', error: 'could not read', not_read: 'unread',
}

function camClass(c?: CameraReading | null) {
  if (!c || c.state !== 'ok') return 'cam-none'
  if (c.depth_cm) return 'cam-water'
  return `cam-${c.traffic ?? 'none'}`
}

/* ---------- one camera, live ---------- */

export function CameraPanel({ cam, canRead, onClose, onRead }: {
  cam: CameraReading; canRead: boolean; onClose: () => void; onRead: (id: string) => Promise<void>
}) {
  const [tick, setTick] = useState(() => Date.now())
  const [broken, setBroken] = useState(false)
  const [reading, setReading] = useState(false)
  useEffect(() => {
    const t = window.setInterval(() => setTick(Date.now()), 13e3)  // the camera refreshes about every 13 s
    return () => window.clearInterval(t)
  }, [cam.id])
  const r = cam.state === 'ok' ? cam : null
  return (
    <aside className="evidence card camera-panel" role="dialog" aria-label={`Camera ${cam.name}`}>
      <header>
        <div>
          <span className="faint">HCMC traffic camera · live</span>
          <h3 className="display">{cam.name}</h3>
        </div>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="evidence-body">
        {broken
          ? <p className="cam-off">Camera is offline.</p>
          : <img className="cam-img" src={`${cam.image_url}?t=${tick}`} alt={`Live camera image ${cam.name}`} onError={() => setBroken(true)} />}
        {r ? (
          <div className="cam-read">
            <div className="stop-tags flat">
              {r.traffic === 'khong_ro'
                ? <Tag tone="muted" icon={<Cctv size={13} />}>Traffic unknown</Tag>
                : r.traffic && r.traffic in TRAFFIC_TONE && <Tag tone={TRAFFIC_TONE[r.traffic as Traffic]} icon={<Cctv size={13} />}>{r.traffic_vi}</Tag>}
              <Tag tone={r.depth_cm ? 'water' : 'ok'} icon={<Droplets size={13} />}>{r.depth_cm ? `Flooding ~${r.depth_cm} cm` : r.depth_class === 'uot' ? 'Wet road, no visible flooding' : 'No flooding visible in image'}</Tag>
            </div>
            <p>{r.evidence}</p>
            <p className="faint">AI read at {(r.image_time ?? r.at ?? '').slice(11, 16)} {r.frames == null ? '· frame count not saved' : `from ${r.frames} frames`} · confidence {Math.round((r.confidence ?? 0) * 100)}%</p>
          </div>
        ) : (
          <p className="faint">{cam.state === 'not_read' || cam.state === 'error' ? `No AI result for this camera yet${canRead ? '' : ' (operator required for a new reading)'}; this segment remains unknown.` : `Unavailable: ${STATE_VI[cam.state]}.`}</p>
        )}
      </div>
      <footer>
        <a href={PORTAL} target="_blank" rel="noreferrer">Traffic Portal <ExternalLink size={12} /></a>
        {canRead && (
          <button type="button" className="btn btn-outline btn-sm" disabled={reading}
            onClick={async () => { setReading(true); try { await onRead(cam.id) } finally { setReading(false) } }}>
            {reading ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}Read with AI now
          </button>
        )}
      </footer>
    </aside>
  )
}
