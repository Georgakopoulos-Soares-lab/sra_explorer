import { Checkbox, Segmented } from 'antd'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { TagOverview } from '../api'
import ChartCard, { type TableData } from '../stats/ChartCard'
import { SeriesLegend } from '../stats/charts'
import { formatInt, SERIES_COLORS } from '../stats/format'
import { isOrganism } from './links'

// The tag co-occurrence network: a node per common tag, a line between two
// tags found on the same projects. Laid out with a force simulation (nodes
// repel, lines pull), computed once per size, so the picture is still.

const HEIGHT = 560
const MARGIN = 28
const ITERATIONS = 400
const MUTED = '#898781'
const INK = 'rgba(0, 0, 0, 0.88)'
const LINE = '#b9b7ad'

interface Node {
  value: string
  count: number
  organism: boolean
  x: number
  y: number
  r: number
}
interface Edge {
  a: number
  b: number
  count: number
}

// Fruchterman-Reingold: every node pushes every other away, each line pulls
// its ends together (harder for more shared projects), a little gravity keeps
// the parts in view, and the step size cools down to settle. Starts from the
// nodes on a circle, most common first, so the same data gives the same picture.
function layout(nodes: Node[], edges: Edge[], width: number, height: number) {
  const n = nodes.length
  if (n === 0) return
  const w = width - 2 * MARGIN
  const h = height - 2 * MARGIN
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n
    node.x = MARGIN + w / 2 + (Math.min(w, h) / 3) * Math.cos(angle)
    node.y = MARGIN + h / 2 + (Math.min(w, h) / 3) * Math.sin(angle)
  })
  const k = Math.sqrt((w * h) / n) * 0.5
  const maxCount = Math.max(...edges.map((e) => e.count), 1)
  const dx = new Float64Array(n)
  const dy = new Float64Array(n)
  for (let it = 0; it < ITERATIONS; it++) {
    const temperature = (Math.max(w, h) / 10) * (1 - it / ITERATIONS) + 0.5
    dx.fill(0)
    dy.fill(0)
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ex = nodes[i].x - nodes[j].x
        let ey = nodes[i].y - nodes[j].y
        let d = Math.hypot(ex, ey)
        if (d < 1) {
          ex = (i - j) * 0.1
          ey = (j - i) * 0.07
          d = 1
        }
        // Bigger nodes keep more room.
        // Bigger nodes keep more room; the push fades with distance so far
        // clusters don't all end up against the frame.
        const f = ((k * k) / d) * (1 + (nodes[i].r + nodes[j].r) / 30) * Math.min(1, (3 * k) / d)
        dx[i] += (ex / d) * f
        dy[i] += (ey / d) * f
        dx[j] -= (ex / d) * f
        dy[j] -= (ey / d) * f
      }
    }
    for (const e of edges) {
      const ex = nodes[e.a].x - nodes[e.b].x
      const ey = nodes[e.a].y - nodes[e.b].y
      const d = Math.max(Math.hypot(ex, ey), 1)
      const f = ((d * d) / k) * (0.3 + 0.7 * Math.sqrt(e.count / maxCount))
      dx[e.a] -= (ex / d) * f
      dy[e.a] -= (ey / d) * f
      dx[e.b] += (ex / d) * f
      dy[e.b] += (ey / d) * f
    }
    for (let i = 0; i < n; i++) {
      const node = nodes[i]
      // Gravity towards the middle.
      dx[i] -= (node.x - (MARGIN + w / 2)) * 0.12
      dy[i] -= (node.y - (MARGIN + h / 2)) * 0.12
      const d = Math.max(Math.hypot(dx[i], dy[i]), 1e-6)
      const step = Math.min(d, temperature)
      node.x = Math.min(MARGIN + w - node.r, Math.max(MARGIN + node.r, node.x + (dx[i] / d) * step))
      node.y = Math.min(MARGIN + h - node.r, Math.max(MARGIN + node.r, node.y + (dy[i] / d) * step))
    }
  }
}

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

export default function TagNetwork({ network, tagged, onPick }: {
  network: TagOverview['network']
  tagged: number
  onPick: (tags: string[]) => void
}) {
  const [size, setSize] = useState<30 | 50 | 80>(50)
  const [perTag, setPerTag] = useState<2 | 3 | 5 | 0>(3)
  const [hideOrganisms, setHideOrganisms] = useState(true)
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<{ node?: number; edge?: number } | null>(null)

  // The nodes and lines to draw: the most common tags, each with its
  // strongest lines (perTag of them, or all), so the picture stays readable.
  const { nodes, edges } = useMemo(() => {
    const shown = network.nodes.filter((n) => !hideOrganisms || !isOrganism(n)).slice(0, size)
    const index = new Map(shown.map((n, i) => [n.value, i]))
    const maxCount = Math.max(...shown.map((n) => n.count), 1)
    const nodes: Node[] = shown.map((n) => ({
      value: n.value,
      count: n.count,
      organism: isOrganism(n),
      x: 0,
      y: 0,
      r: 5 + 17 * Math.sqrt(n.count / maxCount),
    }))
    const all: Edge[] = network.edges
      .filter((e) => index.has(e.source) && index.has(e.target))
      .map((e) => ({ a: index.get(e.source)!, b: index.get(e.target)!, count: e.count }))
      .sort((x, y) => y.count - x.count)
    let edges = all
    if (perTag > 0) {
      const taken = new Map<number, number>()
      const keep = new Set<Edge>()
      for (const e of all) {
        const ta = taken.get(e.a) ?? 0
        const tb = taken.get(e.b) ?? 0
        if (ta < perTag || tb < perTag) {
          keep.add(e)
          taken.set(e.a, ta + 1)
          taken.set(e.b, tb + 1)
        }
      }
      edges = all.filter((e) => keep.has(e))
    }
    return { nodes, edges }
  }, [network, size, perTag, hideOrganisms])

  const placed = useMemo(() => {
    if (width === 0) return nodes
    const copy = nodes.map((n) => ({ ...n }))
    layout(copy, edges, width, HEIGHT)
    return copy
  }, [nodes, edges, width])

  const maxEdge = Math.max(...edges.map((e) => e.count), 1)
  const neighbours = useMemo(() => {
    const m = new Map<number, Set<number>>()
    edges.forEach((e) => {
      if (!m.has(e.a)) m.set(e.a, new Set())
      if (!m.has(e.b)) m.set(e.b, new Set())
      m.get(e.a)!.add(e.b)
      m.get(e.b)!.add(e.a)
    })
    return m
  }, [edges])
  const activeNode = hover?.node ?? null
  const activeEdge = hover?.edge ?? null
  const nodeOn = (i: number) =>
    hover === null ||
    (activeNode !== null && (activeNode === i || neighbours.get(activeNode)?.has(i))) ||
    (activeEdge !== null && (edges[activeEdge].a === i || edges[activeEdge].b === i))
  const edgeOn = (i: number) =>
    hover === null || (activeEdge !== null && activeEdge === i) || (activeNode !== null && (edges[i].a === activeNode || edges[i].b === activeNode))

  const tooltip =
    activeNode !== null
      ? {
          x: placed[activeNode].x,
          y: placed[activeNode].y - placed[activeNode].r,
          title: placed[activeNode].value,
          lines: [
            `${formatInt(placed[activeNode].count)} BioProjects`,
            `${formatInt(neighbours.get(activeNode)?.size ?? 0)} linked tags shown`,
            'Click to choose this tag',
          ],
        }
      : activeEdge !== null
        ? {
            x: (placed[edges[activeEdge].a].x + placed[edges[activeEdge].b].x) / 2,
            y: (placed[edges[activeEdge].a].y + placed[edges[activeEdge].b].y) / 2,
            title: `${placed[edges[activeEdge].a].value} × ${placed[edges[activeEdge].b].value}`,
            lines: [`${formatInt(edges[activeEdge].count)} BioProjects with both`, 'Click to choose both tags'],
          }
        : null

  const table: TableData = {
    columns: [
      { key: 'a', title: 'Tag A' },
      { key: 'b', title: 'Tag B' },
      { key: 'count', title: 'Projects with both', numeric: true },
    ],
    rows: edges.map((e) => ({ a: nodes[e.a].value, b: nodes[e.b].value, count: e.count })),
  }
  const legend = [{ key: 'tag', label: 'Tag', color: SERIES_COLORS[0] }]
  if (!hideOrganisms) legend.push({ key: 'organism', label: 'Organism name', color: SERIES_COLORS[1] })

  return (
    <ChartCard
      title="Tag network"
      csvName="tag_network"
      table={table}
      caption={
        <>
          How the {formatInt(tagged)} tagged BioProjects connect the most common tags: a circle per tag, larger for more
          projects, and a line between two tags found on the same projects, thicker for more of them (pairs on fewer than 20
          projects are left out). Tags that share projects are drawn close together; the exact distances have no meaning.
          Each tag keeps only its strongest lines, chosen below, so that the picture stays readable; the table lists the
          lines drawn. Hover a tag to see its links; click a tag to choose it, or a line to choose both its tags.
        </>
      }
      controls={
        <>
          <Segmented
            size="small"
            value={size}
            onChange={(v) => setSize(v as 30 | 50 | 80)}
            options={[
              { value: 30, label: '30 tags' },
              { value: 50, label: '50 tags' },
              { value: 80, label: '80 tags' },
            ]}
          />
          <Segmented
            size="small"
            value={perTag}
            onChange={(v) => setPerTag(v as 2 | 3 | 5 | 0)}
            options={[
              { value: 2, label: '2 lines per tag' },
              { value: 3, label: '3 lines' },
              { value: 5, label: '5 lines' },
              { value: 0, label: 'All lines' },
            ]}
          />
          <Checkbox checked={hideOrganisms} onChange={(e) => setHideOrganisms(e.target.checked)}>
            Hide organism names
          </Checkbox>
        </>
      }
    >
      {legend.length > 1 && <SeriesLegend items={legend} />}
      <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={HEIGHT} role="img" aria-label="Network of tags linked by the projects they share">
            {edges.map((e, i) => (
              <line
                key={i}
                x1={placed[e.a].x}
                y1={placed[e.a].y}
                x2={placed[e.b].x}
                y2={placed[e.b].y}
                stroke={LINE}
                strokeOpacity={edgeOn(i) ? 0.9 : 0.15}
                strokeWidth={1 + 4 * Math.sqrt(e.count / maxEdge)}
                strokeLinecap="round"
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHover({ edge: i })}
                onClick={() => onPick([nodes[e.a].value, nodes[e.b].value])}
              />
            ))}
            {placed.map((node, i) => (
              <g
                key={node.value}
                style={{ cursor: 'pointer' }}
                opacity={nodeOn(i) ? 1 : 0.25}
                onMouseEnter={() => setHover({ node: i })}
                onClick={() => onPick([node.value])}
              >
                <circle cx={node.x} cy={node.y} r={node.r} fill={node.organism ? SERIES_COLORS[1] : SERIES_COLORS[0]} fillOpacity={0.85} stroke="#fff" strokeWidth={2} />
                <text
                  x={node.x}
                  y={node.y + node.r + 11}
                  textAnchor="middle"
                  fontSize={11}
                  fill={INK}
                  stroke="#fff"
                  strokeWidth={3}
                  paintOrder="stroke"
                  fontWeight={activeNode === i ? 600 : 400}
                >
                  {node.value.length > 22 ? `${node.value.slice(0, 21)}…` : node.value}
                </text>
              </g>
            ))}
          </svg>
        )}
        {tooltip && (
          <div
            className="pointer-events-none absolute z-10 rounded-md bg-white px-3 py-2 text-xs shadow-lg ring-1 ring-black/10"
            style={{
              top: Math.max(0, tooltip.y - 8),
              left: tooltip.x > width - 200 ? undefined : tooltip.x + 14,
              right: tooltip.x > width - 200 ? width - tooltip.x + 14 : undefined,
              color: INK,
            }}
          >
            <div className="font-medium">{tooltip.title}</div>
            {tooltip.lines.map((l, i) => (
              <div key={i} className={i === tooltip.lines.length - 1 ? 'mt-1' : 'tabular-nums'} style={i === tooltip.lines.length - 1 ? { color: MUTED } : undefined}>
                {l}
              </div>
            ))}
          </div>
        )}
      </div>
    </ChartCard>
  )
}
