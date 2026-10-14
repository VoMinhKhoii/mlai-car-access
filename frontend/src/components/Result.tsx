import { ArrowRightLeft, Ban, Newspaper, CarFront, ChevronDown, CircleCheck, Droplets, Footprints, Landmark, LoaderCircle, Navigation, OctagonAlert, Play, RotateCcw, TriangleAlert, X } from 'lucide-react'
import { floodKnowledgeLabel, routeSourceLabel, type AreaBuild, type FloodCheck, type LegFloodCheck, type ManeuverState, type NewsItem, type Plan, type StopPoint } from '../api'
import { Tag, distance, metres, minutes, vn, vnt, type Tone } from '../ds/ui'
import { fmtWidth } from './Directions'
import { timestamp, toLocal } from '../datetime'

export const floodTimeLabel = (iso: string | null | undefined) => {
  const local = iso ? toLocal(iso) : null
  return local ? `${local.slice(11, 16)} ${local.slice(0, 10).split('-').reverse().join('/')} (UTC+7)` : 'thời điểm chưa xác định'
}
export const exitFloodFailure = (plan: Plan) => plan.timing?.failure_codes.includes('flood_exit') ?? false

/* ---------- verdict: say what to do, then why ---------- */

export function Verdict({ plan, onDeparture, stale }: { plan: Plan; onDeparture: (iso: string) => void; stale: boolean }) {
  const best = plan.stop_points[0]
  const verb = plan.intent === 'park' ? 'Đỗ' : 'Dừng đón'
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
    head = timing.failure_codes.includes('flood_exit') ? 'Cần kiểm tra ngập trên đường ra' : floodHazard ? 'Cần kiểm tra ngập cho chuyến đi' : 'Chưa xác định được giờ rời phù hợp'
    sub = [timing.reason, timing.leave_before_at && `Giờ rời sớm hơn: ${floodTimeLabel(timing.leave_before_at)}`,
      plan.intent === 'park' && timing.or_after_at && `Giờ rời muộn hơn: ${floodTimeLabel(timing.or_after_at)}`].filter(Boolean).join('. ')
    if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
      sub += ' Chỗ dừng gợi ý chưa xác minh; giờ rời không xác nhận xe vào và ra được.'
    }
  } else if (plan.verdict.code === 'unverified' || (best && !best.verified)) {
    tone = 'muted'
    head = plan.verdict.headline
    sub = best ? null : sub
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
      {(KICKER[tone] || stale) && <div className="verdict-kicker">{KICKER[tone] && <>{icon}<span>{KICKER[tone]}</span> </>}{stale && <LoaderCircle size={14} className="spin" aria-label="Đang cập nhật" />}</div>}
      <h2 className="display">{head}</h2>
      {sub && <p className="verdict-sub">{sub}</p>}
      {timing?.approximate && <p className="faint">Kiểm tra giờ rời theo khoảng di chuyển ước lượng; không bảo đảm điều kiện thực tế liên tục.</p>}
      {plan.intent === 'park' && (timing?.leave_before_at || timing?.or_after_at) && (
        <div className="verdict-actions">
          {([['leave_before_at', 'Đặt giờ rời sớm'], ['or_after_at', 'Đặt giờ rời muộn']] as const).map(([key, label]) => {
            const iso = timing?.[key]
            return iso && timestamp(iso) != null ? (
              <button key={key} type="button" className="btn btn-tonal btn-sm" disabled={stale} onClick={() => onDeparture(iso)}>
                {label} {floodTimeLabel(iso)}
              </button>
            ) : null
          })}
          {timing?.if_leave_before && <span className="faint">Khi đó: {THEN[timing.if_leave_before.code] ?? lower(timing.if_leave_before.headline)}</span>}
        </div>
      )}
      {plan.intent === 'pickup' && timing && <p className="faint">Dừng đón giữ {plan.window.dwell_min} phút. Muốn ở lại lâu hơn, hãy chọn mục đích đỗ xe và tính lại.</p>}
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
const KICKER: Record<Tone, string> = { ok: 'Vào được', brand: 'Dừng gần đó', warn: 'Cẩn thận giờ về', muted: '', bad: 'Không có chỗ phù hợp', water: '' }
const THEN: Record<string, string> = { door: 'vào và ra tận cửa được', nearby: 'đỗ gần đó, ra được', unverified: 'gợi ý vẫn chưa xác minh', none: 'vẫn chưa có chỗ phù hợp' }
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/* ---------- live area build ---------- */

const STEP_VI = { map: 'Bản đồ hẻm', parcels: 'Bề rộng theo thửa đất', listings: 'Tin rao Chợ Tốt, Alonhadat', match: 'Khớp tin rao với hẻm', news: 'Tin tức về các tuyến quanh đây', photos: 'AI đọc ảnh tin rao' } as const

export function LiveStrip({ build }: { build: AreaBuild }) {
  if (!build.steps) return null
  const steps = Object.entries(build.steps) as [keyof typeof STEP_VI, { state: string; detail: string }][]
  const done = steps.filter(([, s]) => s.state === 'done' || s.state === 'skipped').length
  const current = steps.find(([, s]) => s.state === 'running')
  const c = build.counts
  const summary = build.state === 'queued' ? 'Đang chờ đến lượt trên máy chủ'
    : build.state === 'running'
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
    <details className="news" open={items.some((item) => item.kind !== 'works')}>
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

export function floodPresentation(check: FloodCheck | null | undefined): { tone: Tone; label: string } {
  if (check?.status === 'blocked') return FLOOD.blocked
  if (!check || check.knowledge !== 'known') return { tone: 'muted', label: 'Chưa đủ dữ liệu ngập' }
  return FLOOD[check.status]
}

export function FloodEvidenceDetail({ check }: { check: FloodCheck | null | undefined }) {
  const d = check?.depth
  const validDepth = d != null && Number.isFinite(d.lo) && Number.isFinite(d.hi)
  const source = check?.source ?? check?.freshness?.source
  return (
    <div className="flood-evidence">
      <p>{validDepth ? `Ước lượng nước ${Math.round(d.lo * 100)}–${Math.round(d.hi * 100)} cm.` : check?.knowledge === 'known' && check.status === 'passable' ? 'Không có mực nước ngập được dự báo trong khoảng kiểm tra.' : 'Chưa xác định độ sâu nước; không thể kết luận trong ngưỡng xe.'}</p>
      <p>{floodKnowledgeLabel(check?.knowledge)}{check?.at && ` · kiểm tra ${floodTimeLabel(check.at)}`}.</p>
      {check?.reason && <p>{vnt(check.reason)}</p>}
      {source && <p>Nguồn: {vnt(source)}.</p>}
      {check?.freshness?.observed_at && <p>Ghi nhận: {floodTimeLabel(check.freshness.observed_at)}.</p>}
      {check?.freshness?.valid_until && <p>Hiệu lực tới: {floodTimeLabel(check.freshness.valid_until)}.</p>}
      {d?.drivers.length ? <p>Căn cứ: {vnt(d.drivers.join('; '))}.</p> : null}
      {d?.inferred && <p>Suy từ đường ngập liền kề.</p>}
    </div>
  )
}

function LegFloodEvidence({ check }: { check: LegFloodCheck | null | undefined }) {
  return (
    <>
      <FloodEvidenceDetail check={check} />
      {check?.interval && <p>{check.interval.approximate ? 'Khoảng di chuyển ước lượng' : 'Khoảng thời gian ở lại'}: {floodTimeLabel(check.interval.start)} tới {floodTimeLabel(check.interval.end)}.</p>}
      {check?.legs.length ? <ul className="flood-legs">{check.legs.map((leg, i) => (
        <li key={`${leg.way_id}-${i}`}>
          <b>{leg.name || (leg.way_id != null ? `Đoạn đường ${leg.way_id}` : 'Đoạn đường chưa xác định tên')}</b>
          <Tag tone={floodPresentation(leg).tone}>{floodPresentation(leg).label}</Tag>
          <FloodEvidenceDetail check={leg} />
        </li>
      ))}</ul> : <p>Chưa có bằng chứng theo từng đoạn đường.</p>}
    </>
  )
}

function kindLabel(s: StopPoint) {
  if (s.kind === 'door') return 'Trước cửa'
  if (s.kind === 'lot') return s.lot?.source === 'VETC' ? 'Bãi đỗ · thanh toán VETC' : 'Bãi đỗ'
  return 'Lề đường'
}
function exitTone(s: StopPoint): Tone {
  if (s.way_out.mode === 'none' || !s.way_out.available) return 'bad'
  if (s.way_out.route_verified === false || s.way_out.turn_verified === false || s.kind === 'lot') return 'muted'
  return s.way_out.tight_exit ? 'warn' : 'ok'
}
function exitShort(s: StopPoint) {
  let label: string
  if (!s.way_out.available) {
    label = s.way_out.flood?.status === 'blocked' ? 'Đường ra bị ngập'
      : s.way_out.mode === 'none' ? 'Khó ra' : 'Đường ra chưa xác minh'
  } else if (s.kind === 'lot') label = 'Lối ra bãi chưa xác minh'
  else if (s.way_out.mode === 'reverse') label = `Lùi ${s.way_out.reverse_m ?? ''} m; quay đầu chưa xác minh`.replace('  ', ' ')
  else if (s.way_out.mode === 'turn_here') label = 'Quay đầu chưa xác minh'
  else if (s.way_out.mode === 'through') label = s.way_out.route_verified === false ? 'Lối ra chưa xác minh' : 'Đi thẳng ra'
  else label = s.way_out.mode === 'none' ? 'Khó ra' : 'Ra được'
  return s.way_out.observed?.length ? `${label} · Có thông tin lối ra` : label
}

export function StopRow({ s, plan, index, selected, open, onSelect, onEvidence, maneuver, maneuverDisabled, onManeuver, onReplay, onDismiss }: {
  s: StopPoint; plan: Plan; index: number; selected: boolean; open: boolean
  onSelect: () => void; onEvidence: (wayId: number) => void
  maneuver: ManeuverState | null; maneuverDisabled: boolean
  onManeuver: () => void; onReplay: () => void; onDismiss: () => void
}) {
  const fit = FIT[s.fit.class] ?? FIT.unknown
  const legal = LEGAL[s.legality.status]
  const flood = floodPresentation(s.flood.stay)
  const title = s.kind === 'door' ? 'Trước cửa nhà' : s.kind === 'lot' ? s.lot?.name ?? s.name : s.name
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
      {selected && <div className="maneuver-entry">
        <button type="button" className="btn btn-outline" onClick={onManeuver} disabled={maneuverDisabled} aria-expanded={!!maneuver}>
          <CarFront size={16} />
          {maneuver?.status === 'error' ? 'Thử tải lại' : maneuver ? 'Ẩn mô phỏng' : 'Xem xe trong hẻm'}
        </button>
        {maneuver && <section className="maneuver-panel" aria-label="Mô phỏng quay đầu trong hành lang thẳng">
          <header>
            <div>
              <b>Quỹ đạo quay đầu</b>
              <small>Khung 2D cục bộ. Kết quả không thay đổi kết luận đường vào hay đường ra.</small>
            </div>
            <button type="button" className="icon-btn" aria-label="Đóng mô phỏng" onClick={onDismiss}><X size={16} /></button>
          </header>
          <p className={`maneuver-width ${canShowClearance ? '' : 'is-uncertain'}`}>
            {wr
              ? plan.vehicle.kind === 'class'
                ? <>{plan.vehicle.label}: bề rộng hiển thị {fmtWidth(wr.lo, wr.hi)}. Mô phỏng theo {maneuver.status === 'ready' ? maneuver.result.simulated_vehicle_label : 'thành viên quay đầu khó nhất'} (gương {metres(maneuver.status === 'ready' ? maneuver.result.vehicle_mirror_width_m : plan.vehicle.mirror_width, 2)}); xe rộng nhất nhóm {metres(plan.vehicle.mirror_width, 2)}.</>
                : <>{plan.vehicle.label}: bề rộng hiển thị {fmtWidth(wr.lo, wr.hi)}. Xe rộng cả gương {metres(plan.vehicle.mirror_width, 2)}.</>
              : <>Chưa có khoảng bề rộng để so sánh với xe.</>}
          </p>
          {!canShowClearance && <p className="maneuver-caveat">
            {narrowerThanMirrors
              ? 'Khoảng hẹp nhất nhỏ hơn bề rộng xe cả gương. Không thể kết luận có khoảng hở dương.'
              : 'Bề rộng chưa có bằng chứng quyết định. Nét đứt thể hiện thông tin chưa chắc chắn.'}
            {' '}Mô phỏng không phải bằng chứng an toàn.
          </p>}
          {plan.vehicle.kind === 'class' && <p className="maneuver-caveat">Nhóm xe dùng hồ sơ kích thước bất lợi nhất trong nhóm.</p>}
          {maneuver.status === 'loading' && <p role="status" className="maneuver-status"><LoaderCircle size={15} className="spin" /> Đang tải mô phỏng.</p>}
          {maneuver.status === 'error' && <p role="alert" className="maneuver-error">Không tải được mô phỏng. {maneuver.error}</p>}
          {maneuver.status === 'unavailable' && <p role="status" className="maneuver-status">
            {maneuver.reason === 'missing-width'
              ? 'Chưa có bề rộng hẻm để yêu cầu mô phỏng.'
              : 'Bề rộng nằm ngoài phạm vi mô phỏng (1,5–15 m).'}
            {' '}Hình xe tĩnh chỉ để minh họa kích thước.
          </p>}
          {maneuver.status === 'ready' && (maneuver.result.moves == null || !maneuver.result.poses?.length
            ? <p role="status" className="maneuver-status">Mô phỏng không tìm thấy quỹ đạo quay đầu trong hành lang thẳng này.</p>
            : <div className="maneuver-result">
              <p role="status">Quỹ đạo mô phỏng có {maneuver.result.moves} bước. Có thể cần nhiều lần tiến hoặc lùi.</p>
              {maneuver.result.length_m != null && <p>Chiều dài đường đi mô phỏng: {metres(maneuver.result.length_m)}.</p>}
              {maneuver.playback > 0 && window.matchMedia('(prefers-reduced-motion: reduce)').matches
                && <p>Đang hiển thị tư thế tĩnh theo chế độ giảm chuyển động.</p>}
              {replayable && <button type="button" className="btn btn-tonal" onClick={onReplay}>
                {maneuver.playback > 0 ? <RotateCcw size={16} /> : <Play size={16} />}
                {window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'Hiện tư thế tĩnh' : maneuver.playback > 0 ? 'Phát lại mô phỏng' : 'Chạy mô phỏng'}
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
      <Check icon={<CarFront size={16} />} title="Đường vào" tone={(FIT[s.fit.class] ?? FIT.unknown).tone}>
        {wr ? <>
          {wr.hi == null ? `Rộng ít nhất ${metres(wr.lo)}` : `Rộng ${fmtWidth(wr.lo, wr.hi)}`}
          {wr.top_tier ? '' : ' (chưa đo)'}{need && `, xe cần ${metres(need.tight_min, 2)}`}.
          {s.route_in && (s.route_in.available
            ? s.route_in.meters != null && <> Đoạn trong hẻm {s.route_in.meters} m.</>
            : <> Chưa có đường vào phù hợp với xe.</>)}
          {wr.review && <> <b>Bằng chứng mâu thuẫn, cần duyệt.</b></>}
        </> : s.kind === 'lot' ? 'Bãi đỗ gần đây; chưa có hình học xác minh cổng vào.' : vnt(s.fit.note ?? 'Chưa có dữ liệu bề rộng.')}
        {s.way_id && <button type="button" className="link-btn" onClick={() => onEvidence(s.way_id!)}>Xem bằng chứng</button>}
      </Check>
      <Check icon={<Navigation size={16} />} title="Đường ra" tone={exitTone(s)}>
        {vnt(s.way_out.text)}
        {!!s.way_out.observed?.length && <details className="way-out-observations">
          <summary>{s.way_out.observed.length} thông tin đã duyệt, không đổi kết luận</summary>
          <ul>{s.way_out.observed.slice(0, 4).map((claim, i) => (
            <li key={`${claim.source}-${claim.detail}-${i}`}>
              {vnt(claim.detail)} <small>{vnt(claim.source)}{claim.observed_on ? ` · ${claim.observed_on}` : ''}</small>
            </li>
          ))}</ul>
        </details>}
      </Check>
      <Check icon={<Droplets size={16} />} title="Ngập trên đường vào" tone={floodPresentation(s.route_in?.flood).tone}>
        <LegFloodEvidence check={s.route_in?.flood} />
      </Check>
      <Check icon={<Droplets size={16} />} title="Ngập lúc ở lại" tone={floodPresentation(s.flood.stay).tone}>
        <LegFloodEvidence check={s.flood.stay} />
        <p>Ngưỡng nước của xe: {Math.round(plan.vehicle.safe_water_depth * 100)} cm.</p>
      </Check>
      <Check icon={<Droplets size={16} />} title="Ngập trên đường ra" tone={floodPresentation(s.way_out.flood).tone}>
        <LegFloodEvidence check={s.way_out.flood} />
      </Check>
      <Check icon={<Landmark size={16} />} title={plan.intent === 'park' ? 'Luật đỗ xe' : 'Luật dừng xe'} tone={LEGAL[s.legality.status].tone}>
        <ul className="rules">
          {s.legality.rules.map((r, i) => <li key={i}>{vnt(r.text)} <cite>{r.citation}</cite></li>)}
        </ul>
      </Check>
      <Check icon={<Footprints size={16} />} title="Đi bộ" tone={s.walk.wade ? 'warn' : 'ok'}>
        {s.walk.meters} m, khoảng {minutes(s.walk.minutes)}
        {s.walk.wade && `; lội nước ${Math.round(s.walk.wade.lo * 100)}–${Math.round(s.walk.wade.hi * 100)} cm`}
        {s.walk.connection && !s.walk.connection.mapped && (
          <p className="unverified">
            {s.walk.connection.reason} (điểm dừng {s.walk.connection.stop_to_walk_m} m; địa chỉ {s.walk.connection.destination_to_walk_m} m).
          </p>
        )}
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
    <details className="why contrast">
      <summary>So sánh với tuyến {source}</summary>
      <p>Tuyến tham chiếu đi qua {names}{std.unfit_ways.length > 2 ? ` và ${std.unfit_ways.length - 2} hẻm khác` : ''}: {std.unfit_ways.some((w) => w.fit === 'no') ? 'không vừa' : 'chưa rõ có vừa'} {vehicleLabel}.</p>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onToggle}>{show ? `Ẩn tuyến ${source}` : `Hiện tuyến ${source}`}</button>
    </details>
  )
}

export { vn }
