import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Checkbox, Segmented, Select, Skeleton, Table, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, API_BASE_URL, ApiError, type FacetValue, type SearchHit, type TagOverview, type TagRelated } from '../api'
import CodeBlock from '../components/CodeBlock'
import ExternalLink from '../components/ExternalLink'
import TagList from '../search/TagList'
import ChartCard, { type TableData } from '../stats/ChartCard'
import { BarList, ColumnChart } from '../stats/charts'
import { formatInt, formatPct } from '../stats/format'
import { formatRatio, isOrganism, MAX_TAGS, searchUrl, WORKBENCH_ID } from './links'

const { Text, Title } = Typography

const ENA = 'https://www.ebi.ac.uk/ena/browser/view'
// Tags a related tag needs among the matching projects to be ranked by lift,
// where a tag on two projects would otherwise come first.
const MIN_LIFT_COUNT = 20
const PREVIEW_SIZE = 10
const THIS_YEAR = new Date().getFullYear()

// Tag sets to try, shown under the picker.
const EXAMPLES: string[][] = [
  ['liver', 'mouse'],
  ['gut microbiota'],
  ['cancer', 'T cell'],
  ['soil metagenome'],
  ['Arabidopsis thaliana', 'root'],
  ['macrophage', 'bone marrow'],
  ['osteoarthritis'],
]

// The public API's base URL, as the API documentation page shows it.
const API_ROOT = API_BASE_URL.startsWith('http') ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`

// Every year from the first with a project to this one, so the x axis is a timeline.
function fillYears(years: { year: number; count: number }[]) {
  const counts = new Map(years.map((y) => [y.year, y.count]))
  const first = Math.min(...years.map((y) => y.year))
  const out = []
  for (let y = first; y <= Math.max(THIS_YEAR, first); y++) out.push({ x: y, y: counts.get(y) ?? 0 })
  return out
}

const dedupe = (tags: string[]) => [...new Set(tags.map((t) => t.trim()).filter(Boolean))]

// A multi-select over every tag, searched as the user types (the Tags filter
// of the search page, without the other filters narrowing it).
function TagSelect({ value, onChange }: { value: string[]; onChange: (tags: string[]) => void }) {
  const [options, setOptions] = useState<FacetValue[]>([])
  const [loading, setLoading] = useState(false)
  const request = useRef<{ timer?: number; controller?: AbortController }>({})

  const search = (q: string) => {
    window.clearTimeout(request.current.timer)
    request.current.controller?.abort()
    request.current.timer = window.setTimeout(() => {
      const controller = new AbortController()
      request.current.controller = controller
      setLoading(true)
      api
        .suggest('tag', q, controller.signal)
        .then((values) => {
          setOptions(values)
          setLoading(false)
        })
        .catch(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 250)
  }

  useEffect(() => {
    const current = request.current
    return () => {
      window.clearTimeout(current.timer)
      current.controller?.abort()
    }
  }, [])

  // Chosen tags stay in the options so the control can show them.
  const all: FacetValue[] = [...value.filter((v) => !options.some((o) => o.value === v)).map((v) => ({ value: v, count: 0 })), ...options]
  return (
    <Select
      mode="multiple"
      virtual={false}
      allowClear
      className="w-full"
      size="large"
      maxCount={MAX_TAGS}
      placeholder="Type a tag: a disease, tissue, cell type, organism, chemical, environment…"
      value={value}
      options={all.map((o) => ({ value: o.value, label: o.value, count: o.count, group: o.group }))}
      optionRender={(option) => (
        <span className="flex justify-between gap-2">
          <span className="truncate">{option.label}</span>
          <span className="shrink-0 text-gray-400">
            {option.data.group && <span className="mr-2 text-xs">{option.data.group}</span>}
            {option.data.count > 0 && formatInt(option.data.count)}
          </span>
        </span>
      )}
      showSearch={{ filterOption: false, onSearch: search }}
      loading={loading}
      notFoundContent={loading ? 'Searching…' : 'No tag contains this text'}
      onFocus={() => options.length === 0 && search('')}
      onChange={(next: string[]) => onChange(dedupe(next))}
    />
  )
}

function ExampleChip({ tags, onClick }: { tags: string[]; onClick: () => void }) {
  return (
    <button
      type="button"
      className="inline-flex cursor-pointer items-center gap-1 rounded border border-dashed border-sky-300 bg-sky-50 px-2 py-0.5 text-xs text-sky-800 hover:border-sky-500 hover:bg-sky-100"
      onClick={onClick}
    >
      <PlusOutlined className="text-[9px]" />
      {tags.join(' + ')}
    </button>
  )
}

// The first part of the page: choose tags, see how many projects have them
// and what they are, add tags from what the matches suggest, and open the
// same query on the search page or as an API call.
export default function TagWorkbench({ tags, any, onChange, overview }: {
  tags: string[]
  // Whether a project needs only one of the tags.
  any: boolean
  onChange: (tags: string[], any: boolean) => void
  // For the lift of related tags; null until loaded.
  overview: TagOverview | null
}) {
  const key = JSON.stringify([tags, any])
  const [related, setRelated] = useState<{ key: string; data?: TagRelated; error?: string }>()
  const [preview, setPreview] = useState<{ key: string; items?: SearchHit[]; total?: number }>()
  const [rank, setRank] = useState<'count' | 'lift'>('count')
  const [hideOrganisms, setHideOrganisms] = useState(false)

  useEffect(() => {
    if (tags.length === 0) return
    const controller = new AbortController()
    api
      .tagRelated(tags, any, controller.signal)
      .then((data) => setRelated({ key, data }))
      .catch((err: Error) => {
        if (controller.signal.aborted) return
        const message = err instanceof ApiError && err.status === 422 ? `At most ${MAX_TAGS} tags can be combined.` : err.message
        setRelated({ key, error: message })
      })
    api
      .searchBioprojects(
        { tag: tags, ...(any ? { tag_any: 'true' } : {}), sort: 'release_desc', limit: String(PREVIEW_SIZE) },
        controller.signal,
      )
      .then((r) => setPreview({ key, items: r.items, total: r.total }))
      .catch(() => {}) // the preview is an extra; the counts above it don't depend on it
    return () => controller.abort()
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  const addTags = (more: string[]) => onChange(dedupe([...tags, ...more]).slice(0, MAX_TAGS), any)
  const current = related?.key === key ? related : undefined
  const loading = tags.length > 0 && !current
  const data = current?.data ?? related?.data
  const stale = tags.length > 0 && data && !current
  const anyOf = any && tags.length > 1

  const tagged = overview?.totals.tagged ?? 0
  const relatedItems = useMemo(() => {
    if (!data) return []
    const rows = data.related
      .filter((t) => !hideOrganisms || !isOrganism(t))
      .map((t) => {
        const share = t.count / Math.max(data.projects, 1)
        const lift = tagged ? share / (t.total / tagged) : null
        return { ...t, share, lift }
      })
    return rank === 'lift'
      ? rows.filter((t) => t.count >= MIN_LIFT_COUNT && t.lift !== null).sort((x, y) => y.lift! - x.lift!)
      : rows
  }, [data, hideOrganisms, rank, tagged])

  const apiUrl = `${API_ROOT}/v1/projects?${tags.map((t) => `tag=${encodeURIComponent(t)}`).join('&')}${anyOf ? '&tag_any=true' : ''}`

  const relatedTable: TableData = {
    columns: [
      { key: 'value', title: 'Tag' },
      { key: 'group', title: 'Type' },
      { key: 'count', title: 'Projects with the chosen tags', numeric: true },
      { key: 'share', title: 'Share %', numeric: true },
      { key: 'total', title: 'Projects with the tag', numeric: true },
      { key: 'lift', title: 'Lift', numeric: true },
    ],
    rows: (data?.related ?? []).map((t) => {
      const share = t.count / Math.max(data!.projects, 1)
      return {
        value: t.value,
        group: t.group,
        count: t.count,
        share: Number((100 * share).toFixed(1)),
        total: t.total,
        lift: tagged ? Number((share / (t.total / tagged)).toFixed(2)) : null,
      }
    }),
  }
  const organismsTable: TableData = {
    columns: [
      { key: 'value', title: 'Organism' },
      { key: 'count', title: 'BioProjects', numeric: true },
    ],
    rows: (data?.organisms ?? []).map((o) => ({ value: o.value, count: o.count })),
  }
  const yearsTable: TableData = {
    columns: [
      { key: 'year', title: 'Release year' },
      { key: 'count', title: 'BioProjects', numeric: true },
    ],
    rows: (data?.years ?? []).map((y) => ({ year: y.year, count: y.count })),
  }

  const projectsWord = (n: number) => `${formatInt(n)} BioProject${n === 1 ? '' : 's'}`

  let count: ReactNode = null
  if (tags.length > 0) {
    count = loading && !data ? (
      <Skeleton.Input active size="large" />
    ) : current?.error ? (
      <Alert type="error" showIcon title={current.error} />
    ) : data ? (
      <span className={stale ? 'opacity-50' : ''}>
        <span className="text-3xl font-semibold">{projectsWord(data.projects)}</span>
        <Text type="secondary" className="ml-2">
          {' '}
          {data.projects === 1 ? 'has' : 'have'}{' '}
          {tags.length === 1 ? 'this tag' : anyOf ? 'at least one of these tags' : 'all these tags'}
        </Text>
      </span>
    ) : null
  }

  return (
    <Card id={WORKBENCH_ID} className="scroll-mt-4">
      <Title level={3} className="!mt-0 !mb-1">
        Find projects by tags
      </Title>
      <Text type="secondary" className="mb-3 block">
        Choose one or more tags. The count updates at once, the lists below show what else the matching projects are
        about, and every tag on this page can be added with a click. Then open the same projects on the search page, with
        all its filters, or copy the query for the API.
      </Text>
      <TagSelect value={tags} onChange={(next) => onChange(next.slice(0, MAX_TAGS), any)} />
      {tags.length >= MAX_TAGS && (
        <Text type="secondary" className="mt-1 block text-xs">
          At most {MAX_TAGS} tags can be combined; remove one to add another.
        </Text>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        <span className="text-gray-500">Try:</span>
        {EXAMPLES.map((ex) => (
          <ExampleChip key={ex.join('+')} tags={ex} onClick={() => onChange(ex, false)} />
        ))}
      </div>

      {tags.length === 0 ? (
        <div className="mt-4 rounded-lg bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
          Pick a tag above, click any tag on this page, or try one of the examples.
          {overview && (
            <>
              {' '}
              A tag search looks through the {formatInt(overview.totals.tagged)} BioProjects that have tags.
            </>
          )}
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1">{count}</div>
            {tags.length > 1 && (
              <Segmented
                size="small"
                value={any ? 'any' : 'all'}
                onChange={(v) => onChange(tags, v === 'any')}
                options={[
                  { value: 'all', label: 'All of the tags' },
                  { value: 'any', label: 'Any of the tags' },
                ]}
              />
            )}
            <Link to={searchUrl(tags, any)}>
              <Button type="primary" icon={<SearchOutlined />}>
                {data ? `Show ${projectsWord(data.projects)} in Search` : 'Show in Search'}
              </Button>
            </Link>
          </div>
          <Text type="secondary" className="mt-3 mb-1 block text-xs">
            The same query in the public API (one request per 5 seconds):
          </Text>
          <CodeBlock code={`GET ${apiUrl}`} language="http" />

          {data && (
            <div className={`grid grid-cols-1 gap-4 lg:grid-cols-3 ${stale ? 'opacity-50' : ''}`}>
              <ChartCard
                title="Tags found with these"
                csvName="related_tags"
                table={relatedTable}
                caption={
                  <>
                    The tags most often on the matching projects (the chosen tags left out). <b>Most characteristic</b> ranks
                    them by lift: how much more often a tag occurs among these projects than among all tagged projects, for
                    tags on at least {MIN_LIFT_COUNT} of them. Click a tag to add it.
                  </>
                }
                controls={
                  <>
                    <Segmented
                      size="small"
                      value={rank}
                      onChange={(v) => setRank(v as 'count' | 'lift')}
                      disabled={!tagged}
                      options={[
                        { value: 'count', label: 'Most common' },
                        { value: 'lift', label: 'Most characteristic' },
                      ]}
                    />
                    <Checkbox checked={hideOrganisms} onChange={(e) => setHideOrganisms(e.target.checked)}>
                      Hide organism names
                    </Checkbox>
                  </>
                }
              >
                {relatedItems.length === 0 ? (
                  <Text type="secondary" className="text-xs">
                    {data.related.length === 0 ? 'No other tags on these projects.' : 'Nothing to show with these settings.'}
                  </Text>
                ) : (
                  <BarList
                    format={rank === 'lift' ? (n) => `${formatRatio(n)}×` : formatInt}
                    items={relatedItems.map((t) => ({
                      label: t.value,
                      value: rank === 'lift' ? t.lift! : t.count,
                      onClick: () => addTags([t.value]),
                      detail: (
                        <div className="tabular-nums">
                          <div>
                            {formatInt(t.count)} of {formatInt(data.projects)} matching projects ({formatPct(100 * t.share)})
                          </div>
                          {t.lift !== null && <div>{formatRatio(t.lift)}× more often than among all tagged projects</div>}
                          {t.group && <div className="text-gray-500">{t.group}</div>}
                          <div className="mt-1 text-gray-500">Click to add this tag</div>
                        </div>
                      ),
                    }))}
                  />
                )}
              </ChartCard>
              <ChartCard
                title="Organisms of these projects"
                csvName="related_organisms"
                table={organismsTable}
                caption={
                  <>
                    The projects' organism, as recorded in BioProject: known for {formatInt(data.organism_known)} of{' '}
                    {formatInt(data.projects)}. Click one to open the projects of that organism in Search.
                  </>
                }
              >
                {data.organisms.length === 0 ? (
                  <Text type="secondary" className="text-xs">
                    None recorded.
                  </Text>
                ) : (
                  <BarList
                    format={formatInt}
                    items={data.organisms.map((o) => ({
                      label: o.value,
                      value: o.count,
                      to: searchUrl(tags, any, { organism: o.value }),
                      detail: (
                        <div className="tabular-nums">
                          {formatInt(o.count)} BioProjects ({formatPct((100 * o.count) / Math.max(data.organism_known, 1))} of
                          those with an organism)
                          <div className="mt-1 text-gray-500">Click the name to search</div>
                        </div>
                      ),
                    }))}
                  />
                )}
              </ChartCard>
              <ChartCard
                title="Released per year"
                csvName="related_years"
                table={yearsTable}
                caption={
                  <>
                    Matching BioProjects by the release of their first data. Older projects are only partly tagged yet, so
                    this follows the tagging more than the research: see Coverage by release year below.
                  </>
                }
              >
                {data.years.length === 0 ? (
                  <Text type="secondary" className="text-xs">
                    No release dates.
                  </Text>
                ) : (
                  <ColumnChart
                    data={fillYears(data.years)}
                    format={formatInt}
                    unit="BioProjects"
                    height={220}
                    partial={data.years.some((y) => y.year === THIS_YEAR) ? { x: THIS_YEAR, note: 'Year in progress' } : undefined}
                  />
                )}
              </ChartCard>
            </div>
          )}

          {data && preview?.key === key && preview.items && preview.items.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <Text strong>
                  {preview.items.length < (preview.total ?? 0)
                    ? `The ${formatInt(preview.items.length)} most recently released of ${formatInt(preview.total ?? 0)} matching projects`
                    : 'The matching projects'}
                </Text>
                <Link to={searchUrl(tags, any)}>All results, with filters, in Search</Link>
              </div>
              <Table<SearchHit>
                size="small"
                pagination={false}
                rowKey={(p) => `${p.bioproject}/${p.sra_study}`}
                dataSource={preview.items}
                scroll={{ x: 700 }}
                columns={[
                  {
                    title: 'BioProject',
                    dataIndex: 'bioproject',
                    width: 140,
                    render: (v: string) => <ExternalLink href={`${ENA}/${v}`}>{v}</ExternalLink>,
                  },
                  {
                    title: 'Title',
                    dataIndex: 'title',
                    render: (v: string | null, p) => (
                      <div className="min-w-0">
                        <Typography.Paragraph ellipsis={{ rows: 2, tooltip: v || p.name }} className="!mb-0">
                          {v || p.name || <Text type="secondary">Untitled</Text>}
                        </Typography.Paragraph>
                        <TagList tags={p.tags} organism={p.organism_name} selected={tags} onSelect={(t) => addTags([t])} />
                      </div>
                    ),
                  },
                  { title: 'Organism', dataIndex: 'organism_name', width: 180, ellipsis: true },
                  { title: 'Released', dataIndex: 'release_date', width: 110 },
                ]}
              />
            </div>
          )}
        </>
      )}
    </Card>
  )
}
