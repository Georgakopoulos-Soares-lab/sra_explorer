import { CloudDownloadOutlined, ExportOutlined, FileTextOutlined, FilterOutlined, ReadOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Badge, Button, Descriptions, Drawer, Grid, Input, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType, TableProps } from 'antd'
import { useEffect, useState } from 'react'
import { api, type Bioproject, type ResolvedPublication, type SearchHit, type SearchResults } from '../api'
import ExternalLink from '../components/ExternalLink'
import { countRuns } from '../ena/api'
import ActiveFilters from '../search/ActiveFilters'
import DetailSection from '../search/DetailSection'
import FilterPanel from '../search/FilterPanel'
import Publications from '../search/Publications'
import ResultsSummary from '../search/ResultsSummary'
import SearchExamples from '../search/SearchExamples'
import SearchModes from '../search/SearchModes'
import SearchProgress from '../search/SearchProgress'
import SimilarProjects from '../search/SimilarProjects'
import TagBar from '../search/TagBar'
import TagList from '../search/TagList'
import { projectPublications } from '../search/parsePublications'
import { type SortKey } from '../search/filters'
import { parseReference } from '../search/reference'
import {
  applyUpdate,
  filtersKey,
  PAGE_SIZES,
  useSearchState,
  type ParamUpdate,
} from '../search/useSearchState'

const NCBI = 'https://www.ncbi.nlm.nih.gov'
const ENA = 'https://www.ebi.ac.uk/ena/browser/view'
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

  // Filter changes apply at once. The text box keeps a draft that only runs
  // when Search is clicked; it resets whenever the applied search changes from
  // outside, e.g. with the back button.
  const appliedKey = filtersKey(applied) + appliedQuery
  const [queryDraft, setQueryDraft] = useState(appliedQuery)
  const [draftFor, setDraftFor] = useState(appliedKey)
  if (draftFor !== appliedKey) {
    setDraftFor(appliedKey)
    setQueryDraft(appliedQuery)
  }
  const queryDirty = queryDraft.trim() !== appliedQuery

  const [drawerOpen, setDrawerOpen] = useState(false)
  // The results summary stays open from one search to the next once opened.
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])

  // Until the user searches (text, accessions or filters), the page shows no
  // results and sends no request.
  const noSearch = Object.keys(applied).length === 0 && !state.accessions && !state.semanticQuery
  const hasFilters = Object.keys(applied).length > 0

  // The latest response, tagged with the request it answers, so a stale
  // response never shows as current.
  const requestKey = noSearch ? '' : JSON.stringify(apiParams)
  const [response, setResponse] = useState<{ key: string; error?: string }>()
  const [results, setResults] = useState<SearchResults | null>(null)
  const loading = !noSearch && response?.key !== requestKey
  const error = loading ? null : (response?.error ?? null)
  const canSummarise = !noSearch && !error && (loading || (results?.total ?? 0) > 0)

  // A DOI or PubMed ID is searched as the paper's title and abstract (the
  // backend resolves it); the page looks the paper up too, to show its title.
  const reference = state.semanticQuery ? parseReference(state.semanticQuery) : null
  const [publication, setPublication] = useState<{ key: string; pub?: ResolvedPublication }>()
  useEffect(() => {
    const key = state.semanticQuery
    if (!key || !parseReference(key)) return
    const controller = new AbortController()
    api
      .resolvePublication(key, controller.signal)
      .then((pub) => setPublication({ key, pub }))
      .catch(() => {
        if (!controller.signal.aborted) setPublication({ key }) // the search's own error is shown
      })
    return () => controller.abort()
  }, [state.semanticQuery])
  const resolved = reference && publication?.key === state.semanticQuery ? publication.pub : undefined
  const resolveFailed = !!reference && publication?.key === state.semanticQuery && !publication.pub

  useEffect(() => {
    const key = requestKey
    if (!key) return
    const controller = new AbortController()
    api
      .searchBioprojects(JSON.parse(key), controller.signal)
      .then((data) => {
        setResults(data)
        setResponse({ key })
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setResponse({ key, error: err.message })
      })
    return () => controller.abort()
  }, [requestKey])

  // The step-by-step progress shows only for searches the user starts with
  // the Search button (or Enter) or an example, not for filter, sort or page
  // changes. A click records the search it was made from; the next new
  // search is the one it started, and the progress follows that search only.
  const [progress, setProgress] = useState<{ from: string; key?: string }>()
  if (progress && !progress.key && requestKey !== progress.from) setProgress({ ...progress, key: requestKey })
  const showProgress = loading && !!progress?.key && progress.key === requestKey
  // Called before a search the user started; nothing happens when it would
  // run the search already shown.
  const startWithProgress = (filters: typeof applied, query: string) => {
    if (filtersKey(filters) + query.trim() !== appliedKey) setProgress({ from: requestKey })
  }

  // The text box's Search: runs the typed text with the current filters.
  const runSearch = (query = queryDraft) => {
    startWithProgress(applied, query)
    setQueryDraft(query)
    state.apply(applied, query)
  }

  // Any filter change (sidebar, chip, tag) applies at once and keeps the
  // text search that is already running (the text box may hold unapplied text).
  const applyNow = (update: ParamUpdate, query = appliedQuery) => {
    const next = applyUpdate(applied, update)
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

  const sortable = (key: SortKey) => ({
    key,
    sorter: true,
    sortOrder:
      state.sort === `${key}_asc`
        ? ('ascend' as const)
        : state.sort === `${key}_desc`
          ? ('descend' as const)
          : null,
    sortDirections: ['descend' as const, 'ascend' as const],
  })

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
    ? <div className="h-24" />
    : error
      ? 'Search failed'
      : state.accessions
        ? `No project in the database has the accession ${state.accessions.join(', ')}`
        : state.semanticQuery
          ? `No projects are similar enough to “${state.semanticQuery}”${hasFilters ? ' and match these filters' : ''}. Try describing the data differently.`
          : 'No projects match these filters'

  const activeFilters = (stacked: boolean) => (
    <ActiveFilters
      values={applied}
      accessions={state.accessions ?? []}
      stacked={stacked}
      onChange={applyNow}
      onRemoveAccession={(acc) => {
        const rest = state.accessions!.filter((a) => a !== acc).join(' ')
        setQueryDraft(rest)
        state.update({ q: rest || null })
      }}
      onClear={clearFilters}
    />
  )

  const panel = <FilterPanel values={applied} onChange={applyNow} />

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
            {/* Hidden while no filter is applied (ActiveFilters renders nothing). */}
            <div className="border-b border-gray-100 p-3 empty:hidden">{activeFilters(true)}</div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2">{panel}</div>
          </div>
        </aside>
      )}

      <main className="min-w-0 flex-1">
        <SearchModes text={queryDraft} />
        <div className="mb-1 flex items-center gap-2">
          {/* Two lines, growing with the text: whole abstracts are welcome.
              Enter searches; Shift+Enter starts a new line. */}
          <Input.TextArea
            size="large"
            allowClear
            autoSize={{ minRows: 2, maxRows: 8 }}
            placeholder="Describe the data, or enter accessions (e.g. PRJNA169753, SRP079428) or a paper's DOI or PubMed ID"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
            onPressEnter={(e) => {
              if (e.shiftKey) return
              e.preventDefault()
              runSearch()
            }}
          />
          <Badge dot={queryDirty} offset={[-4, 4]}>
            <Button
              type="primary"
              size="large"
              icon={<SearchOutlined />}
              loading={loading}
              onClick={() => runSearch()}
            >
              Search
            </Button>
          </Badge>
        </div>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-gray-500">
          <span>
            Describe the data, or enter BioProject or SRA study accessions (e.g. PRJNA787491, SRP079428), or a
            paper's DOI or PubMed ID to search with its title and abstract.
          </span>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2 pl-6">
          {!isDesktop && (
            <Badge count={Object.keys(applied).length} size="small">
              <Button icon={<FilterOutlined />} onClick={() => setDrawerOpen(true)}>
                Filters
              </Button>
            </Badge>
          )}
          <span className="text-sm text-gray-600">
            {noSearch
              ? null
              : state.semanticQuery
                ? (
                    <>
                      Search query:{' '}
                      <span className="rounded border border-solid border-sky-200 bg-sky-50 px-2 py-0.5 text-sky-800">
                        {resolved?.title || state.semanticQuery}
                      </span>
                      {resolved && (
                        <span className="ml-2 text-xs text-gray-500">
                          the title and abstract of{' '}
                          <a href={resolved.url} target="_blank" rel="noreferrer">
                            {resolved.pmid ? `PubMed ${resolved.pmid}` : `DOI ${resolved.doi}`} <ExportOutlined />
                          </a>
                        </span>
                      )}
                    </>
                  )
                : results
                  ? `${results.total.toLocaleString()} project${results.total === 1 ? '' : 's'}`
                  : ' '}
          </span>
        </div>

        {/* The table only dims while loading; the steps of the search show
            here, near the search box, so they're in view however long the
            table is. A new component per search restarts them. */}
        {showProgress && (
          <SearchProgress
            key={requestKey}
            semanticQuery={state.semanticQuery}
            accessions={state.accessions}
            filters={applied}
            sort={state.sort}
            page={state.page}
            pageSize={state.pageSize}
            reference={reference}
            resolved={resolved}
            resolveFailed={resolveFailed}
          />
        )}

        {!isDesktop && activeFilters(false)}

        <TagBar
          selected={appliedTags}
          matchAny={applied.tag_any === 'true'}
          params={apiParams}
          suggest={!noSearch && !error && (results?.total ?? 0) > 0}
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

        {noSearch && <SearchExamples
            onRun={(ex) => {
              startWithProgress(applyUpdate(applied, ex.filters ?? {}), ex.query)
              applyNow(ex.filters ?? {}, ex.query)
            }}
          />}

        {!noSearch && (
          <Table<SearchHit>
            rowKey={rowKey}
            rowClassName={(p) => (expandedKeys.includes(rowKey(p)) ? EXPANDED_ROW : '')}
            columns={columns}
            dataSource={error ? [] : (results?.items ?? [])}
            loading={{ spinning: loading, indicator: <span /> }}
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
        )}
      </main>

      {!isDesktop && (
        <Drawer
          title="Filters"
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        >
          {panel}
        </Drawer>
      )}
    </div>
  )
}
