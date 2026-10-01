import { Check, ExternalLink, Flag, ImageOff, X } from 'lucide-react'
import { useState } from 'react'
import type { WayEvidence } from '../api'
import { LookupPanel } from '../LookupPanel'
import { metres } from '../ds/ui'
import { fmtWidth } from './Directions'

type TabId = 'width' | 'photos' | 'flood' | 'lookup'
const TIER_ORDER = ['Measured', 'Official', 'Observed', 'Declared', 'Inferred']

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
          <p><b>{wr.label}</b> · {fmtWidth(wr.lo, wr.hi)}{wr.top_tier && <span className="faint"> · mạnh nhất: {wr.evidence.find((b) => b.tier === wr.top_tier)?.tier_vi}</span>}</p>
          {wr.review && <p className="warn-line">Bằng chứng mâu thuẫn trong cùng một mức tin cậy: cần người duyệt.</p>}
        </div>
        <button type="button" className="icon-btn" aria-label="Đóng" onClick={onClose}><X size={18} /></button>
      </header>
      <div className="tabs" role="tablist">
        {tabs.map((t) => <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      <div className="evidence-body">
        {tab === 'width' && (
          <ol className="tiers">
            {[...wr.evidence].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier)).map((b, i) => (
              <li key={i} className={wr.overruled.some((o) => o.detail === b.detail) ? 'overruled' : ''}>
                <span className={`tier tier-${b.tier}`}>{b.tier_vi}</span>
                <div>
                  <p>{b.detail}</p>
                  <small>{b.source} · {b.hi == null ? `≥ ${metres(b.lo)}` : fmtWidth(b.lo, b.hi)}{b.observed_on && ` · ${b.observed_on}`}{b.ai_feature && ' · AI'}
                    {b.url && <> · <a href={b.url} target="_blank" rel="noreferrer">nguồn</a></>}</small>
                </div>
              </li>
            ))}
            {wr.way_out_claims.map((b, i) => (
              <li key={`o${i}`}><span className="tier">Lối ra</span><div><p>{b.detail}</p><small>{b.source}</small></div></li>
            ))}
          </ol>
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
