import { ArrowRightLeft, Ban, Newspaper, CarFront, ChevronDown, CircleCheck, CircleHelp, Droplets, Footprints, Landmark, LoaderCircle, Navigation, OctagonAlert, TriangleAlert } from 'lucide-react'
import { routeSourceLabel, type AreaBuild, type NewsItem, type Plan, type StopPoint } from '../api'
import { Tag, distance, metres, minutes, vn, vnt, type Tone } from '../ds/ui'
import { fmtWidth } from './Directions'
import { toLocal } from '../datetime'

const hhmm = (iso: string) => toLocal(iso)?.slice(11, 16) ?? 'giờ chưa xác định'

/* ---------- verdict: say what to do, then why ---------- */

export function Verdict({ plan, onLeaveBefore, stale }: { plan: Plan; onLeaveBefore: (hhmm: string) => void; stale: boolean }) {
  const best = plan.stop_points[0]
  const verb = plan.intent === 'park' ? 'Đỗ' : 'Dừng đón'
  const doorWhy = plan.door && !plan.door.ok ? plan.door.fail_reasons[0] : null
  let tone: Tone = 'ok'
  let icon = <CircleCheck size={18} />
  let head = plan.verdict.headline
  let sub: string | null = plan.verdict.detail || null

  if (plan.timing?.leave_before || plan.timing?.or_after) {
    tone = 'warn'
    icon = <Droplets size={18} />
    head = `Lúc ${hhmm(plan.window.depart)} đường ra sẽ ngập`
    sub = [plan.timing.leave_before && `Rời trước ${plan.timing.leave_before}`, plan.timing.or_after && `hoặc ở lại tới sau ${plan.timing.or_after}`]
      .filter(Boolean).join(' ') + '.'
    if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
      sub += ' Chỗ dừng gợi ý chưa xác minh; giờ rời không xác nhận xe vào và ra được.'
    }
  } else if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
    tone = 'muted'
    icon = <CircleHelp size={18} />
    head = 'Gợi ý chưa xác minh'
    sub = best ? `Chưa đủ dữ liệu xác nhận: ${verb.toLowerCase()} ở ${best.name}, đi bộ ${minutes(best.walk.minutes)}.` : sub
  } else if (plan.verdict.code === 'door') {
    head = plan.intent === 'park' ? 'Vào tận cửa được' : 'Dừng đón ngay trước cửa được'
    sub = best ? vnt(best.way_out.text) : sub
  } else if (plan.verdict.code === 'nearby' && best) {
    tone = 'brand'
    icon = <ArrowRightLeft size={18} />
    head = `${verb} ở ${best.name}, đi bộ ${minutes(best.walk.minutes)}`
    sub = doorWhy ? `Không nên vào tận cửa: ${lower(vnt(doorWhy))}` : null
  } else if (plan.verdict.code === 'none') {
    tone = 'bad'
    icon = <Ban size={18} />
  }

  const trip = best?.trip
  return (
    <section className={`verdict tone-${tone} ${stale ? 'is-stale' : ''}`} aria-live="polite">
      <div className="verdict-kicker">{icon}<span>{KICKER[tone]}</span>{stale && <LoaderCircle size={14} className="spin" aria-label="Đang cập nhật" />}</div>
      <h2 className="display">{head}</h2>
      {sub && <p className="verdict-sub">{sub}</p>}
      {plan.timing?.leave_before && (
        <div className="verdict-actions">
          <button type="button" className="btn btn-tonal btn-sm" onClick={() => onLeaveBefore(plan.timing!.leave_before!)}>
            Đặt giờ rời {plan.timing.leave_before}
          </button>
          {plan.timing.if_leave_before && <span className="faint">Khi đó: {THEN[plan.timing.if_leave_before.code] ?? lower(plan.timing.if_leave_before.headline)}</span>}
        </div>
      )}
      {trip && (
        <div className="trip">
          <span className="trip-big display num">{minutes(trip.total_min)}</span>
          <span className="trip-meta"><CarFront size={14} /> {distance(trip.drive_m)} · {minutes(trip.drive_min)} lái</span>
          <span className="trip-meta"><Footprints size={14} /> {trip.walk_m} m đi bộ</span>
        </div>
      )}
    </section>
  )
}
const KICKER: Record<Tone, string> = { ok: 'Vào được', brand: 'Dừng gần đó', warn: 'Cẩn thận giờ về', muted: 'Chưa đủ dữ liệu xác minh', bad: 'Không có chỗ phù hợp', water: '' }
const THEN: Record<string, string> = { door: 'vào và ra tận cửa được', nearby: 'đỗ gần đó, ra được', unverified: 'gợi ý vẫn chưa xác minh', none: 'vẫn chưa có chỗ phù hợp' }
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/* ---------- live area build ---------- */

const STEP_VI = { map: 'Bản đồ hẻm', parcels: 'Bề rộng theo thửa đất', listings: 'Tin rao Chợ Tốt, Alonhadat', match: 'Khớp tin rao với hẻm', news: 'Tin tức về các tuyến quanh đây', photos: 'AI đọc ảnh tin rao' } as const

export function LiveStrip({ build }: { build: AreaBuild }) {
  if (build.state === 'off' || !build.steps) return null
  const steps = Object.entries(build.steps) as [keyof typeof STEP_VI, { state: string; detail: string }][]
  const done = steps.filter(([, s]) => s.state === 'done' || s.state === 'skipped').length
  const current = steps.find(([, s]) => s.state === 'running')
  const c = build.counts
  const summary = build.state === 'running'
    ? `${STEP_VI[current?.[0] ?? 'map']}${current?.[0] === 'listings' && c ? ` · ${c.fetched} tin` : ''}${current?.[0] === 'photos' && c ? ` · ${c.photos_read}/${c.photos_total} ảnh` : ''}`
    : build.state === 'error' ? 'Lỗi khi thu thập dữ liệu' : `${c?.matched ?? 0} tin rao khớp ${c?.alleys ?? 0} hẻm quanh đây`
  return (
    <details className={`live ${build.state}`}>
      <summary>
        {build.state === 'running' ? <LoaderCircle size={15} className="spin" /> : build.state === 'error' ? <OctagonAlert size={15} /> : <CircleCheck size={15} />}
        <span><b>{build.state === 'running' ? 'Đang thu thập dữ liệu khu vực' : 'Dữ liệu khu vực'}</b> · {summary}</span>
        <ChevronDown size={15} className="chev" />
      </summary>
      {build.state === 'running' && <div className="bar"><i style={{ width: `${(done / steps.length) * 100}%` }} /></div>}
      <ol>
        {steps.map(([k, s]) => (
          <li key={k} className={`st-${s.state}`}><span>{STEP_VI[k]}</span><small>{s.detail || (s.state === 'pending' ? 'chờ' : '')}</small></li>
        ))}
      </ol>
      {build.error && <p className="note">{build.error}</p>}
    </details>
  )
}

/* ---------- recent news ---------- */

const NEWS_KIND = { flood: { tone: 'water', label: 'Ngập' }, works: { tone: 'warn', label: 'Thi công' }, ban: { tone: 'bad', label: 'Cấm xe' } } as const

export function NewsList({ items }: { items: NewsItem[] }) {
  if (!items.length) return null
  return (
    <details className="news" open={items.some((n) => n.kind !== 'works')}>
      <summary><Newspaper size={15} /><span><b>Tin gần đây quanh đây</b> · {items.length} tin trong 12 tháng</span><ChevronDown size={15} className="chev" /></summary>
      <ul>
        {items.slice(0, 6).map((n) => (
          <li key={n.url}>
            <Tag tone={NEWS_KIND[n.kind].tone}>{NEWS_KIND[n.kind].label}</Tag>
            <a href={n.url} target="_blank" rel="noreferrer">{n.summary}</a>
            <small>{n.street} · {n.source} · {n.date.split('-').reverse().join('/')}</small>
          </li>
        ))}
      </ul>
      <p className="faint">Tìm qua Google News, Gemini lọc tin đúng tuyến ở TP.HCM. Chỉ để tham khảo, chưa dùng làm bằng chứng.</p>
    </details>
  )
}

/* ---------- stop rows ---------- */

const FIT = {
  fits: { tone: 'ok', label: 'Vừa xe' }, tight: { tone: 'warn', label: 'Chật' }, no: { tone: 'bad', label: 'Không vừa' },
  unknown: { tone: 'muted', label: 'Chưa rõ bề rộng' }, blocked: { tone: 'bad', label: 'Đang bị chặn' }, lot: { tone: 'ok', label: 'Bãi đỗ' },
} as const
const LEGAL = { Permitted: { tone: 'ok', label: 'Được phép' }, Restricted: { tone: 'warn', label: 'Hạn chế' }, Prohibited: { tone: 'bad', label: 'Cấm' }, Unverified: { tone: 'muted', label: 'Chưa rõ luật' } } as const
const FLOOD = { passable: { tone: 'ok', label: 'Trong ngưỡng xe' }, risky: { tone: 'warn', label: 'Có thể ngập' }, blocked: { tone: 'bad', label: 'Quá ngưỡng xe' } } as const

function kindLabel(s: StopPoint) {
  if (s.kind === 'door') return 'Trước cửa'
  if (s.kind === 'lot') return s.lot?.source === 'VETC' ? 'Bãi đỗ · thanh toán VETC' : 'Bãi đỗ'
  return 'Lề đường'
}
function exitTone(s: StopPoint): Tone { return s.way_out.mode === 'none' ? 'bad' : s.way_out.tight_exit ? 'warn' : 'ok' }
function exitShort(s: StopPoint) {
  if (s.kind === 'lot') return 'Ra theo cổng bãi'
  if (s.way_out.mode === 'reverse') return `Lùi ${s.way_out.reverse_m ?? ''} m`.replace('  ', ' ')
  if (s.way_out.mode === 'turn_here') return 'Quay đầu tại chỗ'
  if (s.way_out.mode === 'through') return 'Đi thẳng ra'
  return s.way_out.mode === 'none' ? 'Khó ra' : 'Ra được'
}

export function StopRow({ s, plan, index, selected, onSelect, onEvidence }: {
  s: StopPoint; plan: Plan; index: number; selected: boolean; onSelect: () => void; onEvidence: (wayId: number) => void
}) {
  const fit = FIT[s.fit.class] ?? FIT.unknown
  const legal = LEGAL[s.legality.status]
  const flood = FLOOD[s.flood.stay.status]
  const title = s.kind === 'door' ? 'Trước cửa nhà' : s.kind === 'lot' ? s.lot?.name ?? s.name : s.name
  return (
    <article className={`stop ${selected ? 'is-open' : ''}`}>
      <button type="button" className="stop-head" onClick={onSelect} aria-expanded={selected}>
        <span className={`stop-pin ${s.verified ? '' : 'unverified'}`}>{index + 1}</span>
        <span className="stop-main">
          <span className="stop-name">{title}</span>
          <span className="stop-meta">{kindLabel(s)} · đi bộ {s.walk.meters} m</span>
        </span>
        <span className="stop-time display num">{s.trip ? minutes(s.trip.total_min) : `${s.walk.minutes}′`}</span>
      </button>
      <div className="stop-tags">
        <Tag tone={fit.tone} icon={<CarFront size={13} />}>{fit.label}</Tag>
        <Tag tone={exitTone(s)} icon={<Navigation size={13} />}>{exitShort(s)}</Tag>
        <Tag tone={flood.tone === 'ok' ? 'water' : flood.tone} icon={<Droplets size={13} />}>{flood.label}</Tag>
        <Tag tone={legal.tone} icon={<Landmark size={13} />}>{legal.label}</Tag>
      </div>
      {selected && <StopChecks s={s} plan={plan} onEvidence={onEvidence} />}
    </article>
  )
}

function StopChecks({ s, plan, onEvidence }: { s: StopPoint; plan: Plan; onEvidence: (wayId: number) => void }) {
  const wr = s.fit.width_range
  const need = s.fit.needed
  const d = s.flood.stay.depth
  return (
    <div className="checks">
      <Check icon={<CarFront size={16} />} title="Đường vào" tone={(FIT[s.fit.class] ?? FIT.unknown).tone}>
        {wr ? <>
          {wr.hi == null ? `Rộng ít nhất ${metres(wr.lo)}` : `Rộng ${fmtWidth(wr.lo, wr.hi)}`}
          {wr.top_tier ? '' : ' (chưa đo)'}{need && `, xe cần ${metres(need.tight_min, 2)}`}.
          {s.route_in && <> Đoạn trong hẻm {s.route_in.meters} m.</>}
          {wr.review && <> <b>Bằng chứng mâu thuẫn, cần duyệt.</b></>}
        </> : s.kind === 'lot' ? 'Bãi đỗ: vào bằng cổng chính.' : vnt(s.fit.note ?? 'Chưa có dữ liệu bề rộng.')}
        {s.way_id && <button type="button" className="link-btn" onClick={() => onEvidence(s.way_id!)}>Xem bằng chứng</button>}
      </Check>
      <Check icon={<Navigation size={16} />} title="Đường ra" tone={exitTone(s)}>{vnt(s.way_out.text)}</Check>
      <Check icon={<Droplets size={16} />} title="Ngập lúc ở lại" tone={FLOOD[s.flood.stay.status].tone}>
        {d ? `Nước ${Math.round(d.lo * 100)}–${Math.round(d.hi * 100)} cm${s.flood.stay.at ? ` lúc ${s.flood.stay.at}` : ''}` : 'Chưa ghi nhận ngập ở đây'}
        {`; xe chịu được ${Math.round(plan.vehicle.safe_water_depth * 100)} cm.`}
        {d?.inferred && ' Suy từ đường ngập liền kề.'}
      </Check>
      <Check icon={<Landmark size={16} />} title={plan.intent === 'park' ? 'Luật đỗ xe' : 'Luật dừng xe'} tone={LEGAL[s.legality.status].tone}>
        <ul className="rules">
          {s.legality.rules.map((r, i) => <li key={i}>{vnt(r.text)} <cite>{r.citation}</cite></li>)}
        </ul>
      </Check>
      <Check icon={<Footprints size={16} />} title="Đi bộ" tone={s.walk.wade ? 'warn' : 'ok'}>
        {s.walk.meters} m, khoảng {minutes(s.walk.minutes)}
        {s.walk.wade && `; lội nước ${Math.round(s.walk.wade.lo * 100)}–${Math.round(s.walk.wade.hi * 100)} cm`}
        {plan.intent === 'pickup' && '. Khách đi bộ quãng này tới xe.'}
      </Check>
      {s.unverified_reasons.length > 0 && (
        <p className="unverified"><TriangleAlert size={14} /> Chưa xác minh: {vnt(s.unverified_reasons.join('; '))}</p>
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
    <div className="contrast">
      <p><b>Tuyến tham chiếu {source}</b> đi qua {names}{std.unfit_ways.length > 2 ? ` và ${std.unfit_ways.length - 2} hẻm khác` : ''}: {std.unfit_ways.some((w) => w.fit === 'no') ? 'không vừa' : 'chưa rõ có vừa'} {vehicleLabel}.</p>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onToggle}>{show ? `Ẩn tuyến ${source}` : `Hiện tuyến ${source}`}</button>
    </div>
  )
}

export { vn }
