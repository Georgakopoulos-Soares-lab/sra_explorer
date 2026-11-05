import { Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useEffect, useState } from 'react'
import ExternalLink from '../components/ExternalLink'
import { pubmedSummaries, type PubmedSummary } from '../ncbi/pubmed'
import type { Publication } from './parsePublications'

// Rows shown before the table scrolls; most projects have one to three.
const VISIBLE_ROWS = 4

type Row = Publication & { key: number; pending: boolean }

const LOADING = (
  <Typography.Text type="secondary" italic className="!text-xs">
    Loading from PubMed…
  </Typography.Text>
)

const columns: TableColumnsType<Row> = [
  {
    title: 'Title',
    dataIndex: 'title',
    render: (title: string | null, row) =>
      !title && row.pending ? LOADING : (
        <Typography.Text ellipsis={{ tooltip: title }} className="!text-xs">
          {title ?? '—'}
        </Typography.Text>
      ),
  },
  {
    title: 'Citation',
    dataIndex: 'citation',
    width: '30%',
    render: (citation: string | null, row) =>
      !citation && row.pending ? LOADING : (
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

// PMIDs of publications missing a title or citation, which PubMed can fill in.
const incomplete = (items: Publication[]) =>
  items.filter((p) => p.pmid && (!p.title || !p.citation)).map((p) => p.pmid!)

// A small, muted table, so publications don't compete with the description.
// Titles and citations missing from our data are fetched from PubMed by the
// browser when the table shows, only for those publications (see ncbi/pubmed.ts).
// Only blanks are filled; values from our data are kept.
export default function Publications({ items }: { items: Publication[] }) {
  const pmids = incomplete(items)
  const key = pmids.join(',')
  const [lookup, setLookup] = useState<{ key: string; summaries: Map<string, PubmedSummary | null> }>()

  useEffect(() => {
    if (!key) return
    let active = true
    pubmedSummaries(key.split(','))
      .then((summaries) => active && setLookup({ key, summaries }))
      .catch(() => active && setLookup({ key, summaries: new Map() })) // leave the blanks
    return () => {
      active = false
    }
  }, [key])

  const done = lookup?.key === key
  const rows: Row[] = items.map((pub, i) => {
    const found = pub.pmid && done ? lookup.summaries.get(pub.pmid) : null
    return {
      ...pub,
      key: i,
      title: pub.title ?? found?.title ?? null,
      citation: pub.citation ?? found?.citation ?? null,
      doi: pub.doi ?? found?.doi ?? null,
      pmc: pub.pmc ?? found?.pmc ?? null,
      pending: Boolean(key) && !done && pmids.includes(pub.pmid ?? ''),
    }
  })

  // Shown inside an expanded result row, where antd indents nested tables by
  // the expand column and pulls them past the right edge; !m-0 undoes that so
  // the table fits its Publications box.
  return (
    <Table
      size="small"
      className="text-xs [&_.ant-table]:!m-0 [&_.ant-table-cell]:!py-1 [&_.ant-table-cell]:!text-xs"
      columns={columns}
      dataSource={rows}
      pagination={false}
      tableLayout="fixed"
      scroll={items.length > VISIBLE_ROWS ? { y: VISIBLE_ROWS * 30 } : undefined}
    />
  )
}
