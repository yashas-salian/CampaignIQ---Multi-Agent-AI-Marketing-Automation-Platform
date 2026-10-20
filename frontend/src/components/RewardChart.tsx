import type { CSSProperties, MouseEvent as ReactMouseEvent } from 'react'
import { useId, useState } from 'react'
import styles from './RewardChart.module.css'

export interface RewardPoint {
  key: string
  reward: number
  /** Short x-axis label, e.g. "R2". */
  label: string
  /** Tooltip lines: a bold first line, then an optional muted second line. */
  title: string
  detail?: string
}

/**
 * Single-series reward line (0–1) with a crosshair + tooltip on hover.
 * One orange series, so no legend: the panel title names it.
 */
export default function RewardChart({ points, ariaLabel, showXLabels = false }: { points: RewardPoint[]; ariaLabel: string; showXLabels?: boolean }) {
  const [hover, setHover] = useState<number | null>(null)
  const gradientId = useId()
  const W = 640
  const H = 220
  const pad = { l: 36, r: 16, t: 16, b: showXLabels ? 30 : 16 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const x = (i: number) => pad.l + (points.length > 1 ? (i / (points.length - 1)) * iw : iw / 2)
  const y = (v: number) => pad.t + (1 - v) * ih
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.reward)}`).join(' ')
  const area = `${line} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`

  function onMove(e: ReactMouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let best = 0
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i
    })
    setHover(best)
  }

  const hp = hover !== null ? points[hover] : null
  return (
    <div className={styles.wrap}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.chart}
        role="img"
        aria-label={ariaLabel}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--mos-accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--mos-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className={styles.grid} />
            <text x={pad.l - 8} y={y(v) + 4} textAnchor="end" className={styles.axis}>
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {points.length > 1 && <path d={area} fill={`url(#${gradientId})`} className={styles.area} />}
        <path
          d={line}
          fill="none"
          stroke="var(--mos-accent)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          className={styles.line}
          pathLength={1}
        />
        {hp && hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} className={styles.crosshair} />}
        {points.map((p, i) => (
          <g key={p.key}>
            <circle cx={x(i)} cy={y(p.reward)} r={hover === i ? 6 : 4} className={styles.dot} style={{ '--i': i } as CSSProperties} />
            {showXLabels && (
              <text x={x(i)} y={H - 8} textAnchor="middle" className={styles.axis}>
                {p.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      {hp && hover !== null && (
        <div className={styles.tooltip} style={{ left: `${(x(hover) / W) * 100}%`, top: `${(y(hp.reward) / H) * 100}%` }} role="status">
          <strong>{hp.title}</strong>
          {hp.detail && <span>{hp.detail}</span>}
        </div>
      )}
    </div>
  )
}
