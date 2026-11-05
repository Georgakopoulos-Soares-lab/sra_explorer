import { Checkbox, Segmented } from 'antd'
import { useMemo, useState } from 'react'
import type { TagOverview } from '../api'
import ChartCard, { type TableData } from '../stats/ChartCard'
import { BarList, HeatmapMatrix } from '../stats/charts'
import { formatInt } from '../stats/format'
import { isOrganism } from './links'

// Pairs on fewer projects than this are left out of the "most associated"
// ranking, where a tiny pair of rare tags would otherwise score highest.
const MIN_ASSOCIATED = 50
const LIST_SIZE = 30
const MATRIX_SIZE = 30

interface Pair {
  a: string
  b: string
  // Projects with both tags, and with each.
  count: number
  na: number
  nb: number
  // count / (na + nb - count): 1 when the tags always occur together.
  jaccard: number
}

// Rows ordered so that tags sharing partners sit next to each other: a
// nearest-neighbour chain from the most common tag, by Jaccard similarity.
function seriate(labels: string[], similarity: (a: string, b: string) => number): string[] {
  if (labels.length === 0) return []
  const left = new Set(labels.slice(1))
  const order = [labels[0]]
  while (left.size) {
    const last = order[order.length - 1]
    let best: string | null = null
    let bestValue = -1
    for (const l of left) {
      const v = similarity(last, l)
      if (v > bestValue) {
        best = l
        bestValue = v
      }
    }
    order.push(best!)
    left.delete(best!)
  }
  return order
}

// "Tags that go together": the pairs of common tags found on the same
// projects, as a ranked list or a co-occurrence matrix. Clicking a pair
// chooses both tags in the workbench.
export default function TagPairs({ network, tagged, onPick }: {
  network: TagOverview['network']
  // Tagged projects, for the caption.
  tagged: number
  onPick: (tags: string[]) => void
}) {
  const [metric, setMetric] = useState<'count' | 'jaccard'>('count')
  const [hideOrganisms, setHideOrganisms] = useState(true)
  const [view, setView] = useState<'list' | 'matrix'>('list')

  const { pairs, nodes } = useMemo(() => {
    const counts = new Map(network.nodes.map((n) => [n.value, n]))
    const pairs: Pair[] = network.edges
      .map((e) => {
        const na = counts.get(e.source)?.count ?? e.count
        const nb = counts.get(e.target)?.count ?? e.count
        return { a: e.source, b: e.target, count: e.count, na, nb, jaccard: e.count / (na + nb - e.count) }
      })
      .filter((p) => !hideOrganisms || !(isOrganism(counts.get(p.a)!) && isOrganism(counts.get(p.b)!)))
    const nodes = network.nodes.filter((n) => !hideOrganisms || !isOrganism(n))
    return { pairs, nodes }
  }, [network, hideOrganisms])

  const ranked = useMemo(
    () =>
      metric === 'count'
        ? [...pairs].sort((x, y) => y.count - x.count)
        : pairs.filter((p) => p.count >= MIN_ASSOCIATED).sort((x, y) => y.jaccard - x.jaccard),
    [pairs, metric],
  )

  // The matrix: the most common tags (after the organism filter), ordered so blocks show.
  const matrix = useMemo(() => {
    const shown = nodes.slice(0, MATRIX_SIZE).map((n) => n.value)
    const key = (a: string, b: string) => (a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`)
    const byPair = new Map(pairs.map((p) => [key(p.a, p.b), p]))
    const sim = (a: string, b: string) => byPair.get(key(a, b))?.jaccard ?? 0
    const labels = seriate(shown, sim)
    const value = (i: number, j: number) => {
      const p = byPair.get(key(labels[i], labels[j]))
      return p ? p[metric] : null
    }
    let max = 0
    for (let i = 0; i < labels.length; i++) for (let j = 0; j < i; j++) max = Math.max(max, value(i, j) ?? 0)
    return { labels, value, max, byPair, key }
  }, [nodes, pairs, metric])

  const formatValue = metric === 'count' ? formatInt : (v: number) => v.toFixed(2)
  const items = ranked.slice(0, LIST_SIZE).map((p) => ({
    label: `${p.a} + ${p.b}`,
    value: p[metric],
    onClick: () => onPick([p.a, p.b]),
    detail: (
      <div className="tabular-nums">
        <div>{formatInt(p.count)} projects with both</div>
        <div>
          {formatInt(p.na)} with {p.a}, {formatInt(p.nb)} with {p.b}
        </div>
        <div>Jaccard {p.jaccard.toFixed(2)}</div>
        <div className="mt-1 text-gray-500">Click to choose both tags</div>
      </div>
    ),
  }))
  const table: TableData = {
    columns: [
      { key: 'a', title: 'Tag A' },
      { key: 'b', title: 'Tag B' },
      { key: 'count', title: 'Projects with both', numeric: true },
      { key: 'na', title: 'Projects with A', numeric: true },
      { key: 'nb', title: 'Projects with B', numeric: true },
      { key: 'jaccard', title: 'Jaccard', numeric: true },
    ],
    rows: [...pairs]
      .sort((x, y) => y.count - x.count)
      .map((p) => ({ a: p.a, b: p.b, count: p.count, na: p.na, nb: p.nb, jaccard: Number(p.jaccard.toFixed(3)) })),
  }

  return (
    <ChartCard
      title="Tags that go together"
      csvName="tag_pairs"
      table={table}
      caption={
        <>
          Pairs among the {formatInt(network.nodes.length)} most common tags, counted over the {formatInt(tagged)} tagged
          projects; pairs on fewer than 20 projects are left out. <b>Most frequent</b> ranks pairs by the projects that have
          both tags. <b>Most associated</b> ranks them by how much the two tags' sets of projects overlap (Jaccard index: shared
          projects over projects with either tag), for pairs on at least {MIN_ASSOCIATED} projects.
          Pairs of two organism names are mostly synonyms (mouse + Mus musculus), so they are hidden by default. Click a pair
          to count and open its projects.
        </>
      }
      controls={
        <>
          <Segmented
            size="small"
            value={metric}
            onChange={(v) => setMetric(v as 'count' | 'jaccard')}
            options={[
              { value: 'count', label: 'Most frequent' },
              { value: 'jaccard', label: 'Most associated' },
            ]}
          />
          <Segmented
            size="small"
            value={view}
            onChange={(v) => setView(v as 'list' | 'matrix')}
            options={[
              { value: 'list', label: 'List' },
              { value: 'matrix', label: 'Matrix' },
            ]}
          />
          <Checkbox checked={hideOrganisms} onChange={(e) => setHideOrganisms(e.target.checked)}>
            Hide organism names
          </Checkbox>
        </>
      }
    >
      {view === 'list' ? (
        <BarList items={items} format={formatValue} />
      ) : (
        <HeatmapMatrix
          labels={matrix.labels}
          value={matrix.value}
          max={matrix.max}
          format={(_, i, j) => {
            const p = matrix.byPair.get(matrix.key(matrix.labels[i], matrix.labels[j]))!
            return (
              <div className="tabular-nums">
                <div>{formatInt(p.count)} projects with both</div>
                <div>Jaccard {p.jaccard.toFixed(2)}</div>
                <div className="mt-1 text-gray-500">Click to choose both tags</div>
              </div>
            )
          }}
          onCell={(i, j) => onPick([matrix.labels[i], matrix.labels[j]])}
          onLabel={(i) => onPick([matrix.labels[i]])}
        />
      )}
    </ChartCard>
  )
}
