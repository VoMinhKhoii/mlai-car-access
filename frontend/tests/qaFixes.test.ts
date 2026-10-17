import assert from 'node:assert/strict'
import test from 'node:test'
import { canonicalSuggestions, hasSamples, negativeAccess, orderStops, profileBasis, profileTier, stopLocation } from '../src/qaFixes.ts'
import type { Plan, StopPoint, WidthProfileSegment } from '../src/api.ts'

test('negative estimate or fit never leads suggested stops', () => {
  const door = { kind: 'door', name: 'At the door', fit: { class: 'unknown' }, estimate: { answer: 'no' } } as StopPoint
  const nearby = { kind: 'street', name: 'Main street', fit: { class: 'unknown' } } as StopPoint
  assert.equal(negativeAccess(door), true)
  assert.deepEqual(orderStops({ stop_points: [door, nearby] } as Plan).stop_points, [nearby, door])
  assert.deepEqual(orderStops({ stop_points: [door] } as Plan).stop_points, [])
  assert.equal(stopLocation(door), 'at the door')
  assert.equal(stopLocation(nearby), 'at Main street')
  assert.equal(negativeAccess({ ...nearby, fit: { class: 'no' } }), true)
})

test('zero samples cannot be presented as observed, measured or official', () => {
  for (const tier of ['Observed', 'Measured', 'Official']) {
    const s = { tier, source: 'OSM: motorcars permitted', sample_count: 0, sampled: true } as WidthProfileSegment
    assert.equal(hasSamples(s), false)
    assert.equal(profileTier(s), 'Inferred')
    assert.equal(profileBasis(s), 'assumed from OSM tag, not measured')
    assert.equal(profileTier({ ...s, sample_count: 1 }), tier)
  }
})

test('canonical geocoder point wins across viewport label vertices; distant names remain disambiguated', () => {
  const remote = { label: 'Hẻm 356 Xô Viết Nghệ Tĩnh, Hồ Chí Minh', lat: 10.80376, lon: 106.71230, source: 'Goong' }
  const local = { label: 'Hẻm 356 Xô Viết Nghệ Tĩnh', lat: 10.8044, lon: 106.7126, source: 'On the map' }
  assert.equal(canonicalSuggestions([remote], [local]).length, 1)
  assert.equal(canonicalSuggestions([remote], [{ ...local, lat: 10.8034 }])[0].lat, remote.lat)
  const distinct = canonicalSuggestions([remote], [{ ...local, lat: 10.81 }])
  assert.equal(distinct.length, 2)
  assert.match(distinct[1].subtitle!, /10.81000/)
})
