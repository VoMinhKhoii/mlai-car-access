export type Pending = { id: string; endpoint: string; body: Record<string, unknown>; error?: string }
const KEY = 'ngo-field-pending-v1'
export function readStored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback } catch { return fallback }
}
export function store(key: string, value: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); return true } catch { return false }
}
export function pending(): Pending[] { const list = readStored<Pending[]>(KEY, []); return Array.isArray(list) ? list : [] }
export function savePending(items: Pending[]): boolean { return store(KEY, items) }
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
export async function api<T>(endpoint: string, token: string, body?: unknown): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 20000)
  try {
    const response = await fetch(endpoint, { method: body ? 'POST' : 'GET', signal: controller.signal,
      headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new ApiError(typeof error.detail === 'string' ? error.detail : `Lỗi ${response.status}. Kiểm tra dữ liệu và mã nhóm.`, response.status)
    }
    return await response.json() as T
  } finally { clearTimeout(timer) }
}
export function submissionId(): string {
  if (crypto.randomUUID) return crypto.randomUUID()
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c => (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16))
}
