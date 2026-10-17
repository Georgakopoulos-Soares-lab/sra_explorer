import { CloudDownloadOutlined, ExportOutlined, FilterOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Badge, Button, Descriptions, Drawer, Grid, Input, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType, TableProps } from 'antd'
import { useEffect, useState } from 'react'
import { api, type Bioproject, type SearchResults } from '../api'
import ExternalLink from '../components/ExternalLink'
import { countRuns } from '../ena/api'
import ActiveFilters from '../search/ActiveFilters'
import FilterPanel from '../search/FilterPanel'
import { DEFAULT_SORT, type SortKey } from '../search/filters'
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
const splitList = (value: string | null) => (value ? value.split('; ').filter(Boolean) : [])

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
  const items = [
    { label: 'Organization', value: [p.organization, p.organization_country].filter(Boolean).join(', ') },
    { label: 'Relevance', value: p.relevance },
    { label: 'Objectives', value: p.objectives },
    { label: 'Target', value: [p.target_material, p.target_capture, p.sample_scope].filter(Boolean).join(' · ') },
    { label: 'Access', value: p.access },
    { label: 'Submitted', value: p.submitted_date },
    { label: 'Last updated', value: p.last_update_date },
    { label: 'GEO', value: p.geo_accessions },
    { label: 'Journals', value: p.journals },
  ].filter((i) => i.value)

  return (
    <div className="flex flex-col gap-3 py-1">
      {p.description && (
        <Typography.Paragraph className="!mb-0 whitespace-pre-line">{p.description}</Typography.Paragraph>
      )}
      {items.length > 0 && (
        <Descriptions
          size="small"
          column={{ xs: 1, md: 2, xl: 3 }}
          items={items.map((i) => ({ key: i.label, label: i.label, children: i.value }))}
        />
      )}
      <FilesSummary study={p.sra_study} />
    </div>
  )
}

export default function SearchPage() {
  const state = useSearchState()
  const { apiParams, values: applied, query: appliedQuery } = state
  const isDesktop = Grid.useBreakpoint().lg ?? true

  // Filter edits go into a draft and only reach the URL (and the backend) when
  // Search is clicked. The draft resets whenever the applied search changes
  // from outside, e.g. with the back button.
  const appliedKey = filtersKey(applied) + appliedQuery
  const [draft, setDraft] = useState<FilterValues>(applied)
  const [queryDraft, setQueryDraft] = useState(appliedQuery)
  const [draftFor, setDraftFor] = useState(appliedKey)
  if (draftFor !== appliedKey) {
    setDraftFor(appliedKey)
    setDraft(applied)
    setQueryDraft(appliedQuery)
  }
  const dirty = filtersKey(draft) + queryDraft.trim() !== appliedKey

  const [drawerOpen, setDrawerOpen] = useState(false)

  // With no filters applied, the page shows the latest projects instead of
  // searching the whole table, and pages and sorts nothing on the server.
  const showLatest = Object.keys(applied).length === 0

  // The latest response, tagged with the request it answers, so a stale
  // response never shows as current.
  const requestKey = showLatest ? 'latest' : JSON.stringify(apiParams)
  const [response, setResponse] = useState<{ key: string; error?: string }>()
  const [results, setResults] = useState<SearchResults | null>(null)
  const loading = response?.key !== requestKey
  const error = loading ? null : (response?.error ?? null)

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

  const runSearch = () => {
    state.apply(draft, queryDraft)
    setDrawerOpen(false)
  }

  const reset = () => {
    setDraft({})
    setQueryDraft('')
    state.clearFilters()
  }

  // Removing a chip applies at once, and keeps any other unapplied edits.
  const removeApplied = (update: ParamUpdate) => {
    const next = applyUpdate(applied, update)
    setDraft((d) => applyUpdate(d, update))
    setDraftFor(filtersKey(next) + appliedQuery)
    state.apply(next, appliedQuery)
  }

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

  const columns: TableColumnsType<Bioproject> = [
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
          <Typography.Text ellipsis={{ tooltip: v }} className="block">
            {v || p.name || <Typography.Text type="secondary">Untitled</Typography.Text>}
          </Typography.Text>
          <div className="mt-1 flex flex-wrap gap-y-1">
            {splitList(p.data_types).map((t) => (
              <Tag key={t} color="blue" className="!text-xs">{t}</Tag>
            ))}
          </div>
        </div>
      ),
    },
    { title: 'Organism', dataIndex: 'organism_name', width: 180, ellipsis: true, ...sortable('organism') },
    {
      title: 'Experiments',
      dataIndex: 'n_experiments',
      width: 125,
      align: 'right',
      ...sortable('experiments'),
      render: (v: number | null) => v?.toLocaleString(),
    },
    { title: 'Publications', dataIndex: 'publication_count', width: 130, align: 'right', ...sortable('publications') },
    { title: 'Released', dataIndex: 'project_release_date', width: 120, ...sortable('release') },
  ]

  const onTableChange: TableProps<Bioproject>['onChange'] = (_pagination, _filters, sorter, extra) => {
    if (extra.action !== 'sort' || Array.isArray(sorter)) return
    state.setSort(
      sorter.order ? `${String(sorter.columnKey)}_${sorter.order === 'ascend' ? 'asc' : 'desc'}` : DEFAULT_SORT,
    )
  }

  // Nothing is shown under the spinner until the first response arrives.
  const emptyText = loading
    ? ' '
    : error
      ? 'Search failed'
      : !showLatest
        ? 'No projects match these filters'
        : 'The database has no projects yet. Load data with the scripts in Automations/ (see docs/running.md).'

  const panelFooter = (
    <div className="flex flex-col gap-2">
      {dirty && (
        <Typography.Text type="warning" className="text-xs">
          You have changes that aren't applied yet. Click Search to apply them.
        </Typography.Text>
      )}
      <div className="flex gap-2">
        <Button type="primary" icon={<SearchOutlined />} onClick={runSearch} block>
          Search
        </Button>
        <Button onClick={reset}>Reset</Button>
      </div>
    </div>
  )

  const panel = <FilterPanel values={draft} onChange={(u) => setDraft((d) => applyUpdate(d, u))} />

  return (
    <div className="mx-auto flex max-w-[1600px] gap-6 px-4 py-6">
      {isDesktop && (
        <aside className="w-80 shrink-0">
          <div className="sticky top-4 flex max-h-[calc(100vh-2rem)] flex-col rounded-lg bg-white">
            <div className="px-4 pb-1 pt-3 font-semibold">Filters</div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2">{panel}</div>
            <div className="border-t border-gray-100 p-3">{panelFooter}</div>
          </div>
        </aside>
      )}

      <main className="min-w-0 flex-1">
        <div className="mb-1 flex gap-2">
          <Input
            size="large"
            allowClear
            prefix={<SearchOutlined className="text-gray-400" />}
            placeholder="Describe the data you're looking for, e.g. single-cell RNA-seq of human liver"
            value={queryDraft}
            onChange={(e) => setQueryDraft(e.target.value)}
            onPressEnter={runSearch}
          />
          <Badge dot={dirty} offset={[-4, 4]}>
            <Button type="primary" size="large" onClick={runSearch}>
              Search
            </Button>
          </Badge>
        </div>
        <div className="mb-4 flex items-center gap-2 text-xs text-gray-500">
          <Tag color="gold" className="!m-0">Coming soon</Tag>
          Semantic search isn't connected yet. Results use the filters only.
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
                ? `${results.total.toLocaleString()} projects`
                : ' '}
          </span>
        </div>

        <ActiveFilters values={applied} onChange={removeApplied} onClear={reset} />

        {error && <Alert className="mb-4" type="error" showIcon title={error} />}

        <Table<Bioproject>
          rowKey={(p) => `${p.bioproject}:${p.sra_study}`}
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
