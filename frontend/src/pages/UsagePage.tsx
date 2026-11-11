import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Segmented, Statistic, Table, Tag, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api'
import {
  adminApi,
  type UsageBucket,
  type UsageEvent,
  type UsageFilters,
  type UsageHour,
  type UsagePeriod,
  type UsageQuery,
  type UsageRange,
  type UsageSource,
  type UsageSummary,
  type UsageVisitor,
} from '../api/admin'
import AdminGate from '../components/AdminGate'
import ChartCard from '../stats/ChartCard'
import { BarList, ColumnChart } from '../stats/charts'
import { formatInt, formatPct } from '../stats/format'

const { Title, Paragraph, Text } = Typography

const RANGES: { value: number; label: string }[] = [
  { value: 7, label: '7 days' },
  { value: 30, label: '30 days' },
  { value: 90, label: '90 days' },
  { value: 365, label: 'Year' },
  { value: 0, label: 'All time' },
]

const SOURCES: { value: UsageSource | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'site', label: 'Website' },
  { value: 'api', label: 'Public API' },
]

const errorMessage = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e))

const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

const formatDay = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

// Period labels: the day, the week's first day, or the month.
function bucketLabel(bucket: string, period: UsagePeriod) {
  const d = new Date(`${bucket}T00:00:00`)
  if (period === 'month') return d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })
  if (period === 'week') return `w/c ${formatDay(bucket)}`
  return formatDay(bucket)
}

// Every period between the first bucket (or the range start) and today, with
// zeros where nothing was searched, so quiet days show as gaps in the chart.
function fillBuckets(buckets: UsageBucket[], period: UsagePeriod, days: number): UsageBucket[] {
  const byKey = new Map(buckets.map((b) => [b.bucket, b]))
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  let start = new Date(today)
  if (days) start.setDate(start.getDate() - days + 1)
  if (buckets.length) {
    const first = new Date(`${buckets[0].bucket}T00:00:00`)
    if (!days || first < start) start = first
  }
  // Align the start to the period's first day: Monday (Postgres date_trunc('week')) or the 1st.
  if (period === 'week') start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  if (period === 'month') start.setDate(1)
  const out: UsageBucket[] = []
  for (const d = new Date(start); d <= today; ) {
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    out.push(byKey.get(key) ?? { bucket: key, searches: 0, events: 0, visitors: 0, site: 0, api: 0 })
    if (period === 'day') d.setDate(d.getDate() + 1)
    else if (period === 'week') d.setDate(d.getDate() + 7)
    else d.setMonth(d.getMonth() + 1)
    if (out.length > 2000) break
  }
  return out
}

function Headline({ summary, days }: { summary: UsageSummary; days: number }) {
  const rangeLabel = RANGES.find((r) => r.value === days)?.label.toLowerCase() ?? `${days} days`
  const blocks: { title: string; counts: UsageSummary['period'] }[] = [
    { title: 'Today', counts: summary.today },
    { title: 'Last 7 days', counts: summary.week },
    { title: 'Last 30 days', counts: summary.month },
    { title: days ? `Last ${rangeLabel}` : 'All time', counts: summary.period },
  ]
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {blocks.map((b) => (
        <Card key={b.title} size="small" title={b.title}>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <Statistic title="Searches" value={b.counts.searches} />
            <Statistic title="Visitors" value={b.counts.visitors} />
          </div>
          <Text type="secondary" className="mt-2 block text-xs">
            {formatInt(b.counts.site)} website · {formatInt(b.counts.api)} API
            {b.counts.searches > 0 && <> · {formatPct((100 * b.counts.no_results) / b.counts.searches)} with no results</>}
          </Text>
        </Card>
      ))}
    </div>
  )
}

// The filters of a search as small tags: "tissue: Lung, Lung cancer".
function FilterTags({ filters }: { filters: Record<string, unknown> }) {
  const entries = Object.entries(filters)
  if (!entries.length) return <Text type="secondary">—</Text>
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <Tag key={k} className="!m-0 whitespace-normal">
          <b>{k}</b>: {Array.isArray(v) ? v.join(', ') : String(v)}
        </Tag>
      ))}
    </span>
  )
}

function Usage({ code }: { code: string }) {
  const api = useRef(adminApi(code)).current
  const [days, setDays] = useState(30)
  const [source, setSource] = useState<UsageSource | 'all'>('all')
  const [period, setPeriod] = useState<UsagePeriod>('day')
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)

  const [summary, setSummary] = useState<UsageSummary>()
  const [series, setSeries] = useState<UsageBucket[]>([])
  const [hours, setHours] = useState<UsageHour[]>([])
  const [queries, setQueries] = useState<UsageQuery[]>([])
  const [filters, setFilters] = useState<UsageFilters>({ fields: [], values: [] })
  const [visitors, setVisitors] = useState<UsageVisitor[]>([])
  const [recent, setRecent] = useState<{ total: number; items: UsageEvent[] }>({ total: 0, items: [] })
  const [recentPage, setRecentPage] = useState(1)
  const RECENT_PAGE = 25

  const range = useMemo<UsageRange>(() => ({ days, ...(source === 'all' ? {} : { source }) }), [days, source])

  const load = useCallback(() => {
    setLoading(true)
    setError(undefined)
    Promise.all([
      api.usageSummary(range),
      api.usageSeries(range, period),
      api.usageHours(range),
      api.usageQueries(range, 50),
      api.usageFilters(range, 30),
      api.usageVisitors(range, 30),
    ])
      .then(([s, se, h, q, f, v]) => {
        setSummary(s)
        setSeries(se)
        setHours(h)
        setQueries(q)
        setFilters(f)
        setVisitors(v)
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))
  }, [api, range, period])

  useEffect(load, [load, tick])

  useEffect(() => {
    api
      .usageRecent(range, RECENT_PAGE, (recentPage - 1) * RECENT_PAGE)
      .then(setRecent)
      .catch((e) => setError(errorMessage(e)))
  }, [api, range, recentPage, tick])

  const filled = useMemo(() => fillBuckets(series, period, days), [series, period, days])
  const seriesTable = {
    columns: [
      { key: 'bucket', title: period === 'day' ? 'Day' : period === 'week' ? 'Week starting' : 'Month' },
      { key: 'searches', title: 'Searches', numeric: true },
      { key: 'visitors', title: 'Visitors', numeric: true },
      { key: 'site', title: 'Website', numeric: true },
      { key: 'api', title: 'API', numeric: true },
      { key: 'events', title: 'Requests (with paging)', numeric: true },
    ],
    rows: filled.map((b) => ({ ...b })),
  }
  const axisX = (i: number) => (filled[i] ? bucketLabel(filled[i].bucket, period) : '')

  const queryColumns: TableColumnsType<UsageQuery> = [
    { title: 'Search text', dataIndex: 'query', key: 'query', ellipsis: true },
    { title: 'Searches', dataIndex: 'searches', key: 'searches', align: 'right', width: 100, render: formatInt },
    { title: 'Visitors', dataIndex: 'visitors', key: 'visitors', align: 'right', width: 90, render: formatInt },
    {
      title: 'Results',
      dataIndex: 'total',
      key: 'total',
      align: 'right',
      width: 100,
      render: (n: number | null) => (n === null ? '—' : formatInt(n)),
    },
    { title: 'Last', dataIndex: 'last', key: 'last', width: 160, render: formatDateTime },
  ]

  const valueColumns: TableColumnsType<UsageFilters['values'][number]> = [
    { title: 'Filter', dataIndex: 'field', key: 'field', width: 180 },
    { title: 'Value', dataIndex: 'value', key: 'value', ellipsis: true },
    { title: 'Searches', dataIndex: 'searches', key: 'searches', align: 'right', width: 100, render: formatInt },
  ]

  const visitorColumns: TableColumnsType<UsageVisitor> = [
    {
      title: 'Visitor',
      dataIndex: 'visitor',
      key: 'visitor',
      ellipsis: true,
      render: (v: string, row) => (
        <Tooltip title={row.client_ip ? `IP ${row.client_ip}` : undefined}>
          <span className="font-mono text-xs">{v}</span>
        </Tooltip>
      ),
    },
    { title: 'Searches', dataIndex: 'searches', key: 'searches', align: 'right', width: 100, render: formatInt },
    { title: 'Active days', dataIndex: 'days', key: 'days', align: 'right', width: 110, render: formatInt },
    { title: 'First seen', dataIndex: 'first', key: 'first', width: 160, render: formatDateTime },
    { title: 'Last seen', dataIndex: 'last', key: 'last', width: 160, render: formatDateTime },
  ]

  const recentColumns: TableColumnsType<UsageEvent> = [
    { title: 'When', dataIndex: 'created_at', key: 'created_at', width: 160, render: formatDateTime },
    {
      title: 'Source',
      dataIndex: 'source',
      key: 'source',
      width: 90,
      render: (s: UsageSource, row) => (
        <Tag color={s === 'api' ? 'purple' : 'blue'} className="!m-0">
          {s === 'api' ? (row.kind === 'lookup' ? 'API lookup' : 'API') : 'Website'}
        </Tag>
      ),
    },
    {
      title: 'Search text',
      dataIndex: 'query',
      key: 'query',
      ellipsis: true,
      render: (q: string | null) => q ?? <Text type="secondary">—</Text>,
    },
    { title: 'Filters', dataIndex: 'filters', key: 'filters', width: 320, render: (f: Record<string, unknown>) => <FilterTags filters={f} /> },
    {
      title: 'Results',
      dataIndex: 'total',
      key: 'total',
      align: 'right',
      width: 90,
      render: (n: number | null) => (n === null ? '—' : formatInt(n)),
    },
    {
      title: 'Time',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      align: 'right',
      width: 80,
      render: (ms: number | null) => (ms === null ? '—' : `${formatInt(ms)} ms`),
    },
    {
      title: 'Visitor',
      dataIndex: 'visitor',
      key: 'visitor',
      width: 120,
      ellipsis: true,
      render: (v: string | null, row) => (
        <Tooltip title={[row.client_ip && `IP ${row.client_ip}`, row.user_agent].filter(Boolean).join(' · ') || undefined}>
          <span className="font-mono text-xs">{v ?? '—'}</span>
        </Tooltip>
      ),
    },
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Title level={2}>App usage</Title>
      <Paragraph type="secondary">
        What people search for and how much the app is used. Every search on the website and through the public
        API is recorded (query, filters, results, time taken, who searched). A search is counted once; paging through
        its results is not a new search. A visitor is a browser (an id it keeps), or the client IP for the API.
        Times are shown in your time zone; hours of the day are in UTC.
      </Paragraph>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented
          value={days}
          options={RANGES}
          onChange={(v) => {
            setDays(v as number)
            setRecentPage(1)
          }}
        />
        <Segmented
          value={source}
          options={SOURCES}
          onChange={(v) => {
            setSource(v as UsageSource | 'all')
            setRecentPage(1)
          }}
        />
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => setTick((t) => t + 1)}>
          Refresh
        </Button>
        {summary?.first_event && (
          <Text type="secondary" className="text-xs">
            Recording since {formatDateTime(summary.first_event)}
          </Text>
        )}
      </div>

      {error && <Alert type="error" showIcon closable className="mb-4" title={error} onClose={() => setError(undefined)} />}

      {summary && <Headline summary={summary} days={days} />}

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard
          title="Searches over time"
          caption="New searches per period, website and API together."
          controls={
            <Segmented
              size="small"
              value={period}
              options={[
                { value: 'day', label: 'Day' },
                { value: 'week', label: 'Week' },
                { value: 'month', label: 'Month' },
              ]}
              onChange={(v) => setPeriod(v as UsagePeriod)}
            />
          }
          table={seriesTable}
          csvName={`searches-per-${period}`}
        >
          <ColumnChart
            data={filled.map((b, i) => ({ x: i, y: b.searches }))}
            format={formatInt}
            unit="searches"
            xLabel={period}
            formatX={axisX}
            axisX={axisX}
          />
        </ChartCard>

        <ChartCard
          title="Visitors over time"
          caption="Distinct visitors per period."
          table={seriesTable}
          csvName={`visitors-per-${period}`}
        >
          <ColumnChart
            data={filled.map((b, i) => ({ x: i, y: b.visitors }))}
            format={formatInt}
            unit="visitors"
            xLabel={period}
            formatX={axisX}
            axisX={axisX}
          />
        </ChartCard>

        <ChartCard
          title="Searches by hour of day"
          caption="When searches are made (UTC)."
          table={{
            columns: [
              { key: 'hour', title: 'Hour (UTC)' },
              { key: 'searches', title: 'Searches', numeric: true },
            ],
            rows: hours.map((h) => ({ hour: `${String(h.hour).padStart(2, '0')}:00`, searches: h.searches })),
          }}
          csvName="searches-by-hour"
        >
          <ColumnChart
            data={hours.map((h) => ({ x: h.hour, y: h.searches }))}
            format={formatInt}
            unit="searches"
            xLabel="hour"
            formatX={(h) => `${String(h).padStart(2, '0')}:00 UTC`}
            axisX={(h) => String(h).padStart(2, '0')}
          />
        </ChartCard>

        <ChartCard
          title="Filters used"
          caption="How many searches set each filter."
          table={{
            columns: [
              { key: 'field', title: 'Filter' },
              { key: 'searches', title: 'Searches', numeric: true },
            ],
            rows: filters.fields.map((f) => ({ ...f })),
          }}
          csvName="filters-used"
        >
          {filters.fields.length ? (
            <BarList items={filters.fields.map((f) => ({ label: f.field, value: f.searches }))} format={formatInt} />
          ) : (
            <Text type="secondary">No filtered searches in this period.</Text>
          )}
        </ChartCard>
      </div>

      <Card title="Most searched texts" size="small" className="mt-6">
        <Table<UsageQuery>
          size="small"
          rowKey="query"
          columns={queryColumns}
          dataSource={queries}
          pagination={{ pageSize: 25, size: 'small', hideOnSinglePage: true }}
          locale={{ emptyText: 'No text searches in this period.' }}
        />
      </Card>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Most used filter values" size="small">
          <Table
            size="small"
            rowKey={(r) => `${r.field}=${r.value}`}
            columns={valueColumns}
            dataSource={filters.values}
            pagination={{ pageSize: 15, size: 'small', hideOnSinglePage: true }}
            locale={{ emptyText: 'No filtered searches in this period.' }}
          />
        </Card>
        <Card title="Most active visitors" size="small">
          <Table<UsageVisitor>
            size="small"
            rowKey="visitor"
            columns={visitorColumns}
            dataSource={visitors}
            pagination={{ pageSize: 15, size: 'small', hideOnSinglePage: true }}
            locale={{ emptyText: 'No visitors in this period.' }}
          />
        </Card>
      </div>

      <Card title="Latest searches" size="small" className="mt-6">
        <Table<UsageEvent>
          size="small"
          rowKey="id"
          columns={recentColumns}
          dataSource={recent.items}
          scroll={{ x: 1100 }}
          pagination={{
            current: recentPage,
            pageSize: RECENT_PAGE,
            total: recent.total,
            size: 'small',
            showSizeChanger: false,
            showTotal: (t) => `${formatInt(t)} searches`,
            onChange: setRecentPage,
          }}
          locale={{ emptyText: 'No searches in this period.' }}
        />
      </Card>
    </div>
  )
}

export default function UsagePage() {
  return <AdminGate what="app usage">{(code) => <Usage code={code} />}</AdminGate>
}
