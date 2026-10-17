import { ArrowLeftOutlined, CopyOutlined, DownloadOutlined, DownOutlined } from '@ant-design/icons'
import { Alert, App, Button, Descriptions, Dropdown, Input, Select, Skeleton, Table, Tag, Tooltip, Typography } from 'antd'
import type { MenuProps, TableColumnsType } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, type Bioproject } from '../api'
import ExternalLink from '../components/ExternalLink'
import { countRuns, enaRunUrl, fetchRuns, formatBases, formatBytes, fullReportUrl, type EnaRun } from '../ena/api'

// Runs loaded on first view. ENA can't page through a study, so larger studies
// load more only when asked, up to a size the browser handles comfortably.
const INITIAL_RUNS = 5000
const MAX_RUNS_IN_PAGE = 50000

const KIND_TAGS = {
  submitted: { label: 'Submitted files', hint: 'ENA has no processed FASTQ for this run. These are the files as submitted.' },
  sra: { label: 'SRA format', hint: 'Only the SRA-format file is available for this run.' },
}

const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

function saveText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function FilesCell({ run }: { run: EnaRun }) {
  if (run.files.length === 0) return <Tag>No public files</Tag>
  const tag = run.kind && run.kind !== 'fastq' ? KIND_TAGS[run.kind] : null
  return (
    <div className="flex flex-col gap-1">
      {tag && (
        <Tooltip title={tag.hint}>
          <Tag color="orange" className="self-start">{tag.label}</Tag>
        </Tooltip>
      )}
      {run.files.map((f) => (
        <div key={f.url} className="flex flex-wrap items-center gap-x-2">
          <ExternalLink href={f.url}>
            <span className="text-xs">{f.name}</span>
          </ExternalLink>
          <span className="text-xs text-gray-500">{formatBytes(f.bytes)}</span>
          {f.md5 && (
            <Typography.Text
              className="text-xs"
              copyable={{ text: f.md5, tooltips: [`Copy MD5 (${f.md5})`, 'Copied'] }}
            />
          )}
        </div>
      ))}
    </div>
  )
}

const secondary = (text: string, rows = 1) =>
  text ? (
    <Typography.Paragraph type="secondary" ellipsis={{ rows, tooltip: text }} className="!mb-0 text-xs">
      {text}
    </Typography.Paragraph>
  ) : null

const columns: TableColumnsType<EnaRun> = [
  {
    title: 'Run',
    dataIndex: 'run_accession',
    width: 145,
    render: (v: string, r) => (
      <div className="flex flex-col">
        <ExternalLink href={enaRunUrl(v)}>{v}</ExternalLink>
        {r.run_alias !== v && secondary(r.run_alias)}
      </div>
    ),
  },
  {
    title: 'Experiment',
    dataIndex: 'experiment_accession',
    render: (v: string, r) => (
      <div className="flex min-w-0 flex-col">
        {v && <ExternalLink href={enaRunUrl(v)}>{v}</ExternalLink>}
        {secondary(r.experiment_title, 2)}
      </div>
    ),
  },
  {
    title: 'Sample',
    dataIndex: 'sample_accession',
    width: 180,
    render: (v: string, r) => (
      <div className="flex flex-col">
        {v && <ExternalLink href={enaRunUrl(v)}>{v}</ExternalLink>}
        {r.sample_title && (
          <Typography.Paragraph ellipsis={{ rows: 2, tooltip: r.sample_title }} className="!mb-0 text-xs">
            {r.sample_title}
          </Typography.Paragraph>
        )}
        {r.sample_alias !== v && r.sample_alias !== r.sample_title && secondary(r.sample_alias)}
      </div>
    ),
  },
  {
    title: 'Library name',
    dataIndex: 'library_name',
    width: 190,
    render: (v: string) =>
      v ? <span className="break-all text-xs font-medium">{v}</span> : <span className="text-gray-400">—</span>,
  },
  {
    title: 'Library',
    key: 'library',
    width: 210,
    render: (_, r) => (
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap gap-y-1">
          {r.library_strategy && <Tag color="blue">{r.library_strategy}</Tag>}
          {r.library_source && <Tag color="purple">{r.library_source}</Tag>}
          {r.library_selection && <Tag>{r.library_selection}</Tag>}
          {r.library_layout && <Tag color="cyan">{r.library_layout}</Tag>}
        </div>
        {r.instrument_model && <span className="text-xs text-gray-500">{r.instrument_model}</span>}
      </div>
    ),
  },
  {
    title: 'Reads',
    dataIndex: 'read_count',
    width: 120,
    align: 'right',
    sorter: (a, b) => (a.read_count ?? -1) - (b.read_count ?? -1),
    render: (v: number | null, r) => (
      <div className="flex flex-col">
        <span>{v?.toLocaleString()}</span>
        {r.base_count !== null && (
          <span className="text-xs text-gray-500">{formatBases(r.base_count)}</span>
        )}
      </div>
    ),
  },
  // Pinned to the right so the download links stay visible when the table scrolls sideways.
  { title: 'Files', key: 'files', width: 300, fixed: 'right', render: (_, r) => <FilesCell run={r} /> },
]

// Everything ENA returned for a run, shown when its row is expanded.
function RunDetails({ run: r }: { run: EnaRun }) {
  const items = [
    {
      label: 'Study',
      value: r.secondary_study_accession && (
        <span>
          <ExternalLink href={enaRunUrl(r.secondary_study_accession)}>{r.secondary_study_accession}</ExternalLink>
          {r.study_title && <span className="ml-2">{r.study_title}</span>}
        </span>
      ),
    },
    { label: 'Experiment title', value: r.experiment_title },
    {
      label: 'Submission',
      value: r.submission_accession && (
        <ExternalLink href={enaRunUrl(r.submission_accession)}>{r.submission_accession}</ExternalLink>
      ),
    },
    { label: 'Sample title', value: r.sample_title },
    { label: 'Run alias', value: r.run_alias },
    { label: 'Library name', value: r.library_name },
    {
      label: 'Library',
      value: [r.library_strategy, r.library_source, r.library_selection, r.library_layout].filter(Boolean).join(' · '),
    },
    { label: 'Instrument', value: r.instrument_model },
    { label: 'Bases', value: r.base_count?.toLocaleString() },
  ].filter((i) => i.value)

  return (
    <Descriptions
      size="small"
      column={{ xs: 1, lg: 2 }}
      items={items.map((i) => ({ key: i.label, label: i.label, children: i.value }))}
    />
  )
}

// Runs can be narrowed by these library fields, from a toolbar above the table.
const RUN_FILTERS = [
  { key: 'library_strategy', label: 'Strategy' },
  { key: 'library_source', label: 'Source' },
  { key: 'library_selection', label: 'Selection' },
  { key: 'library_layout', label: 'Layout' },
  { key: 'instrument_model', label: 'Instrument' },
] as const

type RunFilterKey = (typeof RUN_FILTERS)[number]['key']

// Distinct values of a field in the loaded runs, most common first.
function valueCounts(runs: EnaRun[], key: RunFilterKey) {
  const counts = new Map<string, number>()
  for (const r of runs) if (r[key]) counts.set(r[key], (counts.get(r[key]) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1])
}

export default function FilesPage() {
  const { study = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [project, setProject] = useState<Bioproject | null>(null)
  const [count, setCount] = useState<number | null>(null)
  const [limit, setLimit] = useState(INITIAL_RUNS)
  const [filter, setFilter] = useState('')
  const [runFilters, setRunFilters] = useState<Partial<Record<RunFilterKey, string[]>>>({})

  // The latest file report, tagged with the request it answers.
  const requestKey = `${study}:${limit}`
  const [report, setReport] = useState<{ key: string; runs?: EnaRun[]; error?: string }>()
  const loading = report?.key !== requestKey

  // Project title and accessions come from our own API.
  useEffect(() => {
    const controller = new AbortController()
    api
      .listBioprojects({ sra_study: study, limit: 1 }, controller.signal)
      .then((rows) => setProject(rows[0] ?? null))
      .catch(() => {})
    return () => controller.abort()
  }, [study])

  // Everything about runs and files comes from ENA, called from the browser.
  useEffect(() => {
    let active = true
    countRuns(study)
      .then((n) => active && setCount(n))
      .catch(() => {})
    return () => {
      active = false
    }
  }, [study])

  useEffect(() => {
    const controller = new AbortController()
    const key = `${study}:${limit}`
    fetchRuns(study, limit, controller.signal)
      .then((runs) => setReport({ key, runs }))
      .catch((err: Error) => {
        if (!controller.signal.aborted) setReport({ key, error: err.message })
      })
    return () => controller.abort()
  }, [study, limit])

  const runs = useMemo(() => report?.runs ?? [], [report])
  // The text box and the library filters together decide which runs are
  // shown, and which files the copy and download actions cover.
  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const active = RUN_FILTERS.filter((f) => runFilters[f.key]?.length)
    return runs.filter(
      (r) =>
        active.every((f) => runFilters[f.key]!.includes(r[f.key])) &&
        (!needle ||
          [
            r.run_accession,
            r.run_alias,
            r.experiment_accession,
            r.experiment_title,
            r.sample_accession,
            r.sample_alias,
            r.sample_title,
            r.library_name,
          ].some((v) => v.toLowerCase().includes(needle))),
    )
  }, [runs, filter, runFilters])

  const filterOptions = useMemo(
    () => Object.fromEntries(RUN_FILTERS.map((f) => [f.key, valueCounts(runs, f.key)])),
    [runs],
  )

  const files = filtered.flatMap((r) => r.files)
  const totalBytes = files.reduce((sum, f) => sum + (f.bytes ?? 0), 0)
  const partial = count !== null && runs.length > 0 && runs.length < count
  const urls = () => files.map((f) => f.url).join('\n') + '\n'

  const downloadItems: MenuProps['items'] = [
    {
      key: 'txt',
      label: 'Link list (.txt)',
      onClick: () => saveText(`${study}_links.txt`, urls()),
    },
    {
      key: 'wget',
      label: 'wget script (.sh)',
      onClick: () =>
        saveText(
          `${study}_download.sh`,
          `#!/bin/sh\n# ${files.length} files from ENA for ${study}\n` +
            files.map((f) => `wget -c "${f.url}"`).join('\n') +
            '\n',
        ),
    },
    {
      key: 'md5',
      label: 'MD5 checksums (.md5)',
      disabled: !files.some((f) => f.md5),
      onClick: () =>
        saveText(
          `${study}.md5`,
          files.filter((f) => f.md5).map((f) => `${f.md5}  ${f.name}`).join('\n') + '\n',
        ),
    },
    { type: 'divider' },
    {
      key: 'tsv',
      label: (
        <a href={fullReportUrl(study)} target="_blank" rel="noreferrer">
          Full file report from ENA (.tsv, all runs)
        </a>
      ),
    },
  ]

  const copyLinks = () =>
    navigator.clipboard
      .writeText(urls())
      .then(() => message.success(`Copied ${files.length.toLocaleString()} links`))
      .catch(() => message.error("Couldn't copy to the clipboard"))

  const goBack = () => (window.history.state?.idx > 0 ? navigate(-1) : navigate('/search'))

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6">
      <Button type="link" icon={<ArrowLeftOutlined />} className="!px-0" onClick={goBack}>
        Back to search
      </Button>

      <div className="mb-4 mt-2">
        <Typography.Title level={3} className="!mb-1">
          {project?.title || project?.name || runs[0]?.study_title || `Sequencing files for ${study}`}
        </Typography.Title>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600">
          {project && <ExternalLink href={enaRunUrl(project.bioproject)}>{project.bioproject}</ExternalLink>}
          <ExternalLink href={enaRunUrl(study)}>{study}</ExternalLink>
          {project?.organism_name && <span>{project.organism_name}</span>}
        </div>
      </div>

      {report?.error && !loading && (
        <Alert className="mb-4" type="error" showIcon title={`Couldn't load files from ENA: ${report.error}`} />
      )}

      {partial && (
        <Alert
          className="mb-4"
          type="info"
          showIcon
          title={`Showing the first ${runs.length.toLocaleString()} of ${count!.toLocaleString()} runs.`}
          description={
            count! <= MAX_RUNS_IN_PAGE
              ? 'Load the rest here, or download the full file report from ENA.'
              : 'This study is too large to show in full here. Download the full file report from ENA to get every link.'
          }
          action={
            <div className="flex flex-col gap-2">
              {count! <= MAX_RUNS_IN_PAGE && (
                <Button size="small" loading={loading} onClick={() => setLimit(count!)}>
                  Load all {count!.toLocaleString()} runs
                </Button>
              )}
              <Button size="small" href={fullReportUrl(study)} target="_blank">
                Full file report (.tsv)
              </Button>
            </div>
          }
        />
      )}

      {runs.length > 0 && (
        <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {RUN_FILTERS.map((f) => (
            <Select
              key={f.key}
              mode="multiple"
              allowClear
              maxTagCount="responsive"
              placeholder={`${f.label}: any`}
              value={runFilters[f.key] ?? []}
              onChange={(values: string[]) => setRunFilters((prev) => ({ ...prev, [f.key]: values }))}
              options={filterOptions[f.key].map(([value, n]) => ({
                value,
                label: (
                  <span className="flex justify-between gap-2">
                    <span className="truncate">{value}</span>
                    <span className="text-gray-400">{n.toLocaleString()}</span>
                  </span>
                ),
              }))}
              // Search by the value, since the label is JSX.
              showSearch={{ optionFilterProp: 'value' }}
              disabled={filterOptions[f.key].length < 2 && !runFilters[f.key]?.length}
            />
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input.Search
          allowClear
          className="max-w-xs"
          placeholder="Search runs, samples, experiments"
          onChange={(e) => setFilter(e.target.value)}
        />
        <span className="text-sm text-gray-600">
          {loading && !runs.length
            ? 'Loading runs from ENA…'
            : `${plural(filtered.length, 'run')} · ${plural(files.length, 'file')} · ${formatBytes(totalBytes)}`}
        </span>
        <div className="ml-auto flex gap-2">
          <Tooltip
            title={partial ? 'Covers the runs loaded on this page. Use the full file report for every run.' : undefined}
          >
            <Button icon={<CopyOutlined />} disabled={!files.length} onClick={copyLinks}>
              Copy links
            </Button>
          </Tooltip>
          <Dropdown menu={{ items: downloadItems }} disabled={!files.length && !partial}>
            <Button icon={<DownloadOutlined />}>
              Download <DownOutlined />
            </Button>
          </Dropdown>
        </div>
      </div>

      {loading && !runs.length ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : (
        <Table<EnaRun>
          rowKey="run_accession"
          columns={columns}
          dataSource={filtered}
          loading={loading}
          size="small"
          scroll={{ x: 1350 }}
          locale={{ emptyText: runs.length ? 'No runs match these filters' : 'ENA has no runs for this study' }}
          expandable={{ expandedRowRender: (r) => <RunDetails run={r} />, expandRowByClick: true }}
          pagination={{
            defaultPageSize: 25,
            pageSizeOptions: [25, 50, 100, 500],
            showSizeChanger: true,
            showTotal: (total, [from, to]) =>
              `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()} runs`,
          }}
        />
      )}

      <Typography.Paragraph type="secondary" className="mt-4 text-xs">
        File links and run details come straight from the European Nucleotide Archive (ENA), requested by
        your browser. Downloads go directly from ENA to you.
      </Typography.Paragraph>
    </div>
  )
}
