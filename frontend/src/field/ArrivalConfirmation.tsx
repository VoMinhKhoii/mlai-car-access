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
      const status = submit ? await submit(body) : await api(endpoint, token, body).then(() => 'Đã ghi nhận xác nhận sau khi đến.')
      setMessage(status); setDone(true); onConfirmed?.()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Chưa gửi được. Hãy thử lại.') }
    finally { setBusy(false) }
  }
  return <section className="arrival-confirm" aria-labelledby="arrival-title">
    <div className="arrival-eyebrow"><CheckCircle2 size={19} /> XÁC NHẬN SAU KHI ĐẾN</div>
    <h2 id="arrival-title">Bạn đã đến — xe {vehicle.label} vào được tới đâu?</h2>
    <p>Chỉ xác nhận đoạn đã đi qua. Ghi nhận ở tầng Observed, không thay thế số đo thực tế.</p>
    <label className="arrival-check"><input type="checkbox" checked={folded} onChange={e => setFolded(e.target.checked)} disabled={busy || done || disabled} /> Xe đã gập gương khi đi qua</label>
    <div className="arrival-actions">{([['in', 'Vào được'], ['tight', 'Vào được, chật'], ['no', 'Không vào được']] as const).map(([value, label]) =>
      <button key={value} type="button" onClick={() => void send(value)} disabled={busy || done || disabled || !wayIds.length}>{label}</button>)}</div>
    {message && <p role="status">{message}</p>}
  </section>
}
