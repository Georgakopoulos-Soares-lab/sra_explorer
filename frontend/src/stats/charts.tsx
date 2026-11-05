// Small chart components for the statistics page, drawn as SVG/HTML without a
// chart library. Thin marks, hairline grid, one y-axis, a tooltip on hover;
// every chart also has a table view (ChartCard) so no value hides behind colour.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { formatCompact, SERIES_COLORS } from './format'

const GRID = '#e1e0d9'
const BASELINE = '#c3c2b7'
const MUTED = '#898781'
const INK = 'rgba(0, 0, 0, 0.88)'
const INK_2 = 'rgba(0, 0, 0, 0.55)'

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

// Round axis steps (1, 2, 2.5, 5 x 10^n) giving about `count` gridlines up to max.
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0]
  const raw = max / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)!
  const ticks = []
  for (let t = 0; t <= max + step * 0.001; t += step) ticks.push(t)
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  // Kept inside the chart: flips to the left of the pointer near the right edge.
  const left = x > width - 200
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-md bg-white px-3 py-2 text-xs shadow-lg ring-1 ring-black/10"
      style={{ top: Math.max(0, y), left: left ? undefined : x + 12, right: left ? width - x + 12 : undefined, color: INK }}
    >
      {children}
    </div>
  )
}

// A path for a bar from the baseline up to y, with 4px rounded top corners.
function barPath(x: number, y: number, w: number, base: number) {
  const r = Math.min(4, w / 2, (base - y) / 2)
  if (r <= 0) return ''
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`
}

// The right margin leaves room for a centred "2026*" under the last column.
const MARGIN = { top: 12, right: 20, bottom: 26, left: 52 }

// Columns per year. `partial` marks the last column as an incomplete year.
export function ColumnChart({ data, format, unit, partial, height = 260 }: {
  data: { x: number; y: number }[]
  format: (n: number) => string
  unit: string
  partial?: { x: number; note: string }
  height?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right)
  const innerH = height - MARGIN.top - MARGIN.bottom
  const ticks = niceTicks(Math.max(...data.map((d) => d.y), 1))
  const top = ticks[ticks.length - 1]
  const yOf = (v: number) => MARGIN.top + innerH - (v / top) * innerH
  const band = data.length ? innerW / data.length : 0
  const barW = Math.max(2, Math.min(24, band - 2))
  // Label every n-th year so labels don't touch, counted back from the last,
  // which is always labelled (it may carry a partial-year mark).
  const every = Math.max(1, Math.ceil(42 / Math.max(band, 1)))
  const base = MARGIN.top + innerH
  const hovered = hover === null ? null : data[hover]

  return (
    <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Column chart of ${unit} per year`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={yOf(t)} y2={yOf(t)} stroke={t === 0 ? BASELINE : GRID} />
              <text x={MARGIN.left - 8} y={yOf(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={MUTED} className="tabular-nums">
                {formatCompact(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = MARGIN.left + i * band + (band - barW) / 2
            const isPartial = partial?.x === d.x
            return (
              <g key={d.x}>
                <path
                  d={barPath(x, yOf(d.y), barW, base)}
                  fill={SERIES_COLORS[0]}
                  fillOpacity={isPartial ? 0.4 : hover === null || hover === i ? 1 : 0.75}
                />
                {(data.length - 1 - i) % every === 0 && (
                  <text x={x + barW / 2} y={base + 16} textAnchor="middle" fontSize={11} fill={MUTED} className="tabular-nums">
                    {isPartial ? `${d.x}*` : d.x}
                  </text>
                )}
                {/* The hover target is the whole column slot, not just the bar. */}
                <rect
                  x={MARGIN.left + i * band}
                  y={MARGIN.top}
                  width={band}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            )
          })}
        </svg>
      )}
      {hovered && (
        <Tooltip x={MARGIN.left + (hover! + 0.5) * band} y={yOf(hovered.y) - 40} width={width}>
          <div className="font-medium">{hovered.x}</div>
          <div className="tabular-nums">
            {format(hovered.y)} {unit}
          </div>
          {partial?.x === hovered.x && <div style={{ color: INK_2 }}>{partial.note}</div>}
        </Tooltip>
      )}
    </div>
  )
}

export interface LineSeries {
  key: string
  label: string
  color: string
  // One value per x; null where there is no value.
  values: (number | null)[]
}

// Lines over the years on one shared y-scale, with a crosshair tooltip and
// labels at the line ends when there is room.
export function LineChart({ xs, series, format, height = 280, yMax }: {
  xs: number[]
  series: LineSeries[]
  format: (n: number) => string
  height?: number
  yMax?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const endLabels = width >= 560 && series.length <= 6
  const margin = { ...MARGIN, right: endLabels ? 150 : 12 }
  const innerW = Math.max(0, width - margin.left - margin.right)
  const innerH = height - margin.top - margin.bottom
  const max = yMax ?? Math.max(...series.flatMap((s) => s.values.map((v) => v ?? 0)), 1)
  const ticks = niceTicks(max)
  const top = ticks[ticks.length - 1]
  const xOf = (i: number) => margin.left + (xs.length > 1 ? (i / (xs.length - 1)) * innerW : innerW / 2)
  const yOf = (v: number) => margin.top + innerH - (v / top) * innerH
  const every = Math.max(1, Math.ceil(36 / Math.max(innerW / Math.max(xs.length - 1, 1), 1)))

  const path = (values: (number | null)[]) => {
    let d = ''
    let pen = false
    values.forEach((v, i) => {
      if (v === null) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${xOf(i)},${yOf(v)}`
      pen = true
    })
    return d
  }

  // End labels at each line's last value, pushed apart so they don't overlap.
  const labels = series
    .map((s) => {
      const last = s.values.findLastIndex((v) => v !== null)
      return last < 0 ? null : { s, y: yOf(s.values[last]!), value: s.values[last]! }
    })
    .filter((l) => l !== null)
    .sort((a, b) => a.y - b.y)
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14)
  // ...and back up where the lowest ones were pushed below the plot.
  const bottom = margin.top + innerH
  for (let i = labels.length - 1; i >= 0; i--) {
    labels[i].y = Math.min(labels[i].y, i === labels.length - 1 ? bottom : labels[i + 1].y - 14)
  }

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const bounds = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - bounds.left) / Math.max(innerW, 1)) * (xs.length - 1))
    setHover(Math.min(xs.length - 1, Math.max(0, i)))
  }

  return (
    <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Line chart of ${series.map((s) => s.label).join(', ')}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={margin.left} x2={margin.left + innerW} y1={yOf(t)} y2={yOf(t)} stroke={t === 0 ? BASELINE : GRID} />
              <text x={margin.left - 8} y={yOf(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={MUTED} className="tabular-nums">
                {format(t)}
              </text>
            </g>
          ))}
          {xs.map((x, i) =>
            (xs.length - 1 - i) % every === 0 ? (
              <text key={x} x={xOf(i)} y={margin.top + innerH + 16} textAnchor="middle" fontSize={11} fill={MUTED} className="tabular-nums">
                {x}
              </text>
            ) : null,
          )}
          {hover !== null && (
            <line x1={xOf(hover)} x2={xOf(hover)} y1={margin.top} y2={margin.top + innerH} stroke={BASELINE} />
          )}
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {hover !== null &&
            series.map((s) =>
              s.values[hover] === null ? null : (
                <circle key={s.key} cx={xOf(hover)} cy={yOf(s.values[hover]!)} r={4} fill={s.color} stroke="#fff" strokeWidth={2} />
              ),
            )}
          {endLabels &&
            labels.map(({ s, y, value }) => (
              <text key={s.key} x={margin.left + innerW + 8} y={y} dy="0.32em" fontSize={11} fill={INK_2}>
                <tspan fill={INK}>{s.label.length > 14 ? `${s.label.slice(0, 13)}…` : s.label}</tspan> {format(value)}
              </text>
            ))}
          <rect x={margin.left} y={margin.top} width={innerW} height={innerH} fill="transparent" onMouseMove={onMove} />
        </svg>
      )}
      {hover !== null && (
        <Tooltip x={xOf(hover)} y={margin.top} width={width}>
          <div className="mb-1 font-medium">{xs[hover]}</div>
          {series
            .filter((s) => s.values[hover] !== null)
            .sort((a, b) => b.values[hover]! - a.values[hover]!)
            .map((s) => (
              <div key={s.key} className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />
                <span className="flex-1">{s.label}</span>
                <span className="tabular-nums">{format(s.values[hover]!)}</span>
              </div>
            ))}
        </Tooltip>
      )}
    </div>
  )
}

// Legend for a LineChart. With onToggle, clicking an entry shows or hides its
// series; each entry keeps its colour when others are toggled.
export function SeriesLegend({ items, shown, onToggle }: {
  items: { key: string; label: string; color: string }[]
  shown?: Set<string>
  onToggle?: (key: string) => void
}) {
  if (!onToggle) {
    return (
      <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 px-2 text-xs" style={{ color: INK }}>
        {items.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    )
  }
  return (
    <div className="mb-2 flex flex-wrap gap-x-1 gap-y-1">
      {items.map((item) => {
        const on = !shown || shown.has(item.key)
        return (
          <button
            key={item.key}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(item.key)}
            className={`inline-flex cursor-pointer items-center gap-1.5 rounded px-2 py-0.5 text-xs hover:bg-black/5 ${on ? '' : 'opacity-50'}`}
            style={{ color: INK }}
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={on ? { background: item.color } : { boxShadow: `inset 0 0 0 1.5px ${item.color}` }}
            />
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export interface BarItem {
  label: string
  value: number
  // Shown in the tooltip under the value.
  detail?: ReactNode
  // Makes the label a link, e.g. to the search page with this value filtered.
  to?: string
  // Or makes it a button, e.g. adding this value as a filter.
  onClick?: () => void
}

// Horizontal bars, longest first, with the value at the bar's end.
export function BarList({ items, format }: { items: BarItem[]; format: (n: number) => string }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(...items.map((i) => i.value), 1)
  return (
    <div className="flex flex-col gap-1" onMouseLeave={() => setHover(null)}>
      {items.map((item, i) => (
        <div
          key={item.label}
          className="relative grid grid-cols-[minmax(6rem,11rem)_1fr] items-center gap-3 rounded px-1 py-0.5 text-xs hover:bg-black/[0.03] sm:grid-cols-[minmax(8rem,14rem)_1fr]"
          onMouseEnter={() => setHover(i)}
        >
          <span className="truncate text-right" title={item.label} style={{ color: INK }}>
            {item.to ? (
              <Link to={item.to}>{item.label}</Link>
            ) : item.onClick ? (
              <button
                type="button"
                onClick={item.onClick}
                className="cursor-pointer border-0 bg-transparent p-0 text-xs text-[#1677ff] hover:underline"
              >
                {item.label}
              </button>
            ) : (
              item.label
            )}
          </span>
          <span className="flex min-w-0 items-center gap-2">
            <span
              className="h-3.5 shrink-0 rounded-r"
              style={{ width: `calc((100% - 4rem) * ${item.value / max})`, minWidth: 2, background: SERIES_COLORS[0] }}
            />
            <span className="tabular-nums" style={{ color: INK_2 }}>
              {format(item.value)}
            </span>
          </span>
          {hover === i && item.detail && (
            <div className="pointer-events-none absolute top-full left-1/3 z-10 mt-1 rounded-md bg-white px-3 py-2 shadow-lg ring-1 ring-black/10" style={{ color: INK }}>
              <div className="font-medium">{item.label}</div>
              {item.detail}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
