import { ArrowUpDown, Car, Clock, Crosshair, MapPin, ParkingSquare, Search, UserRound, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { api, type Intent, type SearchResult, type Vehicle } from '../api'
import { ChipMenu, Segmented, metres, minutes, vn } from '../ds/ui'

export interface Place { lat: number; lon: number; label: string }
export type VehicleMode = 'class' | 'model' | 'vetc'

/** One place input with Goong/OSM autocomplete. */
function PlaceField({ kind, value, onPick, placeholder, extra, near }: {
  kind: 'origin' | 'dest'; value: Place | null; onPick: (p: Place | null) => void; placeholder: string; extra?: React.ReactNode
  near?: { lat: number; lon: number } | null
}) {
  const [q, setQ] = useState<string | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const timer = useRef<number | undefined>(undefined)
  const text = q ?? value?.label ?? ''

  function type(v: string) {
    setQ(v)
    window.clearTimeout(timer.current)
    if (v.trim().length < 2) return setResults([])
    timer.current = window.setTimeout(() => api.search(v, near).then((r) => setResults(r.results)).catch(() => setResults([])), 250)
  }
  async function pick(r: SearchResult) {
    setResults([])
    setQ(null)
    let d: Place | null = r.lat != null ? { lat: r.lat, lon: r.lon!, label: r.label } : null
    if (!d && r.place_id) d = await api.place(r.place_id)
    if (d) onPick(d)
  }

  return (
    <div className="place">
      <span className={`place-mark ${kind}`} aria-hidden>{kind === 'dest' ? <MapPin size={16} strokeWidth={2.4} /> : <i />}</span>
      <div className="field">
        <input value={text} placeholder={placeholder} aria-label={kind === 'origin' ? 'Điểm đi' : 'Điểm đến'}
          onChange={(e) => type(e.target.value)} onFocus={(e) => e.target.select()}
          onBlur={() => window.setTimeout(() => { setResults([]); setQ(null) }, 150)} />
        {text && <button type="button" className="icon-btn sm" aria-label="Xoá" onClick={() => { setQ(''); onPick(null) }}><X size={15} /></button>}
        {extra}
      </div>
      {results.length > 0 && (
        <ul className="results card" role="listbox">
          {results.slice(0, 6).map((r, i) => (
            <li key={i}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(r)}>
                <Search size={15} /><span>{r.label}<small>{r.source}</small></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Directions(p: {
  origin: Place | null; dest: Place | null; setOrigin: (x: Place | null) => void; setDest: (x: Place | null) => void
  locating: boolean; onLocate: () => void
  vehicle?: Vehicle; fleet: { classes: Vehicle[]; models: Vehicle[] }
  vMode: VehicleMode; setVMode: (m: VehicleMode) => void; classId: string; setClassId: (s: string) => void
  modelId: string; setModelId: (s: string) => void; vetcLinked: boolean; openVetc: () => void; unlinkVetc: () => void
  intent: Intent; setIntent: (i: Intent) => void; dwell: number; setDwell: (n: number) => void
  arrive: string; setArrive: (s: string) => void; arriveNow: boolean; setArriveNow: (b: boolean) => void
}) {
  const v = p.vehicle
  const today = new Date(Date.now() + 7 * 3600e3).toISOString().slice(0, 10)
  const timeLabel = p.arriveNow ? 'Đi ngay' : `Đến ${p.arrive.slice(11, 16)}${p.arrive.slice(0, 10) === today ? '' : ` ${Number(p.arrive.slice(8, 10))}/${Number(p.arrive.slice(5, 7))}`}`
  return (
    <div className="directions">
      <div className="places">
        <PlaceField kind="origin" value={p.origin} onPick={p.setOrigin} near={p.dest ?? p.origin} placeholder="Điểm đi: vị trí của bạn"
          extra={<button type="button" className="icon-btn sm" aria-label="Dùng vị trí hiện tại" title="Dùng vị trí hiện tại" onClick={p.onLocate}>
            <Crosshair size={16} className={p.locating ? 'spin' : ''} /></button>} />
        <PlaceField kind="dest" value={p.dest} onPick={p.setDest} near={p.origin ?? p.dest} placeholder="Đến địa chỉ, hẻm…" />
        <span className="places-rail" aria-hidden />
        <button type="button" className="icon-btn swap" aria-label="Đổi điểm đi và điểm đến" onClick={() => { const o = p.origin; p.setOrigin(p.dest); p.setDest(o) }}>
          <ArrowUpDown size={16} />
        </button>
      </div>

      <div className="chips">
        <ChipMenu icon={<Car size={15} />} label={v ? shortName(v) : 'Chọn xe'}>
          {() => (
            <div className="menu vehicle-menu">
              <Segmented label="Cách chọn xe" value={p.vMode} onChange={p.setVMode}
                options={[{ value: 'class', label: 'Nhóm xe' }, { value: 'model', label: 'Mẫu xe' }, { value: 'vetc', label: 'Từ VETC' }]} />
              {p.vMode === 'class' && (
                <select className="select" value={p.classId} onChange={(e) => p.setClassId(e.target.value)} aria-label="Nhóm xe">
                  {p.fleet.classes.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              )}
              {p.vMode === 'model' && (
                <select className="select" value={p.modelId} onChange={(e) => p.setModelId(e.target.value)} aria-label="Mẫu xe">
                  {p.fleet.models.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              )}
              {p.vMode === 'vetc' && (p.vetcLinked
                ? <p className="vetc-row"><span className="tag brand">Mô phỏng</span> 51K-***.68 · Toyota Fortuner <button type="button" className="btn btn-ghost btn-sm" onClick={p.unlinkVetc}>Huỷ liên kết</button></p>
                : <button type="button" className="btn btn-tonal" onClick={p.openVetc}>Liên kết tài khoản VETC</button>)}
              {v && (
                <dl className="specs">
                  <div><dt>Rộng cả gương</dt><dd>{metres(v.mirror_width, 2)}{v.mirror_estimated ? '*' : ''}</dd></div>
                  <div><dt>Bán kính quay</dt><dd>{metres(v.turning_radius)}</dd></div>
                  <div><dt>Lội nước an toàn</dt><dd>{Math.round(v.safe_water_depth * 100)} cm</dd></div>
                  <div><dt>Quay đầu 3 điểm</dt><dd>≥ {metres(v.three_point_width)}</dd></div>
                </dl>
              )}
              {v?.kind === 'class' && <p className="note">Đang tính theo xe lớn nhất trong nhóm. Chọn đúng mẫu xe để kết quả sát hơn.</p>}
              {v?.mirror_estimated && <p className="note">* Hãng không công bố: lấy thân xe + 0,25 m.</p>}
            </div>
          )}
        </ChipMenu>

        <ChipMenu icon={p.intent === 'park' ? <ParkingSquare size={15} /> : <UserRound size={15} />}
          label={p.intent === 'park' ? `Đỗ xe · ${minutes(p.dwell)}` : 'Dừng đón/trả · 15 phút'}>
          {() => (
            <div className="menu">
              <Segmented label="Bạn sẽ" value={p.intent} onChange={p.setIntent}
                options={[{ value: 'park', label: 'Đỗ xe' }, { value: 'pickup', label: 'Dừng đón/trả' }]} />
              {p.intent === 'park' ? (
                <label className="menu-row">Ở lại
                  <select className="select" value={p.dwell} onChange={(e) => p.setDwell(Number(e.target.value))}>
                    {[30, 60, 120, 180, 240].map((d) => <option key={d} value={d}>{minutes(d)}</option>)}
                  </select>
                </label>
              ) : <p className="note">Dừng tối đa 15 phút. Lề đường chỉ có 1 làn xe: luật cho dừng ngắn, cấm đỗ (Luật 36/2024, Điều 18).</p>}
            </div>
          )}
        </ChipMenu>

        <ChipMenu icon={<Clock size={15} />} label={timeLabel} align="right">
          {(close) => (
            <div className="menu">
              <Segmented label="Thời gian" value={p.arriveNow ? 'now' : 'at'} onChange={(x) => p.setArriveNow(x === 'now')}
                options={[{ value: 'now', label: 'Đi ngay' }, { value: 'at', label: 'Đặt giờ đến' }]} />
              {!p.arriveNow && (
                <input className="input" type="datetime-local" value={p.arrive} onChange={(e) => p.setArrive(e.target.value)} aria-label="Giờ đến" />
              )}
              <button type="button" className="btn btn-primary btn-sm" onClick={close}>Xong</button>
            </div>
          )}
        </ChipMenu>
      </div>
    </div>
  )
}

function shortName(v: Vehicle) {
  if (v.kind === 'class') return v.label.replace(/\s*\(.*\)/, '')
  return v.label
}

export const fmtWidth = (lo: number, hi: number | null) => (hi == null ? `≥ ${vn(lo)} m` : `${vn(lo)}–${vn(hi)} m`)
