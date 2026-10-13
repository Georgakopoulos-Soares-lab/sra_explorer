import { Alert, Input, Layout, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useEffect, useState } from 'react'
import { api, type Bioproject } from './api'

const PAGE_SIZE = 50

const columns: TableColumnsType<Bioproject> = [
  { title: 'BioProject', dataIndex: 'bioproject', width: 140 },
  { title: 'SRA study', dataIndex: 'sra_study', width: 120 },
  { title: 'Title', dataIndex: 'title', ellipsis: true },
  { title: 'Organism', dataIndex: 'organism_name', width: 220, ellipsis: true },
  { title: 'Experiments', dataIndex: 'n_experiments', width: 120, align: 'right' },
  { title: 'Released', dataIndex: 'project_release_date', width: 120 },
]

function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [rows, setRows] = useState<Bioproject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [organism, setOrganism] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const controller = new AbortController()
    api
      .health(controller.signal)
      .then(() => setHealthy(true))
      .catch(() => {
        if (!controller.signal.aborted) setHealthy(false)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    api
      .listBioprojects(
        { organism_name: organism, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE },
        controller.signal,
      )
      .then((data) => {
        setRows(data)
        setError(null)
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [organism, page])

  const goTo = (nextOrganism: string, nextPage: number) => {
    if (nextOrganism === organism && nextPage === page) return
    setLoading(true)
    setOrganism(nextOrganism)
    setPage(nextPage)
  }

  return (
    <Layout className="min-h-screen">
      <Layout.Header className="flex items-center justify-between">
        <Typography.Title level={4} className="!m-0 !text-white">
          SRA Explorer
        </Typography.Title>
        {healthy === null ? (
          <Tag>Checking API…</Tag>
        ) : healthy ? (
          <Tag color="success">API connected</Tag>
        ) : (
          <Tag color="error">API unreachable</Tag>
        )}
      </Layout.Header>

      <Layout.Content className="p-6">
        <div className="mb-4 max-w-md">
          <Input.Search
            placeholder="Filter by organism name"
            allowClear
            onSearch={(value) => goTo(value.trim(), 1)}
          />
        </div>

        {error && <Alert className="mb-4" type="error" showIcon message={error} />}

        <Table<Bioproject>
          rowKey={(row) => `${row.bioproject}:${row.sra_study}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          size="middle"
          // The backend has no total count, so allow paging forward while a full page comes back.
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: (page - 1) * PAGE_SIZE + rows.length + (rows.length === PAGE_SIZE ? 1 : 0),
            showSizeChanger: false,
            onChange: (nextPage) => goTo(organism, nextPage),
          }}
        />
      </Layout.Content>
    </Layout>
  )
}

export default App
