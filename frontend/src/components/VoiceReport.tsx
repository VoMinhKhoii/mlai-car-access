import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Mic, MicOff, Send } from 'lucide-react'
import { api, type StopPoint, type VoiceParseResult } from '../api'

export type ConfirmationResult = 'in' | 'tight' | 'no'
export type ExitMethod = 'through' | 'turned' | 'reversed' | 'unknown'

const RESULT_OPTIONS: { value: ConfirmationResult; label: string }[] = [
  { value: 'in', label: 'Vào được' },
  { value: 'tight', label: 'Hơi chật' },
  { value: 'no', label: 'Không vào được' },
]
const EXIT_OPTIONS: { value: ExitMethod; label: string }[] = [
  { value: 'through', label: 'Đi thẳng' },
  { value: 'turned', label: 'Quay đầu' },
  { value: 'reversed', label: 'Lùi ra' },
  { value: 'unknown', label: 'Chưa rõ' },
]

type RecognitionAlternative = { transcript: string }
type RecognitionEvent = Event & { results: ArrayLike<ArrayLike<RecognitionAlternative>> }
type RecognitionInstance = {
  lang: string
  interimResults: boolean
  onresult: ((event: RecognitionEvent) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}
type RecognitionConstructor = new () => RecognitionInstance

declare global {
  interface Window {
    SpeechRecognition?: RecognitionConstructor
    webkitSpeechRecognition?: RecognitionConstructor
  }
}

export function VoiceReport({ stop, vehicleId, destination, voiceEnabled, onConfirm, onBlockage }: {
  stop: StopPoint
  vehicleId: string
  destination: { lat: number; lon: number }
  voiceEnabled: boolean
  onConfirm: (result: ConfirmationResult, exit: ExitMethod) => Promise<void>
  onBlockage: (reason: string) => Promise<void>
}) {
  const [mode, setMode] = useState<'confirm' | 'blockage'>('confirm')
  const [result, setResult] = useState<ConfirmationResult | ''>('')
  const [exit, setExit] = useState<ExitMethod | ''>('')
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [parse, setParse] = useState<VoiceParseResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [listening, setListening] = useState(false)
  const [clarificationUsed, setClarificationUsed] = useState(false)
  const recognition = useRef<RecognitionInstance | null>(null)
  const Speech = typeof window === 'undefined' ? undefined : window.SpeechRecognition ?? window.webkitSpeechRecognition

  useEffect(() => () => recognition.current?.stop(), [])

  function applyParse(parsed: VoiceParseResult, fallbackText = text) {
    setParse(parsed)
    if (parsed.kind === 'confirmation') {
      setMode('confirm')
      if (parsed.result) setResult(parsed.result)
      if (parsed.exit) setExit(parsed.exit)
      setReason('')
    } else if (parsed.kind === 'blockage') {
      setMode('blockage')
      setReason(parsed.reason || fallbackText.trim())
    } else if (!clarificationUsed) {
      setClarificationUsed(true)
      setError(parsed.question || 'Chưa hiểu báo cáo. Hãy chọn kết quả và cách ra bằng tay.')
    } else setError('Chưa hiểu báo cáo. Hãy hoàn tất các lựa chọn bằng tay.')
  }

  async function parseText() {
    if (!voiceEnabled || !text.trim() || busy) return
    setBusy(true)
    setError('')
    setSubmitted('')
    try { applyParse(await api.parseVoice(text.trim())) }
    catch (e) {
      setParse({ kind: 'unclear', reason: e instanceof Error ? e.message : String(e) })
      setError('Không phân tích được. Hãy nhập báo cáo hoặc dùng các lựa chọn bên dưới.')
    } finally { setBusy(false) }
  }

  function startListening() {
    if (!Speech) {
      setError('Trình duyệt này chưa hỗ trợ nhận dạng giọng nói. Bạn vẫn có thể nhập nội dung hoặc chọn bằng tay.')
      return
    }
    recognition.current?.stop()
    const instance = new Speech()
    instance.lang = 'vi-VN'
    instance.interimResults = false
    instance.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript
      if (transcript) {
        setText(transcript)
        setError('')
        if (voiceEnabled) {
          setBusy(true)
          void api.parseVoice(transcript).then((parsed) => applyParse(parsed, transcript)).catch(() => {
            setParse({ kind: 'unclear' })
            setError('Không phân tích được. Hãy kiểm tra nội dung và chọn bằng tay.')
          }).finally(() => setBusy(false))
        }
      }
    }
    instance.onerror = () => {
      setListening(false)
      setError('Không nhận được giọng nói. Hãy nhập nội dung hoặc chọn bằng tay.')
    }
    instance.onend = () => setListening(false)
    recognition.current = instance
    setError('')
    setListening(true)
    try { instance.start() } catch {
      setListening(false)
      setError('Không thể bắt đầu nhận dạng. Hãy nhập nội dung hoặc chọn bằng tay.')
    }
  }

  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    setSubmitted('')
    try {
      if (mode === 'confirm') {
        if (!result || !exit) { setError('Chọn xe vào được thế nào và đã ra bằng cách nào.'); return }
        await onConfirm(result, exit)
        setSubmitted('Đã gửi xác nhận, đang chờ người điều hành duyệt.')
      } else {
        const finalReason = reason.trim() || text.trim()
        if (!finalReason) { setError('Mô tả vật cản trước khi gửi.'); return }
        await onBlockage(finalReason)
        setSubmitted('Đã gửi báo cáo vật cản, đang chờ người điều hành duyệt.')
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return (
    <section className="voice-report" aria-label="Báo cáo sau khi đến">
      <header className="voice-report-head">
        <div><h3>Báo cáo điểm dừng</h3><p>{stop.name} · chỉ gửi sau khi bạn xác nhận</p></div>
      </header>
      <div className="voice-mode" role="group" aria-label="Loại báo cáo">
        <button type="button" disabled={busy} className={mode === 'confirm' ? 'is-active' : ''} onClick={() => { setMode('confirm'); setError(''); setSubmitted('') }}>Xác nhận vào/ra</button>
        <button type="button" disabled={busy} className={mode === 'blockage' ? 'is-active' : ''} onClick={() => { setMode('blockage'); setError(''); setSubmitted('') }}>Báo vật cản</button>
      </div>
      <label className="voice-field-label" htmlFor="voice-report-text">Nói hoặc nhập nội dung</label>
      <div className="voice-input-row">
        <textarea id="voice-report-text" value={text} disabled={busy} onChange={(event) => {
          setText(event.target.value)
          if (parse) {
            setParse(null)
            if (parse.kind === 'blockage') setReason('')
            setError('')
          }
          setSubmitted('')
        }} rows={2}
          placeholder="Ví dụ: xe vào được, đi thẳng ra" aria-describedby="voice-report-help" />
        <button type="button" className="icon-btn" disabled={busy} aria-label={listening ? 'Dừng ghi âm' : 'Nói báo cáo'} onClick={() => listening ? recognition.current?.stop() : startListening()}>
          {listening ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
      </div>
      <small id="voice-report-help" className="voice-help">
        {voiceEnabled ? 'Nhận dạng tiếng Việt. Nội dung được xem lại trước khi gửi.' : 'Báo cáo giọng nói chưa bật. Bạn có thể nhập nội dung và chọn bên dưới.'}
      </small>
      {voiceEnabled && <button type="button" className="btn btn-ghost voice-parse" onClick={() => void parseText()} disabled={busy || !text.trim()}>
        {busy ? <LoaderCircle size={15} className="spin" /> : null} Phân tích nội dung
      </button>}
      {mode === 'confirm' ? <>
        <fieldset className="voice-choice"><legend>Xe vào điểm dừng thế nào?</legend><div className="voice-chips">
          {RESULT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={result === option.value}
            className={`chip ${result === option.value ? 'selected' : ''}`} disabled={busy} onClick={() => setResult(option.value)}>{option.label}</button>)}
        </div></fieldset>
        <fieldset className="voice-choice"><legend>Xe ra bằng cách nào?</legend><div className="voice-chips">
          {EXIT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={exit === option.value}
            className={`chip ${exit === option.value ? 'selected' : ''}`} disabled={busy} onClick={() => setExit(option.value)}>{option.label}</button>)}
        </div></fieldset>
        <details className="voice-caveat"><summary>Điểm gửi báo cáo</summary><p>Xe {vehicleId}. Điểm đỗ {stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}; điểm đến {destination.lat.toFixed(5)}, {destination.lon.toFixed(5)}. Báo cáo không đổi kết luận phù hợp hoặc an toàn.</p></details>
      </> : <>
        <label className="voice-field-label" htmlFor="blockage-reason">Mô tả vật cản</label>
        <textarea id="blockage-reason" value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} rows={2} placeholder="Ví dụ: xe tải chắn lối ra" />
        {stop.way_id == null && <p className="voice-status">Điểm dừng này chưa có mã đường để gửi báo cáo vật cản.</p>}
      </>}
      {error && <p className="error-line" role="alert">{error}</p>}
      {submitted && <p className="ok-line" role="status">{submitted}</p>}
      <button type="button" className="btn btn-primary voice-submit" disabled={busy || (mode === 'blockage' && stop.way_id == null)} onClick={() => void submit()}>
        {busy ? <LoaderCircle size={16} className="spin" /> : <Send size={15} />} Gửi báo cáo
      </button>
    </section>
  )
}
