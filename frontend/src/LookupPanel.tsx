import { useState } from 'react'

interface Props { lat: number; lon: number; wayId: number; alley: string; google: boolean; grounding: boolean }
interface SV { available: boolean; status?: string; date?: string; image?: string; maps_url?: string; copyright?: string }
interface Place { id: string; name: string; type: string; address: string; maps_url: string }
interface Review { text: string; rating: number; when: string; author: string; author_url: string; keywords: string[] }
interface Details { name: string; rating: number | null; ratings: number | null; parking: Record<string, boolean> | null; website: string | null; maps_url: string; reviews: Review[] }

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText)
  return r.json()
}

const PARKING_VI: Record<string, string> = {
  freeParkingLot: 'Free car park', paidParkingLot: 'Paid car park', freeStreetParking: 'Free street parking',
  paidStreetParking: 'Paid street parking', valetParking: 'Valet parking', freeGarageParking: 'Free garage parking',
  paidGarageParking: 'Paid garage parking',
}

function highlight(text: string, words: string[]) {
  if (!words.length) return text
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))
}

export function LookupPanel({ lat, lon, wayId, alley, google, grounding }: Props) {
  const [sv, setSv] = useState<SV | null>(null)
  const [places, setPlaces] = useState<Place[] | null>(null)
  const [detail, setDetail] = useState<Details | null>(null)
  const [ask, setAsk] = useState<{ text: string; sources: { title: string; uri: string }[] } | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')

  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what); setErr('')
    try { await fn() } catch (e) { setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy('') }
  }

  if (!google && !grounding) return null
  return (
    <section className="lookup">
      <h4>Look up more <span className="live">live · not stored</span></h4>
      <div className="lookup-actions">
        {google && <button disabled={!!busy} onClick={() => run('sv', async () => setSv(await get(`/api/lookup/streetview?lat=${lat}&lon=${lon}&way_id=${wayId}`)))}>Street View</button>}
        {google && <button disabled={!!busy} onClick={() => run('places', async () => { setDetail(null); setPlaces((await get<{ places: Place[] }>(`/api/lookup/places?lat=${lat}&lon=${lon}`)).places) })}>Places in the alley</button>}
        {grounding && <button disabled={!!busy} onClick={() => run('ask', async () => setAsk(await get('/api/lookup/ask', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ lat, lon, alley }) })))}>Ask Gemini</button>}
      </div>
      {busy && <p className="hint">Looking up…</p>}
      {err && <p className="error">{err}</p>}
      {sv && (sv.available ? (
        <figure className="sv">
          <img src={sv.image} alt={`Street View near ${alley}`} />
          <figcaption>Photo {sv.date} · {sv.copyright ?? '© Google'} · <a href={sv.maps_url} target="_blank" rel="noreferrer">Open 360°</a></figcaption>
        </figure>
      ) : <p className="hint">No Street View imagery within 40 m ({sv.status}).</p>)}
      {places && !detail && (
        <ul className="places">
          {places.length === 0 && <li className="hint">Google has no places within 80 m.</li>}
          {places.map((p) => (
            <li key={p.id}><button className="link" onClick={() => run('detail', async () => setDetail(await get(`/api/lookup/place/${p.id}`)))}>{p.name}</button> <small>{p.type} · {p.address}</small></li>
          ))}
        </ul>
      )}
      {detail && (
        <div className="place">
          <button className="link" onClick={() => setDetail(null)}>← Back to list</button>
          <b>{detail.name}</b> {detail.rating && <small>★ {detail.rating} ({detail.ratings})</small>}
          {detail.parking && <p className="chips">{Object.entries(detail.parking).filter(([, v]) => v).map(([k]) => <span key={k} className="badge">{PARKING_VI[k] ?? k}</span>)}</p>}
          <ul className="reviews">
            {detail.reviews.map((r, i) => (
              <li key={i}><small>★{r.rating} · {r.when} · <a href={r.author_url} target="_blank" rel="noreferrer">{r.author}</a></small><p>{highlight(r.text, r.keywords)}</p></li>
            ))}
          </ul>
          <a href={detail.maps_url} target="_blank" rel="noreferrer">View on Google Maps</a>
        </div>
      )}
      {ask && (
        <div className="ask">
          <p>{ask.text}</p>
          <p className="attrib">Source: Google Maps{ask.sources.length > 0 && ' · '}{ask.sources.slice(0, 5).map((s, i) => <a key={i} href={s.uri} target="_blank" rel="noreferrer">{s.title?.replace(' - Google Maps', '')}</a>)}</p>
        </div>
      )}
      <p className="hint">Google content is for your own review before deciding; it is not stored or used as width evidence.</p>
    </section>
  )
}
