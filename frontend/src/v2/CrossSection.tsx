import type { Cut } from './derive'

interface Props {
  cut: Cut
  body: number
  mirror: number
  vehicleName: string
  expanded: boolean
  onToggle: () => void
}

const WALL_H = 2.3
const MAX_SCENE = 8

/** A to-scale section through the narrowest cut: walls, clear width, the car from behind. Units are metres. */
export function CrossSection({ cut, body, mirror, vehicleName, expanded, onToggle }: Props) {
  const lo = cut.lo
  const spareCm = lo != null ? Math.round(((lo - mirror) / 2) * 100) : null
  const short = spareCm != null && spareCm < 0
  const width = lo == null ? '' : cut.hi != null ? `${lo.toFixed(2)} to ${cut.hi.toFixed(2)} m` : `${lo.toFixed(2)} m`

  if (!expanded) {
    return <button type="button" className={`v2-chip ${short ? 'is-short' : ''}`} onClick={onToggle} aria-expanded={false}
      aria-label={`Narrowest cut ${width || 'not measured'}. Show the cross-section`}>
      <span className="v2-num">{lo != null ? `${lo.toFixed(2)} m` : 'Width ?'}</span>
      {spareCm != null && <span key={spareCm} className="v2-xfade v2-num">{short ? `short ${-spareCm} cm` : `${spareCm} cm spare`}</span>}
    </button>
  }

  const span = Math.min(Math.max(cut.hi ?? lo ?? 3, 2.6), MAX_SCENE)
  const half = span / 2 + 0.7
  const loH = lo != null ? Math.min(lo, MAX_SCENE) / 2 : null
  const hiH = cut.hi != null ? Math.min(cut.hi, MAX_SCENE) / 2 : loH
  const s = loH != null ? loH - mirror / 2 : 0
  const t = (v: string) => ({ transform: v })

  return <div className="v2-xs" role="group" aria-label={`Cross-section at the narrowest cut${cut.wayName ? ` on ${cut.wayName}` : ''}`}>
    <div className="v2-xs-head">
      <p className="v2-xs-title">Narrowest cut</p>
      <button type="button" className="v2-xs-close" onClick={onToggle} aria-expanded={true} aria-label="Collapse the cross-section">Hide</button>
    </div>
    {cut.wayName && <p className="v2-xs-way">{cut.wayName}</p>}
    <svg className="v2-xs-svg" viewBox={`${-half} ${-WALL_H - 0.1} ${half * 2} ${WALL_H + 0.35}`} role="img"
      aria-label={lo != null ? `${vehicleName} with mirrors ${mirror.toFixed(2)} m in a ${width} alley` : `${vehicleName}; alley width not measured`}>
      {hiH != null && <>
        <rect className="v2-wall" x={-half - 1} y={-WALL_H} width={half + 1 - hiH} height={WALL_H} />
        <rect className="v2-wall" x={hiH} y={-WALL_H} width={half + 1 - hiH} height={WALL_H} />
      </>}
      {loH != null && hiH != null && hiH > loH && <>
        <rect className="v2-wall-maybe" x={-hiH} y={-WALL_H} width={hiH - loH} height={WALL_H} />
        <rect className="v2-wall-maybe" x={loH} y={-WALL_H} width={hiH - loH} height={WALL_H} />
      </>}
      <rect className="v2-ground" x={-half - 1} y={0} width={half * 2 + 2} height={0.3} />
      {loH != null && <g className={short ? 'v2-spare is-short' : 'v2-spare'}>
        <rect className="v2-anim" x={0} y={-1.3} width={1} height={0.22} style={t(`translate(${-loH}px, 0px) scale(${s}, 1)`)} />
        <rect className="v2-anim" x={0} y={-1.3} width={1} height={0.22} style={t(`translate(${loH}px, 0px) scale(${-s}, 1)`)} />
      </g>}
      <g className="v2-anim" style={t(`scale(${mirror}, 1)`)}>
        <rect className="v2-car" x={-0.5} y={-1.26} width={0.09} height={0.14} />
        <rect className="v2-car" x={0.41} y={-1.26} width={0.09} height={0.14} />
      </g>
      <g className="v2-anim" style={t(`scale(${body}, 1)`)}>
        <rect className="v2-tyre" x={-0.46} y={-0.42} width={0.15} height={0.42} />
        <rect className="v2-tyre" x={0.31} y={-0.42} width={0.15} height={0.42} />
        <path className="v2-car" d="M-0.5 -0.3 L-0.5 -1.12 L-0.41 -1.2 L-0.35 -1.78 L0.35 -1.78 L0.41 -1.2 L0.5 -1.12 L0.5 -0.3 Z" />
        <path className="v2-glass" d="M-0.33 -1.24 L-0.29 -1.68 L0.29 -1.68 L0.33 -1.24 Z" />
        <rect className="v2-lamp" x={-0.47} y={-1.06} width={0.13} height={0.12} />
        <rect className="v2-lamp" x={0.34} y={-1.06} width={0.13} height={0.12} />
        <rect className="v2-plate" x={-0.13} y={-0.78} width={0.26} height={0.15} />
      </g>
    </svg>
    <dl className="v2-xs-nums">
      <div><dt>Alley</dt><dd className="v2-num">{lo != null ? width : 'Not measured'}</dd></div>
      <div><dt>Mirrors</dt><dd key={mirror} className="v2-num v2-xfade">{mirror.toFixed(2)} m</dd></div>
      <div className={short ? 'is-short' : ''}><dt>{short ? 'Short' : 'Spare'}</dt>
        <dd key={spareCm ?? 'x'} className="v2-num v2-xfade">{spareCm == null ? 'Unknown' : `${Math.abs(spareCm)} cm a side`}</dd></div>
    </dl>
    <p className="v2-xs-foot">{cut.tier} width, drawn to scale</p>
  </div>
}
