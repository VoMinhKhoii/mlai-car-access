import { useCallback, useEffect, useRef, useState } from 'react'

const MAX_AUDIO_BYTES = 1024 * 1024
const MAX_RECORDING_MS = 19_000
const TIMESLICE_MS = 1_000
const AUDIO_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus'] as const

export type VoiceCaptureState = 'idle' | 'requesting' | 'recording' | 'stopping' | 'ready' | 'error'

export interface VoiceCapture {
  state: VoiceCaptureState
  audio: Blob | null
  seconds: number
  maxDurationReached: boolean
  error: string
  start: () => Promise<void>
  stop: () => void
  discard: () => void
}

function stopTracks(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop())
}

function permissionMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Không có quyền dùng micrô. Cho phép truy cập micrô hoặc nhập nội dung và chọn bằng tay.'
  }
  if (name === 'NotFoundError' || name === 'NotReadableError' || name === 'AbortError') {
    return 'Không thể dùng micrô lúc này. Hãy thử lại hoặc nhập nội dung và chọn bằng tay.'
  }
  return 'Không thể bắt đầu ghi âm. Hãy thử lại hoặc nhập nội dung và chọn bằng tay.'
}

/** Captures a short in-memory clip. Stopping never uploads it; callers choose when to transcribe. */
export function useVoiceCapture(): VoiceCapture {
  const [state, setState] = useState<VoiceCaptureState>('idle')
  const [audio, setAudio] = useState<Blob | null>(null)
  const [seconds, setSeconds] = useState(0)
  const [maxDurationReached, setMaxDurationReached] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const stream = useRef<MediaStream | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const chunkBytes = useRef(0)
  const startedAt = useRef(0)
  const timer = useRef<number | null>(null)
  const deadlineTimer = useRef<number | null>(null)

  const clearTimers = useCallback((): void => {
    if (timer.current != null) window.clearInterval(timer.current)
    if (deadlineTimer.current != null) window.clearTimeout(deadlineTimer.current)
    timer.current = null
    deadlineTimer.current = null
  }, [])

  const dispose = useCallback((invalidate: boolean): void => {
    if (invalidate) generation.current += 1
    clearTimers()
    const current = recorder.current
    recorder.current = null
    if (current) {
      current.ondataavailable = null
      current.onerror = null
      current.onstart = null
      current.onstop = null
      if (current.state !== 'inactive') {
        try { current.stop() } catch { /* Stop microphone tracks even if the recorder has already ended. */ }
      }
    }
    const currentStream = stream.current
    stream.current = null
    stopTracks(currentStream)
    chunks.current = []
    chunkBytes.current = 0
  }, [clearTimers])

  useEffect(() => () => dispose(true), [dispose])

  const discard = useCallback((): void => {
    dispose(true)
    setAudio(null)
    setSeconds(0)
    setMaxDurationReached(false)
    setError('')
    setState('idle')
  }, [dispose])

  const stop = useCallback((): void => {
    const current = recorder.current
    if (!current || current.state === 'inactive') return
    clearTimers()
    setState('stopping')
    try { current.stop() } catch {
      dispose(true)
      setAudio(null)
      setError('Không thể hoàn tất bản ghi. Hãy thử lại hoặc nhập nội dung và chọn bằng tay.')
      setState('error')
    }
  }, [clearTimers, dispose])

  const start = useCallback(async (): Promise<void> => {
    if (state === 'requesting' || state === 'recording' || state === 'stopping') return
    discard()
    const currentGeneration = generation.current
    setError('')
    setState('requesting')

    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Trình duyệt hoặc kết nối này chưa hỗ trợ ghi âm an toàn. Hãy dùng HTTPS hoặc nhập nội dung và chọn bằng tay.')
      setState('error')
      return
    }

    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      if (currentGeneration !== generation.current) {
        stopTracks(media)
        return
      }
      stream.current = media

      const mimeType = AUDIO_MIME_TYPES.find((candidate) => MediaRecorder.isTypeSupported(candidate))
      if (!mimeType) {
        dispose(true)
        setError('Trình duyệt không hỗ trợ định dạng ghi âm này. Hãy nhập nội dung và chọn bằng tay.')
        setState('error')
        return
      }

      const instance = new MediaRecorder(media, { mimeType })
      recorder.current = instance
      chunks.current = []
      chunkBytes.current = 0
      startedAt.current = performance.now()
      instance.ondataavailable = (event: BlobEvent) => {
        if (currentGeneration !== generation.current || event.data.size === 0) return
        chunkBytes.current += event.data.size
        if (chunkBytes.current > MAX_AUDIO_BYTES) {
          dispose(true)
          setAudio(null)
          setError('Bản ghi vượt quá giới hạn 1 MiB. Hãy ghi câu ngắn hơn.')
          setState('error')
          return
        }
        chunks.current.push(event.data)
      }
      instance.onerror = () => {
        if (currentGeneration !== generation.current) return
        dispose(true)
        setAudio(null)
        setError('Đã xảy ra lỗi khi ghi âm. Hãy thử lại hoặc nhập nội dung và chọn bằng tay.')
        setState('error')
      }
      instance.onstart = () => {
        if (currentGeneration !== generation.current) return
        setState('recording')
        timer.current = window.setInterval(() => {
          const elapsed = Math.min(MAX_RECORDING_MS, performance.now() - startedAt.current)
          setSeconds(Math.floor(elapsed / 1000))
        }, 250)
        deadlineTimer.current = window.setTimeout(() => {
          if (currentGeneration !== generation.current) return
          setMaxDurationReached(true)
          stop()
        }, MAX_RECORDING_MS)
      }
      instance.onstop = () => {
        if (currentGeneration !== generation.current) return
        clearTimers()
        const recorded = new Blob(chunks.current, { type: instance.mimeType || mimeType })
        const elapsed = Math.min(MAX_RECORDING_MS, performance.now() - startedAt.current)
        const currentStream = stream.current
        stream.current = null
        stopTracks(currentStream)
        recorder.current = null
        chunks.current = []
        chunkBytes.current = 0
        setSeconds(Math.max(0, Math.ceil(elapsed / 1000)))
        if (!recorded.size || recorded.size > MAX_AUDIO_BYTES) {
          setAudio(null)
          setError('Không có bản ghi hợp lệ. Hãy thử lại hoặc nhập nội dung và chọn bằng tay.')
          setState('error')
          return
        }
        setAudio(recorded)
        setError('')
        setState('ready')
      }

      instance.start(TIMESLICE_MS)
      // The `start` event is asynchronous; keep an explicit state while the browser opens the device.
    } catch (captureError) {
      if (currentGeneration !== generation.current) return
      dispose(true)
      setAudio(null)
      setError(permissionMessage(captureError))
      setState('error')
    }
  }, [clearTimers, discard, dispose, state, stop])

  return { state, audio, seconds, maxDurationReached, error, start, stop, discard }
}
