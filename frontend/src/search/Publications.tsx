import { Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import ExternalLink from '../components/ExternalLink'
import type { Publication } from './parsePublications'

// Rows shown before the table scrolls; most projects have one to three.
const VISIBLE_ROWS = 4

const columns: TableColumnsType<Publication & { key: number }> = [
  {
    title: 'Title',
    dataIndex: 'title',
    render: (title: string | null) => (
      <Typography.Text ellipsis={{ tooltip: title }} className="!text-xs">
        {title ?? '—'}
      </Typography.Text>
    ),
  },
  {
    title: 'Citation',
    dataIndex: 'citation',
    width: '30%',
    render: (citation: string | null) => (
      <Typography.Text type="secondary" ellipsis={{ tooltip: citation }} className="!text-xs">
        {citation ?? '—'}
      </Typography.Text>
    ),
  },
  {
    title: 'Links',
    key: 'links',
    width: 150,
    render: (_, pub) => (
      <span className="flex flex-wrap gap-x-2">
        {pub.pmid && (
          <ExternalLink href={`https://pubmed.ncbi.nlm.nih.gov/${pub.pmid}/`} mono={false}>
            PubMed
          </ExternalLink>
        )}
        {pub.pmc && (
          <ExternalLink href={`https://pmc.ncbi.nlm.nih.gov/articles/${pub.pmc}/`} mono={false}>
            PMC
          </ExternalLink>
        )}
        {pub.doi && (
          <ExternalLink href={`https://doi.org/${pub.doi}`} mono={false}>
            DOI
          </ExternalLink>
        )}
      </span>
    ),
  },
]

// A small, muted table, so publications don't compete with the description.
export default function Publications({ items }: { items: Publication[] }) {
  return (
    <Table
      size="small"
      className="text-xs [&_.ant-table-cell]:!py-1 [&_.ant-table-cell]:!text-xs"
      columns={columns}
      dataSource={items.map((pub, i) => ({ ...pub, key: i }))}
      pagination={false}
      tableLayout="fixed"
      scroll={items.length > VISIBLE_ROWS ? { y: VISIBLE_ROWS * 30 } : undefined}
    />
  )
}
