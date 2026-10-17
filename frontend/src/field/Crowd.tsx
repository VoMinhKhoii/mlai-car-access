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
  if(!r.ok) throw new Error(typeof value.detail==='string'?value.detail:`Error ${r.status}. Check the measurement, photo and location.`)
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
    if(!navigator.geolocation){setError('Location unavailable on this phone. Open in Safari or Chrome.');setBusy(false);return}
    navigator.geolocation.getCurrentPosition(async p=>{
      const position={lat:p.coords.latitude,lon:p.coords.longitude};setGps(position)
      try {
        await crowdApi('/api/crowd/session',{})
        const data=await crowdApi<{items:Alley[]}>(`/api/crowd/snap?lat=${position.lat}&lon=${position.lon}`)
        setAlleys(data.items);setSelected(data.items[0]||null)
        if(!data.items.length)throw new Error('No nearby alley in the offline data. Try again at the alley.')
        setStep(1)
      }catch(e){setError(e instanceof Error?e.message:'Could not find an alley.')}finally{setBusy(false)}
    },()=>{setBusy(false);setError('Allow precise location and open the HTTPS link. Stand somewhere safe and retry.')},{enableHighAccuracy:true,timeout:15000,maximumAge:10000})
  }
  async function file(file?:File) {
    if(!file)return
    setAttest(false);setPhoto('');setPhotoName('');setError('')
    if(file.size>8*1024*1024){setError('Photos must be at most 8 MB. Choose a smaller JPEG/PNG/WebP.');return}
    setPhoto(await new Promise<string>((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file)}).catch(()=>{setError('Could not read the photo. Select a JPEG/PNG/WebP again.');return ''}));setPhotoName(file.name)
  }
  async function submit() {
    setBusy(true);setError('')
    try {
      const w=Number(width.replace(',','.'))
      if(!gps||!selected||!photo||!attest||!Number.isFinite(w)||w<.8||w>12)throw new Error('GPS, the correct alley, a measurement photo and a width of 0.8–12 m are required.')
      const value=await crowdApi<Reply>('/api/crowd/measure',{submission_id:id.current,way_id:selected.way_id,...gps,width_m:w,method,measured_by:nickname.trim()||'Anonymous',photo_base64:photo,confirmed_way:true,photo_attestation:true,coverage_complete:false,measured_at:new Date().toISOString()})
      setReply(value)
    }catch(e){setError(e instanceof Error?e.message:'Could not submit. Keep this page open and retry when online.')}finally{setBusy(false)}
  }
  return <div className="field-shell crowd-shell"><header className="field-header"><span className="field-brand"><span className="field-mark">n.</span>Ngõ Ngách</span><span className="count">COMMUNITY</span></header><main>
    <div className="intro"><p className="eyebrow">CONTRIBUTE A MEASUREMENT TO THE CITY</p><h1>Measure your alley<br />in 30 seconds.</h1><p>No sign-in. One real measurement, one clear photo.</p></div>
    {reply ? <section className="crowd-done"><CheckCircle2 size={42}/><h2>{reply.status==='pending'?'Received, awaiting review.':'Measurement corroborated.'}</h2><p>{reply.reason}</p><p className="hint">Only reviewed or corroborated measurements contribute to Measured evidence.</p></section> : <>
      <ol className="crowd-progress">{['GPS','Correct alley','Measure & photograph'].map((s,i)=><li key={s} className={step===i?'current':''}>{i+1}. {s}</li>)}</ol>
      {step===0 && <section className="crowd-step"><LocateFixed size={32}/><h2>Start at the alley.</h2><p>GPS helps find the right segment. No guessing; no name required.</p><button className="primary" disabled={busy} onClick={locate}>{busy?'Finding location…':'Get GPS & find alley'}<LocateFixed size={19}/></button></section>}
      {step===1 && <section className="crowd-step"><h2>Is this your alley?</h2><p className="hint">The bold line is the OSM segment; the blue dot is your phone. Check the shape, name and pin before confirming.</p>{selected && <MiniMap coords={selected.coords} gps={gps||undefined}/>}<label>Alley segment<select value={selected?.way_id||''} onChange={e=>setSelected(alleys.find(a=>a.way_id===Number(e.target.value))||null)}>{alleys.map(a=><option key={a.way_id} value={a.way_id}>{a.name} · {a.distance_m} m</option>)}</select></label>{selected && <a className="text-button" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/way/${selected.way_id}`}><MapPin size={16}/> View segment on OpenStreetMap</a>}<button className="primary" disabled={!selected} onClick={()=>setStep(2)}>This is the alley <CheckCircle2 size={19}/></button><button className="text-button" onClick={locate} disabled={busy}>Refresh GPS</button></section>}
      {step===2 && <section className="crowd-step"><h2>Measure the narrowest point.</h2><p className="hint">Measure across the usable clearance, excluding steps and obstructions. Do not measure diagonally or use the planned road width.</p><label>Measurement method<select value={method} onChange={e=>setMethod(e.target.value)}><option value="lidar">iPhone Measure with LiDAR</option><option value="tape">Tape measure</option></select></label><label>Clear width (m)<div className="width-input"><input inputMode="decimal" value={width} onChange={e=>setWidth(e.target.value)} placeholder="2.40" maxLength={6}/><span>m</span></div><small>0.8–12 m. Use a tape measure or a LiDAR device only.</small></label><label className="photo-input"><Camera size={25}/><span><strong>{photoName||'Required: photo showing the measurement'}</strong><small>Photograph the tape or Measure result across the alley with both clear edges visible. No faces needed.</small></span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>void file(e.target.files?.[0])}/></label><label className="check-row"><input type="checkbox" checked={attest} onChange={e=>setAttest(e.target.checked)}/><span>The photo shows a measurement across this alley clearance and both measured edges.</span></label><label>Nickname (optional)<input value={nickname} onChange={e=>setNickname(e.target.value)} maxLength={80} placeholder="May be left blank"/></label><p className="hint">Photo metadata is stripped except GPS/time. GPS and photos support verification; the stage page shows only the OSM segment location.</p><button className="primary" disabled={busy||!photo||!width||!attest} onClick={()=>void submit()}>{busy?'Submitting…':'Submit measurement for review'}<Ruler size={19}/></button><button className="text-button" onClick={()=>setStep(1)}>Recheck alley segment</button></section>}
    </>}{error&&<p className="notice error" role="alert">{error}</p>}<p className="crowd-safety">Stand somewhere safe, out of traffic. Politely ask residents for permission. “30 seconds” refers to submission; allow enough time to measure safely.</p>
  </main></div>
}
