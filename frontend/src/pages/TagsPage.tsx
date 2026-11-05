import { DownloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Segmented, Skeleton, Statistic, Typography } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { api, ApiError, type TagOverview } from '../api'
import BrandName from '../components/BrandName'
import ChartCard, { type TableData } from '../stats/ChartCard'
import { BarList, ColumnChart, LineChart, SeriesLegend } from '../stats/charts'
import { downloadFile, formatInt, formatPct, SERIES_COLORS } from '../stats/format'
import HowTagsAreMade from '../tags/HowTagsAreMade'
import { isOrganism, MAX_TAGS, scrollToWorkbench } from '../tags/links'
import TagNetwork from '../tags/TagNetwork'
import TagPairs from '../tags/TagPairs'
import TagWorkbench from '../tags/TagWorkbench'

const { Title, Paragraph, Text } = Typography

// Shares over time leave out years with fewer tagged projects than this.
const MIN_YEAR_N = 2000
const THIS_YEAR = new Date().getFullYear()

const formatDate = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })

function Section({ id, title, intro, children }: { id?: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="mt-10 scroll-mt-4">
      <Title level={3} className="!mb-1">
        {title}
      </Title>
      {intro && <Paragraph type="secondary">{intro}</Paragraph>}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{children}</div>
    </section>
  )
}

function Totals({ overview }: { overview: TagOverview }) {
  const t = overview.totals
  const band = (n: number) => overview.frequency.find((f) => f.min_projects === n)?.tags ?? 0
  const items: { label: string; value: string; note?: ReactNode }[] = [
    {
      label: 'BioProjects with tags',
      value: formatInt(t.tagged),
      note: (
        <>
          {formatPct((100 * t.tagged) / Math.max(t.projects, 1))} of {formatInt(t.projects)}; <a href="#coverage">by year</a>
        </>
      ),
    },
    { label: 'Distinct tags', value: formatInt(t.distinct_tags), note: `${formatInt(t.occurrences)} tag occurrences` },
    {
      label: 'Tags per project',
      value: t.tags_per_project_median === null ? '–' : `median ${formatInt(t.tags_per_project_median)}`,
      note: t.tags_per_project_mean === null ? undefined : `mean ${t.tags_per_project_mean.toFixed(1)}, at most 20`,
    },
    {
      label: 'Tags on 10+ projects',
      value: formatInt(band(10)),
      note: `${formatInt(band(100))} on 100+, ${formatInt(band(1000))} on 1,000+`,
    },
    {
      label: 'Projects with tag types',
      value: formatInt(t.labelled),
      note: t.labelled ? `${formatPct((100 * t.labelled) / Math.max(t.tagged, 1))} of the tagged projects` : 'kept for projects tagged since types were added',
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
      {items.map((item) => (
        <Card key={item.label} size="small">
          <Statistic title={item.label} value={item.value} />
          {item.note && (
            <Text type="secondary" className="text-xs">
              {item.note}
            </Text>
          )}
        </Card>
      ))}
    </div>
  )
}

function TopTagsCard({ overview, onPick }: { overview: TagOverview; onPick: (tags: string[]) => void }) {
  const [scope, setScope] = useState<'other' | 'all'>('other')
  const [top, setTop] = useState<30 | 100>(30)
  const [type, setType] = useState<string>('any')
  const tagged = overview.totals.tagged
  const rows = overview.top.filter(
    (t) => (scope === 'all' || !isOrganism(t)) && (type === 'any' || t.group === type),
  )
  const singletons = (overview.frequency.find((f) => f.min_projects === 1)?.tags ?? 0) - (overview.frequency.find((f) => f.min_projects === 2)?.tags ?? 0)
  const table: TableData = {
    columns: [
      { key: 'value', title: 'Tag' },
      { key: 'group', title: 'Type' },
      { key: 'count', title: 'BioProjects', numeric: true },
      { key: 'share', title: 'Share of tagged projects %', numeric: true },
    ],
    rows: overview.top.map((t) => ({
      value: t.value,
      group: t.group,
      count: t.count,
      share: Number(((100 * t.count) / Math.max(tagged, 1)).toFixed(2)),
    })),
  }
  return (
    <ChartCard
      title="Most common tags"
      csvName="top_tags"
      table={table}
      caption={
        <>
          Tagged BioProjects carrying each tag, among {formatInt(tagged)}. Spelling variants and synonyms are separate tags
          (mouse and Mus musculus; E. coli and Escherichia coli), so one thing can be spread over several bars.{' '}
          <b>Other tags</b> leaves out organism names
          {overview.has_labels ? ' and tags of type organism' : ' (tag types are not stored for these projects yet)'}.{' '}
          {formatInt(singletons)} of the {formatInt(overview.totals.distinct_tags)} distinct tags are on a single project.
          Click a tag to count and open its projects.
        </>
      }
      controls={
        <>
          <Segmented
            size="small"
            value={scope}
            onChange={(v) => setScope(v as 'other' | 'all')}
            options={[
              { value: 'other', label: 'Other tags' },
              { value: 'all', label: 'All tags' },
            ]}
          />
          <Segmented
            size="small"
            value={top}
            onChange={(v) => setTop(v as 30 | 100)}
            options={[
              { value: 30, label: 'Top 30' },
              { value: 100, label: 'Top 100' },
            ]}
          />
          {overview.has_labels && overview.types.length > 0 && (
            <Segmented
              size="small"
              value={type}
              onChange={(v) => setType(v as string)}
              options={[{ value: 'any', label: 'Any type' }, ...overview.types.map((x) => ({ value: x.value, label: x.value }))]}
            />
          )}
        </>
      }
    >
      <BarList
        format={formatInt}
        items={rows.slice(0, top).map((t) => ({
          label: t.value,
          value: t.count,
          onClick: () => onPick([t.value]),
          detail: (
            <div className="tabular-nums">
              <div>
                {formatInt(t.count)} BioProjects ({formatPct((100 * t.count) / Math.max(tagged, 1))} of the tagged projects)
              </div>
              <div className="text-gray-500">{t.group ?? 'type not known'}</div>
              <div className="mt-1 text-gray-500">Click to choose this tag</div>
            </div>
          ),
        }))}
      />
    </ChartCard>
  )
}

function CoverageCard({ overview }: { overview: TagOverview }) {
  const [measure, setMeasure] = useState<'counts' | 'share'>('share')
  const years = overview.coverage_by_year
  const xs = years.map((y) => y.year)
  const series =
    measure === 'counts'
      ? [
          { key: 'all', label: 'All BioProjects', color: SERIES_COLORS[0], values: years.map((y) => y.projects) },
          { key: 'tagged', label: 'With tags', color: SERIES_COLORS[1], values: years.map((y) => y.tagged) },
        ]
      : [
          {
            key: 'share',
            label: 'Share with tags',
            color: SERIES_COLORS[1],
            values: years.map((y) => (y.projects ? (100 * y.tagged) / y.projects : null)),
          },
        ]
  const table: TableData = {
    columns: [
      { key: 'year', title: 'Release year' },
      { key: 'projects', title: 'BioProjects', numeric: true },
      { key: 'tagged', title: 'With tags', numeric: true },
      { key: 'share', title: 'Share with tags %', numeric: true },
    ],
    rows: years.map((y) => ({
      year: y.year,
      projects: y.projects,
      tagged: y.tagged,
      share: y.projects ? Number(((100 * y.tagged) / y.projects).toFixed(1)) : null,
    })),
  }
  // Three sample years for the caption: the latest full year and two older ones.
  const samples = [THIS_YEAR - 1, THIS_YEAR - 3, THIS_YEAR - 7]
    .map((year) => years.find((y) => y.year === year))
    .filter((y) => y !== undefined && y.projects > 0)
    .map((y) => `${y!.year} ${formatPct((100 * y!.tagged) / y!.projects)}`)
  return (
    <ChartCard
      title="Projects with tags by release year"
      csvName="tag_coverage_by_year"
      table={table}
      caption={
        <>
          BioProjects by the release of their first data, and how many of them have tags. Tagging runs weekly on new
          projects and on about 20,000 not-yet-tagged older projects, newest first, so coverage rises every week and is lowest
          for old projects{samples.length > 0 && <>: {samples.join(', ')}</>}. Until it reaches the oldest years, the counts on
          this page describe mostly recent projects. Do not read a tag count as a trend over time.
          {xs.includes(THIS_YEAR) && ` ${THIS_YEAR} is in progress.`}
        </>
      }
      controls={
        <Segmented
          size="small"
          value={measure}
          onChange={(v) => setMeasure(v as 'counts' | 'share')}
          options={[
            { value: 'share', label: 'Share with tags' },
            { value: 'counts', label: 'Counts' },
          ]}
        />
      }
    >
      {measure === 'counts' && <SeriesLegend items={series} />}
      <LineChart
        xs={xs}
        series={series}
        format={measure === 'share' ? (n) => `${Math.round(n)}%` : formatInt}
        yMax={measure === 'share' ? 100 : undefined}
      />
    </ChartCard>
  )
}

function TagsPerProjectCard({ overview }: { overview: TagOverview }) {
  const t = overview.totals
  const rows = overview.tags_per_project
  const table: TableData = {
    columns: [
      { key: 'n', title: 'Tags' },
      { key: 'projects', title: 'BioProjects', numeric: true },
      { key: 'share', title: 'Share %', numeric: true },
    ],
    rows: rows.map((r) => ({ n: r.n, projects: r.projects, share: Number(((100 * r.projects) / Math.max(t.tagged, 1)).toFixed(1)) })),
  }
  return (
    <ChartCard
      title="Number of tags per project"
      csvName="tags_per_project"
      table={table}
      caption={
        <>
          Among the {formatInt(t.tagged)} tagged projects
          {t.tags_per_project_median !== null && t.tags_per_project_mean !== null && (
            <> (median {formatInt(t.tags_per_project_median)}, mean {t.tags_per_project_mean.toFixed(1)})</>
          )}
          . The first tag is the project's organism name when it has one; the rest are kept by relevance, at most 20.
          {t.empty > 0 && <> {formatInt(t.empty)} projects where nothing was recognised have no tags and are not counted here.</>}
        </>
      }
    >
      <ColumnChart
        data={rows.map((r) => ({ x: r.n, y: r.projects }))}
        format={formatInt}
        unit="BioProjects"
        xLabel="number of tags"
        formatX={(n) => `${n} tag${n === 1 ? '' : 's'}`}
      />
    </ChartCard>
  )
}

// The share of each year's tagged projects carrying each of the most common
// tags: shares within a year, so partial tagging of a year cancels out.
function SharesCard({ overview, onPick }: { overview: TagOverview; onPick: (tags: string[]) => void }) {
  const counts = useMemo(() => new Map(overview.coverage_by_year.map((y) => [y.year, y.tagged])), [overview])
  const tags = useMemo(() => {
    const order = new Map(overview.top.map((t, i) => [t.value, i]))
    return [...new Set(overview.by_year.map((r) => r.value))].sort((a, b) => (order.get(a) ?? 1e9) - (order.get(b) ?? 1e9)).slice(0, 8)
  }, [overview])
  const options = tags.map((t, i) => ({ key: t, label: t, color: SERIES_COLORS[i] }))
  const [shown, setShown] = useState(() => {
    const organisms = new Set(overview.top.filter(isOrganism).map((t) => t.value))
    return new Set(tags.filter((t) => !organisms.has(t)).slice(0, 5))
  })
  const xs = overview.coverage_by_year.filter((y) => y.tagged >= MIN_YEAR_N).map((y) => y.year)
  const byKey = useMemo(() => new Map(overview.by_year.map((r) => [`${r.value}\u0000${r.year}`, r.count])), [overview])
  const count = (tag: string, year: number) => byKey.get(`${tag}\u0000${year}`) ?? 0
  const lines = options
    .filter((o) => shown.has(o.key))
    .map((o) => ({ ...o, values: xs.map((y) => (100 * count(o.key, y)) / counts.get(y)!) }))
  const table: TableData = {
    columns: [
      { key: 'year', title: 'Release year' },
      { key: 'tagged', title: 'Tagged BioProjects', numeric: true },
      ...tags.map((t) => ({ key: t, title: t, numeric: true })),
    ],
    rows: overview.coverage_by_year.map((y) => ({ year: y.year, tagged: y.tagged, ...Object.fromEntries(tags.map((t) => [t, count(t, y.year)])) })),
  }
  if (xs.length < 2) return null
  return (
    <ChartCard
      title="Most common tags over time"
      csvName="top_tags_by_year"
      table={table}
      caption={
        <>
          Share of the tagged BioProjects released each year that carry the tag, for the most common tags. Years with fewer
          than {formatInt(MIN_YEAR_N)} tagged projects are left out. Older years are only partly tagged, so their tagged
          projects may not represent the year; read with the coverage chart. Click a name in the legend to show or hide it,
          and the tag's bar in Most common tags to find its projects.
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
      <Text type="secondary" className="mt-2 block text-xs">
        {tags.map((t, i) => (
          <span key={t}>
            {i > 0 && ' · '}
            <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-xs text-[#1677ff] hover:underline" onClick={() => onPick([t])}>
              {t}
            </button>
          </span>
        ))}
      </Text>
    </ChartCard>
  )
}

export default function TagsPage() {
  const [params, setParams] = useSearchParams()
  const tags = useMemo(() => [...new Set(params.getAll('tag').map((t) => t.trim()).filter(Boolean))].slice(0, MAX_TAGS), [params])
  const any = params.get('any') === 'true'
  const [overview, setOverview] = useState<TagOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api
      .tagOverview(controller.signal)
      .then(setOverview)
      .catch((err: Error) => {
        if (controller.signal.aborted) return
        setError(err instanceof ApiError && err.status === 503 ? err.message : `${err.message}. Is the API running?`)
      })
    return () => controller.abort()
  }, [])

  // The chosen tags live in the URL, so a view can be shared and the back button undoes a choice.
  const setTags = (next: string[], nextAny: boolean) => {
    const p = new URLSearchParams()
    for (const t of next.slice(0, MAX_TAGS)) p.append('tag', t)
    if (nextAny) p.set('any', 'true')
    setParams(p)
  }
  // A tag picked anywhere below the workbench is added to it, and the page scrolls up to show the result.
  const pick = (more: string[]) => {
    setTags([...new Set([...tags, ...more])], any)
    scrollToWorkbench()
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Title level={2} className="!mb-1">
            Tag explorer
          </Title>
          <Paragraph type="secondary" className="max-w-3xl">
            Every tagged BioProject in <BrandName /> carries a short list of tag words: the organisms, diseases, tissues,
            organs, cell types, cell lines, chemicals and environments named in its title, name and description, extracted by a
            biomedical language model. Combine tags to find projects, see which tags go together, and read how the tags are
            made. Every chart has a table view and a CSV download.
          </Paragraph>
        </div>
        {overview && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => downloadFile('srascout_tags.json', JSON.stringify(overview, null, 2), 'application/json')}
          >
            All tag statistics (JSON)
          </Button>
        )}
      </div>

      <TagWorkbench tags={tags} any={any} onChange={setTags} overview={overview} />

      {error && <Alert className="mt-6" type="error" showIcon message="Could not load the tag statistics" description={error} />}
      {!overview && !error && (
        <div className="mt-6">
          <Paragraph type="secondary">
            Loading the tag statistics. Right after the server starts they are still being computed, which takes a few
            seconds.
          </Paragraph>
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
      )}

      {overview && (
        <>
          <section className="mt-10">
            <Title level={3} className="!mb-1">
              The tags in numbers
            </Title>
            <Text type="secondary" className="mb-3 block text-sm">
              Computed {formatDate(overview.generated_at)}. Tagging started with the newest projects and works back in weekly
              batches, so coverage differs by release year (see <a href="#coverage">Coverage</a>); a tag search finds only
              projects that have tags.
            </Text>
            <Totals overview={overview} />
          </section>

          <Section title="What the tags say">
            <TopTagsCard overview={overview} onPick={pick} />
            <TagPairs network={overview.network} tagged={overview.totals.tagged} onPick={pick} />
          </Section>
          <div className="mt-4">
            <TagNetwork network={overview.network} tagged={overview.totals.tagged} onPick={pick} />
          </div>

          <Section
            id="coverage"
            title="Coverage"
            intro="Which projects have tags, and how many each has. These charts put every other number on this page in context."
          >
            <CoverageCard overview={overview} />
            <TagsPerProjectCard overview={overview} />
            <SharesCard overview={overview} onPick={pick} />
          </Section>

          <HowTagsAreMade overview={overview} onPick={pick} />
        </>
      )}
    </div>
  )
}
