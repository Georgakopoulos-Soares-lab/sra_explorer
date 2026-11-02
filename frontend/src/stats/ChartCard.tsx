import { DownloadOutlined } from '@ant-design/icons'
import { Button, Card, Segmented, Table, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { downloadFile } from './format'

export interface TableData {
  columns: { key: string; title: string; numeric?: boolean }[]
  rows: Record<string, string | number | null>[]
}

function csvCell(value: string | number | null) {
  if (value === null) return ''
  const s = String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function downloadCsv(name: string, table: TableData) {
  const lines = [
    table.columns.map((c) => csvCell(c.title)).join(','),
    ...table.rows.map((row) => table.columns.map((c) => csvCell(row[c.key] ?? null)).join(',')),
  ]
  downloadFile(`${name}.csv`, lines.join('\n') + '\n', 'text/csv;charset=utf-8')
}

// A chart with its caption, controls, a table view of the same numbers and a
// CSV download of that table.
export default function ChartCard({ title, caption, controls, table, csvName, children }: {
  title: string
  caption: ReactNode
  controls?: ReactNode
  table: TableData
  csvName: string
  children: ReactNode
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <Card
      title={title}
      size="small"
      className="min-w-0"
      extra={
        <span className="flex items-center gap-1">
          <Segmented
            size="small"
            value={view}
            onChange={(v) => setView(v as 'chart' | 'table')}
            options={[
              { value: 'chart', label: 'Chart' },
              { value: 'table', label: 'Table' },
            ]}
          />
          <Button
            size="small"
            type="text"
            icon={<DownloadOutlined />}
            onClick={() => downloadCsv(csvName, table)}
            title="Download the numbers as CSV"
          >
            CSV
          </Button>
        </span>
      }
    >
      <Typography.Paragraph type="secondary" className="!mb-3 text-sm">
        {caption}
      </Typography.Paragraph>
      {controls && <div className="mb-3 flex flex-wrap items-center gap-2">{controls}</div>}
      {view === 'chart' ? (
        children
      ) : (
        <Table
          size="small"
          pagination={false}
          scroll={{ y: 360, x: 'max-content' }}
          rowKey={(_, i) => String(i)}
          dataSource={table.rows}
          columns={table.columns.map((c) => ({
            key: c.key,
            dataIndex: c.key,
            title: c.title,
            align: c.numeric ? 'right' : 'left',
            className: c.numeric ? 'tabular-nums' : undefined,
            render: (v: string | number | null) => (typeof v === 'number' ? v.toLocaleString('en') : (v ?? '–')),
          }))}
        />
      )}
    </Card>
  )
}
