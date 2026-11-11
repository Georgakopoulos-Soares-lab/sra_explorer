import { DeleteOutlined, EditOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Input,
  Modal,
  Popconfirm,
  Select,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api'
import { adminApi, type Job, type NormalizeField, type Rule, type ValueCount } from '../api/admin'
import AdminGate from '../components/AdminGate'

const { Title, Text, Paragraph } = Typography

const PAGE_SIZE = 50

const errorMessage = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e))

// Picks or types the new value; suggests existing values of the field, so
// merging into an existing spelling is a click away. Enter only picks a
// suggestion; the rename starts with the dialog's button, never from the
// keyboard, so it always uses the value shown.
function ValueInput({ api, field, value, onChange }: {
  api: ReturnType<typeof adminApi>
  field: string
  value: string
  onChange: (v: string) => void
}) {
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  const timer = useRef<number>(undefined)
  // Only the latest request's answer is shown, whatever order they arrive in.
  const latest = useRef(0)
  const search = (q: string) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      const request = ++latest.current
      api
        .values(field, q, 10, 0)
        .then((list) => {
          if (request !== latest.current) return
          setOptions(list.items.map((v) => ({ value: v.value, label: `${v.value}  (${v.count.toLocaleString()})` })))
        })
        .catch(() => request === latest.current && setOptions([]))
    }, 200)
  }
  return (
    <AutoComplete
      className="w-full"
      value={value}
      options={options}
      placeholder="New value"
      onChange={onChange}
      onSearch={search}
      onFocus={() => search(value)}
    />
  )
}

function Normalizer({ code }: { code: string }) {
  const api = useRef(adminApi(code)).current
  const [fields, setFields] = useState<NormalizeField[]>([])
  const [field, setField] = useState<string>()
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [values, setValues] = useState<{ total: number; items: ValueCount[] }>({ total: 0, items: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()
  const [selected, setSelected] = useState<string[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  const [job, setJob] = useState<Job>()
  // Rename dialog: the values being changed and the new value.
  const [dialog, setDialog] = useState<{ from: string[]; to: string }>()
  // Bumped when a job ends, to reload the values and rules it changed.
  const [reloadToken, setReloadToken] = useState(0)

  const current = fields.find((f) => f.name === field)

  useEffect(() => {
    api
      .fields()
      .then((list) => {
        setFields(list)
        setField(list[0]?.name)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [api])

  const loadValues = useCallback(() => {
    if (!field) return
    const controller = new AbortController()
    setLoading(true)
    api
      .values(field, query, PAGE_SIZE, (page - 1) * PAGE_SIZE, controller.signal)
      .then((list) => {
        setValues(list)
        setError(undefined)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e))
      })
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [api, field, query, page, reloadToken]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(loadValues, [loadValues])

  const loadRules = useCallback(() => {
    if (!field) return
    api.rules(field).then(setRules).catch((e) => setError(errorMessage(e)))
  }, [api, field, reloadToken]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(loadRules, [loadRules])

  // While a job is queued or running, ask about it every 1.5 s; when it ends,
  // reload the values and rules it changed. If the API no longer lists the job
  // (it restarted), stop and say so rather than waiting forever.
  const jobId = job && (job.status === 'queued' || job.status === 'running') ? job.id : undefined
  useEffect(() => {
    if (!jobId) return
    let active = true
    const timer = window.setInterval(() => {
      api
        .jobs()
        .then((jobs) => {
          if (!active) return
          const latest = jobs.find((j) => j.id === jobId)
          if (!latest) {
            setJob((j) =>
              j && j.id === jobId
                ? { ...j, status: 'failed', message: 'The API no longer knows this job (it may have restarted). Check the values and rules below; re-run the rename if it is missing.' }
                : j,
            )
            setReloadToken((t) => t + 1)
            return
          }
          setJob(latest)
          if (latest.status === 'done' || latest.status === 'failed') setReloadToken((t) => t + 1)
        })
        .catch(() => {})
    }, 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [jobId, api])

  const busy = job?.status === 'queued' || job?.status === 'running'

  // The values actually renamed: merging into one of the selected values
  // leaves that one as it is and changes the others.
  const renaming = dialog ? dialog.from.filter((v) => v !== dialog.to.trim()) : []
  const canRename = !!dialog && dialog.to.trim() !== '' && renaming.length > 0

  const startRename = async () => {
    if (!dialog || !field || !canRename) return
    try {
      const started = await api.rename(field, renaming, dialog.to.trim())
      setJob(started)
      setDialog(undefined)
      setSelected([])
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const startCapitalize = async () => {
    if (!field) return
    try {
      setJob(await api.capitalize(field))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const startApply = async () => {
    try {
      setJob(await api.apply())
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const columns: TableColumnsType<ValueCount> = [
    { title: 'Value', dataIndex: 'value', render: (v: string) => <span className="font-mono text-sm">{v}</span> },
    {
      title: current ? current.counts[0].toUpperCase() + current.counts.slice(1) : 'Count',
      dataIndex: 'count',
      width: 120,
      align: 'right',
      render: (n: number) => n.toLocaleString(),
    },
    {
      title: '',
      key: 'actions',
      width: 110,
      render: (_, row) => (
        <Button size="small" icon={<EditOutlined />} disabled={busy} onClick={() => setDialog({ from: [row.value], to: row.value })}>
          Rename
        </Button>
      ),
    },
  ]

  const jobText = (j: Job) => {
    const fieldLabel = fields.find((f) => f.name === j.field)?.label ?? j.field
    const what =
      j.kind === 'apply'
        ? 'Re-applying all rules'
        : j.kind === 'capitalize'
          ? `Capitalising the first letter of every ${fieldLabel} value`
          : `Changing ${j.from_values.map((v) => `“${v}”`).join(', ')} to “${j.to_value}”`
    if (j.status === 'done') {
      const refreshed = j.refreshed.length ? `; refreshed ${j.refreshed.join(', ')}` : ''
      const rowName = fields.find((f) => f.name === j.field)?.rows ?? 'rows'
      return `${what}: done. ${j.rows.toLocaleString()} ${rowName} changed${refreshed}. ${j.message}`
    }
    if (j.status === 'failed') return `${what}: failed. ${j.message}`
    return `${what}… (${j.status}). Large changes take minutes: an assay type touches millions of runs, and views are refreshed afterwards.`
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <Title level={3} className="!mb-1">
        Normalise filter values
      </Title>
      <Paragraph type="secondary">
        Rename a value and it changes at once in every row of the database. Each rename is kept as a rule, and
        after the weekly data load the rules are applied again (
        <Text code>python -m app.normalize apply</Text>, or the button below), so the normalisation done here is
        never lost. Values are listed by exact spelling; the search ignores case.
      </Paragraph>

      {error && <Alert type="error" showIcon closable className="mb-4" title={error} onClose={() => setError(undefined)} />}
      {job && (
        <Alert
          className="mb-4"
          showIcon
          type={job.status === 'done' ? 'success' : job.status === 'failed' ? 'error' : 'info'}
          icon={busy ? <Spin size="small" /> : undefined}
          title={jobText(job)}
          closable={!busy}
          onClose={() => setJob(undefined)}
        />
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          className="w-56"
          value={field}
          options={fields.map((f) => ({ value: f.name, label: f.label }))}
          onChange={(next) => {
            setField(next)
            setPage(1)
            setQuery('')
            setSelected([])
          }}
        />
        <Input
          className="w-72"
          allowClear
          prefix={<SearchOutlined className="text-gray-400" />}
          placeholder="Find values containing…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setPage(1)
          }}
        />
        <Text type="secondary" className="text-sm">
          {values.total.toLocaleString()} distinct values
        </Text>
        <span className="flex-1" />
        <Popconfirm
          title={`Capitalise every ${current?.label ?? ''} value?`}
          description={
            <span className="block max-w-xs">
              Makes the first letter of every value upper case (“liver” becomes “Liver”); the rest of each value is kept.
              Kept as a rule, so values from future data loads are capitalised too.
            </span>
          }
          onConfirm={startCapitalize}
          okText="Capitalise"
        >
          <Button disabled={busy || !field}>Capitalise first letters</Button>
        </Popconfirm>
        <Popconfirm
          title="Apply all rules again?"
          description="Needed after loading new data. Every recorded rename for every field is applied, then the views are refreshed."
          onConfirm={startApply}
          okText="Apply"
        >
          <Button icon={<ReloadOutlined />} disabled={busy}>
            Re-apply all rules
          </Button>
        </Popconfirm>
      </div>

      {selected.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded border border-blue-200 bg-blue-50 px-3 py-2">
          <Text>{selected.length} selected:</Text>
          {selected.map((v) => (
            <Tag
              key={v}
              closable
              className="!m-0 font-mono"
              onClose={(e) => {
                e.preventDefault()
                setSelected((s) => s.filter((x) => x !== v))
              }}
            >
              {v}
            </Tag>
          ))}
          <Button type="primary" size="small" disabled={busy} onClick={() => setDialog({ from: selected, to: '' })}>
            Merge into one value…
          </Button>
          <Button size="small" onClick={() => setSelected([])}>
            Clear selection
          </Button>
        </div>
      )}

      <Table<ValueCount>
        size="small"
        rowKey="value"
        columns={columns}
        dataSource={values.items}
        loading={loading}
        rowSelection={{
          selectedRowKeys: selected,
          // Kept across pages and searches, so values found separately can be merged.
          preserveSelectedRowKeys: true,
          onChange: (keys) => setSelected(keys as string[]),
        }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: values.total,
          showSizeChanger: false,
          onChange: setPage,
          showTotal: (total, [from, to]) => `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`,
        }}
      />

      <Card size="small" className="mt-6" title={`Rules for ${current?.label ?? '…'} (${rules.length})`}>
        {rules.length === 0 ? (
          <Text type="secondary">No renames recorded for this field yet.</Text>
        ) : (
          <Table<Rule>
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={rules}
            columns={[
              {
                title: 'From',
                dataIndex: 'from_value',
                render: (v: string, rule) =>
                  rule.action === 'capitalize' ? <Text type="secondary">every value</Text> : <span className="font-mono text-sm">{v}</span>,
              },
              {
                title: 'To',
                dataIndex: 'to_value',
                render: (v: string, rule) =>
                  rule.action === 'capitalize' ? <Text type="secondary">first letter capitalised</Text> : <span className="font-mono text-sm">{v}</span>,
              },
              {
                title: 'Rows changed',
                dataIndex: 'rows',
                width: 130,
                align: 'right',
                render: (n: number | null) => n?.toLocaleString() ?? '–',
              },
              {
                title: 'When',
                dataIndex: 'created_at',
                width: 170,
                render: (d: string | null) => (d ? new Date(d).toLocaleString() : '–'),
              },
              {
                title: '',
                key: 'delete',
                width: 60,
                render: (_, rule) => (
                  <Popconfirm
                    title="Forget this rule?"
                    description="It won't be applied after the next data load. Rows already changed stay as they are; rename them back if needed."
                    onConfirm={() => api.deleteRule(rule.id).then(loadRules).catch((e) => setError(errorMessage(e)))}
                  >
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={busy} />
                  </Popconfirm>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Modal
        title={dialog && dialog.from.length > 1 ? `Merge ${dialog.from.length} values` : 'Rename value'}
        open={!!dialog}
        okText={dialog && dialog.from.length > 1 ? 'Merge' : 'Rename'}
        okButtonProps={{ disabled: !canRename || busy }}
        onOk={startRename}
        onCancel={() => setDialog(undefined)}
        destroyOnHidden
      >
        {dialog && field && (
          <div className="flex flex-col gap-3">
            <div>
              <div className="mb-1 text-sm text-gray-500">{dialog.from.length > 1 ? 'Values to merge' : 'Value'}</div>
              <div className="flex flex-wrap gap-1">
                {dialog.from.map((v) => (
                  <Tag key={v} className="!m-0 font-mono">
                    {v}
                  </Tag>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-sm text-gray-500">New value</div>
              <ValueInput api={api} field={field} value={dialog.to} onChange={(to) => setDialog({ ...dialog, to })} />
            </div>
            <Text type="secondary" className="text-xs">
              {dialog.to.trim() && dialog.from.includes(dialog.to.trim()) && renaming.length > 0 && (
                <>“{dialog.to.trim()}” is already spelled this way and stays; the other {renaming.length} change to it. </>
              )}
              Changes every row of <b>{current?.label}</b> with {renaming.length > 1 ? 'these values' : 'this value'} now, and is
              kept as a rule for future data loads.
            </Text>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default function NormalizePage() {
  return <AdminGate what="data normalisation">{(code) => <Normalizer code={code} />}</AdminGate>
}
