import assert from 'node:assert/strict'
import test from 'node:test'
import { featurePlace, matchMapPlaces, normalizeName } from '../src/mapSearch.ts'

const center = { lat: 10.7605, lon: 106.6905 }
const company = { name: 'Cong Ty Cp Vuong Pham', ...center, layer: 'point_map' }
const university = { name: 'Trường Đại học Sư phạm TP.HCM, 280 An Dương Vương', lat: 10.76, lon: 106.68, layer: 'point_map' }

test('Vietnamese diacritics, Đ and case normalize to exact tokens', () => {
  assert.equal(normalizeName('ĐƯỜNG Vương Phạm'), 'duong vuong pham')
  assert.deepEqual(matchMapPlaces('Công ty CP VƯƠNG PHẠM', [university, company], center), [company])
  assert.deepEqual(matchMapPlaces('Vuong Pham', [university, company], center), [company])
})
test('coverage precedes distance, duplicate tile features disappear', () => {
  const near = { ...company, name: 'Vương Phạm', lat: 10.7606 }
  const partial = { ...company, name: 'Vương Phạm Long' }
  assert.deepEqual(matchMapPlaces('Vuong Pham Long', [company, partial], center), [partial])
  assert.deepEqual(matchMapPlaces('Vuong Pham', [near, company, { ...company }], center), [company, near])
  assert.deepEqual(matchMapPlaces('công ty tnhh', [company], center), [])
})
test('agent messages retain named POIs without matching a look-alike', () => {
  assert.deepEqual(matchMapPlaces('Tôi lái Vios đến công ty Vương Phạm lúc 18h', [university, company], center, 20, true), [company])
  assert.equal(matchMapPlaces('Vuong Pham', Array.from({ length: 30 }, (_, i) => ({ ...company, lat: center.lat + i / 1000 })), center).length, 20)
})
test('Goong street and place label properties and line coordinates are supported', () => {
  assert.equal(featurePlace({ properties: { st_name: 'Hẻm 115 Trần Đình Xu' }, geometry: { type: 'LineString', coordinates: [[106.69, 10.76], [106.8, 10.8]] } }, 'streets_label', center)?.name, 'Hẻm 115 Trần Đình Xu')
  assert.equal(featurePlace({ properties: { name_vn: 'Bến Thành' }, geometry: { type: 'Point', coordinates: [106.69, 10.76] } }, 'vietnam_administrator', center)?.lon, 106.69)
  assert.equal(featurePlace({ properties: {}, geometry: { type: 'Point', coordinates: [106.69, 10.76] } }, 'point_map', center), null)
})
