import React, { useEffect, useRef, useState } from 'react'
import { money } from './lib.js'

export function Money({ value, currency, whole, sign, tone, className = '' }) {
  const toneClass = tone === 'auto' ? (value < 0 ? 'out' : value > 0 ? 'in' : '') : tone || ''
  return <span className={`money ${toneClass} ${className}`.trim()}>{money(value, currency, { whole, sign })}</span>
}

export function Loading({ label = 'Loading' }) {
  return <div className="loading" role="status"><span className="loading-bar" />{label}</div>
}

export function ErrorNote({ message, onRetry }) {
  return (
    <div className="error-note" role="alert">
      <p>{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  )
}

export function Empty({ children, action }) {
  return (
    <div className="empty">
      <p>{children}</p>
      {action}
    </div>
  )
}

export function PageHead({ title, children, note }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {note && <p className="page-note">{note}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  )
}

export function Dialog({ title, onClose, children, footer, wide }) {
  const ref = useRef(null)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const previous = document.activeElement
    const first = ref.current?.querySelector('input, select, textarea, button')
    first?.focus()
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [])
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <section className={wide ? 'dialog wide' : 'dialog'} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" /></svg>
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </section>
    </div>
  )
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`field ${className}`.trim()}>
      <span className="field-label">{label}{hint && <span className="field-hint">{hint}</span>}</span>
      {children}
    </label>
  )
}

/** Thin progress rule with an optional projection tick. */
export function PaceBar({ spent, limit, projected, status }) {
  const max = Math.max(limit, spent, projected || 0) || 1
  const spentPct = Math.min(100, (spent / max) * 100)
  const limitPct = (limit / max) * 100
  const projPct = projected ? Math.min(100, (projected / max) * 100) : null
  return (
    <div className={`pace pace-${status}`} aria-hidden="true">
      <span className="pace-fill" style={{ width: `${spentPct}%` }} />
      {projPct !== null && projPct > spentPct && (
        <span className="pace-proj" style={{ left: `${spentPct}%`, width: `${projPct - spentPct}%` }} />
      )}
      <span className="pace-limit" style={{ left: `${limitPct}%` }} />
    </div>
  )
}

function niceMax(v) {
  if (v <= 0) return 1
  const pow = Math.pow(10, Math.floor(Math.log10(v)))
  const n = v / pow
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => n <= s)
  return step * pow
}

/** Cumulative spending: this month (ink), last month (faint) and the projection (dashed). */
export function SpendCurve({ curves, daysInMonth, day, currency, limitTotal, prevLabel }) {
  const [hover, setHover] = useState(null)
  const W = 640, H = 230, L = 8, R = 64, T = 14, B = 26
  const prev = curves.prev || []
  const thisM = curves.this || []
  const proj = curves.projection || []
  const top = niceMax(Math.max(...prev, ...thisM, ...proj, 1))
  const x = (d) => L + ((d - 1) / Math.max(daysInMonth - 1, 1)) * (W - L - R)
  const y = (v) => T + (1 - v / top) * (H - T - B)
  const path = (pts) => pts.map(([d, v], i) => `${i ? 'L' : 'M'}${x(d).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const prevPts = prev.slice(0, daysInMonth).map((v, i) => [i + 1, v])
  const thisPts = thisM.map((v, i) => [i + 1, v])
  const projPts = thisM.length ? [[day, thisM[thisM.length - 1]], ...proj.map((v, i) => [day + 1 + i, v])] : []
  const ticks = [0, top / 2, top]
  const xTicks = [1, 8, 15, 22, daysInMonth].filter((d, i, a) => d <= daysInMonth && a.indexOf(d) === i)

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const d = Math.round(((px - L) / (W - L - R)) * (daysInMonth - 1)) + 1
    setHover(Math.max(1, Math.min(daysInMonth, d)))
  }
  const hv = hover && {
    d: hover,
    thisV: thisM[hover - 1],
    projV: hover > day ? proj[hover - day - 1] : undefined,
    prevV: prev[hover - 1]
  }

  return (
    <figure className="curve">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Spending so far this month compared with last month"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
            <text x={W - R + 8} y={y(t) + 4} className="axis">{money(t, currency, { whole: true })}</text>
          </g>
        ))}
        {xTicks.map((d) => <text key={d} x={x(d)} y={H - 6} className="axis" textAnchor="middle">{d}</text>)}
        <line x1={x(day)} x2={x(day)} y1={T} y2={H - B} className="today-line" />
        {prevPts.length > 1 && <path d={path(prevPts)} className="line-prev" />}
        {projPts.length > 1 && <path d={path(projPts)} className="line-proj" />}
        {thisPts.length > 0 && <path d={path(thisPts)} className="line-this" />}
        {thisPts.length > 0 && <circle cx={x(day)} cy={y(thisM[thisM.length - 1])} r="3.5" className="dot-this" />}
        {hv && <line x1={x(hv.d)} x2={x(hv.d)} y1={T} y2={H - B} className="hover-line" />}
      </svg>
      <figcaption className="curve-legend">
        {hv ? (
          <span>
            Day {hv.d}: {hv.thisV !== undefined ? <b>{money(hv.thisV, currency, { whole: true })} spent</b>
              : hv.projV !== undefined ? <b>about {money(hv.projV, currency, { whole: true })} expected</b> : null}
            {hv.prevV !== undefined && <> against {money(hv.prevV, currency, { whole: true })} in {prevLabel}</>}
          </span>
        ) : (
          <>
            <span className="key key-this">This month</span>
            <span className="key key-proj">Projected</span>
            <span className="key key-prev">{prevLabel}</span>
          </>
        )}
      </figcaption>
    </figure>
  )
}

/** Paired monthly bars: money in vs money out. */
export function MonthBars({ labels, income, expenses, currency }) {
  const W = 640, H = 220, L = 8, R = 64, T = 10, B = 26
  const top = niceMax(Math.max(...income, ...expenses, 1))
  const n = labels.length || 1
  const slot = (W - L - R) / n
  const bw = Math.min(18, slot / 3)
  const y = (v) => T + (1 - v / top) * (H - T - B)
  return (
    <figure className="bars">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Money in and money out by month">
        {[0, top / 2, top].map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
            <text x={W - R + 8} y={y(t) + 4} className="axis">{money(t, currency, { whole: true })}</text>
          </g>
        ))}
        {labels.map((lab, i) => {
          const cx = L + slot * i + slot / 2
          return (
            <g key={lab}>
              <rect x={cx - bw - 1} y={y(income[i])} width={bw} height={Math.max(0, H - B - y(income[i]))} className="bar-in">
                <title>{`${lab}: ${money(income[i], currency, { whole: true })} in`}</title>
              </rect>
              <rect x={cx + 1} y={y(expenses[i])} width={bw} height={Math.max(0, H - B - y(expenses[i]))} className="bar-out">
                <title>{`${lab}: ${money(expenses[i], currency, { whole: true })} out`}</title>
              </rect>
              <text x={cx} y={H - 6} className="axis" textAnchor="middle">{lab}</text>
            </g>
          )
        })}
      </svg>
      <figcaption className="curve-legend">
        <span className="key key-in">Money in</span>
        <span className="key key-out">Money out</span>
      </figcaption>
    </figure>
  )
}

export function Spark({ values, width = 120, height = 26 }) {
  const max = Math.max(...values, 1)
  const step = values.length > 1 ? width / (values.length - 1) : width
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`).join('')
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

export function CurrencyPicker({ value, onChange, label = 'Display currency' }) {
  return (
    <select className="select-quiet" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      {['INR', 'USD', 'EUR', 'GBP', 'CAD', 'JPY'].map((c) => <option key={c} value={c}>{c}</option>)}
    </select>
  )
}
