import { BarChartOutlined, DownloadOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Skeleton, Statistic, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api, ApiError, type SearchParams, type SearchSummary, type SummaryDimension } from '../api'
import { BarList, ColumnChart } from '../stats/charts'
import { downloadFile, formatInt, formatPct } from '../stats/format'

const { Text } = Typography

// Shown before the bars, so the cards read in this order.
const ORDER = [
  'assay_type', 'organism', 'tissue', 'cell_type', 'cell_line', 'disease_state', 'sex',
  'molecular_target', 'library_source', 'instrument', 'submitter_country', 'sample_country',
]

function summaryCsv(s: SearchSummary) {
  const lines = ['dimension,value,count,unit']
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  for (const d of s.dimensions) {
    for (const v of d.values) lines.push([cell(d.label), cell(v.value), v.count, d.unit].join(','))
    lines.push([cell(d.label), '(any recorded)', d.known, d.unit].join(','))
  }
  for (const y of s.years) lines.push(['Release year', y.year, y.count, 'projects'].join(','))
  return lines.join('\n') + '\n'
}

function DimensionCard({ dim, total, selected, onAdd }: {
  dim: SummaryDimension
  // All units of this kind among the results, for "recorded for n of N".
  total: number
  selected: string[]
  onAdd: (filter: string, value: string) => void
}) {
  const filter = dim.filter
  return (
    <Card size="small" title={dim.label} className="min-w-0">
      <Text type="secondary" className="mb-2 block text-xs">
        Recorded for {formatInt(dim.known)} of {formatInt(total)} {dim.unit === 'projects' ? 'BioProjects' : 'SRA studies'}
        {dim.known > 0 && ` (${formatPct((100 * dim.known) / Math.max(total, 1))})`}.
        {filter && dim.values.length > 0 && ' Click a value to filter by it.'}
      </Text>
      {dim.values.length > 0 ? (
        <BarList
          format={formatInt}
          items={dim.values.map((v) => ({
            label: v.value,
            value: v.count,
            onClick: filter && !selected.includes(v.value) ? () => onAdd(filter, v.value) : undefined,
            detail: (
              <div className="tabular-nums">
                {formatInt(v.count)} {dim.unit === 'projects' ? 'BioProjects' : 'SRA studies'} (
                {formatPct((100 * v.count) / Math.max(total, 1))} of the results)
              </div>
            ),
          }))}
        />
      ) : (
        <Text type="secondary" className="text-xs">
          None recorded.
        </Text>
      )}
    </Card>
  )
}

// A collapsible section above the results: its header bar opens it, and it
// then counts everything the search matches (release years, assays,
// organisms, sample attributes, countries). Nothing is fetched while closed.
// Clicking a value adds it as a filter.
export default function ResultsSummary({ open, onToggle, params, values, onAdd }: {
  open: boolean
  onToggle: () => void
  // The search's parameters; paging and sorting are ignored.
  params: SearchParams
  // The applied filters, so values already selected aren't offered again.
  values: SearchParams
  onAdd: (filter: string, value: string) => void
}) {
  const { sort: _sort, limit: _limit, offset: _offset, ...rest } = params
  const key = open ? JSON.stringify(rest) : ''
  const [state, setState] = useState<{ key: string; summary?: SearchSummary; error?: string }>()

  useEffect(() => {
    if (!key) return
    const controller = new AbortController()
    api
      .searchSummary(JSON.parse(key), controller.signal)
      .then((summary) => setState({ key, summary }))
      .catch((e) => {
        if (!controller.signal.aborted) setState({ key, error: e instanceof ApiError || e instanceof Error ? e.message : String(e) })
      })
    return () => controller.abort()
  }, [key])

  const current = key && state?.key === key ? state : undefined
  const s = current?.summary

  return (
    <section
      className={`mb-6 rounded-lg border ${open ? 'border-blue-200 bg-blue-50/60 shadow-sm' : 'border-gray-200 bg-white'}`}
    >
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-left"
        >
          <BarChartOutlined className="text-base text-[#1677ff]" />
          <span className="font-semibold">Summary statistics</span>
          <Text type="secondary" className="hidden text-sm sm:inline">
            of current search results
          </Text>
        </button>
        {s && (
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => downloadFile('search_summary.csv', summaryCsv(s), 'text/csv;charset=utf-8')}
          >
            CSV
          </Button>
        )}
        <Button size="small" type={open ? 'default' : 'primary'} icon={open ? <UpOutlined /> : <DownOutlined />} onClick={onToggle}>
          {open ? 'Hide' : 'Show'}
        </Button>
      </div>
      {open && (
        <div className="border-t border-blue-200 p-3">
          {current?.error ? (
            <Alert type="warning" showIcon message="Couldn't summarise these results" description={current.error} />
          ) : !s ? (
            <>
              <Text type="secondary" className="text-sm">
                Counting everything this search matches. Broad searches can take up to 20 seconds.
              </Text>
              <Skeleton active paragraph={{ rows: 4 }} />
            </>
          ) : (
            <SummaryBody s={s} values={values} onAdd={onAdd} />
          )}
        </div>
      )}
    </section>
  )
}

function SummaryBody({ s, values, onAdd }: {
  s: SearchSummary
  values: SearchParams
  onAdd: (filter: string, value: string) => void
}) {
  const selected = (name: string | null) => (name ? ([] as string[]).concat(values[name] ?? []) : [])
  const dimensions = [...s.dimensions].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name))
  const tiles = [
    { label: 'BioProjects', value: formatInt(s.projects) },
    { label: 'SRA studies', value: formatInt(s.studies) },
    { label: 'Sequencing runs', value: formatInt(s.runs) },
    { label: 'With a publication', value: formatPct((100 * s.projects_published) / Math.max(s.projects, 1)) },
    { label: 'With a GEO series', value: formatPct((100 * s.projects_geo) / Math.max(s.projects, 1)) },
  ]

  return (
    <>
      <Text type="secondary" className="mb-3 block text-xs">
        Counts cover all results, not just this page. Run attributes count SRA studies; sample attributes and countries of
        submitters count BioProjects.
      </Text>
      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {tiles.map((t) => (
          <Card key={t.label} size="small">
            <Statistic title={t.label} value={t.value} />
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Card size="small" title="Released per year" className="min-w-0">
          <Text type="secondary" className="mb-2 block text-xs">
            BioProjects by the release of their first data.
          </Text>
          <ColumnChart data={s.years.map((y) => ({ x: y.year, y: y.count }))} format={formatInt} unit="BioProjects" height={200} />
        </Card>
        {dimensions.map((d) => (
          <DimensionCard
            key={d.name}
            dim={d}
            total={d.unit === 'projects' ? s.projects : s.studies}
            selected={selected(d.filter)}
            onAdd={onAdd}
          />
        ))}
      </div>
    </>
  )
}
