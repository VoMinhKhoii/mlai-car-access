import { ArrowRightLeft, Ban, Newspaper, CarFront, ChevronDown, CircleCheck, Droplets, Footprints, Landmark, LoaderCircle, Navigation, OctagonAlert, Play, RotateCcw, TriangleAlert, X } from 'lucide-react'
import { floodKnowledgeLabel, routeSourceLabel, type AreaBuild, type FloodCheck, type LegFloodCheck, type ManeuverState, type NewsItem, type Plan, type PlanComparison, type Vehicle, type StopPoint } from '../api'
import { Tag, distance, metres, minutes, vn, vnt, type Tone } from '../ds/ui'
import { fmtWidth } from './Directions'
import { timestamp, toLocal } from '../datetime'
import { Transparency } from './Transparency'
import { negativeAccess, stopLocation } from '../qaFixes'

export const floodTimeLabel = (iso: string | null | undefined) => {
  const local = iso ? toLocal(iso) : null
  return local ? `${local.slice(11, 16)} ${local.slice(0, 10).split('-').reverse().join('/')} (UTC+7)` : 'unknown time'
}
export const exitFloodFailure = (plan: Plan) => plan.timing?.failure_codes.includes('flood_exit') ?? false

function knownPassable(check: LegFloodCheck | null | undefined): boolean {
  return !!check && check.status === 'passable' && check.knowledge === 'known' && check.legs.length > 0
    && check.legs.every((leg) => leg.status === 'passable' && leg.knowledge === 'known')
}


/* ---------- verdict: say what to do, then why ---------- */

export function Verdict({ plan, onDeparture, stale, comparison, fleet, onVehicle }: { plan: Plan; onDeparture: (iso: string) => void; stale: boolean; comparison: PlanComparison | null; fleet: Vehicle[]; onVehicle: (id: string) => void }) {
  const best = plan.stop_points.find((s) => !negativeAccess(s))
  const verb = plan.intent === 'park' ? 'Park' : 'Pick up'
  const door = plan.door
  const accessSuccess = !!door && door.kind === 'door' && door.ok && door.fit.class === 'fits'
    && door.route_in !== null && door.route_in.available
    && door.way_out.available && door.way_out.mode !== 'none'
    && door.way_out.route_verified !== false
    && door.way_out.turn_verified !== false && door.way_out.tight_exit !== true
    && door.legality.status === 'Unverified' && door.unverified_reasons.length > 0
    && door.unverified_reasons.every((reason) => reason.startsWith('Stopping permission unverified:'))
    && knownPassable(door.route_in.flood) && knownPassable(door.flood.stay) && knownPassable(door.way_out.flood)
  const isUnverified = plan.verdict.code === 'unverified' || !!(best && !best.verified)
  const recommendation = isUnverified && best && !accessSuccess
    ? `Suggested: ${verb} ${stopLocation(best)} · walk ${minutes(best.walk.minutes)}`
    : null
  const doorWhy = plan.door && !plan.door.ok ? plan.door.fail_reasons[0] : null
  let tone: Tone = 'ok'
  let icon = <CircleCheck size={18} />
  let head = plan.verdict.headline
  let sub: string | null = plan.verdict.detail || null

  // A non-null timing result means the backend authorized a flood-specific sweep.
  const timing = plan.timing
  const floodHazard = timing?.failure_codes.some((code) => code === 'flood_exit' || code === 'flood_arrival' || code === 'flood_stay') ?? false
  if (timing && (floodHazard || timing.reason || timing.leave_before_at || timing.or_after_at)) {
    tone = 'warn'
    icon = floodHazard ? <Droplets size={18} /> : <TriangleAlert size={18} />
    head = timing.failure_codes.includes('flood_exit') ? 'Check flooding on the exit route' : floodHazard ? 'Check flooding for this trip' : 'Suitable departure time unknown'
    sub = [timing.reason, timing.leave_before_at && `Earlier departure: ${floodTimeLabel(timing.leave_before_at)}`,
      plan.intent === 'park' && timing.or_after_at && `Later departure: ${floodTimeLabel(timing.or_after_at)}`].filter(Boolean).join('. ')
    if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
      sub += ' Suggested stop is unverified; departure time does not confirm entry or exit.'
    }
  } else if (accessSuccess) {
    tone = 'ok'
    icon = <CarFront size={18} />
    head = 'Vehicle can enter and exit'
    sub = plan.intent === 'park'
      ? 'Flooding is within vehicle limits in all three check windows. Parking rules are unverified.'
      : 'Flooding is within vehicle limits in all three check windows. Stopping rules are unverified.'
  } else if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
    tone = 'muted'
    head = plan.verdict.headline
    sub = best ? null : sub

  } else if (plan.verdict.code === 'door') {
    head = plan.intent === 'park' ? 'Can reach the door' : 'Can pick up at the door'
    sub = best ? vnt(best.way_out.text) : sub
  } else if (plan.verdict.code === 'nearby' && best) {
    tone = 'brand'
    icon = <ArrowRightLeft size={18} />
    head = `${verb} ${stopLocation(best)}, walk ${minutes(best.walk.minutes)}`
    sub = doorWhy ? `Avoid driving to the door: ${lower(vnt(doorWhy))}` : null
  } else if (plan.verdict.code === 'none') {
    tone = 'bad'
    icon = <Ban size={18} />
  }

  const trip = best?.trip
  return (
    <section className={`verdict tone-${tone} ${stale ? 'is-stale' : ''}`} aria-live="polite">
      {(KICKER[tone] || stale) && <div className="verdict-kicker">{KICKER[tone] && <>{icon}<span>{KICKER[tone]}</span> </>}{stale && <LoaderCircle size={14} className="spin" aria-label="Updating" />}</div>}
      <h2 className="display">{head}</h2>
      {sub && <p className="verdict-sub">{sub}</p>}
      {recommendation && <p className="verdict-recommendation">{recommendation}</p>}
      {timing?.approximate && <p className="faint">Departure checks use estimated travel windows; they do not guarantee continuous real-world conditions.</p>}
      {plan.intent === 'park' && (timing?.leave_before_at || timing?.or_after_at) && (
        <div className="verdict-actions">
          {([['leave_before_at', 'Set earlier departure'], ['or_after_at', 'Set later departure']] as const).map(([key, label]) => {
            const iso = timing?.[key]
            return iso && timestamp(iso) != null ? (
              <button key={key} type="button" className="btn btn-tonal btn-sm" disabled={stale} onClick={() => onDeparture(iso)}>
                {label} {floodTimeLabel(iso)}
              </button>
            ) : null
          })}
          {timing?.if_leave_before && <span className="faint">Then: {THEN[timing.if_leave_before.code] ?? lower(timing.if_leave_before.headline)}</span>}
        </div>
      )}
      {plan.intent === 'pickup' && timing && <p className="faint">Pickup uses a {plan.window.dwell_min} min window. For a longer stay, select parking and recalculate.</p>}
      {!best && plan.door && <Transparency plan={plan} stop={plan.door} comparison={comparison} fleet={fleet} onVehicle={onVehicle} disabled={stale} top />}
      {trip && (
        <div className="trip">
          <span className="trip-big display num">{minutes(trip.total_min)}</span>
          <span className="trip-meta"><CarFront size={14} /> {distance(trip.drive_m)} · {minutes(trip.drive_min)} driving</span>
          <span className="trip-meta"><Footprints size={14} /> {trip.walk_m} m walk</span>
        </div>
      )}
    </section>
  )
}
const KICKER: Record<Tone, string> = { ok: 'Can enter', brand: 'Stop nearby', warn: 'Watch your departure time', muted: '', bad: 'No suitable stop', water: '' }
const THEN: Record<string, string> = { door: 'can enter and exit at the door', nearby: 'park nearby with an exit', unverified: 'suggestion remains unverified', none: 'still no suitable stop' }
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/* ---------- live area build ---------- */

const STEP_VI = { map: 'Alley map', parcels: 'Width from parcels', listings: 'Chợ Tốt and Alonhadat listings', match: 'Match listings to alleys', news: 'News on nearby routes', photos: 'AI reading of listing photos' } as const

export function LiveStrip({ build }: { build: AreaBuild }) {
  if (!build.steps) return null
  const steps = Object.entries(build.steps) as [keyof typeof STEP_VI, { state: string; detail: string }][]
  const done = steps.filter(([, s]) => s.state === 'done' || s.state === 'skipped').length
  const current = steps.find(([, s]) => s.state === 'running')
  const c = build.counts
  const summary = build.state === 'queued' ? 'Queued on the server'
    : build.state === 'running'
    ? `${STEP_VI[current?.[0] ?? 'map']}${current?.[0] === 'listings' && c ? ` · ${c.fetched} listings` : ''}${current?.[0] === 'photos' && c ? ` · ${c.photos_read}/${c.photos_total} photos` : ''}`
    : build.state === 'error' ? 'Data collection failed' : `${c?.matched ?? 0} listings matched to ${c?.alleys ?? 0} nearby alleys`
  return (
    <details className={`live ${build.state}`}>
      <summary>
        {build.state === 'running' ? <LoaderCircle size={15} className="spin" /> : build.state === 'error' ? <OctagonAlert size={15} /> : <CircleCheck size={15} />}
        <span><b>{build.state === 'running' ? 'Collecting area data' : 'Area data'}</b> · {summary}</span>
        <ChevronDown size={15} className="chev" />
      </summary>
      {build.state === 'running' && <div className="bar"><i style={{ width: `${(done / steps.length) * 100}%` }} /></div>}
      <ol>
        {steps.map(([k, s]) => (
          <li key={k} className={`st-${s.state}`}><span>{STEP_VI[k]}</span><small>{s.detail || (s.state === 'pending' ? 'pending' : '')}</small></li>
        ))}
      </ol>
      {build.error && <p className="note">{build.error}</p>}
    </details>
  )
}

/* ---------- recent news ---------- */

const NEWS_KIND = { flood: { tone: 'water', label: 'Flooding' }, works: { tone: 'warn', label: 'Roadworks' }, ban: { tone: 'bad', label: 'Vehicle restriction' } } as const

export function NewsList({ items }: { items: NewsItem[] }) {
  if (!items.length) return null
  return (
    <details className="news" open={items.some((item) => item.kind !== 'works')}>
      <summary><Newspaper size={15} /><span><b>Recent local news</b> · {items.length} stories in 12 months</span><ChevronDown size={15} className="chev" /></summary>
      <ul>
        {items.slice(0, 6).map((n) => (
          <li key={n.url}>
            <Tag tone={NEWS_KIND[n.kind].tone}>{NEWS_KIND[n.kind].label}</Tag>
            <a href={n.url} target="_blank" rel="noreferrer">{n.summary}</a>
            <small>{n.street} · {n.source} · {n.date.split('-').reverse().join('/')}</small>
          </li>
        ))}
      </ul>
      <p className="faint">Found via Google News; Gemini filters for the relevant HCMC roads. For reference only, not used as evidence.</p>
    </details>
  )
}

/* ---------- stop rows ---------- */

const FIT = {
  fits: { tone: 'ok', label: 'Fits' }, tight: { tone: 'warn', label: 'Tight' }, no: { tone: 'bad', label: 'Does not fit' },
  unknown: { tone: 'muted', label: 'Unknown width' }, blocked: { tone: 'bad', label: 'Currently blocked' }, lot: { tone: 'ok', label: 'Car park' },
} as const
const LEGAL = { Permitted: { tone: 'ok', label: 'Permitted' }, Restricted: { tone: 'warn', label: 'Restricted' }, Prohibited: { tone: 'bad', label: 'Prohibited' }, Unverified: { tone: 'muted', label: 'Unknown rules' } } as const
const FLOOD = { passable: { tone: 'ok', label: 'Within vehicle limits' }, risky: { tone: 'warn', label: 'Possible flooding' }, blocked: { tone: 'bad', label: 'Exceeds vehicle limits' } } as const

export function floodPresentation(check: FloodCheck | null | undefined): { tone: Tone; label: string } {
  if (check?.status === 'blocked') return FLOOD.blocked
  if (!check || check.knowledge !== 'known') return { tone: 'muted', label: 'Insufficient flood data' }
  return FLOOD[check.status]
}

export function FloodEvidenceDetail({ check }: { check: FloodCheck | null | undefined }) {
  const d = check?.depth
  const validDepth = d != null && Number.isFinite(d.lo) && Number.isFinite(d.hi)
  const source = check?.source ?? check?.freshness?.source
  return (
    <div className="flood-evidence">
      <p>{validDepth ? `Estimated water depth ${Math.round(d.lo * 100)}–${Math.round(d.hi * 100)} cm.` : check?.knowledge === 'known' && check.status === 'passable' ? 'No flood depth forecast within the check window.' : 'Water depth is unknown; cannot confirm it is within vehicle limits.'}</p>
      <p>{floodKnowledgeLabel(check?.knowledge)}{check?.at && ` · checked ${floodTimeLabel(check.at)}`}.</p>
      {check?.reason && <p>{vnt(check.reason)}</p>}
      {source && <p>Source: {vnt(source)}.</p>}
      {check?.freshness?.observed_at && <p>Observed: {floodTimeLabel(check.freshness.observed_at)}.</p>}
      {check?.freshness?.valid_until && <p>Valid until: {floodTimeLabel(check.freshness.valid_until)}.</p>}
      {d?.drivers.length ? <p>Basis: {vnt(d.drivers.join('; '))}.</p> : null}
      {d?.inferred && <p>Inferred from an adjacent flooded road.</p>}
    </div>
  )
}

function LegFloodEvidence({ check }: { check: LegFloodCheck | null | undefined }) {
  return (
    <>
      <FloodEvidenceDetail check={check} />
      {check?.interval && <p>{check.interval.approximate ? 'Estimated travel window' : 'Stay window'}: {floodTimeLabel(check.interval.start)} to {floodTimeLabel(check.interval.end)}.</p>}
      {check?.legs.length ? <ul className="flood-legs">{check.legs.map((leg, i) => (
        <li key={`${leg.way_id}-${i}`}>
          <b>{leg.name || (leg.way_id != null ? `Road segment ${leg.way_id}` : 'Unnamed road segment')}</b>
          <Tag tone={floodPresentation(leg).tone}>{floodPresentation(leg).label}</Tag>
          <FloodEvidenceDetail check={leg} />
        </li>
      ))}</ul> : <p>No evidence for individual road segments yet.</p>}
    </>
  )
}

function kindLabel(s: StopPoint) {
  if (s.kind === 'door') return 'At the door'
  if (s.kind === 'lot') return s.lot?.source === 'VETC' ? 'Car park · VETC payment' : 'Car park'
  return 'Roadside'
}
function exitTone(s: StopPoint): Tone {
  if (s.way_out.mode === 'none' || !s.way_out.available) return 'bad'
  if (s.way_out.route_verified === false || s.way_out.turn_verified === false || s.kind === 'lot') return 'muted'
  return s.way_out.tight_exit ? 'warn' : 'ok'
}
function exitShort(s: StopPoint) {
  let label: string
  if (!s.way_out.available) {
    label = s.way_out.flood?.status === 'blocked' ? 'Flooded exit route'
      : s.way_out.mode === 'none' ? 'Difficult exit' : 'Unverified exit route'
  } else if (s.kind === 'lot') label = 'Car park exit unverified'
  else if (s.way_out.mode === 'reverse') label = `Reverse ${s.way_out.reverse_m ?? ''} m; turning space unverified`.replace('  ', ' ')
  else if (s.way_out.mode === 'turn_here') label = 'Turning space unverified'
  else if (s.way_out.mode === 'through') label = s.way_out.route_verified === false ? 'Exit unverified' : 'Exit forwards'
  else label = s.way_out.mode === 'none' ? 'Difficult exit' : 'Can exit'
  return s.way_out.observed?.length ? `${label} · Exit information available` : label
}

export function StopRow({ s, plan, index, selected, open, onSelect, onEvidence, maneuver, maneuverDisabled, onManeuver, onReplay, onDismiss, comparison, fleet, onVehicle }: {
  s: StopPoint; plan: Plan; index: number; selected: boolean; open: boolean
  comparison: PlanComparison | null; fleet: Vehicle[]; onVehicle: (id: string) => void
  onSelect: () => void; onEvidence: (wayId: number) => void
  maneuver: ManeuverState | null; maneuverDisabled: boolean
  onManeuver: () => void; onReplay: () => void; onDismiss: () => void
}) {
  const fit = FIT[s.fit.class] ?? FIT.unknown
  const legal = LEGAL[s.legality.status]
  const flood = floodPresentation(s.flood.stay)
  const title = s.kind === 'door' ? 'At the door' : s.kind === 'lot' ? s.lot?.name ?? s.name : s.name
  const wr = s.fit.width_range
  const supportedWidth = !!wr?.decisive_clearance && wr.evidence.length > 0
  const narrowerThanMirrors = wr != null && wr.lo < plan.vehicle.mirror_width
  const canShowClearance = supportedWidth && !narrowerThanMirrors
  const replayable = maneuver?.status === 'ready' && maneuver.result.moves != null && !!maneuver.result.poses?.length
  return (
    <article className={`stop ${selected ? 'is-selected' : ''}`}>
      <button type="button" className="stop-head" onClick={onSelect} aria-expanded={open}>
        <span className={`stop-pin ${s.verified ? '' : 'unverified'}`}>{index + 1}</span>
        <span className="stop-main">
          <span className="stop-name">{title}</span>
          <span className="stop-meta">{kindLabel(s)} · walk {s.walk.meters} m</span>
        </span>
        <span className="stop-time display num">{s.trip ? minutes(s.trip.total_min) : `${s.walk.minutes} min`}</span>
      </button>
      <div className="stop-tags">
        {negativeAccess(s) && <Tag tone="bad" icon={<Ban size={13} />}>Access unlikely</Tag>}
        <Tag tone={fit.tone} icon={<CarFront size={13} />}>{fit.label}</Tag>
        <Tag tone={exitTone(s)} icon={<Navigation size={13} />}>{exitShort(s)}</Tag>
        <Tag tone={flood.tone === 'ok' ? 'water' : flood.tone} icon={<Droplets size={13} />}>{flood.label}</Tag>
        <Tag tone={legal.tone} icon={<Landmark size={13} />}>{legal.label}</Tag>
      </div>
      {selected && <Transparency key={`${s.lat},${s.lon}`} plan={plan} stop={s} comparison={comparison} fleet={fleet} onVehicle={onVehicle} disabled={maneuverDisabled} top={index === 0} />}
      {selected && <div className="maneuver-entry">
        <button type="button" className="btn btn-outline" onClick={onManeuver} disabled={maneuverDisabled} aria-expanded={!!maneuver}>
          <CarFront size={16} />
          {maneuver?.status === 'error' ? 'Retry loading' : maneuver ? 'Hide simulation' : 'Preview vehicle in alley'}
        </button>
        {maneuver && <section className="maneuver-panel" aria-label="Turning simulation in a straight corridor">
          <header>
            <div>
              <b>Turning path</b>
              <small>Local 2D view. Results do not change entry or exit conclusions.</small>
            </div>
            <button type="button" className="icon-btn" aria-label="Close simulation" onClick={onDismiss}><X size={16} /></button>
          </header>
          <p className={`maneuver-width ${canShowClearance ? '' : 'is-uncertain'}`}>
            {wr
              ? plan.vehicle.kind === 'class'
                ? <>{plan.vehicle.label}: displayed width {fmtWidth(wr.lo, wr.hi)}. Simulated using {maneuver.status === 'ready' ? maneuver.result.simulated_vehicle_label : 'the class member needing the most turning space'} (mirrors {metres(maneuver.status === 'ready' ? maneuver.result.vehicle_mirror_width_m : plan.vehicle.mirror_width, 2)}); widest vehicle in class {metres(plan.vehicle.mirror_width, 2)}.</>
                : <>{plan.vehicle.label}: displayed width {fmtWidth(wr.lo, wr.hi)}. Vehicle width including mirrors {metres(plan.vehicle.mirror_width, 2)}.</>
              : <>No width range available to compare with the vehicle.</>}
          </p>
          {!canShowClearance && <p className="maneuver-caveat">
            {narrowerThanMirrors
              ? 'The narrowest bound is below the vehicle width including mirrors. Positive clearance cannot be confirmed.'
              : 'Width lacks decisive evidence. Dashed lines show uncertainty.'}
            {' '}Simulation is not safety evidence.
          </p>}
          {plan.vehicle.kind === 'class' && <p className="maneuver-caveat">Vehicle classes use the most conservative dimensions within the class.</p>}
          {maneuver.status === 'loading' && <p role="status" className="maneuver-status"><LoaderCircle size={15} className="spin" /> Loading simulation.</p>}
          {maneuver.status === 'error' && <p role="alert" className="maneuver-error">Could not load simulation. {maneuver.error}</p>}
          {maneuver.status === 'unavailable' && <p role="status" className="maneuver-status">
            {maneuver.reason === 'missing-width'
              ? 'No alley width available to request a simulation.'
              : 'Width is outside the simulation range (1.5–15 m).'}
            {' '}The static vehicle illustrates dimensions only.
          </p>}
          {maneuver.status === 'ready' && (maneuver.result.moves == null || !maneuver.result.poses?.length
            ? <p role="status" className="maneuver-status">Simulation found no turning path in this straight corridor.</p>
            : <div className="maneuver-result">
              <p role="status">The simulated path has {maneuver.result.moves} moves. Multiple forward and reverse moves may be needed.</p>
              {maneuver.result.length_m != null && <p>Simulated path length: {metres(maneuver.result.length_m)}.</p>}
              {maneuver.playback > 0 && window.matchMedia('(prefers-reduced-motion: reduce)').matches
                && <p>Showing a static pose for reduced motion.</p>}
              {replayable && <button type="button" className="btn btn-tonal" onClick={onReplay}>
                {maneuver.playback > 0 ? <RotateCcw size={16} /> : <Play size={16} />}
                {window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'Show static pose' : maneuver.playback > 0 ? 'Replay simulation' : 'Run simulation'}
              </button>}
            </div>)}
        </section>}
      </div>}
      {open && <StopChecks s={s} plan={plan} onEvidence={onEvidence} />}
    </article>
  )
}

function StopChecks({ s, plan, onEvidence }: { s: StopPoint; plan: Plan; onEvidence: (wayId: number) => void }) {
  const wr = s.fit.width_range
  const need = s.fit.needed
  return (
    <div className="checks">
      <Check icon={<CarFront size={16} />} title="Entry route" tone={(FIT[s.fit.class] ?? FIT.unknown).tone}>
        {wr ? <>
          {wr.hi == null ? `At least ${metres(wr.lo)}` : `Width ${fmtWidth(wr.lo, wr.hi)}`}
          {wr.width_basis === 'synthetic_demo_width' || !wr.top_tier ? ' (unmeasured)' : ''}{need && `, vehicle needs ${metres(need.tight_min, 2)}`}.
          {s.route_in && (s.route_in.available
            ? s.route_in.meters != null && <> Alley section {s.route_in.meters} m.</>
            : <> No suitable entry route for this vehicle yet.</>)}
          {wr.review && <> <b>Conflicting evidence needs review.</b></>}
        </> : s.kind === 'lot' ? 'Nearby car park; entrance geometry is unverified.' : vnt(s.fit.note ?? 'No width data yet.')}
        {s.way_id && <button type="button" className="link-btn" onClick={() => onEvidence(s.way_id!)}>View evidence</button>}
      </Check>
      <Check icon={<Navigation size={16} />} title="Exit route" tone={exitTone(s)}>
        {vnt(s.way_out.text)}
        {!!s.way_out.observed?.length && <details className="way-out-observations">
          <summary>{s.way_out.observed.length} approved observations; conclusions unchanged</summary>
          <ul>{s.way_out.observed.slice(0, 4).map((claim, i) => (
            <li key={`${claim.source}-${claim.detail}-${i}`}>
              {vnt(claim.detail)} <small>{vnt(claim.source)}{claim.observed_on ? ` · ${claim.observed_on}` : ''}</small>
            </li>
          ))}</ul>
        </details>}
      </Check>
      <Check icon={<Droplets size={16} />} title="Entry route flooding" tone={floodPresentation(s.route_in?.flood).tone}>
        <LegFloodEvidence check={s.route_in?.flood} />
      </Check>
      <Check icon={<Droplets size={16} />} title="Flooding during stay" tone={floodPresentation(s.flood.stay).tone}>
        <LegFloodEvidence check={s.flood.stay} />
        <p>Vehicle water limit: {Math.round(plan.vehicle.safe_water_depth * 100)} cm.</p>
      </Check>
      <Check icon={<Droplets size={16} />} title="Exit route flooding" tone={floodPresentation(s.way_out.flood).tone}>
        <LegFloodEvidence check={s.way_out.flood} />
      </Check>
      <Check icon={<Landmark size={16} />} title={plan.intent === 'park' ? 'Parking rules' : 'Stopping rules'} tone={LEGAL[s.legality.status].tone}>
        <ul className="rules">
          {s.legality.rules.map((r, i) => <li key={i}>{vnt(r.text)} <cite>{r.citation}</cite></li>)}
        </ul>
      </Check>
      <Check icon={<Footprints size={16} />} title="Walk" tone={s.walk.wade ? 'warn' : 'ok'}>
        {s.walk.meters} m, about {minutes(s.walk.minutes)}
        {s.walk.wade && `; wading depth ${Math.round(s.walk.wade.lo * 100)}–${Math.round(s.walk.wade.hi * 100)} cm`}
        {s.walk.connection && !s.walk.connection.mapped && (
          <p className="unverified">
            {s.walk.connection.reason} (stop {s.walk.connection.stop_to_walk_m} m; address {s.walk.connection.destination_to_walk_m} m).
          </p>
        )}
        {plan.intent === 'pickup' && '. Passengers walk this distance to the car.'}
      </Check>
      {s.unverified_reasons.length > 0 && (
        <p className="unverified"><TriangleAlert size={14} /> Unverified: {vnt(s.unverified_reasons.join('; '))}</p>
      )}
    </div>
  )
}

function Check({ icon, title, tone, children }: { icon: React.ReactNode; title: string; tone: Tone; children: React.ReactNode }) {
  return (
    <div className={`check t-${tone}`}>
      <span className="check-ico">{icon}</span>
      <div><b>{title}</b><div className="check-detail">{children}</div></div>
    </div>
  )
}

export function StandardRouteContrast({ plan, vehicleLabel, show, onToggle }: { plan: Plan; vehicleLabel: string; show: boolean; onToggle: () => void }) {
  const std = plan.standard_route
  if (!std || !std.unfit_ways.length) return null
  const names = std.unfit_ways.slice(0, 2).map((w) => w.name).join(', ')
  const source = routeSourceLabel(std.source)
  return (
    <details className="why contrast">
      <summary>Compare with route {source}</summary>
      <p>Reference route passes through {names}{std.unfit_ways.length > 2 ? ` and ${std.unfit_ways.length - 2} other alleys` : ''}: {std.unfit_ways.some((w) => w.fit === 'no') ? 'does not fit' : 'fit unknown'} {vehicleLabel}.</p>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onToggle}>{show ? `Hide route ${source}` : `Show route ${source}`}</button>
    </details>
  )
}

export { vn }
