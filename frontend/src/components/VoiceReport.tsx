import { useCallback, useEffect, useRef, useState } from 'react'
import { LoaderCircle, Mic, MicOff, Send, Trash2 } from 'lucide-react'
import { ApiError, api, type StopPoint, type VoiceParseResult } from '../api'
import { useVoiceCapture } from '../voice'

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

type ReportMode = 'confirm' | 'blockage'

export function VoiceReport({ stop, vehicleId, destination, voiceEnabled, audioEnabled, audioReady, audioModel, textProvider, onConfirm, onBlockage }: {
  stop: StopPoint
  vehicleId: string
  destination: { lat: number; lon: number }
  voiceEnabled: boolean
  audioEnabled: boolean
  audioReady: boolean
  audioModel: string | null
  textProvider: [string, string] | null
  onConfirm: (result: ConfirmationResult, exit: ExitMethod) => Promise<void>
  onBlockage: (reason: string) => Promise<void>
}) {
  const capture = useVoiceCapture()
  const [mode, setMode] = useState<ReportMode>('confirm')
  const [result, setResult] = useState<ConfirmationResult | ''>('')
  const [exit, setExit] = useState<ExitMethod | ''>('')
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [transcribing, setTranscribing] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [clarificationUsed, setClarificationUsed] = useState(false)
  const revision = useRef(0)
  const transcribeController = useRef<AbortController | null>(null)
  const parseController = useRef<AbortController | null>(null)

  const recording = capture.state === 'requesting' || capture.state === 'recording' || capture.state === 'stopping'
  const busy = transcribing || parsing || submitting
  const locked = busy || recording || !!submitted
  const audioAvailable = audioEnabled && audioReady

  const invalidatePending = useCallback((updateState = true): void => {
    revision.current += 1
    transcribeController.current?.abort()
    parseController.current?.abort()
    transcribeController.current = null
    parseController.current = null
    if (updateState) {
      setTranscribing(false)
      setParsing(false)
    }
  }, [])
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState !== 'hidden') return
      invalidatePending()
      capture.discard()
      setError('Bản ghi đang mở đã được xóa khi chuyển sang thẻ khác. Hãy ghi âm lại hoặc nhập nội dung.')
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [capture.discard, invalidatePending])
  useEffect(() => {
    if (audioAvailable || (capture.state === 'idle' && !capture.audio)) return
    invalidatePending()
    capture.discard()
  }, [audioAvailable, capture.audio, capture.discard, capture.state, invalidatePending])

  useEffect(() => () => invalidatePending(false), [invalidatePending])

  function clearParsedDraft(resetClarification = true): void {
    setResult('')
    setExit('')
    setReason('')
    setMode('confirm')
    if (resetClarification) setClarificationUsed(false)
    setError('')
    setSubmitted('')
  }

  function changeText(value: string): void {
    invalidatePending()
    setText(value)
    clearParsedDraft()
  }

  function applyParse(parsed: VoiceParseResult, sourceText: string): void {
    setResult('')
    setExit('')
    setReason('')
    if (parsed.kind === 'confirmation') {
      setMode('confirm')
      setResult(parsed.result ?? '')
      setExit(parsed.exit ?? '')
      return
    }
    if (parsed.kind === 'blockage') {
      setMode('blockage')
      setReason(parsed.reason ?? sourceText.trim())
      return
    }
    if (!clarificationUsed) {
      setClarificationUsed(true)
      setError(parsed.question || 'Chưa hiểu báo cáo. Hãy chọn kết quả và cách ra bằng tay.')
    } else {
      setError('Chưa hiểu báo cáo. Hãy hoàn tất các lựa chọn bằng tay.')
    }
  }

  function transcribeErrorMessage(cause: unknown): string {
    if (cause instanceof ApiError) {
      if (cause.status === 408) return 'Tải bản ghi quá chậm. Bản ghi vẫn còn trên thiết bị này; thử lại hoặc nhập nội dung.'
      if (cause.status === 413) return 'Bản ghi vượt quá giới hạn 1 MiB. Hãy ghi câu ngắn hơn.'
      if (cause.status === 415 || cause.status === 422) return 'Bản ghi không hợp lệ hoặc dài quá 20 giây. Hãy ghi lại hoặc nhập nội dung.'
      if (cause.status === 429) return 'Đã chạm hạn mức voice hoặc Gemini. Hãy thử lại sau; không tự gửi lại.'
      if (cause.status === 424) return 'Gemini Audio chưa sẵn sàng. Hãy nhập nội dung hoặc dùng lựa chọn thủ công.'
    }
    return 'Chưa chuyển được bản ghi thành văn bản. Bản ghi vẫn còn trên thiết bị này; thử lại hoặc nhập nội dung.'
  }

  async function transcribe(): Promise<void> {
    if (!audioAvailable || !capture.audio || busy || submitted) return
    invalidatePending()
    const currentRevision = revision.current
    const controller = new AbortController()
    transcribeController.current = controller
    setTranscribing(true)
    setError('')
    try {
      const response = await api.transcribeVoice(capture.audio, controller.signal)
      if (controller.signal.aborted || currentRevision !== revision.current) return
      capture.discard()
      if (response.kind === 'transcript' && response.text) {
        setText(response.text)
        clearParsedDraft()
      } else {
        setError(response.question || 'Chưa nhận ra lời nói rõ ràng. Hãy thử lại, sửa nội dung hoặc chọn bằng tay.')
      }
    } catch (cause) {
      if (controller.signal.aborted || currentRevision !== revision.current) return
      setError(transcribeErrorMessage(cause))
    } finally {
      if (currentRevision === revision.current) {
        setTranscribing(false)
        transcribeController.current = null
      }
    }
  }

  function cancelTranscription(): void {
    invalidatePending()
    setError('Đã hủy chuyển thành văn bản. Bản ghi vẫn còn trên thiết bị này.')
  }

  async function parseText(): Promise<void> {
    const sourceText = text.trim()
    if (!voiceEnabled || !sourceText || busy || recording || capture.audio || submitted || clarificationUsed) return
    invalidatePending()
    const currentRevision = revision.current
    const controller = new AbortController()
    parseController.current = controller
    clearParsedDraft(false)
    setParsing(true)
    setError('')
    try {
      const parsed = await api.parseVoice(sourceText, controller.signal)
      if (controller.signal.aborted || currentRevision !== revision.current) return
      applyParse(parsed, sourceText)
    } catch (cause) {
      if (controller.signal.aborted || currentRevision !== revision.current) return
      if (cause instanceof ApiError && cause.status === 424) {
        setError('Chưa cấu hình nhà cung cấp AI cho phân tích văn bản. Hãy dùng lựa chọn thủ công.')
      } else if (cause instanceof ApiError && cause.status === 429) {
        setError('Đã chạm hạn mức voice hoặc AI. Hãy thử lại sau; lựa chọn thủ công vẫn dùng được.')
      } else {
        setError('Không phân tích được. Hãy kiểm tra nội dung và chọn bằng tay.')
      }
    } finally {
      if (currentRevision === revision.current) {
        setParsing(false)
        parseController.current = null
      }
    }
  }

  async function submit(): Promise<void> {
    if (locked || capture.audio) return
    setSubmitting(true)
    setError('')
    try {
      if (mode === 'confirm') {
        if (!result || !exit) {
          setError('Chọn xe vào điểm dừng thế nào và đã ra bằng cách nào.')
          return
        }
        await onConfirm(result, exit)
        setSubmitted('Đã gửi xác nhận, đang chờ người điều hành duyệt.')
      } else {
        const finalReason = reason.trim() || text.trim()
        if (!finalReason) {
          setError('Mô tả vật cản trước khi gửi.')
          return
        }
        await onBlockage(finalReason)
        setSubmitted('Đã gửi báo cáo vật cản, đang chờ người điều hành duyệt.')
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setSubmitting(false)
    }
  }

  function selectMode(nextMode: ReportMode): void {
    if (locked || mode === nextMode) return
    invalidatePending()
    setMode(nextMode)
    setResult('')
    setExit('')
    setReason(nextMode === 'blockage' ? text.trim() : '')
    setError('')
    setSubmitted('')
  }

  const captureStatus = capture.state === 'requesting'
    ? 'Đang chờ quyền dùng micrô…'
    : capture.state === 'recording'
      ? `Đang ghi âm · ${capture.seconds} giây`
      : capture.state === 'stopping'
        ? 'Đang hoàn tất bản ghi…'
        : capture.audio
          ? `Bản ghi trên thiết bị này · ${capture.seconds} giây${capture.maxDurationReached ? ' · đã đạt giới hạn' : ''} · chưa gửi`
          : ''

  return (
    <section className="voice-report" aria-label="Báo cáo sau khi đến">
      <header className="voice-report-head">
        <div><h3>Báo cáo điểm dừng</h3><p>{stop.name} · chỉ gửi sau khi bạn xác nhận</p></div>
      </header>
      <div className="voice-mode" role="group" aria-label="Loại báo cáo">
        <button type="button" disabled={locked} className={mode === 'confirm' ? 'is-active' : ''} onClick={() => selectMode('confirm')}>Xác nhận vào/ra</button>
        <button type="button" disabled={locked} className={mode === 'blockage' ? 'is-active' : ''} onClick={() => selectMode('blockage')}>Báo vật cản</button>
      </div>
      <label className="voice-field-label" htmlFor="voice-report-text">Nội dung báo cáo</label>
      <textarea id="voice-report-text" className="voice-textarea" value={text} disabled={locked || !!capture.audio} onChange={(event) => changeText(event.target.value)}
        rows={2} placeholder="Ví dụ: xe vào được, đi thẳng ra" aria-describedby="voice-report-help" />
      <small id="voice-report-help" className="voice-help">
        {voiceEnabled
          ? textProvider
            ? `Khi bấm Phân tích, văn bản được gửi ${textProvider[0]} / ${textProvider[1]}. Tránh nội dung nhạy cảm nếu chưa xác minh điều khoản.`
            : 'Nhà cung cấp AI chưa sẵn sàng. Bạn vẫn có thể chọn kết quả bằng tay.'
          : 'Nhập nội dung hoặc chọn kết quả bằng tay.'}
      </small>
      {audioAvailable ? <>
        <p className="voice-audio-disclosure">Âm thanh chỉ gửi tới Gemini / {audioModel ?? 'model chưa xác định'} khi bạn bấm Chuyển thành văn bản. Ứng dụng không lưu bản ghi; Gemini xử lý theo điều khoản gói đã xác minh và có thể lưu log giới hạn.</p>
        <div className="voice-audio-actions">
          {(capture.state === 'idle' || capture.state === 'error') && (
            <button type="button" className="btn btn-outline voice-audio-button" disabled={locked} onClick={() => {
              invalidatePending()
              clearParsedDraft()
              setText('')
              void capture.start()
            }}>
              <Mic size={16} /> Bắt đầu ghi âm
            </button>
          )}
          {(capture.state === 'requesting' || capture.state === 'recording' || capture.state === 'stopping') && (
            <button type="button" className="btn btn-outline voice-audio-button" disabled={capture.state === 'stopping'} onClick={() => {
              if (capture.state === 'recording') capture.stop()
              else {
                invalidatePending()
                capture.discard()
                setError('Yêu cầu micrô đã được hủy. Hãy bắt đầu lại hoặc nhập nội dung.')
              }
            }}>
              {capture.state === 'recording' ? <><MicOff size={16} /> Dừng ghi âm</>
                : capture.state === 'requesting' ? 'Hủy yêu cầu micrô' : 'Đang hoàn tất…'}
            </button>
          )}
          {capture.audio && <>
            <button type="button" className="btn btn-ghost voice-audio-button" disabled={busy} onClick={() => {
              invalidatePending()
              clearParsedDraft()
              setText('')
              void capture.start()
            }}><Mic size={16} /> Ghi âm lại</button>
            <button type="button" className="btn btn-ghost voice-audio-button" disabled={busy} onClick={() => {
              invalidatePending()
              capture.discard()
              setError('')
            }}><Trash2 size={16} /> Xóa bản ghi</button>
            <button type="button" className="btn btn-primary voice-audio-button" disabled={busy || !capture.audio} onClick={() => void transcribe()}>
              {transcribing ? <LoaderCircle size={16} className="spin" /> : null} Chuyển thành văn bản
            </button>
          </>}
          {transcribing && <button type="button" className="btn btn-ghost voice-audio-button" onClick={cancelTranscription}>Hủy chuyển</button>}
        </div>
        {captureStatus && <p className="voice-status" role="status" aria-live="polite">{captureStatus}</p>}
      </> : audioEnabled
        ? <p className="voice-status" role="status">Gemini Audio chưa sẵn sàng trên máy chủ. Hãy dùng ô nhập và các lựa chọn bên dưới.</p>
        : <p className="voice-status" role="status">Ghi âm Gemini đang tắt. Bạn vẫn có thể nhập nội dung và chọn bằng tay.</p>}
      {voiceEnabled && <button type="button" className="btn btn-ghost voice-parse" onClick={() => void parseText()}
        disabled={busy || recording || !!capture.audio || !text.trim() || !!submitted || clarificationUsed}>
      </button>}
      {mode === 'confirm' ? <>
        <fieldset className="voice-choice"><legend>Xe vào điểm dừng thế nào?</legend><div className="voice-chips">
          {RESULT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={result === option.value}
            className={`chip ${result === option.value ? 'selected' : ''}`} disabled={locked} onClick={() => { setResult(option.value); setSubmitted('') }}>{option.label}</button>)}
        </div></fieldset>
        <fieldset className="voice-choice"><legend>Xe ra bằng cách nào?</legend><div className="voice-chips">
          {EXIT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={exit === option.value}
            className={`chip ${exit === option.value ? 'selected' : ''}`} disabled={locked} onClick={() => { setExit(option.value); setSubmitted('') }}>{option.label}</button>)}
        </div></fieldset>
        <details className="voice-caveat"><summary>Điểm gửi báo cáo</summary><p>Xe {vehicleId}. Điểm dừng {stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}; điểm đến {destination.lat.toFixed(5)}, {destination.lon.toFixed(5)}. Báo cáo không đổi kết luận phù hợp hoặc an toàn.</p></details>
      </> : <>
        <label className="voice-field-label" htmlFor="blockage-reason">Mô tả vật cản</label>
        <textarea id="blockage-reason" className="voice-textarea" value={reason} disabled={locked || !!capture.audio}
          onChange={(event) => { setReason(event.target.value); setSubmitted('') }} rows={2} placeholder="Ví dụ: xe tải chắn lối ra" />
        {stop.way_id == null && <p className="voice-status">Điểm dừng này chưa có mã đường để gửi báo cáo vật cản.</p>}
      </>}
      {(error || capture.error) && <p className="error-line" role="alert">{error || capture.error}</p>}
      {submitted && <p className="ok-line" role="status">{submitted}</p>}
      <button type="button" className="btn btn-primary voice-submit"
        disabled={locked || !!capture.audio || recording || (mode === 'confirm' && (!result || !exit)) || (mode === 'blockage' && (stop.way_id == null || !(reason.trim() || text.trim())))}
        onClick={() => void submit()}>
        {submitting ? <LoaderCircle size={16} className="spin" /> : <Send size={15} />} Gửi báo cáo
      </button>
    </section>
  )
}
