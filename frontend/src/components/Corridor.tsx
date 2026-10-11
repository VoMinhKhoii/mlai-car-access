import { Cctv, ChevronDown, Droplets, ExternalLink, LoaderCircle, RefreshCw, Route, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { CameraReading, Corridor, CorridorRoute, Hotspot, Traffic } from '../api'
import { Tag, distance, minutes, type Tone } from '../ds/ui'
import { FloodEvidenceDetail, floodPresentation, floodTimeLabel } from './Result'

const PORTAL = 'https://giaothong.hochiminhcity.gov.vn/Map.aspx'
const TRAFFIC_TONE: Record<Traffic, Tone> = { thong_thoang: 'ok', dong: 'muted', un_u: 'warn', ket_cung: 'bad' }
const STATUS = { ok: { tone: 'ok', label: 'Trong ngưỡng tại các điểm có dữ liệu' }, risky: { tone: 'warn', label: 'Có thể ngập' }, blocked: { tone: 'bad', label: 'Ngập quá ngưỡng xe' } } as const

/* ---------- which large road to take ---------- */

export function CorridorCard({ corridor, busy, selected, onSelect, onCamera }: {
  corridor: Corridor | null; busy: boolean; selected: number; onSelect: (id: number) => void; onCamera: (c: CameraReading) => void
}) {
  if (!corridor) {
    return busy ? (
      <section className="corridor">
        <header><LoaderCircle size={15} className="spin" /><span><b>Tuyến đường lớn</b> · đang đọc camera trên các tuyến (~30 giây)…</span></header>
      </section>
    ) : null
  }
  if (!corridor.available) return null
  return (
    <section className={`corridor ${busy ? 'is-stale' : ''}`} aria-live="polite">
      <header>
        {busy ? <LoaderCircle size={15} className="spin" /> : <Route size={15} />}
        <span><b>Tuyến đường lớn</b> · {corridor.live ? `camera ${floodTimeLabel(corridor.checked_at)}` : 'theo dự báo'}</span>
      </header>
      <p className="corridor-sum">{corridor.summary}</p>
      {corridor.live_note && <p className="faint corridor-note">{corridor.live_note}</p>}
      <ol className="corr-list">
        {corridor.routes.map((r) => (
          <li key={r.id}>
            <RouteRow r={r} open={r.id === selected} onSelect={() => onSelect(r.id)} />
            {r.id === selected && <RouteDetail r={r} live={corridor.live} onCamera={onCamera} />}
          </li>
        ))}
      </ol>
      <p className="faint corridor-src">
        {corridor.live ? `${corridor.cameras_read} camera đọc được, ${corridor.cameras_offline} mất tín hiệu. ` : ''}
        Nguồn: camera <a href={PORTAL} target="_blank" rel="noreferrer">Cổng thông tin giao thông TP.HCM</a>, Gemini đọc 2 khung hình cách 13 giây; tuyến Goong; ngập theo triều, mưa và lịch sử IRD.
      </p>
    </section>
  )
}

function RouteRow({ r, open, onSelect }: { r: CorridorRoute; open: boolean; onSelect: () => void }) {
  const jam = r.hotspots.filter((h) => h.traffic === 'ket_cung' || h.traffic === 'un_u').length
  const unknownCoverage = !r.flood_forecast.length || r.flood_forecast.some((f) => f.knowledge !== 'known')
  const st = r.status === 'blocked' ? STATUS.blocked : unknownCoverage ? { tone: 'muted' as const, label: 'Chưa đủ dữ liệu ngập trên tuyến' } : STATUS[r.status]
  return (
    <button type="button" className={`corr-row ${open ? 'is-open' : ''} ${r.chosen ? 'is-best' : ''}`} onClick={onSelect} aria-expanded={open}>
      <span className="corr-main">
        <span className="corr-name">{r.chosen && <b className="corr-best">Nên đi · </b>}{r.label}</span>
        <span className="corr-tags">
          {r.is_goong && <Tag tone="muted">Goong gợi ý</Tag>}
          <Tag tone={st.tone} icon={<Droplets size={13} />}>{st.label}</Tag>
          {jam > 0 && <Tag tone="bad" icon={<Cctv size={13} />}>{jam} điểm kẹt</Tag>}
          {r.alleys.length > 0 && <Tag tone="warn">Qua hẻm</Tag>}
        </span>
      </span>
      <span className="corr-time">
        <span className="display num">{minutes(r.eta_min)}</span>
        <small>{distance(r.distance_m)}{r.delay_min > 0 ? ` · +${r.delay_min}′ kẹt` : ''}</small>
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
      <p className="faint">Goong {minutes(r.base_min)} khi đường trống{r.delay_min > 0 ? `, +${r.delay_min} phút theo camera` : ''}.</p>
      {r.reasons.length > 0 && <ul className="corr-reasons">{r.reasons.map((x, i) => <li key={i}><TriangleAlert size={13} />{x}</li>)}</ul>}
      <p className="faint">Dự báo theo thời điểm đi qua từng đường, không xác nhận toàn tuyến hoặc lối vào và ra hẻm.</p>
      {r.flood_forecast.length ? <ul className="corr-forecast">{r.flood_forecast.map((f, i) => (
        <li key={`${f.street}-${f.at}-${i}`}>
          <b>{f.street}</b> <Tag tone={floodPresentation(f).tone}>{floodPresentation(f).label}</Tag>
          <FloodEvidenceDetail check={f} />
        </li>
      ))}</ul> : <p className="faint">Chưa có dữ liệu dự báo ngập cho các đoạn của tuyến; không thể kết luận trong ngưỡng xe.</p>}
      {live && (
        <ul className="corr-cams">
          {r.hotspots.map((h) => {
            const cam = h.cameras.find((c) => c.state === 'ok') ?? h.cameras[0]
            return (
              <li key={`${h.name}${h.along_m}`}>
                <button type="button" onClick={() => cam && onCamera(cam)}>
                  <i className={`cam-dot ${camClass(cam)}`} />
                  <span>{h.name}</span>
                  <small>{h.depth_cm ? `ngập ~${h.depth_cm} cm` : h.traffic_vi ?? STATE_VI[cam?.state ?? 'not_read']}</small>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {live && calm.length > 0 && !r.reasons.length && <p className="faint">{calm.length} điểm camera đều thông thoáng hoặc đông nhưng vẫn chạy.</p>}
    </div>
  )
}

const STATE_VI: Record<CameraReading['state'], string> = {
  ok: 'đã đọc', offline: 'mất tín hiệu', stale: 'ảnh cũ', unusable: 'ảnh không rõ', no_model: 'chưa có AI', error: 'chưa đọc được', not_read: 'chưa đọc',
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
          <span className="faint">Camera giao thông TP.HCM · trực tiếp</span>
          <h3 className="display">{cam.name}</h3>
        </div>
        <button type="button" className="icon-btn" aria-label="Đóng" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="evidence-body">
        {broken
          ? <p className="cam-off">Camera đang mất tín hiệu.</p>
          : <img className="cam-img" src={`${cam.image_url}?t=${tick}`} alt={`Ảnh trực tiếp camera ${cam.name}`} onError={() => setBroken(true)} />}
        {r ? (
          <div className="cam-read">
            <div className="stop-tags flat">
              {r.traffic && r.traffic in TRAFFIC_TONE && <Tag tone={TRAFFIC_TONE[r.traffic as Traffic]} icon={<Cctv size={13} />}>{r.traffic_vi}</Tag>}
              <Tag tone={r.depth_cm ? 'water' : 'ok'} icon={<Droplets size={13} />}>{r.depth_cm ? `Ngập ~${r.depth_cm} cm` : r.depth_class === 'uot' ? 'Đường ướt, không ngập' : 'Chưa thấy ngập trong ảnh'}</Tag>
            </div>
            <p>{r.evidence}</p>
            <p className="faint">AI đọc lúc {(r.image_time ?? r.at ?? '').slice(11, 16)} từ {r.frames ?? 1} khung hình · độ tin cậy {Math.round((r.confidence ?? 0) * 100)}%</p>
          </div>
        ) : (
          <p className="faint">{cam.state === 'not_read' || cam.state === 'error' ? 'Chưa có kết quả AI cho camera này.' : `Không dùng được: ${STATE_VI[cam.state]}.`}</p>
        )}
      </div>
      <footer>
        <a href={PORTAL} target="_blank" rel="noreferrer">Cổng thông tin giao thông <ExternalLink size={12} /></a>
        {canRead && (
          <button type="button" className="btn btn-outline btn-sm" disabled={reading}
            onClick={async () => { setReading(true); try { await onRead(cam.id) } finally { setReading(false) } }}>
            {reading ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}AI đọc ngay
          </button>
        )}
      </footer>
    </aside>
  )
}
