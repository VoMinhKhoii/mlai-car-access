import { Check, LoaderCircle, MapPin, MessageCircle, Mic, Send, Waves, X, Route } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type AgentEvent, type AgentPlan, type AgentEvidence, type WayEvidence, type Estimate } from '../api'
import type { Place } from './Directions'
import { EvidencePanel } from './Evidence'
import './Agent.css'

const SUGGESTIONS = [
  'Tôi lái Fortuner tới Hẻm 113/4 Võ Duy Ninh, ở 2 tiếng. Đỗ ở đâu?',
  'Còn xe VF 3 của vợ tôi thì sao?',
  'Vios tới Hẻm 220/9 Xô Viết Nghệ Tĩnh lúc 20:00, ở 2 tiếng',
  'VF 5 đón khách ở Hẻm 328 Xô Viết Nghệ Tĩnh',
]
const STEPS: Record<string, { label: string; icon: typeof MapPin }> = {
  understand: { label: 'Hiểu câu hỏi', icon: MessageCircle },
  tim_dia_diem: { label: 'Tìm địa điểm', icon: MapPin },
  lap_ke_hoach: { label: 'Kiểm tra bề rộng hẻm & lập kế hoạch', icon: Route },
  muc_trieu: { label: 'Xem mực triều', icon: Waves },
}
interface Step { name: string; args: Record<string, unknown>; summary?: string }
interface Turn { question: string; steps: Step[]; answer: string; blind: string; error?: string; blindError?: string; evidence?: AgentEvidence[]; progress?: string; estimate?: Estimate }
interface Speech {
  lang: string; interimResults: boolean
  onresult: ((e: { results: { transcript: string }[][] }) => void) | null
  onerror: (() => void) | null; onend: (() => void) | null
  start: () => void; stop: () => void
}
type SpeechWindow = Window & { SpeechRecognition?: new () => Speech; webkitSpeechRecognition?: new () => Speech }

const STORAGE_KEY = 'ngo-ngach-agent-v1'
function restore() {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (data?.version === 1 && Array.isArray(data.turns) && Array.isArray(data.contents) && Array.isArray(data.blindContents)) {
      return { ...data, turns: data.turns.filter((t: Turn) => typeof t?.question === 'string' && typeof t.answer === 'string' && Array.isArray(t.steps)).slice(-20) }
    }
  } catch { /* Private browsing, corrupt data, and disabled storage are recoverable. */ }
  return { turns: [], contents: [], blindContents: [] }
}
function recentHistory(history: Record<string, unknown>[]) {
  if (history.length <= 40) return history
  const first = history.findIndex((c, i) => i >= history.length - 40 && c.role === 'user' && Array.isArray(c.parts) && c.parts.some((p) => typeof p.text === 'string'))
  return first >= 0 ? history.slice(first) : []
}

export function Agent({ origin, onPlan, open, setOpen }: { origin: Place | null; onPlan: (p: AgentPlan) => void; open: boolean; setOpen: (open: boolean) => void }) {
  const [saved] = useState(restore)
  const [evidence, setEvidence] = useState<{ way: WayEvidence; at: [number, number] } | null>(null)
  const [evidenceError, setEvidenceError] = useState('')
  const abort = useRef<AbortController | null>(null)
  const requestIds = useRef<string[]>([])
  const [input, setInput] = useState('')
  const [compare, setCompare] = useState(false)
  const [busy, setBusy] = useState(false)
  const [hasHistory, setHasHistory] = useState(saved.contents.length > 0)
  const [listening, setListening] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const [turns, setTurns] = useState<Turn[]>(saved.turns)
  const contents = useRef<Record<string, unknown>[]>(saved.contents)
  const blindContents = useRef<Record<string, unknown>[]>(saved.blindContents)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const launchRef = useRef<HTMLButtonElement>(null)
  const sending = useRef(false)
  const speech = useRef<Speech | null>(null)
  const Recognition = (window as SpeechWindow).SpeechRecognition ?? (window as SpeechWindow).webkitSpeechRecognition

  useEffect(() => { if (open) inputRef.current?.focus() }, [open])
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [turns, open])
  useEffect(() => () => { speech.current?.stop(); abort.current?.abort(); requestIds.current.forEach((id) => { void api.cancelAgent(id).catch(() => {}) }) }, [])
  useEffect(() => {
    try {
      const data = JSON.stringify({ version: 1, turns: turns.slice(-20), contents: contents.current, blindContents: blindContents.current })
      if (data.length < 350000) localStorage.setItem(STORAGE_KEY, data)
    } catch { /* Storage quota/permission failures must not interrupt the conversation. */ }
  }, [turns, busy])

  function stop() {
    abort.current?.abort()
    requestIds.current.forEach((id) => { void api.cancelAgent(id).catch(() => {}) })
  }

  async function openEvidence(chip: AgentEvidence) {
    setEvidenceError('')
    try {
      const way = await api.wayEvidence(chip.way_id, chip.lat, chip.lon, null)
      setEvidence({ way, at: [chip.lat, chip.lon] })
    } catch { setEvidenceError('Chưa tải được bằng chứng. Hãy thử lại.') }
  }

  function close() {
    speech.current?.stop()
    setOpen(false)
    launchRef.current?.focus()
  }

  function dictate() {
    if (!Recognition) return
    if (listening) { speech.current?.stop(); return }
    const rec = new Recognition()
    speech.current = rec
    rec.lang = 'vi-VN'
    rec.interimResults = false
    rec.onresult = (e) => { setInput(e.results[0][0].transcript); inputRef.current?.focus() }
    rec.onerror = () => { setListening(false); setVoiceError('Chưa nghe được. Bạn có thể nhập câu hỏi.') }
    rec.onend = () => setListening(false)
    try { rec.start(); setListening(true); setVoiceError('') } catch { setVoiceError('Chưa bật được mic. Bạn có thể nhập câu hỏi.') }
  }

  async function send(question = input.trim()) {
    if (!question || sending.current) return
    sending.current = true
    const controller = new AbortController()
    abort.current = controller
    requestIds.current = []
    speech.current?.stop()
    setBusy(true)
    setInput('')
    const index = turns.length
    setTurns((ts) => [...ts, { question, steps: [{ name: 'understand', args: {} }], answer: '', blind: '' }])
    const update = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, i) => i === index ? fn(t) : t))
    const near: [number, number] | null = origin ? [origin.lat, origin.lon] : null
    // Keep the baseline's own history; it never receives tool evidence from Ngõ Ngách.
    const blindBody = { contents: blindContents.current, message: question, origin: near, tools: false }
    async function run(blind: boolean) {
      const requestId = crypto.randomUUID()
      requestIds.current.push(requestId)
      try {
        const payload = { ...(blind ? blindBody : { contents: contents.current, message: question, origin: near, tools: true }), request_id: requestId }
        await api.agent(payload, (e: AgentEvent) => {
          if (e.type === 'done') { if (blind) blindContents.current = recentHistory(e.contents); else { contents.current = recentHistory(e.contents); setHasHistory(true) } }
          if (e.type === 'ui' && !blind) onPlan(e.plan)
          if (e.type === 'answer') update((t) => ({ ...t, steps: blind ? t.steps : t.steps.map((s) => s.name === 'understand' ? { ...s, summary: 'Đã hiểu yêu cầu' } : s), [blind ? 'blind' : 'answer']: e.text, ...(!blind ? { evidence: e.evidence } : {}) }))
          if (e.type === 'progress' && !blind) update((t) => ({ ...t, progress: e.text }))
          if (e.type === 'error') update((t) => ({ ...t, [blind ? 'blindError' : 'error']: e.text }))
          if (e.type === 'tool_call' && !blind) update((t) => ({ ...t, steps: [...t.steps.map((s) => s.name === 'understand' ? { ...s, summary: 'Đã hiểu yêu cầu' } : s), { name: e.name, args: e.args }] }))
          if (e.type === 'tool_result' && !blind) update((t) => {
            const pending = t.steps.findIndex((s) => s.name === e.name && s.summary === undefined)
            return { ...t, estimate: e.result?.verdict?.estimate ?? t.estimate, steps: t.steps.map((s, i) => i === pending ? { ...s, summary: e.summary } : s) }
          })
        }, controller.signal)
      } catch (e) { update((t) => ({ ...t, [blind ? 'blindError' : 'error']: controller.signal.aborted ? 'Đã dừng kiểm tra.' : e instanceof Error ? e.message : String(e) })) }
    }
    await Promise.all([run(false), ...(compare ? [run(true)] : [])])
    abort.current = null
    requestIds.current = []
    sending.current = false
    setBusy(false)
    inputRef.current?.focus()
  }

  return <>
    <button ref={launchRef} type="button" className="btn btn-primary agent-launch" aria-expanded={open} aria-controls="agent-panel" onClick={() => open ? close() : setOpen(true)}>
      <MessageCircle size={18} />AlleyAI
    </button>
    {open && <section id="agent-panel" className="agent card" aria-label="AlleyAI" onKeyDown={(e) => { if (e.key === 'Escape') close() }}>
      <header className="agent-head"><div><h2 className="display">AlleyAI</h2><p>Hỏi bằng lời, xem kế hoạch trên bản đồ.</p></div>
        <button type="button" className="icon-btn" aria-label="Đóng trợ lý" onClick={close}><X size={18} /></button>
      </header>
      <div className="agent-log" ref={logRef} role="log" aria-label="Cuộc trò chuyện" aria-live="polite">
        {!turns.length && <div className="agent-empty"><Route size={26} /><h3 className="display">Bạn lái xe gì, tới hẻm nào?</h3><p className="muted">Tôi kiểm tra chỗ xe vào được, đường ra và quãng đi bộ.</p></div>}
        {turns.map((t, i) => <div className="agent-turn" key={i}>
          <p className="agent-question">{t.question}</p>
          {(t.blind || t.blindError) && <div className="agent-bubble agent-blind"><b>AI thường (không có Ngõ Ngách)</b><p>{plain(t.blind || t.blindError || '')}</p></div>}
          {!!t.steps.length && <ol className="agent-steps">{t.steps.map((s, j) => {
            const spec = STEPS[s.name] ?? { label: s.name, icon: Route }
            const Icon = spec.icon
            return <li key={j} className={s.summary === undefined && busy && i === turns.length - 1 ? 'working' : ''}>
              <Icon size={16} /><div><b>{spec.label}</b><small>{argsLabel(s.args)}</small>{s.summary !== undefined && <p>{s.summary}</p>}</div>
              {s.summary !== undefined ? <Check size={14} /> : busy && i === turns.length - 1 ? <LoaderCircle size={14} className="spin" /> : null}
            </li>
          })}</ol>}
          {t.answer && <div className="agent-bubble"><b>AlleyAI{t.estimate && ` · độ tin cậy ${{ high: 'cao', medium: 'trung bình', low: 'thấp' }[t.estimate.confidence]}`}</b><p>{plain(t.answer)}</p>
            {!!t.evidence?.length && <div className="agent-evidence-chips" aria-label="Nguồn bằng chứng">{t.evidence.map((chip) => <button type="button" key={chip.way_id} onClick={() => openEvidence(chip)} title={chip.source}>Bằng chứng · {chip.label}</button>)}</div>}
          </div>}
          {t.error && <div role="alert"><p className="error-line">{t.error}</p><button type="button" className="btn btn-tonal btn-sm" disabled={busy} onClick={() => send(t.question)}>Thử lại</button></div>}
        </div>)}
        {busy && <p className="agent-pending"><LoaderCircle size={14} className="spin" />{turns[turns.length - 1]?.progress || 'Đang kiểm tra cho xe của bạn…'}</p>}
      </div>
      <div className="agent-suggestions" aria-label="Câu hỏi gợi ý">{SUGGESTIONS.map((q, i) => <button type="button" key={q} disabled={busy || (i === 1 && !hasHistory)} onClick={() => send(q)}>{q}</button>)}</div>
      {evidenceError && <p className="error-line" role="alert">{evidenceError}</p>}
      <form className="agent-compose" onSubmit={(e) => { e.preventDefault(); send() }}>
        <label className="agent-compare"><input type="checkbox" checked={compare} disabled={busy} onChange={(e) => setCompare(e.target.checked)} />So sánh: AI không có Ngõ Ngách</label>
        <div className="agent-input"><textarea ref={inputRef} rows={2} value={input} maxLength={8000} placeholder="Tôi lái Fortuner, muốn đỗ xe ở…" aria-label="Câu hỏi cho trợ lý" onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }} />
          {Recognition && <button type="button" className={`icon-btn ${listening ? 'is-listening' : ''}`} aria-label={listening ? 'Dừng nghe' : 'Nói câu hỏi'} aria-pressed={listening} disabled={busy} onClick={dictate}><Mic size={18} /></button>}
          {busy ? <button type="button" className="btn btn-tonal agent-stop" onClick={stop}>Dừng</button> : <button type="submit" className="icon-btn agent-send" aria-label="Gửi câu hỏi" disabled={!input.trim()}><Send size={18} /></button>}
        </div>
        {(listening || voiceError) && <p className="note" role="status">{listening ? 'Đang nghe tiếng Việt…' : voiceError}</p>}
      </form>
    </section>}
    {open && evidence && <div className="agent-evidence-panel" onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setEvidence(null) } }}>
      <EvidencePanel way={evidence.way} at={evidence.at} google={false} grounding={false} onClose={() => setEvidence(null)}
        onReview={() => {}} onBlockage={() => { void api.blockage({ way_id: evidence.way.way_id, reason: 'Vật cản tạm thời (tài xế báo)' }).catch(() => setEvidenceError('Chưa gửi được báo cáo.')) }} />
    </div>}
  </>
}

function argsLabel(args: Record<string, unknown>) {
  if (args.query) return String(args.query)
  return [args.label, args.vehicle_id, args.arrive_at ? String(args.arrive_at).slice(11, 16) : null, args.dwell_min ? `${args.dwell_min} phút` : null, args.start].filter(Boolean).join(' · ')
}

const plain = (text: string) => text.replace(/\*\*(.*?)\*\*/g, '$1')
