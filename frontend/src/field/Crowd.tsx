import { useEffect, useRef, useState } from 'react'
import { Camera, CheckCircle2, LocateFixed, MapPin, Ruler } from 'lucide-react'
import { MiniMap } from './MiniMap'
import { submissionId } from './storage'

type Location = { lat: number; lon: number }
type Alley = { way_id: number; name: string; distance_m: number; coords: number[][] }
type Reply = { status: string; reason: string }
async function crowdApi<T>(url: string, body?: unknown): Promise<T> {
  const r=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},...(body?{body:JSON.stringify(body)}:{})})
  const value=await r.json()
  if(!r.ok) throw new Error(typeof value.detail==='string'?value.detail:`Lỗi ${r.status}. Kiểm tra số đo, ảnh và vị trí.`)
  return value
}
export function Crowd() {
  const [step,setStep]=useState(0), [gps,setGps]=useState<Location|null>(null), [alleys,setAlleys]=useState<Alley[]>([]), [selected,setSelected]=useState<Alley|null>(null)
  const [error,setError]=useState(''), [busy,setBusy]=useState(false), [photo,setPhoto]=useState(''), [photoName,setPhotoName]=useState(''), [reply,setReply]=useState<Reply|null>(null)
  const [attest,setAttest]=useState(false)
  const [method,setMethod]=useState('lidar'), [width,setWidth]=useState(''), [nickname,setNickname]=useState('')
  const id=useRef(submissionId())
  useEffect(()=>{void crowdApi('/api/crowd/session',{}).catch(e=>setError(e.message))},[])
  function locate() {
    setBusy(true);setError('')
    if(!navigator.geolocation){setError('Điện thoại chưa hỗ trợ vị trí. Mở bằng Safari hoặc Chrome.');setBusy(false);return}
    navigator.geolocation.getCurrentPosition(async p=>{
      const position={lat:p.coords.latitude,lon:p.coords.longitude};setGps(position)
      try {
        await crowdApi('/api/crowd/session',{})
        const data=await crowdApi<{items:Alley[]}>(`/api/crowd/snap?lat=${position.lat}&lon=${position.lon}`)
        setAlleys(data.items);setSelected(data.items[0]||null)
        if(!data.items.length)throw new Error('Chưa tìm thấy hẻm gần GPS trong kho offline. Thử lại ngay tại hẻm.')
        setStep(1)
      }catch(e){setError(e instanceof Error?e.message:'Chưa tìm được hẻm.')}finally{setBusy(false)}
    },()=>{setBusy(false);setError('Cho phép vị trí chính xác và mở link HTTPS. Đứng ở nơi an toàn rồi thử lại.')},{enableHighAccuracy:true,timeout:15000,maximumAge:10000})
  }
  async function file(file?:File) {
    if(!file)return
    setAttest(false);setPhoto('');setPhotoName('');setError('')
    if(file.size>8*1024*1024){setError('Ảnh tối đa 8 MB. Chọn ảnh JPEG/PNG/WebP nhỏ hơn.');return}
    setPhoto(await new Promise<string>((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file)}).catch(()=>{setError('Không đọc được ảnh. Chọn lại ảnh JPEG/PNG/WebP.');return ''}));setPhotoName(file.name)
  }
  async function submit() {
    setBusy(true);setError('')
    try {
      const w=Number(width.replace(',','.'))
      if(!gps||!selected||!photo||!attest||!Number.isFinite(w)||w<.8||w>12)throw new Error('Cần GPS, đúng đoạn hẻm, ảnh phép đo và bề rộng 0,8–12 m.')
      const value=await crowdApi<Reply>('/api/crowd/measure',{submission_id:id.current,way_id:selected.way_id,...gps,width_m:w,method,measured_by:nickname.trim()||'Ẩn danh',photo_base64:photo,confirmed_way:true,photo_attestation:true,coverage_complete:false,measured_at:new Date().toISOString()})
      setReply(value)
    }catch(e){setError(e instanceof Error?e.message:'Chưa gửi được. Giữ trang và thử lại khi có mạng.')}finally{setBusy(false)}
  }
  return <div className="field-shell crowd-shell"><header className="field-header"><span className="field-brand"><span className="field-mark">n.</span>Ngõ Ngách</span><span className="count">CỘNG ĐỒNG</span></header><main>
    <div className="intro"><p className="eyebrow">GÓP MỘT SỐ ĐO CHO THÀNH PHỐ</p><h1>Đo hẻm nhà bạn<br />trong 30 giây.</h1><p>Không đăng nhập. Một số đo thật, một ảnh rõ.</p></div>
    {reply ? <section className="crowd-done"><CheckCircle2 size={42}/><h2>{reply.status==='pending'?'Đã nhận, đang chờ kiểm tra.':'Số đo đã được đối chiếu.'}</h2><p>{reply.reason}</p><p className="hint">Chỉ số đo đã được duyệt hoặc có đồng thuận mới góp vào bằng chứng Measured.</p></section> : <>
      <ol className="crowd-progress">{['GPS','Đúng hẻm','Đo & chụp'].map((s,i)=><li key={s} className={step===i?'current':''}>{i+1}. {s}</li>)}</ol>
      {step===0 && <section className="crowd-step"><LocateFixed size={32}/><h2>Bắt đầu ngay tại hẻm.</h2><p>GPS giúp tìm đúng đoạn. Không đoán số, không cần gửi tên.</p><button className="primary" disabled={busy} onClick={locate}>{busy?'Đang tìm vị trí…':'Lấy GPS & tìm hẻm'}<LocateFixed size={19}/></button></section>}
      {step===1 && <section className="crowd-step"><h2>Đây có phải hẻm của bạn?</h2><p className="hint">Đường đậm là đoạn OSM, chấm xanh là vị trí điện thoại. Đối chiếu hình dạng, tên và ghim trước khi xác nhận.</p>{selected && <MiniMap coords={selected.coords} gps={gps||undefined}/>}<label>Đoạn hẻm<select value={selected?.way_id||''} onChange={e=>setSelected(alleys.find(a=>a.way_id===Number(e.target.value))||null)}>{alleys.map(a=><option key={a.way_id} value={a.way_id}>{a.name} · {a.distance_m} m</option>)}</select></label>{selected && <a className="text-button" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/way/${selected.way_id}`}><MapPin size={16}/> Xem đoạn trên OpenStreetMap</a>}<button className="primary" disabled={!selected} onClick={()=>setStep(2)}>Đúng hẻm này <CheckCircle2 size={19}/></button><button className="text-button" onClick={locate} disabled={busy}>Lấy lại GPS</button></section>}
      {step===2 && <section className="crowd-step"><h2>Đo chỗ hẹp nhất.</h2><p className="hint">Đo ngang phần trống xe dùng được, trừ bậc thềm và vật cản. Không đo chéo, không lấy lộ giới.</p><label>Đo bằng<select value={method} onChange={e=>setMethod(e.target.value)}><option value="lidar">iPhone Measure có LiDAR</option><option value="tape">Thước dây</option></select></label><label>Bề rộng thông thủy (m)<div className="width-input"><input inputMode="decimal" value={width} onChange={e=>setWidth(e.target.value)} placeholder="2,40" maxLength={6}/><span>mét</span></div><small>0,8–12 m. Chỉ dùng thước dây hoặc máy có LiDAR.</small></label><label className="photo-input"><Camera size={25}/><span><strong>{photoName||'Bắt buộc: ảnh cho thấy phép đo'}</strong><small>Chụp thước hoặc kết quả Measure bắc ngang hẻm, thấy hai mép phần trống. Không cần khuôn mặt.</small></span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>void file(e.target.files?.[0])}/></label><label className="check-row"><input type="checkbox" checked={attest} onChange={e=>setAttest(e.target.checked)}/><span>Ảnh cho thấy phép đo bắc ngang phần trống của hẻm này và hai mép đo.</span></label><label>Biệt danh (không bắt buộc)<input value={nickname} onChange={e=>setNickname(e.target.value)} maxLength={80} placeholder="Có thể để trống"/></label><p className="hint">Ảnh được xóa metadata ngoài GPS/thời gian. GPS và ảnh dùng để đối chiếu; trang sân khấu chỉ hiện vị trí đoạn OSM.</p><button className="primary" disabled={busy||!photo||!width||!attest} onClick={()=>void submit()}>{busy?'Đang gửi…':'Gửi số đo để kiểm tra'}<Ruler size={19}/></button><button className="text-button" onClick={()=>setStep(1)}>Kiểm tra lại đoạn hẻm</button></section>}
    </>}{error&&<p className="notice error" role="alert">{error}</p>}<p className="crowd-safety">Đứng ở nơi an toàn, không giữa dòng xe. Xin phép cư dân lịch sự. “30 giây” là thao tác gửi, dành đủ thời gian đo an toàn.</p>
  </main></div>
}
