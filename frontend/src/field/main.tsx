import { StrictMode, useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDown, ArrowUpRight, Camera, Check, CheckCircle2, ChevronLeft, CloudUpload, LocateFixed, LockKeyhole, MapPin, Navigation, Ruler, WifiOff } from 'lucide-react'
import { ArrivalConfirmation } from './ArrivalConfirmation'
import { ApiError, api, pending, readStored, savePending, store, submissionId } from './storage'
import type { Pending } from './storage'
import './field.css'
import { Crowd } from './Crowd'
import { Review } from './Review'
import { Stage } from './Stage'

type Place = { lat: number; lon: number; accuracy_m?: number }
type Campus = Place & { id: string; name: string; official_address: string }
type Vehicle = { id: string; label: string }
type Way = Place & { way_id: number; name: string; lo: number; hi: number | null; top_tier: string | null; review: boolean; thresholds_straddled: string[]; plan_requests: number }
type Recent = { submission_id: string; osm_way_id: string; width_m: string; tier: string; measured_by: string; date: string }
type Bootstrap = { campuses: Campus[]; vehicles: Vehicle[] }
const DEFAULT = { lat: 10.801617, lon: 106.714455 }
const format = (n: number) => n.toLocaleString('vi-VN', { maximumFractionDigits: 2 })
const distance = (a: Place, b: Place) => Math.hypot((a.lat-b.lat)*110574, (a.lon-b.lon)*109400)
const mapLink = (p: Place) => `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=19/${p.lat}/${p.lon}`
function why(w: Way) {
  if (w.review) return 'Các nguồn đang mâu thuẫn. Cần kiểm tra thực địa.'
  if (w.thresholds_straddled.length) return `Chưa quyết định được độ vừa xe ${w.thresholds_straddled.map(x => ({ vf3: 'VF 3', sedan: 'sedan', suv: 'SUV' })[x] || x).join(', ')}.`
  return w.top_tier === 'Measured' ? 'Đã có số đo, có thể kiểm tra lại khi hiện trạng thay đổi.' : 'Thiếu số đo thông thủy tại chỗ hẹp nhất.'
}

function FieldApp() {
  const [token, setToken] = useState(() => readStored('ngo-field-token', ''))
  const [tokenDraft, setTokenDraft] = useState('')
  const [unlocked, setUnlocked] = useState(false)
  const [boot, setBoot] = useState<Bootstrap>(() => readStored('ngo-field-bootstrap', { campuses: [], vehicles: [] }))
  const [center, setCenter] = useState<Place>(DEFAULT)
  const [gps, setGps] = useState<Place | null>(null)
  const [ways, setWays] = useState<Way[]>(() => readStored('ngo-field-ways', []))
  const [selected, setSelected] = useState<Way | null>(null)
  const [wayId, setWayId] = useState('')
  const [position, setPosition] = useState<Place | null>(null)
  const [positionKind, setPositionKind] = useState('')
  const [tab, setTab] = useState<'measure' | 'arrival'>('measure')
  const [method, setMethod] = useState('tape')
  const [turn, setTurn] = useState('unknown')
  const [measurer, setMeasurer] = useState(() => readStored('ngo-field-measurer', ''))
  const [photo, setPhoto] = useState<{ data: string; name: string; size: number } | null>(null)
  const [items, setItems] = useState<Pending[]>(pending)
  const [recent, setRecent] = useState<Recent[]>([])
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [online, setOnline] = useState(navigator.onLine)
  const [vehicleId, setVehicleId] = useState('toyota-vios')
  const [allWays, setAllWays] = useState(false)
  const syncing = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const formSection = useRef<HTMLElement>(null)
  const alive = useRef(true)

  const loadRecent = useCallback(async () => {
    try { const r = await api<{ items: Recent[] }>('/api/field/recent', token); setRecent(r.items) } catch { /* Preserve last view offline. */ }
  }, [token])

  useEffect(() => {
    if (!token) return
    let current = true
    api<Bootstrap>('/api/field/bootstrap', token).then(data => {
      if (!current) return
      setBoot(data); store('ngo-field-bootstrap', data); setUnlocked(true); setError('')
    }).catch(e => {
      if (!current) return
      if (!(e instanceof ApiError) && boot.campuses.length) { setUnlocked(true); setStatus('Chế độ ngoại tuyến. Số đo sẽ chờ gửi lại.') }
      else setError(e.message)
    })
    return () => { current = false }
  // Cached bootstrap is intentionally read only on initial load.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    if (!unlocked) return
    let current = true
    const d = .018
    const bbox = `${center.lon-d},${center.lat-d},${center.lon+d},${center.lat+d}`
    setLoading(true)
    api<{ items: Way[]; available: boolean }>(`/api/field/queue?limit=60&bbox=${bbox}`, token).then(data => {
      if (!current) return
      if (!data.available) throw new Error('Kho bằng chứng chưa sẵn sàng trên máy chủ.')
      const sorted = data.items.sort((a,b) => distance(a,center)-distance(b,center))
      setWays(sorted); store('ngo-field-ways', sorted)
      setSelected(s => s && sorted.some(w => w.way_id === s.way_id) ? s : sorted[0] || null)
      if (!gps) setWayId(String(sorted[0]?.way_id || ''))
      setError('')
    }).catch(e => { if (current) setError(`${e.message} Danh sách lưu gần nhất vẫn dùng được.`) }).finally(() => { if (current) setLoading(false) })
    void loadRecent()
    return () => { current = false }
  }, [center, token, unlocked, loadRecent, gps])

  const retry = useCallback(async () => {
    if (syncing.current || !token || !navigator.onLine) return
    syncing.current = true
    try {
      for (const entry of pending()) {
        try {
          await api(entry.endpoint, token, entry.body)
          const remaining = pending().filter(x => x.id !== entry.id)
          if (!savePending(remaining)) { setError('Đã gửi nhưng không cập nhật được bộ nhớ máy. Có thể gửi lại an toàn nhờ mã bản ghi.'); break }
          setItems(remaining)
        } catch (e) {
          const message = e instanceof Error ? e.message : 'Chưa kết nối được.'
          const remaining = pending().map(x => x.id === entry.id ? { ...x, error: message } : x)
          savePending(remaining); setItems(remaining)
          if (!(e instanceof ApiError) || e.status === 401 || e.status >= 500) break
        }
      }
      void loadRecent()
    } finally { syncing.current = false }
  }, [token, loadRecent])

  useEffect(() => {
    alive.current = true
    function network() { setOnline(navigator.onLine); if (navigator.onLine) void retry() }
    window.addEventListener('online', network); window.addEventListener('offline', network)
    const timer = setInterval(() => void retry(), 30000)
    if (unlocked) void retry()
    return () => { alive.current = false; window.removeEventListener('online', network); window.removeEventListener('offline', network); clearInterval(timer) }
  }, [retry, unlocked])

  useEffect(() => {
    if ('serviceWorker' in navigator && import.meta.env.PROD) {
      navigator.serviceWorker.register('/field-sw.js', { scope: '/field' }).then(() => {
        void navigator.serviceWorker.ready.then(() => { if (alive.current) setStatus('Trang đã sẵn sàng để mở lại khi mất mạng.') })
      }).catch(() => setStatus('Không lưu được trang ngoại tuyến. Giữ tab này mở khi đi đo.'))
    }
  }, [])

  async function send(endpoint: string, body: Record<string, unknown>) {
    const id = String(body.submission_id)
    const entry: Pending = { id, endpoint, body }
    const durable = savePending([...pending(), entry])
    if (durable) setItems(pending())
    try {
      await api(endpoint, token, body)
      if (durable) {
        const remaining = pending().filter(x => x.id !== id)
        savePending(remaining); setItems(remaining)
      }
      void loadRecent()
      return 'Đã gửi và nạp vào bằng chứng. Cảm ơn bạn!'
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Mất kết nối.'
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![401,408,429].includes(e.status)) {
        if (durable) { const remaining = pending().filter(x => x.id !== id); savePending(remaining); setItems(remaining) }
        throw e
      }
      if (!durable) throw new Error(`Chưa gửi và chưa lưu được: bộ nhớ máy đầy hoặc bị chặn. Giữ biểu mẫu, chọn ảnh nhỏ hơn rồi thử lại. ${message}`)
      const updated = pending().map(x => x.id === id ? { ...x, error: message } : x)
      savePending(updated); setItems(updated)
      return `Đã lưu trên máy, chờ gửi lại. ${message}`
    }
  }

  function locate() {
    setStatus('Đang lấy GPS chính xác…'); setError('')
    if (!navigator.geolocation) { setError('Trình duyệt không hỗ trợ GPS. Nhập tọa độ tại chỗ đo.'); return }
    navigator.geolocation.getCurrentPosition(async ({ coords }) => {
      const p = { lat: coords.latitude, lon: coords.longitude, accuracy_m: Math.round(coords.accuracy) }
      setGps(p); setCenter(p); setPosition(p); setPositionKind('GPS điện thoại')
      setStatus(`Đã lấy GPS, sai số khoảng ${Math.round(coords.accuracy)} m. Kiểm tra đoạn đường trước khi đo.`)
      try {
        const data = await api<{ items: { way_id: number; name: string; distance_m: number }[] }>(`/api/field/snap?lat=${p.lat}&lon=${p.lon}`, token)
        if (data.items[0]) { setWayId(String(data.items[0].way_id)); setStatus(`GPS gần ${data.items[0].name} (${data.items[0].distance_m} m). Way ID đã điền, hãy kiểm tra.`) }
      } catch (e) { setError(e instanceof Error ? e.message : 'Chưa ghép được GPS với đường.') }
    }, () => { setError('Chưa lấy được GPS. Cho phép vị trí trên Safari/Chrome và mở bằng HTTPS; hoặc nhập tọa độ tại chỗ đo.') }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 15000 })
  }

  async function choosePhoto(file?: File) {
    if (!file) { setPhoto(null); return }
    if (file.size > 8*1024*1024) { setError('Ảnh tối đa 8 MB. Chọn ảnh khác; giữ ảnh gốc có GPS nếu có.'); return }
    try {
      const data = await new Promise<string>((resolve,reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = reject; r.readAsDataURL(file) })
      setPhoto({ data, name: file.name, size: file.size }); setError('')
    } catch { setError('Không đọc được ảnh. Chọn lại ảnh gốc.') }
  }

  async function submitMeasurement(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault(); setError(''); setStatus('')
    if (!position) { setError('Lấy GPS hoặc nhập tọa độ thực tế tại vị trí đo trước khi gửi.'); return }
    const values = new FormData(e.currentTarget)
    const num = (key: string) => values.get(key) ? Number(String(values.get(key)).replace(',', '.')) : null
    const width = num('width_m')
    if (width === null || !Number.isFinite(width) || width<.5 || width>15) { setError('Bề rộng cần từ 0,5 đến 15 m.'); return }
    if (!Number.isInteger(Number(wayId)) || Number(wayId)<=0) { setError('Way ID phải là số nguyên dương.'); return }
    const body = { submission_id: submissionId(), measured_at: new Date().toISOString(), way_id: Number(wayId), width_m: width, method, measured_by: measurer.trim(), ...position,
      position_note: String(values.get('position_note') || ''), note: String(values.get('note') || ''), obstructions: values.getAll('obstructions'),
      turn_space: turn, turn_width_m: turn === 'yes' ? num('turn_width_m') : null, turn_length_m: turn === 'yes' ? num('turn_length_m') : null,
      coverage_complete: values.get('coverage_complete') === 'on', photo_base64: photo?.data || null }
    setSaving(true)
    try {
      const message = await send('/api/field/measure', body)
      store('ngo-field-measurer', measurer); setStatus(message)
      form.current?.reset(); setPhoto(null); setTurn('unknown'); setMethod('tape')
    } catch (e) { setError(e instanceof Error ? e.message : 'Chưa lưu được số đo.') }
    finally { setSaving(false) }
  }

  const vehicle = boot.vehicles.find(v => v.id === vehicleId) || boot.vehicles[0]
  const arrivalPosition = position || gps
  return <div className="field-shell">
    <header className="field-header"><a href="/field" className="field-brand"><span className="field-mark">n.</span><span>Ngõ Ngách<small>BỘ ĐO HIỆN TRƯỜNG</small></span></a><span className={`connection ${online ? '' : 'offline'}`}>{online ? <span className="live-dot" /> : <WifiOff size={15} />}{online ? 'Có mạng' : 'Ngoại tuyến'}</span></header>
    {!unlocked ? <main className="unlock"><div className="lock-symbol"><LockKeyhole size={28} /></div><p className="eyebrow">DÀNH CHO NHÓM ĐI ĐO</p><h1>Mỗi số đo,<br />bớt một lần đoán.</h1><p>Đo phần hẻm xe thực sự đi qua được. Ghi nguồn, vị trí và thời điểm để cả nhóm dùng ngay.</p><form onSubmit={e => { e.preventDefault(); const value = tokenDraft.trim(); store('ngo-field-token', value); setToken(value); if (value === token) api<Bootstrap>('/api/field/bootstrap', value).then(data => { setBoot(data); setUnlocked(true); setError('') }).catch(e => setError(e.message)) }}><label>Mã nhóm<input type="password" autoComplete="current-password" value={tokenDraft} onChange={e => setTokenDraft(e.target.value)} required placeholder="Nhập FIELD_TOKEN được chia sẻ" /></label><button className="primary" type="submit">Mở bộ đo <ArrowUpRight size={19} /></button></form><p className="hint">Mã được nhớ trên máy này. Dùng điện thoại cá nhân và đổi mã sau chuyến đo.</p>{error && <p className="notice error" role="alert">{error}</p>}</main> : <main>
      <div className="intro"><p className="eyebrow">TỪ ƯỚC LƯỢNG ĐẾN SỐ ĐO</p><h1>Đo hẻm hôm nay.</h1><p>Đo chỗ hẹp nhất. Ghi đúng phần xe đi được.</p></div>
      <nav className="field-tabs" aria-label="Công việc"><button className={tab==='measure' ? 'active' : ''} onClick={() => setTab('measure')}><Ruler size={18} /> Đo bề rộng</button><button className={tab==='arrival' ? 'active' : ''} onClick={() => setTab('arrival')}><CheckCircle2 size={18} /> Đã đến nơi</button></nav>
      {(error || status) && <div className={`notice ${error ? 'error' : ''}`} role={error ? 'alert' : 'status'}>{error || status}<button type="button" onClick={() => { setError(''); setStatus('') }} aria-label="Đóng thông báo">×</button></div>}
      <section className="location-block" aria-label="Chọn khu vực"><button type="button" className="gps-button" onClick={locate}><LocateFixed size={20} /> Dùng GPS của tôi <ArrowUpRight size={17} /></button><label className="campus-label">Hoặc chọn khuôn viên HUTECH<select aria-label="Khuôn viên HUTECH" defaultValue="" onChange={e => { const c=boot.campuses.find(x=>x.id===e.target.value); if(c) { setCenter(c); setAllWays(false) } }}><option value="" disabled>Điện Biên Phủ · 475A</option>{boot.campuses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><p className="hint">Chọn trường để tìm hẻm. Khi đo, lấy GPS ngay tại chỗ.</p></section>
      {tab==='measure' && <>
        <section className="next-section" aria-labelledby="next-title"><div className="section-heading"><div><p className="eyebrow">01 / CHỌN ĐOẠN</p><h2 id="next-title">Đo tiếp ở đâu?</h2></div><span className="count">{ways.length} đoạn</span></div><p className="hint">Gần vị trí đã chọn, ưu tiên từ hàng chờ bằng chứng.</p>
          {loading && <p role="status">Đang tìm những đoạn cần đo…</p>}
          {!loading && !ways.length && <p className="notice">Chưa có đoạn trong khu vực này. Chọn trường khác hoặc lấy GPS để thử lại.</p>}
          <ol className="way-list">{ways.slice(0, allWays ? 12 : 3).map((w,i) => <li key={w.way_id} className={selected?.way_id===w.way_id ? 'selected' : ''}>
            <button type="button" className="way-select" onClick={() => { setSelected(w); setWayId(String(w.way_id)) }} aria-pressed={selected?.way_id===w.way_id}><span className="way-index">{selected?.way_id===w.way_id ? <Check size={18} /> : String(i+1).padStart(2,'0')}</span><span className="way-content"><strong>{w.name || `Đoạn không tên · ${w.way_id}`}</strong><span className="range">{format(w.lo)}–{w.hi===null ? '?' : format(w.hi)} m <span>· {w.top_tier || 'Chưa có nguồn'}</span></span><small>{why(w)}</small></span></button>
            <a className="pin-link" href={mapLink(w)} target="_blank" rel="noreferrer" aria-label={`Mở ghim ${w.name || w.way_id} trên bản đồ`}><MapPin size={16} /> {Math.round(distance(center,w))} m <ArrowUpRight size={14} /></a>
          </li>)}</ol>
          {ways.length>3 && <button type="button" className="text-button" onClick={() => setAllWays(!allWays)}>{allWays ? 'Thu gọn danh sách' : 'Xem thêm đoạn cần đo'} <ArrowDown size={16} /></button>}
          {selected && <button type="button" className="primary" onClick={() => formSection.current?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })}>Đo đoạn đã chọn <Ruler size={18} /></button>}
        </section>
        <section className="measurement-section" ref={formSection}><div className="section-heading"><div><p className="eyebrow">02 / GHI SỐ ĐO</p><h2>Phần xe đi được</h2></div><Ruler size={24} /></div>
          <form ref={form} onSubmit={e => void submitMeasurement(e)}>
            <label>Way ID <input name="way_id" inputMode="numeric" value={wayId} onChange={e=>setWayId(e.target.value)} required /><small>Được ghép từ GPS hoặc đoạn đã chọn. Có thể sửa.</small></label>
            <fieldset><legend>Phương pháp</legend><div className="method-options">{([['tape','Thước dây'],['lidar','LiDAR'],['pacing','Bước chân']] as const).map(([value,label]) => <label key={value} className={method===value ? 'chosen' : ''}><input type="radio" name="method" checked={method===value} onChange={()=>setMethod(value)} />{label}</label>)}</div><p className="tier-line">{method==='pacing' ? 'Observed · Bước chân là quan sát, sai số ±0,5 m.' : 'Measured · Đo thực tế, khoảng sai số ±0,1 m.'}</p></fieldset>
            <label className="width-label">Bề rộng thông thủy hẹp nhất<div className="width-input"><input name="width_m" type="text" maxLength={6} inputMode="decimal" placeholder="2,40" required aria-describedby="width-help" /><span>mét</span></div><small id="width-help">0,5–15 m. Trừ bậc thềm, chậu cây và vật cản hiện có.</small></label>
            <label className="check-row"><input type="checkbox" name="coverage_complete" /><span>Tôi đã kiểm tra toàn bộ đoạn này và đo chỗ hẹp nhất.<small>Không chọn nếu chỉ đo một vị trí. Một mẫu không chứng nhận cả hẻm.</small></span></label>
            <div className="position-heading"><h3>Vị trí dọc hẻm</h3><button type="button" className="text-button" onClick={locate}><LocateFixed size={17} /> Lấy GPS</button></div>
            <p className="hint">{positionKind || 'Chưa có vị trí đo. Lấy GPS hoặc nhập tọa độ thực tế.'}{position?.accuracy_m!==undefined ? ` · Sai số ±${position.accuracy_m} m` : ''}</p>
            <div className="two-columns"><label>Vĩ độ<input type="number" step="any" value={position?.lat ?? ''} required onChange={e => { setPosition({ lat:Number(e.target.value),lon:position?.lon ?? center.lon }); setPositionKind('Tọa độ nhập tay') }} placeholder="10.8016" /></label><label>Kinh độ<input type="number" step="any" value={position?.lon ?? ''} required onChange={e => { setPosition({lat:position?.lat ?? center.lat,lon:Number(e.target.value)}); setPositionKind('Tọa độ nhập tay') }} placeholder="106.7145" /></label></div>
            <label>Mốc dễ nhận ra<input name="position_note" maxLength={500} placeholder="Ví dụ: chỗ hẹp nhất, trước nhà số 12" /></label>
            <fieldset><legend>Vật cản tại lúc đo</legend>{([['steps','Bậc thềm / dốc lên nhà'],['motorbikes','Xe máy đậu'],['stall','Sạp hàng']] as const).map(([value,label]) => <label className="check-row" key={value}><input type="checkbox" name="obstructions" value={value} />{label}</label>)}</fieldset>
            <label>Cuối hẻm có chỗ quay xe?<select value={turn} onChange={e=>setTurn(e.target.value)}><option value="unknown">Chưa kiểm tra</option><option value="yes">Có khoảng trống</option><option value="no">Không</option></select><small>Ghi hiện trạng, chưa phải xác nhận xe cụ thể quay được.</small></label>
            {turn==='yes' && <div className="two-columns"><label>Rộng (m)<input name="turn_width_m" type="number" min="0.5" max="100" step="0.01" inputMode="decimal" /></label><label>Dài (m)<input name="turn_length_m" type="number" min="0.5" max="100" step="0.01" inputMode="decimal" /></label></div>}
            <label className="photo-input"><Camera size={22} /><span><strong>{photo ? photo.name : 'Thêm ảnh hiện trường'}</strong><small>{photo ? `${(photo.size/1024/1024).toFixed(1)} MB · Giữ nguyên ảnh gốc` : 'Ảnh gốc tối đa 8 MB, giữ EXIF GPS nếu có. Không cần khuôn mặt.'}</small></span><input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif" onChange={e=>void choosePhoto(e.target.files?.[0])} /></label>
            {photo && <button type="button" className="text-button" onClick={()=>setPhoto(null)}>Bỏ ảnh đã chọn</button>}
            <label>Người đo<input name="measured_by" autoComplete="name" value={measurer} onChange={e=>setMeasurer(e.target.value)} maxLength={100} required placeholder="Tên của bạn" /></label>
            <label>Ghi chú thêm (tùy chọn)<textarea name="note" maxLength={1000} rows={2} placeholder="Vật cản cố định hay tạm thời, hướng đi…" /></label>
            <div className="safety-note"><Navigation size={18} /><p>Đứng ở nơi an toàn, không đứng giữa dòng xe. Xin phép cư dân khi đo sát nhà.</p></div>
            <button className="primary" type="submit" disabled={saving}>{saving ? 'Đang lưu số đo…' : 'Lưu số đo hiện trường'} <CloudUpload size={20} /></button>
          </form>
        </section>
      </>}
      {tab==='arrival' && <section className="arrival-section"><p className="eyebrow">CHỈ GHI NHẬN ĐOẠN BẠN ĐÃ ĐI QUA</p><label>Mẫu xe<select value={vehicleId} onChange={e=>setVehicleId(e.target.value)}>{boot.vehicles.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}</select></label><label>Way ID của đoạn vừa đi<input inputMode="numeric" value={wayId} onChange={e=>setWayId(e.target.value)} /></label>{vehicle ? <ArrivalConfirmation key={`${vehicle.id}-${wayId}`} vehicle={vehicle} lat={arrivalPosition?.lat ?? center.lat} lon={arrivalPosition?.lon ?? center.lon} wayIds={Number(wayId)>0 ? [Number(wayId)] : []} disabled={!arrivalPosition || !Number.isInteger(Number(wayId)) || Number(wayId)<=0} submit={body=>send('/api/field/confirm',body)} /> : null}{!arrivalPosition && <p className="notice">Lấy GPS ở trên và chọn Way ID để xác nhận xe đã đến.</p>}</section>}
      <section className="pending-section"><div className="section-heading"><h2>Chờ gửi <span className="count">{items.length}</span></h2><button type="button" className="text-button" onClick={()=>void retry()}>Gửi lại <CloudUpload size={17} /></button></div><p className="hint">{items.length ? 'Đã lưu trên điện thoại. Tự thử lại khi có mạng, mỗi 30 giây và khi mở trang.' : 'Số đo được giữ trên máy trước khi gửi. Không đóng trang nếu có báo chưa lưu được.'}</p>{items.map(item=><div className="pending-item" key={item.id}><strong>{item.endpoint.includes('measure') ? `Đo ${String(item.body.width_m)} m` : 'Xác nhận đã đến'} · Way {String(item.body.way_id || (item.body.way_ids as number[])?.[0])}</strong><p>{item.error || 'Chờ kết nối'}</p><button type="button" className="text-button" onClick={()=>{ const next=pending().filter(x=>x.id!==item.id); if(savePending(next)) setItems(next) }}>Bỏ bản chờ này</button></div>)}</section>
      <section className="recent-section"><p className="eyebrow">CẢ NHÓM VỪA GHI NHẬN</p><h2>Số đo gần đây</h2>{recent.length ? <ul>{recent.slice(0,5).map((r,i)=><li key={r.submission_id || i}><Ruler size={18} /><div><strong>{r.width_m} m <span>· {r.tier}</span></strong><small>Way {r.osm_way_id} · {r.measured_by}<br />{new Date(r.date).toLocaleString('vi-VN')}</small></div></li>)}</ul> : <p className="hint">Chưa có số đo. Hãy ghi nhận đoạn đầu tiên của chuyến đi.</p>}</section>
      <footer><span>Ngõ Ngách · Đo thực tế, ghi rõ nguồn.</span><button type="button" onClick={()=>{ store('ngo-field-token',''); setToken(''); setTokenDraft(''); setUnlocked(false) }}><ChevronLeft size={15} /> Đổi mã nhóm</button></footer>
    </main>}
  </div>
}

const page = location.pathname === '/field/review' ? <Review /> : location.pathname === '/field/qr' ? <Stage /> : new URLSearchParams(location.search).get('crowd') === '1' ? <Crowd /> : <FieldApp />
createRoot(document.getElementById('root')!).render(<StrictMode>{page}</StrictMode>)
