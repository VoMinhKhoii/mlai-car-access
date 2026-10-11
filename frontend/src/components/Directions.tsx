import { ArrowUpDown, Car, Clock, Crosshair, MapPin, ParkingSquare, Search, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api, type Intent, type SearchResult, type Vehicle } from '../api'
import { ChipMenu, Segmented, metres, minutes, vn } from '../ds/ui'
import { fromLocal } from '../datetime'

export interface Place { lat: number; lon: number; label: string }
export type VehicleMode = 'class' | 'model' | 'vetc'

/** One place input with Goong/OSM autocomplete. */
function PlaceField({ kind, value, onPick, placeholder, extra, near }: {
  kind: 'origin' | 'dest'; value: Place | null; onPick: (p: Place | null) => void; placeholder: string; extra?: React.ReactNode
  near?: { lat: number; lon: number } | null
}) {
  const [q, setQ] = useState<string | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [active, setActive] = useState(-1)
  const [status, setStatus] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const timer = useRef<number | undefined>(undefined)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  const text = q ?? value?.label ?? ''
  const expanded = results.length > 0

  const cancel = useCallback(() => {
    generation.current++
    window.clearTimeout(timer.current)
    controller.current?.abort()
    controller.current = null
  }, [])
  const dismiss = useCallback(() => {
    cancel()
    setResults([])
    setActive(-1)
    setStatus('idle')
    setQ(null)
  }, [cancel])
  useEffect(() => () => cancel(), [cancel])
  useEffect(() => { dismiss() }, [value, dismiss]) // external place changes also invalidate pending detail
  useEffect(() => {
    if (active >= 0) document.getElementById(`${id}-${active}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active, id])

  function type(v: string) {
    cancel()
    setQ(v)
    setResults([])
    setActive(-1)
    setStatus('idle')
    if (v.trim().length < 2) return
    const gen = generation.current
    const request = new AbortController()
    controller.current = request
    setStatus('loading')
    setMessage('Đang tìm địa chỉ…')
    timer.current = window.setTimeout(async () => {
      try {
        const r = await api.search(v, near, request.signal)
        if (gen !== generation.current || request.signal.aborted) return
        setResults(r.results.slice(0, 6))
        setStatus(r.results.length ? 'idle' : 'empty')
        setMessage('Không tìm thấy địa chỉ. Thử tên đường hoặc địa chỉ khác.')
      } catch {
        if (gen !== generation.current || request.signal.aborted) return
        setStatus('error')
        setMessage('Không tìm được địa chỉ do lỗi kết nối. Hãy nhập lại để thử.')
      }
    }, 250)
  }
  async function pick(r: SearchResult) {
    cancel()
    const gen = generation.current
    const request = new AbortController()
    controller.current = request
    setResults([])
    setActive(-1)
    setQ(r.label)
    setStatus('loading')
    setMessage('Đang lấy vị trí địa chỉ…')
    input.current?.focus()
    try {
      let place: Place | null = r.lat != null && r.lon != null ? { lat: r.lat, lon: r.lon, label: r.label } : null
      if (!place && r.place_id) place = await api.place(r.place_id, request.signal)
      if (gen !== generation.current || request.signal.aborted) return
      if (!place) throw new Error('Không có vị trí')
      setStatus('idle')
      setQ(null)
      onPick(place)
    } catch {
      if (gen !== generation.current || request.signal.aborted) return
      setStatus('error')
      setMessage('Không lấy được vị trí địa chỉ. Hãy tìm và chọn lại; điểm đã chọn chưa thay đổi.')
    }
  }
  function key(e: React.KeyboardEvent<HTMLInputElement>) {
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && results.length) {
      e.preventDefault()
      setActive((a) => e.key === 'ArrowDown' ? (a + 1) % results.length : (a < 0 ? results.length - 1 : (a - 1 + results.length) % results.length))
    } else if (e.key === 'Enter' && active >= 0 && expanded) {
      e.preventDefault()
      void pick(results[active])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      dismiss()
    }
  }

  return (
    <div className="place">
      <span className={`place-mark ${kind}`} aria-hidden>{kind === 'dest' ? <MapPin size={16} strokeWidth={2.4} /> : <i />}</span>
      <div className="field">
        <input ref={input} value={text} placeholder={placeholder} aria-label={kind === 'origin' ? 'Điểm đi' : 'Điểm đến'}
          role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={`${id}-list`}
          aria-activedescendant={expanded && active >= 0 ? `${id}-${active}` : undefined} aria-describedby={`${id}-status`} aria-busy={status === 'loading'}
          onChange={(e) => type(e.target.value)} onFocus={(e) => e.target.select()}
          onKeyDown={key} onBlur={dismiss} />
        {text && <button type="button" className="icon-btn sm" aria-label="Xoá" onPointerDown={(e) => e.preventDefault()}
          onClick={() => { dismiss(); setQ(''); onPick(null); input.current?.focus() }}><X size={15} /></button>}
        {extra}
      </div>
      <ul id={`${id}-list`} className="results card" role="listbox" aria-label={kind === 'origin' ? 'Gợi ý điểm đi' : 'Gợi ý điểm đến'} hidden={!expanded}>
        {results.map((r, i) => (
          <li key={r.place_id ?? `${r.label}-${i}`} id={`${id}-${i}`} role="option" aria-selected={active === i}
            onPointerDown={(e) => e.preventDefault()} onClick={() => void pick(r)} onPointerMove={() => setActive(i)}>
            <Search size={15} /><span>{r.label}<small>{r.source}</small></span>
          </li>
        ))}
      </ul>
      <div id={`${id}-status`} aria-live="polite" className={status === 'idle' ? 'sr-only' : `results card search-status ${status === 'error' ? 'error-line' : 'note'}`}>
        {status !== 'idle' ? message : expanded ? `${results.length} địa chỉ gợi ý. Dùng phím lên, xuống và Enter để chọn.` : ''}
      </div>
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
          label={p.intent === 'park' ? `Đỗ xe · ${minutes(p.dwell)}` : 'Dừng đón/trả · kiểm tra 15 phút'}>
          {() => (
            <div className="menu">
              <Segmented label="Bạn sẽ" value={p.intent} onChange={p.setIntent}
                options={[{ value: 'park', label: 'Đỗ xe' }, { value: 'pickup', label: 'Dừng đón/trả' }]} />
              {p.intent === 'park' ? (
                <label className="menu-row">Ở lại
                  <select className="select" value={p.dwell} onChange={(e) => p.setDwell(Number(e.target.value))}>
                    {[...new Set([30, 60, 120, 180, 240, p.dwell])].sort((a, b) => a - b).map((d) => <option key={d} value={d}>{minutes(d)}</option>)}
                  </select>
                </label>
              ) : <p className="note">Thời gian kiểm tra dự kiến: 15 phút. Đây không phải thời gian được luật cho phép dừng; cần kiểm tra biển báo và quy định tại điểm dừng.</p>}
            </div>
          )}
        </ChipMenu>

        <ChipMenu icon={<Clock size={15} />} label={timeLabel} align="right">
          {(close) => <TimeMenu arrive={p.arrive} arriveNow={p.arriveNow} close={close}
            onCommit={(value, now) => { p.setArrive(value); p.setArriveNow(now) }} />}
        </ChipMenu>
      </div>
    </div>
  )
}

function TimeMenu({ arrive, arriveNow, close, onCommit }: {
  arrive: string; arriveNow: boolean; close: () => void; onCommit: (value: string, now: boolean) => void
}) {
  const [draft, setDraft] = useState(arrive)
  const [now, setNow] = useState(arriveNow)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  function validate() {
    const valid = now || (!!fromLocal(draft) && !!input.current?.validity.valid)
    setError(valid ? '' : 'Nhập đầy đủ ngày và giờ đến hợp lệ (giờ Việt Nam, UTC+07:00). Chuyến đi chưa cập nhật; vẫn giữ giờ đã chọn trước đó.')
    return valid
  }
  function commit() {
    if (!validate()) {
      input.current?.focus()
      return
    }
    onCommit(now ? arrive : draft, now)
    close()
  }
  return (
    <div className="menu">
      <Segmented label="Thời gian" value={now ? 'now' : 'at'} onChange={(x) => { setNow(x === 'now'); setError('') }}
        options={[{ value: 'now', label: 'Đi ngay' }, { value: 'at', label: 'Đặt giờ đến' }]} />
      {!now && <>
        <label htmlFor={`${id}-arrival`} className="note">Giờ đến tại Việt Nam (UTC+07:00)</label>
        <input ref={input} id={`${id}-arrival`} className="input" type="datetime-local" required value={draft}
          onChange={(e) => setDraft(e.target.value)} onBlur={validate} aria-invalid={!!error} aria-describedby={`${id}-error`} />
      </>}
      <p id={`${id}-error`} className="error-line" aria-live="polite">{error}</p>
      <button type="button" className="btn btn-primary btn-sm" onClick={commit}>Xong</button>
    </div>
  )
}

function shortName(v: Vehicle) {
  if (v.kind === 'class') return v.label.replace(/\s*\(.*\)/, '')
  return v.label
}

export const fmtWidth = (lo: number, hi: number | null) => (hi == null ? `≥ ${vn(lo)} m` : `${vn(lo)}–${vn(hi)} m`)
