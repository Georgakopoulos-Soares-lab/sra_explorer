import { ClusterOutlined } from '@ant-design/icons'
import { Button, Skeleton, Tooltip, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, type SearchHit } from '../api'
import DetailSection from './DetailSection'

const SHOWN = 5
const MAX = 20

// The projects whose titles and descriptions mean the most similar thing to
// this one's (the same embeddings as the text search). Loaded when a result
// is expanded; each opens as an accession search.
export default function SimilarProjects({ bioproject }: { bioproject: string }) {
  const [state, setState] = useState<{ items?: SearchHit[]; error?: string }>()
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api
      .similarBioprojects(bioproject, MAX, controller.signal)
      .then((items) => setState({ items }))
      .catch((e: Error) => {
        if (!controller.signal.aborted) setState({ error: e.message })
      })
    return () => controller.abort()
  }, [bioproject])

  // Nothing to show for projects without an embedding.
  if (state?.items?.length === 0) return null
  const items = state?.items ?? []
  const shown = expanded ? items : items.slice(0, SHOWN)

  return (
    <DetailSection
      icon={<ClusterOutlined />}
      title={
        <Tooltip title="Projects whose titles and descriptions are closest in meaning to this one, compared with the same language model as the text search. The percentage is the cosine similarity.">
          <span className="cursor-help">
            Similar projects{' '}
            <Typography.Text type="secondary" className="text-xs font-normal">
              by description
            </Typography.Text>
          </span>
        </Tooltip>
      }
    >
      {!state && <Skeleton active title={false} paragraph={{ rows: 3 }} />}
      {state?.error && (
        <Typography.Text type="secondary" className="text-sm">
          Couldn't load similar projects: {state.error}
        </Typography.Text>
      )}
      <ul className="m-0 list-none divide-y divide-gray-100 p-0">
        {shown.map((p) => (
          <li key={p.bioproject} className="flex items-start gap-3 py-2">
            <span
              className="mt-0.5 w-11 shrink-0 rounded bg-blue-50 py-0.5 text-center text-xs font-medium tabular-nums text-blue-700"
              title="Similarity"
            >
              {Math.round((p.similarity ?? 0) * 100)}%
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-sm">{p.title || p.name || <Typography.Text type="secondary">Untitled</Typography.Text>}</div>
              <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-gray-500">
                <Link
                  to={`/search?q=${encodeURIComponent(p.bioproject)}`}
                  onClick={(e) => e.stopPropagation()}
                  className="font-mono"
                >
                  {p.bioproject}
                </Link>
                {p.organism_name && <span>{p.organism_name}</span>}
                {p.release_date && <span>Released {p.release_date.slice(0, 4)}</span>}
                {p.n_experiments != null && <span>{p.n_experiments.toLocaleString()} experiments</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {items.length > SHOWN && (
        <Button
          type="link"
          size="small"
          className="!px-0"
          onClick={(e) => {
            e.stopPropagation()
            setExpanded((x) => !x)
          }}
        >
          {expanded ? 'Show fewer' : `Show ${items.length - SHOWN} more`}
        </Button>
      )}
    </DetailSection>
  )
}
