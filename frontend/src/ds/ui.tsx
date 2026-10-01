import { useEffect, useRef, useState, type ReactNode } from 'react'

/** Number formatting for Vietnamese: decimal comma, metres/km/minutes. */
export const vn = (n: number, digits = 1) => n.toFixed(digits).replace('.', ',')
export const metres = (n: number, digits = 1) => `${vn(n, digits)} m`
export const distance = (m: number) => (m >= 1000 ? `${vn(m / 1000, 1)} km` : `${Math.round(m)} m`)
export const minutes = (min: number) => (min >= 60 ? `${Math.floor(min / 60)} giờ ${min % 60 ? `${min % 60} phút` : ''}`.trim() : `${min} phút`)

/** Decimal points → Vietnamese commas inside server-written sentences ("5.5 m" → "5,5 m"). */
export const vnt = (s: string) => s.replace(/(\d)\.(\d)/g, '$1,$2')

export type Tone = 'ok' | 'warn' | 'bad' | 'muted' | 'water' | 'brand'

export function Tag({ tone = 'muted', icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return <span className={`tag ${tone}`}>{icon}{children}</span>
}

/** A chip that opens a popover underneath it; closes on outside click and Escape. */
export function ChipMenu({ icon, label, children, align = 'left' }: { icon: ReactNode; label: ReactNode; children: (close: () => void) => ReactNode; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useOutside(ref, open, () => setOpen(false))
  return (
    <div className="chip-wrap" ref={ref}>
      <button type="button" className="chip" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}>
        {icon}<span>{label}</span>
      </button>
      {open && <div className={`popover ${align === 'right' ? 'pop-right' : ''}`} role="dialog">{children(() => setOpen(false))}</div>}
    </div>
  )
}

export function useOutside(ref: React.RefObject<HTMLElement | null>, active: boolean, onOut: () => void) {
  useEffect(() => {
    if (!active) return
    const down = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onOut() }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onOut() }
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key) }
  }, [ref, active, onOut])
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: ReactNode; disabled?: boolean }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} disabled={o.disabled} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}
