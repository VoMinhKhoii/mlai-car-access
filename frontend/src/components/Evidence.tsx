import { Check, ExternalLink, Flag, ImageOff, X } from 'lucide-react'
import { useState } from 'react'
import type { Bound, WayEvidence, WidthBasis, WidthCoverage } from '../api'
import { LookupPanel } from '../LookupPanel'
import { metres } from '../ds/ui'
import { fmtWidth } from './Directions'

type TabId = 'width' | 'photos' | 'flood' | 'lookup'
const TIER_ORDER = ['Measured', 'Official', 'Observed', 'Declared', 'Inferred']
const WIDTH_BASIS_LABEL: Record<WidthBasis, string> = {
  measured_clear_width: 'Đo thực tế bề rộng thông thủy',
  observed_clear_width: 'Quan sát bề rộng thông thủy',
  parcel_gap_estimate: 'Ước tính khoảng trống từ hình học thửa đất',
  road_width_estimate: 'Ước tính bề rộng đường, không phải thông thủy',
  declared_width: 'Bề rộng được khai báo',
  inferred: 'Suy luận, chưa xác minh',
  unknown: 'Chưa rõ cơ sở bề rộng',
}

function CoverageDetails({ coverage }: { coverage: WidthCoverage | null }) {
  if (!coverage) return <small className="width-meta">Không có dữ liệu phủ theo vị trí.</small>
  return (
    <small className="width-meta">
      Mẫu cắt: {coverage.cut_count} · đầu: {coverage.start_covered ? 'có phủ' : 'chưa phủ'} · cuối: {coverage.end_covered ? 'có phủ' : 'chưa phủ'}
      {' · '}khoảng cách lớn nhất: {coverage.max_spacing_m == null ? 'chưa rõ' : metres(coverage.max_spacing_m)}
      {' · '}đầy đủ: {coverage.complete ? 'có' : 'không'} · bị cắt theo giới hạn: {coverage.truncated ? 'có' : 'không'}
      {coverage.reason && <> · Lý do: {coverage.reason}</>}
    </small>
  )
}

function BoundWidthMetadata({ bound }: { bound: Bound }) {
  return (
    <div className="width-meta-block">
      <small className="width-basis">{WIDTH_BASIS_LABEL[bound.width_basis]}</small>
      <small>Độ không chắc chắn: {bound.uncertainty_m == null ? 'chưa nêu' : `±${metres(bound.uncertainty_m)}`}</small>
      <CoverageDetails coverage={bound.coverage} />
      {bound.width_basis === 'parcel_gap_estimate' && (
        <small className="width-caveat">Đây là khoảng trống ước tính từ hình học thửa đất, không phải phép đo bề rộng thông thủy. Nguồn gốc dữ liệu được giữ riêng bên dưới.</small>
      )}
    </div>
  )
}

function WidthRangeMetadata({ basis, coverage, decisive }: {
  basis: WidthBasis; coverage: WidthCoverage; decisive: boolean
}) {
  return (
    <section className="width-summary" aria-label="Cơ sở và độ phủ của bề rộng">
      <b>{WIDTH_BASIS_LABEL[basis]}</b>
      <CoverageDetails coverage={coverage} />
      <small>{decisive
        ? 'Khoảng thông thủy có cơ sở đo rõ ràng và đủ phủ để đánh giá.'
        : 'Chưa đủ bằng chứng đo và độ phủ để xác nhận xe đi lọt.'}</small>
    </section>
  )
}


export function EvidencePanel({ way, at, google, grounding, onClose, onReview, onBlockage }: {
  way: WayEvidence; at: [number, number]; google: boolean; grounding: boolean
  onClose: () => void; onReview: (id: string, approve: boolean) => void; onBlockage: () => void
}) {
  const [tab, setTab] = useState<TabId>('width')
  const wr = way.width_range
  const tabs: { id: TabId; label: string }[] = [
    { id: 'width', label: `Bề rộng · ${wr.evidence.length}` },
    { id: 'photos', label: `Ảnh · ${way.photos.length}` },
    { id: 'flood', label: `Ngập · ${way.flood_history.records.length}` },
    ...(google || grounding ? [{ id: 'lookup' as TabId, label: 'Tra cứu' }] : []),
  ]
  return (
    <aside className="evidence card" role="dialog" aria-label={`Bằng chứng về ${way.name || 'đoạn đường'}`}>
      <header>
        <div>
          <span className="faint">Bằng chứng cho đoạn đường</span>
          <h3 className="display">{way.name || 'Đoạn không tên'}</h3>
          <p><b>{wr.decisive_clearance && !wr.review ? wr.label : 'Chưa xác minh'}</b> · {fmtWidth(wr.lo, wr.hi)}{wr.top_tier && <span className="faint"> · nguồn mạnh nhất: {wr.evidence.find((b) => b.tier === wr.top_tier)?.tier_vi}</span>}</p>
          {wr.review && <p className="warn-line">Bằng chứng mâu thuẫn, cần người duyệt. Chưa thể xác nhận xe đi lọt.</p>}
        </div>
        <button type="button" className="icon-btn" aria-label="Đóng" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="tabs" role="tablist">
        {tabs.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      <div className="evidence-body">
        {tab === 'width' && (
          <>
            <WidthRangeMetadata basis={wr.width_basis} coverage={wr.coverage} decisive={wr.decisive_clearance && !wr.review} />
            <ol className="tiers">
              {[...wr.evidence].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier)).map((b, i) => (
                <li key={i} className={wr.overruled.some((o) => o.detail === b.detail) ? 'overruled' : ''}>
                  <span className={`tier tier-${b.tier}`}>{b.tier_vi}</span>
                  <div>
                    <p>{b.detail}</p>
                    <small>{b.width_basis === 'parcel_gap_estimate' ? `Nguồn dữ liệu gốc: ${b.source}` : b.source} · {b.hi == null ? `≥ ${metres(b.lo)}` : fmtWidth(b.lo, b.hi)}{b.observed_on && ` · ${b.observed_on}`}{b.ai_feature && ' · AI'}
                      {b.url && <> · <a href={b.url} target="_blank" rel="noreferrer">nguồn</a></>}</small>
                    <BoundWidthMetadata bound={b} />
                  </div>
                </li>
              ))}
              {wr.way_out_claims.map((b, i) => (
                <li key={`o${i}`}><span className="tier">Lối ra</span><div><p>{b.detail}</p><small>{b.source}</small><BoundWidthMetadata bound={b} /></div></li>
              ))}
            </ol>
          </>
        )}
        {tab === 'photos' && (way.photos.length === 0 ? (
          <div className="empty"><ImageOff size={22} /><p>Chưa có ảnh tin rao chụp con hẻm này.</p></div>
        ) : (
          <ul className="photos">
            {way.photos.map((ph) => (
              <li key={ph.id} className={`ph-${ph.status}`}>
                <a href={ph.image_url} target="_blank" rel="noreferrer"><img src={ph.image_url} alt={`Ảnh tin rao ở ${ph.alley}`} loading="lazy" /></a>
                <div>
                  <b>{ph.width_m ? `AI ước lượng ≈ ${metres(ph.width_m)}` : 'AI không ước lượng được'}</b>
                  <small>{ph.reference ? `Theo ${ph.reference}` : ph.notes}{ph.confidence != null && ` · tin cậy ${Math.round(ph.confidence * 100)}%`}</small>
                  <small><a href={ph.listing_url} target="_blank" rel="noreferrer">Tin rao gốc <ExternalLink size={11} /></a>{ph.posted_at && ` · ${ph.posted_at.slice(0, 10)}`}</small>
                  {ph.status === 'pending' && ph.width_m ? (
                    <div className="ph-actions">
                      <button type="button" className="btn btn-tonal btn-sm" onClick={() => onReview(ph.id, true)}><Check size={14} /> Đúng</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => onReview(ph.id, false)}>Sai, bỏ</button>
                    </div>
                  ) : ph.status !== 'pending' && <small className={`ph-status ${ph.status}`}>{ph.status === 'approved' ? 'Đã duyệt: dùng làm bằng chứng “Đã quan sát”' : 'Đã bỏ'}</small>}
                </div>
              </li>
            ))}
          </ul>
        ))}
        {tab === 'flood' && (way.flood_history.records.length === 0 ? (
          <div className="empty"><p>Chưa có ghi nhận ngập. Không có ghi nhận chưa có nghĩa là không ngập.</p></div>
        ) : (
          <ol className="tiers">
            {way.flood_history.inferred_from && <li className="faint">Suy từ đường ngập liền kề: {way.flood_history.inferred_from}</li>}
            {way.flood_history.records.slice(0, 10).map((r, i) => (
              <li key={i}><span className="tier tier-water">{r.year ?? '?'}</span>
                <div><p>{r.street} · {r.cause === 'tide' ? 'triều cường' : r.cause === 'rain' ? 'mưa' : r.cause}</p>
                  <small>{r.depth_max_cm ? `sâu tới ${r.depth_max_cm} cm` : 'không rõ độ sâu'} · vị trí {r.precision} · IRD 2002–2026</small></div></li>
            ))}
          </ol>
        ))}
        {tab === 'lookup' && (
          <LookupPanel key={way.way_id} lat={at[0]} lon={at[1]} wayId={way.way_id} alley={way.name || 'hẻm không tên'} google={google} grounding={grounding} />
        )}
      </div>
      <footer>
        <a href={way.osm_url} target="_blank" rel="noreferrer">OpenStreetMap <ExternalLink size={12} /></a>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onBlockage}><Flag size={14} /> Báo hẻm đang bị chặn</button>
      </footer>
    </aside>
  )
}
