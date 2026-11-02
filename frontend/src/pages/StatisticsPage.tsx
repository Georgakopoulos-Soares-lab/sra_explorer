import { DownloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Segmented, Skeleton, Statistic, Typography } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, type DatabaseStatistics, type StatisticsDimension, type YearCounts } from '../api'
import BrandName from '../components/BrandName'
import ChartCard, { type TableData } from '../stats/ChartCard'
import { BarList, ColumnChart, LineChart, SeriesLegend } from '../stats/charts'
import { downloadFile, formatCompact, formatInt, formatPct, SERIES_COLORS } from '../stats/format'

const { Title, Paragraph, Text } = Typography

// Shares over time leave out years with fewer projects or studies than this
// with a known value: the early years are too small for a share to mean much.
const MIN_YEAR_N = 200

// Statistics dimension -> search page filter, for the values that can be
// searched for as they are listed here.
const SEARCH_FILTER: Partial<Record<StatisticsDimension['name'], string>> = {
  assay_type: 'assay_type',
  instrument: 'instrument',
  library_layout: 'librarylayout',
  submitter_country: 'organization_country',
}

const searchLink = (dim: StatisticsDimension, value: string) => {
  const key = SEARCH_FILTER[dim.name]
  return key ? `/search?${new URLSearchParams({ [key]: value })}` : undefined
}

const formatDate = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })

// The last year is incomplete unless the data reaches 31 December.
function partialYear(stats: DatabaseStatistics) {
  const through = stats.data_through
  if (!through || through.endsWith('-12-31')) return undefined
  return { x: Number(through.slice(0, 4)), note: `Up to ${formatDate(through)}` }
}

function Section({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-10">
      <Title level={3} className="!mb-1">
        {title}
      </Title>
      {intro && <Paragraph type="secondary">{intro}</Paragraph>}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{children}</div>
    </section>
  )
}

function Totals({ stats }: { stats: DatabaseStatistics }) {
  const t = stats.totals
  const items: { label: string; value: string; note?: string }[] = [
    { label: 'BioProjects', value: formatInt(t.projects) },
    { label: 'SRA studies', value: formatInt(t.studies) },
    { label: 'Sequencing runs', value: formatInt(t.runs) },
    { label: 'Assay types', value: formatInt(t.assay_types) },
    { label: 'Submitter countries', value: formatInt(t.submitter_countries) },
    {
      label: 'Projects with a publication',
      value: formatPct((100 * t.projects_published) / t.projects),
      note: `${formatInt(t.projects_published)} projects`,
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
      {items.map((item) => (
        <Card key={item.label} size="small">
          <Statistic title={item.label} value={item.value} />
          {item.note && <Text type="secondary" className="text-xs">{item.note}</Text>}
        </Card>
      ))}
    </div>
  )
}

const YEAR_MEASURES = {
  projects: { label: 'Projects', unit: 'BioProjects' },
  studies: { label: 'Studies', unit: 'SRA studies' },
  runs: { label: 'Runs', unit: 'runs' },
} as const

function GrowthCard({ stats }: { stats: DatabaseStatistics }) {
  const [measure, setMeasure] = useState<keyof typeof YEAR_MEASURES>('projects')
  const [cumulative, setCumulative] = useState(false)
  const data = stats.years.map((y, i) => ({
    x: y.year,
    y: cumulative ? stats.years.slice(0, i + 1).reduce((sum, z) => sum + z[measure], 0) : y[measure],
  }))
  const partial = partialYear(stats)
  const table: TableData = {
    columns: [
      { key: 'year', title: 'Year' },
      { key: 'projects', title: 'BioProjects', numeric: true },
      { key: 'studies', title: 'SRA studies', numeric: true },
      { key: 'runs', title: 'Runs', numeric: true },
    ],
    rows: stats.years.map((y) => ({ year: y.year, projects: y.projects, studies: y.studies, runs: y.runs })),
  }
  return (
    <ChartCard
      title="Data released per year"
      csvName="released_per_year"
      table={table}
      caption={
        <>
          BioProjects by the release of their first data, SRA studies by the release of their first run, runs by their own
          release date.{partial && ` * ${partial.x} is ${partial.note.toLowerCase()}.`}
        </>
      }
      controls={
        <>
          <Segmented
            size="small"
            value={measure}
            onChange={(v) => setMeasure(v as keyof typeof YEAR_MEASURES)}
            options={Object.entries(YEAR_MEASURES).map(([value, m]) => ({ value, label: m.label }))}
          />
          <Segmented
            size="small"
            value={cumulative ? 'cumulative' : 'year'}
            onChange={(v) => setCumulative(v === 'cumulative')}
            options={[
              { value: 'year', label: 'Per year' },
              { value: 'cumulative', label: 'Cumulative' },
            ]}
          />
        </>
      }
    >
      <ColumnChart
        data={data}
        format={formatInt}
        unit={cumulative ? `${YEAR_MEASURES[measure].unit} in total` : YEAR_MEASURES[measure].unit}
        partial={partial}
      />
    </ChartCard>
  )
}

// Most common values of a dimension as bars, in its unit or (where counted) in runs.
function CategoryCard({ dim, title, caption, top = 15 }: {
  dim: StatisticsDimension
  title: string
  caption: ReactNode
  top?: number
}) {
  const hasRuns = dim.values.some((v) => v.runs != null)
  const [measure, setMeasure] = useState<'count' | 'runs'>('count')
  const values = [...dim.values]
    .sort((a, b) => (measure === 'runs' ? (b.runs ?? 0) - (a.runs ?? 0) : b.count - a.count))
    .slice(0, top)
  const unit = dim.unit
  const items = values.map((v) => ({
    label: v.value,
    value: measure === 'runs' ? (v.runs ?? 0) : v.count,
    to: searchLink(dim, v.value),
    detail: (
      <div className="tabular-nums">
        <div>
          {formatInt(v.count)} {unit}
        </div>
        {v.runs != null && <div>{formatInt(v.runs)} runs</div>}
        {searchLink(dim, v.value) && <div className="mt-1 text-gray-500">Click the name to search</div>}
      </div>
    ),
  }))
  const table: TableData = {
    columns: [
      { key: 'value', title: dim.label },
      { key: 'count', title: unit === 'projects' ? 'BioProjects' : 'SRA studies', numeric: true },
      ...(hasRuns ? [{ key: 'runs', title: 'Runs', numeric: true }] : []),
    ],
    rows: [
      ...dim.values.map((v) => ({ value: v.value, count: v.count, runs: v.runs ?? null })),
      { value: '(not recorded)', count: dim.unknown, runs: null },
    ],
  }
  return (
    <ChartCard
      title={title}
      csvName={dim.name}
      table={table}
      caption={
        <>
          {caption} {formatInt(dim.distinct)} distinct values; {formatInt(dim.unknown)} {unit} have none recorded.
        </>
      }
      controls={
        hasRuns && (
          <Segmented
            size="small"
            value={measure}
            onChange={(v) => setMeasure(v as 'count' | 'runs')}
            options={[
              { value: 'count', label: unit === 'projects' ? 'Projects' : 'Studies' },
              { value: 'runs', label: 'Runs' },
            ]}
          />
        )
      }
    >
      <BarList items={items} format={measure === 'runs' ? formatCompact : formatInt} />
    </ChartCard>
  )
}

// The share of each year's projects or studies having each of the dimension's
// most common values.
function SharesCard({ dim, title, caption, series = 8, initiallyShown = 5 }: {
  dim: StatisticsDimension
  title: string
  caption: ReactNode
  series?: number
  initiallyShown?: number
}) {
  const options = dim.values.slice(0, series).map((v, i) => ({ key: v.value, label: v.value, color: SERIES_COLORS[i] }))
  const [shown, setShown] = useState(() => new Set(options.slice(0, initiallyShown).map((o) => o.key)))
  const { xs, known, counts } = useMemo(() => {
    const known = new Map(dim.known_by_year.map((r) => [r.year, r.count]))
    const xs = [...known.keys()].filter((y) => known.get(y)! >= MIN_YEAR_N).sort((a, b) => a - b)
    const counts = new Map(dim.by_year.map((r) => [`${r.value}\u0000${r.year}`, r.count]))
    return { xs, known, counts }
  }, [dim])
  const count = (value: string, year: number) => counts.get(`${value}\u0000${year}`) ?? 0
  const lines = options
    .filter((o) => shown.has(o.key))
    .map((o) => ({ ...o, values: xs.map((y) => (100 * count(o.key, y)) / known.get(y)!) }))
  const unitTitle = dim.unit === 'projects' ? 'BioProjects' : 'SRA studies'
  const table: TableData = {
    columns: [
      { key: 'year', title: 'Year' },
      { key: 'known', title: `${unitTitle} with a known value`, numeric: true },
      ...options.map((o) => ({ key: o.key, title: o.label, numeric: true })),
    ],
    rows: xs.map((y) => ({ year: y, known: known.get(y)!, ...Object.fromEntries(options.map((o) => [o.key, count(o.key, y)])) })),
  }
  return (
    <ChartCard
      title={title}
      csvName={`${dim.name}_by_year`}
      table={table}
      caption={
        <>
          {caption} Years with fewer than {MIN_YEAR_N} {dim.unit} with a known value are left out. The table and CSV give the
          counts.
        </>
      }
    >
      <SeriesLegend
        items={options}
        shown={shown}
        onToggle={(key) =>
          setShown((s) => {
            const next = new Set(s)
            if (!next.delete(key)) next.add(key)
            return next
          })
        }
      />
      <LineChart xs={xs} series={lines} format={(n) => `${Math.round(n)}%`} />
    </ChartCard>
  )
}

function PublicationsCard({ stats }: { stats: DatabaseStatistics }) {
  const years = stats.years.filter((y) => y.projects >= MIN_YEAR_N)
  const pct = (y: YearCounts, n: number) => (100 * n) / y.projects
  const series = [
    { key: 'pub', label: 'Publication', color: SERIES_COLORS[0], values: years.map((y) => pct(y, y.projects_published)) },
    { key: 'geo', label: 'GEO series', color: SERIES_COLORS[1], values: years.map((y) => pct(y, y.projects_geo)) },
  ]
  const t = stats.totals
  const table: TableData = {
    columns: [
      { key: 'year', title: 'Year' },
      { key: 'projects', title: 'BioProjects', numeric: true },
      { key: 'published', title: 'With a publication', numeric: true },
      { key: 'geo', title: 'With a GEO series', numeric: true },
    ],
    rows: stats.years.map((y) => ({ year: y.year, projects: y.projects, published: y.projects_published, geo: y.projects_geo })),
  }
  return (
    <ChartCard
      title="Projects linked to a publication or GEO series"
      csvName="publications_by_year"
      table={table}
      caption={
        <>
          Share of the BioProjects released each year that link to at least one publication (in BioProject or ENA) or GEO
          series. Recent years are lower partly because papers follow data release:
          {t.publication_lag_days !== null && (
            <>
              {' '}
              for the {formatInt(t.publication_lag_projects)} projects published after release, the median delay is{' '}
              {formatInt(Math.round(t.publication_lag_days))} days.
            </>
          )}
        </>
      }
    >
      <SeriesLegend items={series} />
      <LineChart xs={years.map((y) => y.year)} series={series} format={(n) => `${Math.round(n)}%`} />
    </ChartCard>
  )
}

function Methods({ stats }: { stats: DatabaseStatistics }) {
  return (
    <section className="mt-10">
      <Title level={3}>Definitions and caveats</Title>
      <Card size="small">
        <ul className="list-disc space-y-2 pl-5 text-sm">
          <li>
            <Text strong>Units.</Text> A <i>BioProject</i> is counted once, however many SRA studies it has. An{' '}
            <i>SRA study</i> (SRP/ERP/DRP) groups the runs submitted together. A <i>run</i> (SRR/ERR/DRR) is one
            sequencing run of one sample.
          </li>
          <li>
            <Text strong>Dates.</Text> Years are release years, not submission years: a study is dated by its first public
            run, a run by its own release date, and a BioProject by the release of its first data (or, without runs, its
            NCBI release or submission date).
            {stats.data_through && <> The data reach runs released up to {formatDate(stats.data_through)}.</>}
          </li>
          <li>
            <Text strong>Run attributes.</Text> Assay type, platform, instrument, library and organism are taken from the
            runs, so a study whose runs differ counts once for each value. Counts per value therefore add up to more than
            the number of studies, and shares over time do not add up to 100%.
          </li>
          <li>
            <Text strong>Countries.</Text> <i>Submitter country</i> is the country of the submitting organisation in the
            BioProject record. <i>Sample origin</i> is NCBI's country computed from the samples' geographic location
            (geo_loc_name); many samples, for example from cell lines or model organisms, have none.
          </li>
          <li>
            <Text strong>Vocabulary.</Text> Values are shown as submitted to SRA (its controlled vocabularies for assay type,
            platform and library source), apart from spelling variants merged for the search filters.
          </li>
          <li>
            <Text strong>Scope.</Text> <BrandName /> covers the public SRA metadata and BioProject records it has loaded;
            controlled-access data and projects without SRA runs are not included.
          </li>
        </ul>
      </Card>
    </section>
  )
}

export default function StatisticsPage() {
  const [stats, setStats] = useState<DatabaseStatistics | null>(null)
  const [error, setError] = useState<string>()

  useEffect(() => {
    const controller = new AbortController()
    api
      .statistics(controller.signal)
      .then(setStats)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof ApiError || e instanceof Error ? e.message : String(e))
      })
    return () => controller.abort()
  }, [])

  const dim = (name: StatisticsDimension['name']) => stats!.dimensions.find((d) => d.name === name)!

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Title level={2} className="!mb-1">
            Database statistics
          </Title>
          <Paragraph type="secondary" className="max-w-3xl">
            What the sequencing data in <BrandName /> covers: how it has grown, which assays and technologies produced it,
            where it comes from and how much of it is published. Every chart has a table view and a CSV download.
          </Paragraph>
        </div>
        {stats && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => downloadFile('srascout_statistics.json', JSON.stringify(stats, null, 2), 'application/json')}
          >
            All statistics (JSON)
          </Button>
        )}
      </div>

      {error && <Alert type="error" showIcon message="Could not load the statistics" description={error} />}
      {!stats && !error && (
        <>
          <Paragraph type="secondary">
            Loading. Right after the server starts the statistics are still being computed, which takes a minute or two.
          </Paragraph>
          <Skeleton active paragraph={{ rows: 10 }} />
        </>
      )}

      {stats && (
        <>
          <Text type="secondary" className="mb-3 block text-sm">
            {stats.data_through && (
              <>
                Data released up to <Text strong>{formatDate(stats.data_through)}</Text>.{' '}
              </>
            )}
            Computed {formatDate(stats.generated_at)}.
          </Text>
          <Totals stats={stats} />

          <Section title="Growth">
            <GrowthCard stats={stats} />
            <PublicationsCard stats={stats} />
          </Section>

          <Section
            title="Assays"
            intro="The experimental strategy of the runs, as recorded in SRA (LIBRARY_STRATEGY), such as RNA-Seq, WGS or ChIP-Seq."
          >
            <CategoryCard dim={dim('assay_type')} title="Most common assay types" caption="SRA studies with at least one run of each assay type." />
            <SharesCard
              dim={dim('assay_type')}
              title="Assay types over time"
              caption="Share of the SRA studies released each year with at least one run of each assay type."
            />
            <CategoryCard
              dim={dim('library_source')}
              title="Library sources"
              caption="The type of source material sequenced (genomic, transcriptomic, metagenomic, single cell, …)."
              top={10}
            />
            <SharesCard
              dim={dim('library_source')}
              title="Library sources over time"
              caption="Share of the SRA studies released each year with at least one run of each library source."
              series={6}
              initiallyShown={5}
            />
          </Section>

          <Section title="Sequencing technology">
            <SharesCard
              dim={dim('platform')}
              title="Sequencing platforms over time"
              caption="Share of the SRA studies released each year with at least one run on each platform."
              series={7}
              initiallyShown={4}
            />
            <CategoryCard dim={dim('instrument')} title="Most used instruments" caption="SRA studies with at least one run on each instrument model." />
          </Section>

          <Section title="Submitters" intro="Where the organisations that submitted the projects are based.">
            <CategoryCard
              dim={dim('submitter_country')}
              title="Submitter countries"
              caption="BioProjects by the country of the submitting organisation."
              top={20}
            />
            <SharesCard
              dim={dim('submitter_country')}
              title="Submitter countries over time"
              caption="Share of the BioProjects released each year, among those with a submitter country, from each country."
              series={6}
              initiallyShown={6}
            />
          </Section>

          <Section title="Samples" intro="What was sequenced and where the samples were collected.">
            <CategoryCard
              dim={dim('organism')}
              title="Most studied organisms"
              caption="SRA studies with at least one run from each organism, including metagenomes. Names are as in the runs' taxonomy, so strains count separately."
              top={20}
            />
            <CategoryCard
              dim={dim('sample_country')}
              title="Sample origin countries"
              caption="SRA studies with samples collected in each country, as computed by NCBI from the samples' location."
              top={20}
            />
          </Section>

          <Methods stats={stats} />
        </>
      )}
    </div>
  )
}
