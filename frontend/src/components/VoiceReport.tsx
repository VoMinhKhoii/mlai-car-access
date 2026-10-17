import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, Mic, MicOff, Send } from 'lucide-react'
import { api, type StopPoint, type VoiceParseResult } from '../api'

export type ConfirmationResult = 'in' | 'tight' | 'no'
export type ExitMethod = 'through' | 'turned' | 'reversed' | 'unknown'

const RESULT_OPTIONS: { value: ConfirmationResult; label: string }[] = [
  { value: 'in', label: 'Can enter' },
  { value: 'tight', label: 'Tight fit' },
  { value: 'no', label: 'Cannot enter' },
]
const EXIT_OPTIONS: { value: ExitMethod; label: string }[] = [
  { value: 'through', label: 'Exit forwards' },
  { value: 'turned', label: 'Turn around' },
  { value: 'reversed', label: 'Reverse to exit' },
  { value: 'unknown', label: 'Unknown' },
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
      setError(parsed.question || 'Report not understood. Select the access result and exit method manually.')
    } else setError('Report not understood. Complete the choices manually.')
  }

  async function parseText() {
    if (!voiceEnabled || !text.trim() || busy) return
    setBusy(true)
    setError('')
    setSubmitted('')
    try { applyParse(await api.parseVoice(text.trim())) }
    catch (e) {
      setParse({ kind: 'unclear', reason: e instanceof Error ? e.message : String(e) })
      setError('Could not parse report. Type a report or use the choices below.')
    } finally { setBusy(false) }
  }

  function startListening() {
    if (!Speech) {
      setError('This browser does not support speech recognition. Type your report or choose manually.')
      return
    }
    recognition.current?.stop()
    const instance = new Speech()
    instance.lang = 'en-GB'
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
            setError('Could not parse report. Review the text and choose manually.')
          }).finally(() => setBusy(false))
        }
      }
    }
    instance.onerror = () => {
      setListening(false)
      setError('No speech received. Type your report or choose manually.')
    }
    instance.onend = () => setListening(false)
    recognition.current = instance
    setError('')
    setListening(true)
    try { instance.start() } catch {
      setListening(false)
      setError('Could not start speech recognition. Type your report or choose manually.')
    }
  }

  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    setSubmitted('')
    try {
      if (mode === 'confirm') {
        if (!result || !exit) { setError('Select how the vehicle entered and exited.'); return }
        await onConfirm(result, exit)
        setSubmitted('Confirmation submitted; awaiting operator review.')
      } else {
        const finalReason = reason.trim() || text.trim()
        if (!finalReason) { setError('Describe the blockage before submitting.'); return }
        await onBlockage(finalReason)
        setSubmitted('Blockage report submitted; awaiting operator review.')
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return (
    <section className="voice-report" aria-label="Report after arrival">
      <header className="voice-report-head">
        <div><h3>Stop report</h3><p>{stop.name} · sent only after your confirmation</p></div>
      </header>
      <div className="voice-mode" role="group" aria-label="Report type">
        <button type="button" disabled={busy} className={mode === 'confirm' ? 'is-active' : ''} onClick={() => { setMode('confirm'); setError(''); setSubmitted('') }}>Confirm entry/exit</button>
        <button type="button" disabled={busy} className={mode === 'blockage' ? 'is-active' : ''} onClick={() => { setMode('blockage'); setError(''); setSubmitted('') }}>Report blockage</button>
      </div>
      <label className="voice-field-label" htmlFor="voice-report-text">Speak or type your report</label>
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
          placeholder="Example: car entered, exited forwards" aria-describedby="voice-report-help" />
        <button type="button" className="icon-btn" disabled={busy} aria-label={listening ? 'Stop recording' : 'Speak report'} onClick={() => listening ? recognition.current?.stop() : startListening()}>
          {listening ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
      </div>
      <small id="voice-report-help" className="voice-help">
        {voiceEnabled ? 'Vietnamese speech recognition. Review the text before submitting.' : 'Voice reporting is disabled. Type your report and use the choices below.'}
      </small>
      {voiceEnabled && <button type="button" className="btn btn-ghost voice-parse" onClick={() => void parseText()} disabled={busy || !text.trim()}>
        {busy ? <LoaderCircle size={15} className="spin" /> : null} Parse report
      </button>}
      {mode === 'confirm' ? <>
        <fieldset className="voice-choice"><legend>How did the vehicle enter the stop?</legend><div className="voice-chips">
          {RESULT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={result === option.value}
            className={`chip ${result === option.value ? 'selected' : ''}`} disabled={busy} onClick={() => setResult(option.value)}>{option.label}</button>)}
        </div></fieldset>
        <fieldset className="voice-choice"><legend>How did the vehicle exit?</legend><div className="voice-chips">
          {EXIT_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={exit === option.value}
            className={`chip ${exit === option.value ? 'selected' : ''}`} disabled={busy} onClick={() => setExit(option.value)}>{option.label}</button>)}
        </div></fieldset>
        <details className="voice-caveat"><summary>Report location</summary><p>Vehicle {vehicleId}. Stop {stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}; destination {destination.lat.toFixed(5)}, {destination.lon.toFixed(5)}. Reports do not change fit or safety conclusions.</p></details>
      </> : <>
        <label className="voice-field-label" htmlFor="blockage-reason">Describe the blockage</label>
        <textarea id="blockage-reason" value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} rows={2} placeholder="Example: truck blocking the exit" />
        {stop.way_id == null && <p className="voice-status">This stop has no road ID for a blockage report.</p>}
      </>}
      {error && <p className="error-line" role="alert">{error}</p>}
      {submitted && <p className="ok-line" role="status">{submitted}</p>}
      <button type="button" className="btn btn-primary voice-submit" disabled={busy || (mode === 'blockage' && stop.way_id == null)} onClick={() => void submit()}>
        {busy ? <LoaderCircle size={16} className="spin" /> : <Send size={15} />} Submit report
      </button>
    </section>
  )
}
