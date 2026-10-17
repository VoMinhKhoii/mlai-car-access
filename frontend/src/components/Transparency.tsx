import { hasSamples, profileTier, profileBasis } from '../qaFixes'
import { useState } from 'react'
import { Check, ChevronDown, CircleHelp, Minus, TriangleAlert, X } from 'lucide-react'
import { EVIDENCE_TIERS, evidenceTier, type DecidedBy, type Plan, type PlanComparison, type StopPoint, type Vehicle, type WidthProfileSegment } from '../api'

export function TierLegend() {
  return <div className="evidence-key" aria-label="Evidence tiers, strongest to weakest">{EVIDENCE_TIERS.map((tier) => <span key={tier}><i className={`evidence-swatch evidence-${tier.replace(' ', '-')}`} />{tier}</span>)}</div>
}

const m = (value: number | null | undefined) => value != null && Number.isFinite(value) ? `${value.toFixed(2)} m` : 'unknown'
const range = (lo: number | null, hi: number | null) => lo == null ? 'Width unknown' : hi == null ? `≥ ${m(lo)}` : `${lo.toFixed(2)}–${hi.toFixed(2)} m`
const decisionText = (decision?: DecidedBy | null) => typeof decision === 'string' ? decision.replaceAll('_', ' ') : decision?.reason || decision?.check?.replaceAll('_', ' ') || ''
type Status = 'pass' | 'tight' | 'fail' | 'unknown'
const STATUS = { pass: { icon: Check, label: 'Pass' }, tight: { icon: TriangleAlert, label: 'Tight' }, fail: { icon: X, label: 'Fail' }, unknown: { icon: CircleHelp, label: 'Unknown' } }
function StatusChip({ status, answer = false }: { status: Status; answer?: boolean }) {
  const { icon: Icon, label } = STATUS[status]
  return <span className={`logic-status logic-${status}`}><Icon size={13} aria-hidden="true" />{answer ? status === 'pass' ? 'Fits' : status === 'fail' ? 'No' : label : label}</span>
}
const answerStatus = (answer: string): Status => /^(fits|pass|yes|door)$/.test(answer) ? 'pass' : answer === 'tight' ? 'tight' : /^(no|fail|blocked|none)$/.test(answer) ? 'fail' : 'unknown'

/** A fallback only for the named arrival legs: never invent a route order from nearby map features. */
function fallbackProfile(plan: Plan, stop: StopPoint): WidthProfileSegment[] {
  const legs = stop.route_in?.flood?.legs ?? []
  let start = 0
  return legs.map((leg) => {
    const id = leg.way_id ?? -1
    const props = plan.layers.fit.features.find((f) => f.properties?.way_id === id)?.properties
    const wr = stop.way_id === id ? stop.fit.width_range : undefined
    const bound = wr?.evidence.find((b) => b.estimate_m != null) ?? wr?.evidence.find((b) => b.tier === wr.top_tier)
    const limiting = stop.estimate?.limiting_width
    const length = (stop.route_in?.meters || legs.length) / legs.length
    const segment = { way_id: id, name: leg.name, start_m: start, length_m: length,
      width_lo: wr?.lo ?? props?.lo ?? null, width_hi: wr?.hi ?? props?.hi ?? null,
      estimate_m: bound?.estimate_m ?? (limiting?.way_id === id ? limiting.value_m : null) ?? null,
      tier: bound?.tier ?? wr?.top_tier ?? props?.top_tier ?? null,
      source: bound?.source ?? (limiting?.way_id === id ? limiting.source : null) ?? null,
      sampled: (bound?.sample_count ?? 0) > 0, sample_count: bound?.sample_count ?? null }
    start += length
    return segment
  })
}

// Preserve physical edges, repeated ways and evidence gaps.
const groupedProfile = (profile: WidthProfileSegment[]) => profile.filter((s) => Number.isFinite(s.length_m) && s.length_m > 0)
const noWidth = (s: WidthProfileSegment) => s.estimate_m == null && !(s.width_lo != null && s.width_lo > 0)
const displayedTier = (s: WidthProfileSegment) => noWidth(s) ? 'No data' : evidenceTier(profileTier(s))

function WidthProfile({ profile, needed, endLabel, schematic = false }: { profile: WidthProfileSegment[]; needed: number; endLabel: string; schematic?: boolean }) {
  const [active, setActive] = useState(0)
  const segments = groupedProfile(profile)
  if (!segments.length) return null
  const segment = segments[Math.min(active, segments.length - 1)]
  const known = segments.filter((s) => s.estimate_m != null || s.width_lo != null && s.width_lo > 0)
  const narrow = known.reduce<WidthProfileSegment | null>((a, b) => !a || (b.estimate_m ?? b.width_lo!) < (a.estimate_m ?? a.width_lo!) ? b : a, null)
  const total = segments.reduce((sum, s) => sum + s.length_m, 0)
  // The horizontal axis is distance, the vertical axis is width. Keep even the shortest tap target 44 px wide.
  const chartWidth = Math.max(280, total / Math.min(...segments.map((s) => s.length_m)) * 44)
  const maxWidth = Math.max(needed, ...segments.map((s) => s.width_hi ?? s.estimate_m ?? s.width_lo ?? 0)) * 1.12
  return <section className="logic-profile" aria-label="Arrival width profile">
    <div className="logic-heading"><b>Width along the arrival route</b><span>{Math.round(total)} m</span></div>
    <p className="logic-caption">Street → {endLabel}. {schematic ? 'Segment distances unavailable; spacing is schematic.' : 'Segment lengths follow route distance.'} Scroll for all segments. Height shows width. Gaps mean no width data.</p>
    <div className="width-scroll" tabIndex={0} aria-label="Width profile, scroll horizontally for more segments">
      <div className="width-chart" style={{ width: `max(100%, ${chartWidth}px)` }}>
        <div className="width-needed" style={{ bottom: `${needed / maxWidth * 100}%` }}><span>Needs {m(needed)}</span></div>
        {segments.map((s, i) => <button type="button" key={`${s.way_id}-${i}`} className={`width-segment ${i === active ? 'active' : ''}`}
          style={{ width: `${s.length_m / total * 100}%` }} aria-label={`${s.name || 'Unnamed segment'}: ${range(s.width_lo, s.width_hi)}, ${displayedTier(s)}`}
          aria-pressed={i === active} onClick={() => setActive(i)} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)}>
          <span className={`width-column evidence-${displayedTier(s).replace(' ', '-')}`}
            style={{ height: `${Math.max(6, (s.estimate_m ?? s.width_lo ?? 0) / maxWidth * 100)}%` }} />
          {noWidth(s) && <span className="width-gap">No data</span>}
          {s === narrow && <span className="width-narrow" aria-label="Narrowest segment"><Minus size={18} /></span>}
        </button>)}
      </div>
    </div>
    <div className="profile-ends"><span>Street · 0 m</span><span>{endLabel} · {Math.round(total)} m</span></div>
    {narrow && <p className="logic-narrow"><b>{hasSamples(narrow) ? 'Narrowest sampled' : 'Narrowest estimate'} {hasSamples(narrow) ? '' : '≈'}{m(narrow.estimate_m ?? narrow.width_lo)}</b> · {profileBasis(narrow)} · {narrow.source || 'Source unavailable'}</p>}
    <p className="segment-detail" aria-live="polite"><b>{segment.name || `Way ${segment.way_id}`}</b><br />{range(segment.width_lo, segment.width_hi)} · {segment.sample_count != null ? `${segment.sample_count} sample${segment.sample_count === 1 ? '' : 's'}` : segment.sampled ? 'Sample count unavailable' : 'No samples reported'} · {noWidth(segment) ? 'No data' : profileBasis(segment)}<br />Source: {segment.source || 'Unavailable'}</p>
    <TierLegend />
    <p className="logic-caption">Isolated samples and inferred widths do not confirm continuous clear width.</p>
  </section>
}

export function Transparency({ plan, stop, comparison, fleet, onVehicle, disabled, top = false }: {
  plan: Plan; stop: StopPoint; comparison: PlanComparison | null; fleet: Vehicle[]
  onVehicle: (id: string) => void; disabled: boolean; top?: boolean
}) {
  const estimate = stop.estimate ?? (top ? plan.verdict.estimate : undefined)
  const suppliedProfile = top && plan.verdict.profile?.length ? plan.verdict.profile : stop.profile?.length ? stop.profile : top ? comparison?.profile : undefined
  const profile = suppliedProfile?.length ? suppliedProfile : fallbackProfile(plan, stop)
  const wr = stop.fit.width_range
  const needed = comparison?.vehicles.find((v) => v.vehicle_id === plan.vehicle.id)?.needed_m ?? stop.fit.needed?.fits_min ?? plan.vehicle.fits_min
  const flood = stop.flood.stay
  const out = stop.way_out
  const needsTurning = out.mode === 'reverse' || out.mode === 'turn_here'
  const exitStatus: Status = !out.available || out.mode === 'none' ? 'fail' : out.route_verified !== true || needsTurning && out.turn_verified !== true || out.turn_verified === false ? 'unknown' : out.tight_exit ? 'tight' : 'pass'
  const widthStatus: Status = stop.fit.class === 'lot' ? 'unknown' : stop.fit.class === 'unknown' && estimate?.answer ? answerStatus(estimate.answer) : answerStatus(stop.fit.class)
  const estWidth = estimate?.limiting_width?.value_m ?? null
  const floodStatus: Status = flood.status === 'blocked' ? 'fail' : flood.knowledge !== 'known' ? 'unknown' : flood.status === 'risky' ? 'tight' : 'pass'
  const legalStatus: Status = stop.legality.status === 'Permitted' ? 'pass' : stop.legality.status === 'Prohibited' ? 'fail' : stop.legality.status === 'Restricted' ? 'tight' : 'unknown'
  const walkStatus: Status = stop.walk.connection?.mapped === false ? 'unknown' : stop.walk.wade ? 'tight' : stop.walk.meters === 0 || stop.walk.connection?.mapped === true ? 'pass' : 'unknown'
  const checks = [
    { id: 'width', label: 'Width', status: widthStatus, reason: `${estWidth != null ? `≈${m(estWidth)} sampled (range ${wr ? range(wr.lo, wr.hi) : 'unknown'})` : wr ? range(wr.lo, wr.hi) : 'No width range'}; needs ${m(needed)} for comfortable clearance`, source: estimate?.limiting_width?.source || wr?.evidence.find((b) => b.estimate_m != null)?.source || wr?.evidence.find((b) => b.tier === wr.top_tier)?.source || 'Width evidence unavailable' },
    { id: 'exit', label: 'Turning / way out', status: exitStatus, reason: out.text || 'Way out not verified', source: out.observed?.[0]?.source || 'OSM route geometry' },
    { id: 'flood', label: 'Flood during stay', status: floodStatus, reason: flood.reason || (floodStatus === 'pass' ? 'Forecast within vehicle limits for the stay window' : 'Cannot confirm water stays within vehicle limits'), source: flood.source || flood.freshness?.source || 'Flood evidence unavailable' },
    { id: 'law', label: 'Stopping law', status: legalStatus, reason: stop.legality.rules[0]?.text || 'Stopping permission unverified', source: stop.legality.rules[0]?.citation || 'No applicable rule evidence' },
    { id: 'walk', label: 'Walk', status: walkStatus, reason: stop.walk.connection?.reason || `${stop.walk.meters} m · ${stop.walk.minutes} min${stop.walk.wade ? '; possible wading' : ''}`, source: stop.walk.connection?.mapped === true ? 'OSM walking connection' : 'Walking connection not verified' },
  ]
  const decision = decisionText(stop.decided_by ?? (top ? plan.verdict.decided_by ?? comparison?.vehicles.find((v) => v.vehicle_id === plan.vehicle.id)?.decided_by : null))
  const normalizedDecision = decision.toLowerCase()
  const deciding = decision ? /width|clearance/.test(normalizedDecision) ? 'width' : /turn|way out|exit|revers|dead end/.test(normalizedDecision) ? 'exit' : /flood|tide|water/.test(normalizedDecision) ? 'flood' : /law|legal|stop|park/.test(normalizedDecision) ? 'law' : /walk/.test(normalizedDecision) ? 'walk' : null : null
  const fallbackDecision = checks.find((c) => c.status === 'fail') ?? checks.find((c) => c.status === 'unknown') ?? checks.find((c) => c.status === 'tight')
  const decided = deciding ?? fallbackDecision?.id
  const decisionLabel = deciding ? checks.find((c) => c.id === deciding) : null
  const decisionReason = decisionLabel && /^(width|way out|legal|flood|walk)$/.test(normalizedDecision) ? `${decisionLabel.label.toLowerCase()}: ${decisionLabel.reason}` : decision
  const confidenceBasis = (estimate?.limiting_width?.sample_count ?? 0) > 0 ? estimate?.basis
    : estimate?.basis?.replace(/\b(observed|measured|official)(?=\s*(?:≈|\d))/gi, 'assumed')
  const coverage = estimate?.coverage
  const routeWays = groupedProfile(profile)
  const measured = routeWays.filter((s) => hasSamples(s)).length
  const drivers = [coverage ? `${coverage.sampled_segments}/${coverage.total_segments} segments with width samples` : routeWays.length ? `${measured}/${routeWays.length} segments with width samples` : 'Route width coverage unavailable',
    exitStatus === 'unknown' ? 'way out not verified' : exitStatus === 'fail' ? 'no suitable way out' : exitStatus === 'tight' ? 'tight exit' : 'exit route checked',
    floodStatus === 'pass' ? 'flood forecast covers stay' : 'flood evidence incomplete']
  const vehicles = top ? comparison?.vehicles ?? [] : []
  return <details className="transparency" open={top}>
    <summary><span>Why this answer</span><ChevronDown size={16} className="chev" /></summary>
    <div className="logic-body">
      <WidthProfile profile={profile} needed={needed} endLabel={stop.kind === 'door' ? 'Door' : 'Stop'} schematic={!suppliedProfile?.length} />
      <section aria-label="Decision checks">
        <b className="logic-section-title">Checks, in order</b>
        <p className="logic-decision"><b>{decision ? 'Decided by:' : 'Limiting check:'}</b> {decisionReason || (fallbackDecision ? `${fallbackDecision.label.toLowerCase()}: ${fallbackDecision.status === 'unknown' ? 'not verified' : fallbackDecision.status}` : 'all checks pass')}</p>
        <ol className="logic-checks">{checks.map((c) => <li key={c.id} className={c.id === decided ? 'is-decisive' : ''}>
          <div><b>{c.label}</b><StatusChip status={c.status} /></div><p>{c.reason} <span>Source: {c.source}.</span></p>
        </li>)}</ol>
      </section>
      <section className="logic-confidence"><b>Confidence{estimate?.confidence ? `: ${estimate.confidence}` : ''}</b><p>{drivers.join(' · ')}.</p>{confidenceBasis && <details><summary>Full confidence basis</summary><p>{confidenceBasis}</p></details>}</section>
      {top && <section aria-label="Vehicle comparison">
        <b className="logic-section-title">All vehicle classes · same route</b>
        <p className="logic-caption">{vehicles.length ? 'Same arrival route and stay. Select a vehicle to recalculate.' : 'Comparison loading/unavailable.'}</p>
        {!!vehicles.length && <div className="vehicle-table" role="table" aria-label="Vehicle width thresholds">
          <div className="vehicle-table-head" role="row"><span role="columnheader">Vehicle</span><span role="columnheader">Mirrors</span><span role="columnheader">Needs</span><span role="columnheader">Answer</span></div>
          {vehicles.map((v) => <div role="row" key={v.vehicle_id} className={v.vehicle_id === plan.vehicle.id ? 'is-current' : ''}>
            <span role="cell"><button type="button" disabled={disabled} aria-pressed={v.vehicle_id === plan.vehicle.id} onClick={() => onVehicle(v.vehicle_id)}>{fleet.find((f) => f.id === v.vehicle_id)?.kind === 'class' ? fleet.find((f) => f.id === v.vehicle_id)?.size_class : v.label}</button></span>
            <span role="cell">{v.mirror_width.toFixed(2)} m</span><span role="cell">{v.needed_m.toFixed(2)} m</span><span role="cell"><StatusChip status={answerStatus(v.answer)} answer /></span>
          </div>)}
        </div>}
        {!!vehicles.length && <p className="logic-caption">Needs = comfortable width including the vehicle margin. Unknown means evidence is insufficient.</p>}
      </section>}
    </div>
  </details>
}
