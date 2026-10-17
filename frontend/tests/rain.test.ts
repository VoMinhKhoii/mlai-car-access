import assert from 'node:assert/strict'
import test from 'node:test'
import { planningRain } from '../src/rain.ts'

const arrival = '2026-10-17T08:00:00+07:00'
const scenario = [
  { start: arrival, end: '2026-10-17T10:00:00+07:00', mm_per_h: 60 },
  { start: '2026-10-17T11:00:00+07:00', end: '2026-10-17T12:00:00+07:00', mm_per_h: 20 },
]

test('an agent or preset rain scenario retains every interval and intensity', () => {
  assert.deepEqual(planningRain(true, arrival, 45, scenario), scenario)
  assert.deepEqual(planningRain(false, arrival, 45, scenario), [])
})

test('response provenance metadata is not sent as trusted rain input', () => {
  const observed = scenario.map((s) => ({ ...s, source: 'measurement', measured: true }))
  assert.deepEqual(planningRain(true, arrival, 45, observed), scenario)
})

test('manual slider rainfall keeps the documented half-hour offset', () => {
  assert.deepEqual(planningRain(true, arrival, 45, null), [{
    start: '2026-10-17T01:30:00.000Z', end: '2026-10-17T02:30:00.000Z', mm_per_h: 45,
  }])
  assert.deepEqual(planningRain(true, null, 45, null), [])
  assert.deepEqual(planningRain(true, arrival, 45, []), planningRain(true, arrival, 45, null))
})
