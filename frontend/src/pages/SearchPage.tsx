import { CloudDownloadOutlined, ExportOutlined, FileTextOutlined, FilterOutlined, ReadOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Badge, Button, Descriptions, Drawer, Grid, Input, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType, TableProps } from 'antd'
import { useEffect, useState } from 'react'
import { api, type Bioproject, type SearchHit, type SearchResults } from '../api'
import ExternalLink from '../components/ExternalLink'
import { countRuns } from '../ena/api'
import ActiveFilters from '../search/ActiveFilters'
import DetailSection from '../search/DetailSection'
import FilterPanel from '../search/FilterPanel'
import Publications from '../search/Publications'
import ResultsSummary from '../search/ResultsSummary'
import SimilarProjects from '../search/SimilarProjects'
import TagBar from '../search/TagBar'
import TagList from '../search/TagList'
import { projectPublications } from '../search/parsePublications'
import { RELEVANCE_SORT, type SortKey } from '../search/filters'
import {
  applyUpdate,
  filtersKey,
  PAGE_SIZES,
  useSearchState,
  type FilterValues,
  type ParamUpdate,
} from '../search/useSearchState'

const NCBI = 'https://www.ncbi.nlm.nih.gov'
const ENA = 'https://www.ebi.ac.uk/ena/browser/view'
const LATEST_COUNT = 100
// Shown under the search box; clicking it runs this search.
const EXAMPLE_QUERY = 'RNA-seq of breast cancer tumors treated with tamoxifen'
const splitList = (value: string | null) => (value ? value.split('; ').filter(Boolean) : [])
// Publications tag: darker green for more publications, in three steps
// (antd's green palette; text keeps enough contrast on each background).
const publicationShade = (n: number) =>
  n >= 3
    ? '!border-[#237804] !bg-[#237804] !text-white' // 3+: green-8, white text
    : n === 2
      ? '!border-[#73d13d] !bg-[#95de64] !text-[#135200]' // 2: green-4, green-9 text
      : '!border-[#95de64] !bg-[#d9f7be] !text-[#389e0d]' // 1: green-2, green-7 text
const rowKey = (p: SearchHit) => `${p.bioproject}:${p.sra_study}`
// Small muted label above a field of an expanded result (Title, Description).
const FIELD_LABEL = 'mb-0.5 text-xs font-medium uppercase tracking-wide text-gray-400'
// An expanded project and its details share a tint and a blue bar on the left,
// and a border under the details marks where the next project starts.
const EXPANDED_ROW = '[&>td]:!bg-blue-50 [&>td:first-child]:shadow-[inset_3px_0_0_#1677ff]'
const EXPANDED_DETAILS =
  '[&>td]:!bg-blue-50/40 [&>td]:shadow-[inset_3px_0_0_#1677ff] [&>td]:!border-b-2 [&>td]:!border-b-blue-200'

// Asks ENA (from the browser) how many runs the study has, and links to the
// files page. The files themselves are never listed here: a study can have
// thousands of runs.
function FilesSummary({ study }: { study: string }) {
  const [result, setResult] = useState<{ count?: number; error?: string }>()

  useEffect(() => {
    let active = true
    countRuns(study)
      .then((count) => active && setResult({ count }))
      .catch((err: Error) => active && setResult({ error: err.message }))
    return () => {
      active = false
    }
  }, [study])

  const text = !result
    ? 'Checking ENA for runs…'
    : result.error
      ? `Couldn't reach ENA: ${result.error}`
      : result.count === 0
        ? 'ENA has no runs for this study yet.'
        : `${result.count!.toLocaleString()} run${result.count === 1 ? '' : 's'} in ENA, with FASTQ download links.`

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-gray-200 bg-white px-3 py-2">
      <CloudDownloadOutlined className="text-lg text-blue-600" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">Sequencing files</div>
        <Typography.Text type={result?.error ? 'danger' : 'secondary'} className="text-sm">
          {!result && <Spin size="small" className="mr-2" />}
          {text}
        </Typography.Text>
      </div>
      <Button
        type="primary"
        disabled={!result?.count}
        href={`/files/${encodeURIComponent(study)}`}
        target="_blank"
        rel="noreferrer"
        icon={<ExportOutlined />}
        iconPlacement="end"
      >
        View files
      </Button>
    </div>
  )
}

function ProjectDetails({ project: p }: { project: Bioproject }) {
  const publications = projectPublications(p)
  const items = [
    {
      label: 'Organization',
      value: p.organization && (
        <span>
          {p.organization}
          <Typography.Text type="secondary">
            {' · '}
            {p.organization_country ?? 'country not given'}
          </Typography.Text>
        </span>
      ),
    },
    {
      label: 'GEO',
      value: p.geo_accessions && (
        <span className="inline-flex flex-wrap gap-x-3">
          {splitList(p.geo_accessions).map((gse) => (
            <ExternalLink key={gse} href={`${NCBI}/geo/query/acc.cgi?acc=${encodeURIComponent(gse)}`}>
              {gse}
            </ExternalLink>
          ))}
        </span>
      ),
    },
  ].filter((i) => i.value)

  // Three blocks, then the files: the project itself, its publications, and
  // similar projects.
  return (
    <div className="flex flex-col gap-3 py-1">
      <DetailSection icon={<FileTextOutlined />} title="Project">
        <div className={FIELD_LABEL}>Title</div>
        <Typography.Title level={5} className="!mb-3 !mt-0">
          {p.title || p.name || <Typography.Text type="secondary">Untitled</Typography.Text>}
        </Typography.Title>
        {p.description && (
          <>
            <div className={FIELD_LABEL}>Description</div>
            <Typography.Paragraph className="!mb-2 whitespace-pre-line">{p.description}</Typography.Paragraph>
          </>
        )}
        {items.length > 0 && (
          <Descriptions
            size="small"
            className="border-t border-gray-100 pt-2"
            column={{ xs: 1, md: 2, xl: 3 }}
            items={items.map((i) => ({ key: i.label, label: i.label, children: i.value }))}
          />
        )}
      </DetailSection>
      {publications.length > 0 && (
        <DetailSection icon={<ReadOutlined />} title={`Publications (${publications.length})`}>
          <Publications items={publications} />
        </DetailSection>
      )}
      <SimilarProjects bioproject={p.bioproject} />
      <FilesSummary study={p.sra_study} />
    </div>
  )
}

export default function SearchPage() {
  const state = useSearchState()
  const { apiParams, values: applied, query: appliedQuery } = state
  const isDesktop = Grid.useBreakpoint().lg ?? true

  // Filter edits go into a draft and only reach the URL (and the backend) when
  // Search or Apply filters is clicked. The draft resets whenever the applied
  // search changes from outside, e.g. with the back button.
  const appliedKey = filtersKey(applied) + appliedQuery
  const [draft, setDraft] = useState<FilterValues>(applied)
  const [queryDraft, setQueryDraft] = useState(appliedQuery)
  const [draftFor, setDraftFor] = useState(appliedKey)
  if (draftFor !== appliedKey) {
    setDraftFor(appliedKey)
    setDraft(applied)
    setQueryDraft(appliedQuery)
  }
  // The sidebar's Apply filters button applies the filter draft only; the
  // Search button next to the text box applies both the text and the draft.
  // Each has its own pending flag.
  const filtersDirty = filtersKey(draft) !== filtersKey(applied)
  const queryDirty = queryDraft.trim() !== appliedQuery

  const [drawerOpen, setDrawerOpen] = useState(false)
  // The results summary stays open from one search to the next once opened.
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])

  // With no filters applied, the page shows the latest projects instead of
  // searching the whole table, and pages and sorts nothing on the server.
  const showLatest = Object.keys(applied).length === 0 && !state.accessions && !state.semanticQuery
  const hasFilters = Object.keys(applied).length > 0

  // The latest response, tagged with the request it answers, so a stale
  // response never shows as current.
  const requestKey = showLatest ? 'latest' : JSON.stringify(apiParams)
  const [response, setResponse] = useState<{ key: string; error?: string }>()
  const [results, setResults] = useState<SearchResults | null>(null)
  const loading = response?.key !== requestKey
  const error = loading ? null : (response?.error ?? null)
  // Only real searches with results are summarised, not the latest-projects list.
  const canSummarise = !showLatest && !error && (loading || (results?.total ?? 0) > 0)

  useEffect(() => {
    const controller = new AbortController()
    const key = requestKey
    const request: Promise<SearchResults> =
      key === 'latest'
        ? api.latestBioprojects(LATEST_COUNT, controller.signal).then((items) => ({ total: items.length, items }))
        : api.searchBioprojects(JSON.parse(key), controller.signal)
    request
      .then((data) => {
        setResults(data)
        setResponse({ key })
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setResponse({ key, error: err.message })
      })
    return () => controller.abort()
  }, [requestKey])

  // The text box's Search: runs the typed text and applies any pending
  // filter edits from the sidebar at the same time.
  const runSearch = (query = queryDraft) => {
    setQueryDraft(query)
    state.apply(draft, query)
  }

  // The sidebar's Apply filters: applies the filter draft and keeps the text
  // search that is already running (the text box may hold unapplied text).
  const applyFilters = () => {
    state.apply(draft, appliedQuery)
    setDrawerOpen(false)
  }

  // Reset clears the filters only; a text search stays.
  const reset = () => {
    setDraft({})
    state.apply({}, appliedQuery)
    setDrawerOpen(false)
  }

  // Removing a chip or clicking a tag applies at once, and keeps any other
  // unapplied edits.
  const applyNow = (update: ParamUpdate, query = appliedQuery) => {
    const next = applyUpdate(applied, update)
    setDraft((d) => applyUpdate(d, update))
    if (query !== appliedQuery) setQueryDraft(query)
    setDraftFor(filtersKey(next) + query)
    state.apply(next, query)
  }

  // A value clicked in the results summary is added to that filter's selection.
  const addFilterValue = (filter: string, value: string) => {
    const current = ([] as string[]).concat(applied[filter] ?? [])
    if (!current.includes(value)) applyNow({ [filter]: [...current, value] })
  }

  const appliedTags = (applied.tag as string[] | undefined) ?? []
  const selectTag = (tag: string) => {
    if (!appliedTags.includes(tag)) applyNow({ tag: [...appliedTags, tag] })
  }
  // The Filters row's Clear all: every filter except tags, and accessions typed
  // in the search box (shown in that row); a text search stays.
  const clearFilters = () =>
    applyNow(
      Object.fromEntries(Object.keys(applied).filter((k) => k !== 'tag').map((k) => [k, null])),
      state.accessions ? '' : appliedQuery,
    )

  // The latest list has no server-side sorting, so its columns aren't sortable.
  const sortable = (key: SortKey) =>
    showLatest
      ? { key }
      : {
          key,
          sorter: true,
          sortOrder:
            state.sort === `${key}_asc`
              ? ('ascend' as const)
              : state.sort === `${key}_desc`
                ? ('descend' as const)
                : null,
          sortDirections: ['descend' as const, 'ascend' as const],
        }

  const columns: TableColumnsType<SearchHit> = [
    {
      title: 'BioProject',
      dataIndex: 'bioproject',
      width: 140,
      ...sortable('bioproject'),
      render: (v: string, p) => (
        <div className="flex flex-col">
          <ExternalLink href={`${ENA}/${v}`}>{v}</ExternalLink>
          <span className="text-xs">
            <ExternalLink href={`${NCBI}/sra/?term=${p.sra_study}`}>{p.sra_study}</ExternalLink>
          </span>
        </div>
      ),
    },
    {
      title: 'Title',
      dataIndex: 'title',
      render: (v: string | null, p) => (
        <div className="min-w-0">
          <Typography.Paragraph ellipsis={{ rows: 2, tooltip: v || p.name }} className="!mb-0">
            {v || p.name || <Typography.Text type="secondary">Untitled</Typography.Text>}
          </Typography.Paragraph>
          <TagList tags={p.tags} organism={p.organism_name} selected={appliedTags} onSelect={selectTag} />
        </div>
      ),
    },
    {
      title: 'Organism',
      dataIndex: 'organism_name',
      width: 160,
      ...sortable('organism'),
      render: (v: string | null) => (
        <Typography.Paragraph ellipsis={{ rows: 2, tooltip: v }} className="!mb-0">
          {v}
        </Typography.Paragraph>
      ),
    },
    {
      title: 'Experiments',
      dataIndex: 'n_experiments',
      width: 125,
      align: 'right',
      ...sortable('experiments'),
      render: (v: number | null) => v?.toLocaleString(),
    },
    {
      // The number of publications in a green tag; nothing when there are none.
      title: 'Publications',
      dataIndex: 'publication_count',
      width: 130,
      align: 'center',
      ...sortable('publications'),
      render: (n: number | null) =>
        n ? (
          <Tag
            className={`!m-0 ${publicationShade(n)}`}
            title={`${n.toLocaleString()} publication${n === 1 ? '' : 's'}`}
          >
            {n.toLocaleString()}
          </Tag>
        ) : null,
    },
    {
      title: <span title="When the project's first run became public on SRA">Released</span>,
      dataIndex: 'release_date',
      width: 112,
      ...sortable('release'),
    },
  ]
  const onTableChange: TableProps<SearchHit>['onChange'] = (_pagination, _filters, sorter, extra) => {
    if (extra.action !== 'sort' || Array.isArray(sorter)) return
    state.setSort(
      sorter.order ? `${String(sorter.columnKey)}_${sorter.order === 'ascend' ? 'asc' : 'desc'}` : null,
    )
  }

  // Nothing is shown under the spinner until the first response arrives.
  const emptyText = loading
    ? ' '
    : error
      ? 'Search failed'
      : state.accessions
        ? `No project in the database has the accession ${state.accessions.join(', ')}`
        : state.semanticQuery
          ? `No projects are similar enough to “${state.semanticQuery}”${hasFilters ? ' and match these filters' : ''}. Try describing the data differently.`
          : !showLatest
          ? 'No projects match these filters'
          : 'The database has no projects yet. Load data with the scripts in Automations/ (see docs/running.md).'

  const panelFooter = (
    <div className="flex flex-col gap-2">
      {filtersDirty && (
        <Typography.Text type="warning" className="text-xs">
          Filter changes aren't applied yet. Click Apply filters or Search.
        </Typography.Text>
      )}
      <div className="flex gap-2">
        <Button type="primary" icon={<FilterOutlined />} onClick={applyFilters} block>
          Apply filters
        </Button>
        <Button onClick={reset}>Reset</Button>
      </div>
    </div>
  )

  const panel = <FilterPanel values={draft} onChange={(u) => setDraft((d) => applyUpdate(d, u))} />

  return (
    <div className="mx-auto flex max-w-[1920px] gap-6 px-4 py-6">
      {isDesktop && (
        <aside className="w-72 shrink-0">
          {/* The box is capped so it fits the viewport even at the top of the
              page, where it starts under the 64px header and the page padding
              (about 6.5rem in all); the Search bar sits above the scrolling
              filter list so it is always in view, never below the fold. */}
          <div className="sticky top-4 flex max-h-[calc(100vh-6.5rem)] flex-col rounded-lg bg-white">
            <div className="px-4 pb-1 pt-3 font-semibold">Filters</div>
            <div className="border-b border-gray-100 p-3">{panelFooter}</div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2">{panel}</div>
          </div>
        </aside>
      )}

      <main className="min-w-0 flex-1">
        <div className="mb-1 flex gap-2">
          <Input
            size="large"
            allowClear
            prefix={<SearchOutlined className="text-gray-400" />}
            placeholder="BioProject or SRA study accession (e.g. PRJNA169753, SRP079428), or describe the data"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
            onPressEnter={() => runSearch()}
          />
          <Badge dot={queryDirty} offset={[-4, 4]}>
            <Button type="primary" size="large" onClick={() => runSearch()}>
              Search
            </Button>
          </Badge>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
          <span>
            Enter BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accessions, several separated
            by spaces, or describe the data to find similar projects. Try{' '}
            <button
              type="button"
              className="cursor-pointer border-0 bg-transparent p-0 text-xs text-blue-600 underline-offset-2 hover:underline"
              onClick={() => runSearch(EXAMPLE_QUERY)}
            >
              “{EXAMPLE_QUERY}”
            </button>
            .
          </span>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          {!isDesktop && (
            <Badge count={Object.keys(applied).length} size="small">
              <Button icon={<FilterOutlined />} onClick={() => setDrawerOpen(true)}>
                Filters
              </Button>
            </Badge>
          )}
          <span className="text-sm text-gray-600">
            {showLatest
              ? `Showing the ${LATEST_COUNT} most recently released BioProjects. Choose filters and click Search to search all projects.`
              : results
                ? `${results.total.toLocaleString()} project${results.total === 1 ? '' : 's'}` +
                  (state.semanticQuery
                    ? ` similar to “${state.semanticQuery}”` +
                      (state.sort === RELEVANCE_SORT ? ', most similar first' : '')
                    : '')
                : ' '}
          </span>
        </div>

        <ActiveFilters
          values={applied}
          accessions={state.accessions ?? []}
          onChange={applyNow}
          onRemoveAccession={(acc) => {
            const rest = state.accessions!.filter((a) => a !== acc).join(' ')
            setQueryDraft(rest)
            state.update({ q: rest || null })
          }}
          onClear={clearFilters}
        />

        <TagBar
          selected={appliedTags}
          matchAny={applied.tag_any === 'true'}
          params={apiParams}
          suggest={!showLatest && !error && (results?.total ?? 0) > 0}
          onAdd={selectTag}
          onRemove={(tag) => applyNow({ tag: appliedTags.filter((t) => t !== tag) })}
          onClear={() => applyNow({ tag: null, tag_any: null })}
        />

        {error && <Alert className="mb-4" type="error" showIcon title={error} />}

        {canSummarise && (
          <ResultsSummary
            open={summaryOpen}
            onToggle={() => setSummaryOpen((o) => !o)}
            params={apiParams}
            values={applied}
            onAdd={addFilterValue}
          />
        )}

        <Table<SearchHit>
          rowKey={rowKey}
          rowClassName={(p) => (expandedKeys.includes(rowKey(p)) ? EXPANDED_ROW : '')}
          columns={columns}
          dataSource={error ? [] : (results?.items ?? [])}
          loading={loading}
          size="middle"
          scroll={{ x: 1000 }}
          locale={{ emptyText }}
          onChange={onTableChange}
          expandable={{
            expandedRowRender: (p) => <ProjectDetails project={p} />,
            expandRowByClick: true,
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: (keys) => setExpandedKeys(keys as string[]),
            expandedRowClassName: EXPANDED_DETAILS,
          }}
          pagination={{
            current: state.page,
            pageSize: state.pageSize,
            total: results?.total ?? 0,
            pageSizeOptions: PAGE_SIZES,
            showSizeChanger: true,
            showTotal: (total, [from, to]) =>
              `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`,
            onChange: (page, size) => {
              state.setPage(page, size)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            },
          }}
        />
      </main>

      {!isDesktop && (
        <Drawer
          title="Filters"
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          footer={panelFooter}
        >
          {panel}
        </Drawer>
      )}
    </div>
  )
}
