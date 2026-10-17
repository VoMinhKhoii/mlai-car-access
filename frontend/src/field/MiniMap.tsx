export type MapPoint = { lat: number; lon: number }
export function MiniMap({ coords = [], points = [], gps, label = 'OSM alley segment map' }: { coords?: number[][]; points?: MapPoint[]; gps?: MapPoint; label?: string }) {
  const all = [...coords, ...points.map(p=>[p.lon,p.lat]), ...(gps ? [[gps.lon,gps.lat]] : [])]
  const xs = all.map(p=>p[0]), ys = all.map(p=>p[1])
  const cx = all.length ? (Math.min(...xs)+Math.max(...xs))/2 : 106.7145
  const cy = all.length ? (Math.min(...ys)+Math.max(...ys))/2 : 10.8016
  const span = Math.max(all.length ? Math.max(...xs)-Math.min(...xs) : .006, all.length ? (Math.max(...ys)-Math.min(...ys))*1.6 : .006,.0015)*1.3
  const xy=(x:number,y:number)=>[160+(x-cx)/span*300,100-(y-cy)/span*300]
  return <div className="mini-map"><svg viewBox="0 0 320 200" role="img" aria-label={label}><defs><pattern id="map-grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="currentColor" strokeWidth=".5" /></pattern></defs><rect width="320" height="200" fill="url(#map-grid)" opacity=".18" />{coords.length>1 && <polyline points={coords.map(([x,y])=>xy(x,y).join(',')).join(' ')} fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />}{points.map((p,i)=>{const [x,y]=xy(p.lon,p.lat);return <circle key={i} cx={x} cy={y} r="5" fill="currentColor" />})}{gps && (()=>{const [x,y]=xy(gps.lon,gps.lat); return <g><circle cx={x} cy={y} r="13" fill="oklch(65% .15 240 / .2)"/><circle cx={x} cy={y} r="6" fill="oklch(55% .15 240)" stroke="oklch(98% .005 190)" strokeWidth="2" /></g>})()}<text x="295" y="22" fontSize="11" fill="currentColor">N ↑</text><text x="12" y="185" fontSize="9" fill="currentColor">{gps ? 'OSM geometry · blue dot: GPS' : all.length ? 'Recorded alleys · OSM representative points' : 'Approved alleys will appear here'}</text></svg></div>
}
