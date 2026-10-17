import type { RainSpell } from './api'
import { timestamp } from './datetime.ts'

/** Preserve supplied weather intervals; the demo slider creates its own one-hour spell. */
export function planningRain(enabled: boolean, arrival: string | null, mmPerHour: number,
  scenario: RainSpell[] | null): RainSpell[] {
  if (!enabled) return []
  if (scenario?.length) {
    // Source/measurement labels are response metadata, not trusted request fields.
    return scenario.map(({ start, end, mm_per_h }) => ({ start, end, mm_per_h }))
  }
  const at = arrival == null ? null : timestamp(arrival)
  if (at == null) return []
  const start = at + 30 * 60e3
  return [{ start: new Date(start).toISOString(), end: new Date(start + 3600e3).toISOString(), mm_per_h: mmPerHour }]
}
