const VN = 7 * 3600e3

/** Accept only complete, timezone-aware ISO timestamps, never browser-local dates. */
export function timestamp(iso: string): number | null {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/.exec(iso)
  if (!match || !validLocal(`${match[1]}T${match[2]}`) || Number(match[3] ?? 0) > 59) return null
  if (match[4] !== 'Z') {
    const [h, m] = match[4].slice(1).split(':').map(Number)
    if (h > 23 || m > 59) return null
  }
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

function validLocal(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) || Number(value.slice(0, 4)) === 0) return false
  const t = Date.parse(`${value}:00+07:00`)
  return Number.isFinite(t) && new Date(t + VN).toISOString().slice(0, 16) === value
}

/** A native datetime-local draft is interpreted explicitly in Vietnam (UTC+07:00). */
export function fromLocal(value: string): string | null {
  return validLocal(value) ? `${value}:00+07:00` : null
}

export function toLocal(iso: string): string | null {
  const t = timestamp(iso)
  return t == null ? null : new Date(t + VN).toISOString().slice(0, 16)
}
