import { useEffect, useState } from 'react'
import { api, readStored, store } from './storage'
import { MiniMap } from './MiniMap'

type Item = { id:string;way_id:number;lat:number;lon:number;width:number;method:string;nickname:string;status:string;reason:string;recorded_at:string;reviewer:string;official_bounds?:{lo:number;hi:number|null;detail:string;source:string}[] }
function ReviewPhoto({ id,token }: {id:string;token:string}) {
  const [url,setUrl]=useState('')
  useEffect(()=>{let value='',active=true;fetch(`/api/field/crowd/photo/${id}`,{headers:{Authorization:`Bearer ${token}`}}).then(r=>{if(!r.ok)throw new Error('Could not load photo');return r.blob()}).then(b=>{value=URL.createObjectURL(b);if(active)setUrl(value);else URL.revokeObjectURL(value)}).catch(()=>{});return()=>{active=false;if(value)URL.revokeObjectURL(value)}},[id,token])
  return url?<img className="review-photo" src={url} alt="Measurement photo for teammates to check both alley edges"/>:<p className="hint">Loading protected photo…</p>
}
export function Review() {
  const [token,setToken]=useState(()=>readStored('ngo-field-token','')), [input,setInput]=useState(''), [items,setItems]=useState<Item[]>([]), [selected,setSelected]=useState<Item|null>(null), [error,setError]=useState(''), [reviewer,setReviewer]=useState(''), [note,setNote]=useState(''), [ack,setAck]=useState(false), [busy,setBusy]=useState(false)
  async function load() {
    try {const data=await api<{items:Item[]}>('/api/field/crowd/review',token);setItems(data.items);setError('')}
    catch(e){setError(e instanceof Error?e.message:'Could not load review queue.')}
  }
  useEffect(()=>{if(token)void load()},[token])
  async function decide(decision:'approved'|'rejected') {
    if(!selected)return
    setBusy(true)
    try{await api(`/api/field/crowd/review/${selected.id}`,token,{decision,reviewer,note,official_override_ack:ack});setSelected(null);setNote('');setAck(false);await load()}
    catch(e){setError(e instanceof Error?e.message:'Could not complete review.')}finally{setBusy(false)}
  }
  return <div className="field-shell"><header className="field-header"><a className="field-brand" href="/field">Ngõ Ngách</a><span className="count">COMMUNITY REVIEW</span></header><main><div className="intro"><p className="eyebrow">ONLY VERIFIABLE MEASUREMENTS COUNT</p><h1>Verify before trusting.</h1><p>Compare the photo, cross-section, location and Official evidence. Reject unclear measurement photos or measure again.</p></div><form className="review-login" onSubmit={e=>{e.preventDefault();store('ngo-field-token',input);setToken(input)}}><label>Team code<input type="password" value={input} onChange={e=>setInput(e.target.value)} autoComplete="current-password"/></label><button className="primary">Open review queue</button></form>{error&&<p className="notice error" role="alert">{error}</p>}
    {selected?<section className="crowd-step"><button className="text-button" onClick={()=>setSelected(null)}>← Back to queue</button><h2>{selected.width} m · Way {selected.way_id}</h2><p>{selected.method} · {selected.nickname} · {selected.status}</p><p className="hint">{selected.reason}</p><ReviewPhoto id={selected.id} token={token}/><MiniMap gps={selected}/><a className="text-button" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/way/${selected.way_id}`}>Check way on OpenStreetMap ↗</a>{selected.official_bounds?.map((b,i)=><p className="notice" key={i}>Official: {b.lo}–{b.hi ?? "?"} m. {b.source}: {b.detail}</p>)}<label>Reviewer<input value={reviewer} onChange={e=>setReviewer(e.target.value)} maxLength={80}/></label><label>Photo/location review conclusion<textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={1000}/></label><label className="check-row"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/><span>I checked Official cadastral data and accept using this measurement where it differs.</span></label><div className="two-columns"><button className="primary" disabled={busy||!reviewer.trim()||!note.trim()} onClick={()=>void decide('approved')}>Approve Measured</button><button disabled={busy||!reviewer.trim()||!note.trim()} onClick={()=>void decide('rejected')}>Reject</button></div></section>:<section className="review-list">{items.length===0&&<p className="hint">No submissions, or the queue has not been opened.</p>}{items.map(i=><button key={i.id} onClick={()=>{setSelected(i);setAck(false);setNote('')}}><span><strong>{i.width} m · Way {i.way_id}</strong><small>{i.nickname} · {i.method}<br/>{i.reason}</small></span><span className="count">{i.status}</span></button>)}</section>}
    </main></div>
}
