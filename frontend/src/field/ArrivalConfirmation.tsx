import { useState } from 'react'
import { CheckCircle2 } from 'lucide-react'

export type ArrivalReport = { submission_id: string; lat: number; lon: number; vehicle_id: string;
  result: 'in' | 'tight' | 'no'; way_ids: number[]; mirrors_folded: boolean }
export type ArrivalConfirmationProps = {
  vehicle: { id: string; label: string }; lat: number; lon: number; wayIds: number[];
  /** Default is the existing main-app endpoint. Field shell supplies its offline sender. */
  endpoint?: string; token?: string; disabled?: boolean;
  submit?: (body: ArrivalReport) => Promise<string>; onConfirmed?: () => void;
}
import { api, submissionId } from './storage'
import './arrival.css'

export function ArrivalConfirmation({ vehicle, lat, lon, wayIds, endpoint = '/api/confirm', token = '', disabled = false, submit, onConfirmed }: ArrivalConfirmationProps) {
  const [busy, setBusy] = useState(false)
  const [folded, setFolded] = useState(false)
  const [message, setMessage] = useState('')
  const [done, setDone] = useState(false)
  async function send(result: ArrivalReport['result']) {
    setBusy(true); setMessage('')
    try {
      const body: ArrivalReport = { submission_id: submissionId(), lat, lon, vehicle_id: vehicle.id, result, way_ids: wayIds, mirrors_folded: folded }
      const status = submit ? await submit(body) : await api(endpoint, token, body).then(() => 'Arrival confirmation recorded.')
      setMessage(status); setDone(true); onConfirmed?.()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not submit. Please retry.') }
    finally { setBusy(false) }
  }
  return <section className="arrival-confirm" aria-labelledby="arrival-title">
    <div className="arrival-eyebrow"><CheckCircle2 size={19} /> ARRIVAL CONFIRMATION</div>
    <h2 id="arrival-title">You have arrived — how far did your {vehicle.label} get?</h2>
    <p>Confirm only the segment you travelled. Recorded as Observed evidence; it does not replace actual measurements.</p>
    <label className="arrival-check"><input type="checkbox" checked={folded} onChange={e => setFolded(e.target.checked)} disabled={busy || done || disabled} /> Mirrors were folded while passing</label>
    <div className="arrival-actions">{([['in', 'Can enter'], ['tight', 'Can enter, tight'], ['no', 'Cannot enter']] as const).map(([value, label]) =>
      <button key={value} type="button" onClick={() => void send(value)} disabled={busy || done || disabled || !wayIds.length}>{label}</button>)}</div>
    {message && <p role="status">{message}</p>}
  </section>
}
