import { Check, ExternalLink, Flag, ImageOff, X } from 'lucide-react'
import { useState } from 'react'
import type { Bound, WayEvidence, WidthBasis, WidthCoverage } from '../api'
import { LookupPanel } from '../LookupPanel'
import { metres } from '../ds/ui'
import { fmtWidth } from './Directions'

type TabId = 'width' | 'photos' | 'flood' | 'lookup'
const TIER_ORDER = ['Synthetic', 'Measured', 'Official', 'Observed', 'Declared', 'Inferred']
const WIDTH_BASIS_LABEL: Record<WidthBasis, string> = {
  measured_clear_width: 'Measured clear width',
  observed_clear_width: 'Observed clear width',
  synthetic_demo_width: 'Clear width',
  parcel_gap_estimate: 'Gap estimated from parcel geometry',
  road_width_estimate: 'Estimated road width, not clear width',
  declared_width: 'Declared width',
  inferred: 'Inferred, unverified',
  unknown: 'Unknown width basis',
}

function CoverageDetails({ coverage }: { coverage: WidthCoverage | null }) {
  if (!coverage) return <small className="width-meta">No spatial coverage data.</small>
  return (
    <small className="width-meta">
      Cross-sections: {coverage.cut_count} · start: {coverage.start_covered ? 'covered' : 'not covered'} · end: {coverage.end_covered ? 'covered' : 'not covered'}
      {' · '}maximum spacing: {coverage.max_spacing_m == null ? 'unknown' : metres(coverage.max_spacing_m)}
      {' · '}complete: {coverage.complete ? 'yes' : 'no'} · truncated by limit: {coverage.truncated ? 'yes' : 'no'}
      {coverage.reason && <> · Reason: {coverage.reason}</>}
    </small>
  )
}

function BoundWidthMetadata({ bound }: { bound: Bound }) {
  return (
    <div className="width-meta-block">
      <small className="width-basis">{WIDTH_BASIS_LABEL[bound.width_basis]}</small>
      <small>Uncertainty: {bound.uncertainty_m == null ? 'not specified' : `±${metres(bound.uncertainty_m)}`}</small>
      <CoverageDetails coverage={bound.coverage} />
      {bound.width_basis === 'parcel_gap_estimate' && (
        <small className="width-caveat">This gap is estimated from parcel geometry rather than measured clear width. Original data provenance appears separately below.</small>
      )}
    </div>
  )
}

function WidthRangeMetadata({ basis, coverage, decisive }: {
  basis: WidthBasis; coverage: WidthCoverage; decisive: boolean
}) {
  return (
    <section className="width-summary" aria-label="Width basis and coverage">
      <b>{WIDTH_BASIS_LABEL[basis]}</b>
      <CoverageDetails coverage={coverage} />
      <small>{decisive
        ? basis === 'synthetic_demo_width'
          ? 'Sufficient information along this route.'
          : 'Clearance has a documented measurement basis and sufficient coverage for assessment.'
        : 'Insufficient measurement evidence and coverage to confirm clearance.'}</small>
    </section>
  )
}


export function EvidencePanel({ way, at, google, grounding, canReview, onClose, onReview, onBlockage }: {
  way: WayEvidence; at: [number, number]; google: boolean; grounding: boolean; canReview: boolean
  onClose: () => void; onReview: (id: string, approve: boolean) => void; onBlockage: () => void
}) {
  const [tab, setTab] = useState<TabId>('width')
  const wr = way.width_range
  const visibleEvidence = wr.evidence.filter((bound) => bound.tier !== 'Synthetic')
  const tabs: { id: TabId; label: string }[] = [
    { id: 'width', label: `Width · ${visibleEvidence.length}` },
    { id: 'photos', label: `Photo · ${way.photos.length}` },
    { id: 'flood', label: `Flooding · ${way.flood_history.records.length}` },
    ...(google || grounding ? [{ id: 'lookup' as TabId, label: 'Lookup' }] : []),
  ]
  return (
    <aside className="evidence card" role="dialog" aria-label={`Evidence for ${way.name || 'road segment'}`}>
      <header>
        <div>
          <span className="faint">Road segment evidence</span>
          <h3 className="display">{way.name || 'Unnamed segment'}</h3>
          <p><b>{wr.decisive_clearance && !wr.review ? wr.label : 'Unverified'}</b> · {fmtWidth(wr.lo, wr.hi)}{wr.top_tier && wr.width_basis !== 'synthetic_demo_width' && <span className="faint"> · strongest source: {wr.evidence.find((b) => b.tier === wr.top_tier)?.tier_vi}</span>}</p>
          {wr.review && <p className="warn-line">Conflicting evidence needs review. Vehicle clearance cannot yet be confirmed.</p>}
        </div>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="tabs" role="tablist">
        {tabs.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      <div className="evidence-body">
        {tab === 'width' && (
          <>
            <WidthRangeMetadata basis={wr.width_basis} coverage={wr.coverage} decisive={wr.decisive_clearance && !wr.review} />
            <ol className="tiers">
              {[...visibleEvidence].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier)).map((b, i) => (
                <li key={i} className={wr.overruled.some((o) => o.detail === b.detail) ? 'overruled' : ''}>
                  <span className={`tier tier-${b.tier}`}>{b.tier_vi}</span>
                  <div>
                    <p>{b.detail}</p>
                    <small>{b.width_basis === 'parcel_gap_estimate' ? `Original data source: ${b.source}` : b.source} · {b.hi == null ? `≥ ${metres(b.lo)}` : fmtWidth(b.lo, b.hi)}{b.observed_on && ` · ${b.observed_on}`}{b.ai_feature && ' · AI'}
                      {b.url && <> · <a href={b.url} target="_blank" rel="noreferrer">source</a></>}</small>
                    <BoundWidthMetadata bound={b} />
                  </div>
                </li>
              ))}
              {wr.way_out_claims.map((b, i) => (
                <li key={`o${i}`}><span className="tier">Exit</span><div><p>{b.detail}</p><small>{b.source}</small><BoundWidthMetadata bound={b} /></div></li>
              ))}
            </ol>
          </>
        )}
        {tab === 'photos' && (way.photos.length === 0 ? (
          <div className="empty"><ImageOff size={22} /><p>No listing photos of this alley yet.</p></div>
        ) : (
          <ul className="photos">
            {way.photos.map((ph) => (
              <li key={ph.id} className={`ph-${ph.status}`}>
                <a href={ph.image_url} target="_blank" rel="noreferrer"><img src={ph.image_url} alt={`Listing photo at ${ph.alley}`} loading="lazy" /></a>
                <div>
                  <b>{ph.width_m ? `AI estimate ≈ ${metres(ph.width_m)}` : 'AI could not estimate'}</b>
                  <small>{ph.reference ? `Based on ${ph.reference}` : ph.notes}{ph.confidence != null && ` · confidence ${Math.round(ph.confidence * 100)}%`}</small>
                  <small><a href={ph.listing_url} target="_blank" rel="noreferrer">Original listing <ExternalLink size={11} /></a>{ph.posted_at && ` · ${ph.posted_at.slice(0, 10)}`}</small>
                  {ph.status === 'pending' && ph.width_m && canReview ? (
                    <div className="ph-actions">
                      <button type="button" className="btn btn-tonal btn-sm" onClick={() => onReview(ph.id, true)}><Check size={14} /> Correct</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => onReview(ph.id, false)}>Incorrect, reject</button>
                    </div>
                  ) : ph.status === 'pending'
                    ? <small className="ph-status">Awaiting operator review; not yet used as observed evidence</small>
                    : <small className={`ph-status ${ph.status}`}>{ph.status === 'approved' ? 'Approved: used as observed evidence' : 'Rejected'}</small>}
                </div>
              </li>
            ))}
          </ul>
        ))}
        {tab === 'flood' && (way.flood_history.records.length === 0 ? (
          <div className="empty"><p>No flood records. Absence of records does not establish flood-free conditions.</p></div>
        ) : (
          <ol className="tiers">
            {way.flood_history.inferred_from && <li className="faint">Inferred from adjacent flooded road: {way.flood_history.inferred_from}</li>}
            {way.flood_history.records.slice(0, 10).map((r, i) => (
              <li key={i}><span className="tier tier-water">{r.year ?? '?'}</span>
                <div><p>{r.street} · {r.cause === 'tide' ? 'high tide' : r.cause === 'rain' ? 'rain' : r.cause}</p>
                  <small>{r.depth_max_cm ? `up to ${r.depth_max_cm} cm` : 'depth unknown'} · location {r.precision} · IRD 2002–2026</small></div></li>
            ))}
          </ol>
        ))}
        {tab === 'lookup' && (
          <LookupPanel key={way.way_id} lat={at[0]} lon={at[1]} wayId={way.way_id} alley={way.name || 'unnamed alley'} google={google} grounding={grounding} />
        )}
      </div>
      <footer>
        <a href={way.osm_url} target="_blank" rel="noreferrer">OpenStreetMap <ExternalLink size={12} /></a>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onBlockage}><Flag size={14} /> Report blocked alley (pending review)</button>
      </footer>
    </aside>
  )
}
