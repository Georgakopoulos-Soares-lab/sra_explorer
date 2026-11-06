import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { useEffect, useState, type ReactNode } from 'react'
import type { ResolvedPublication } from '../api'
import { ALL_FILTERS, paramKeys, RELEVANCE_SORT } from './filters'
import { referenceLabel, type Reference } from './reference'
import type { FilterValues } from './useSearchState'

// What the search is doing, step by step, while it runs. Nothing extra is
// requested for it: the steps are the ones the backend takes for this kind of
// search (backend/app/search.py), shown in order as time passes. Only the
// paper lookup of a DOI or PubMed ID search follows a real event (the page's
// own /resolve request). The parent mounts it per search and unmounts it
// when the results arrive.

type Status = 'done' | 'active' | 'error'
interface Step {
  text: ReactNode
  detail?: ReactNode
  status: Status
}
// A step of the search proper, shown `at` ms after the search (or the paper
// lookup) started, if the search is still running then.
interface Timed {
  at: number
  text: ReactNode
  detail?: ReactNode
}

// Hidden for searches faster than this, so quick ones don't flash it.
const SHOW_AFTER_MS = 250
const TICK_MS = 100

const SORT_LABELS: Record<string, string> = {
  release: 'release date',
  experiments: 'number of experiments',
  publications: 'number of publications',
  bioproject: 'accession',
  organism: 'organism',
}

const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
const wordCount = (text: string) => text.split(/\s+/).filter(Boolean).length

// The labels of the applied filters, once each (a date range is one filter).
function filterLabels(values: FilterValues): string[] {
  return ALL_FILTERS.filter((def) => def.key !== 'tag_any' && paramKeys(def).some((k) => values[k])).map(
    (def) => def.label,
  )
}

function sortStep(sort: string, page: number, pageSize: number): Pick<Timed, 'text' | 'detail'> {
  const from = (page - 1) * pageSize + 1
  const rows = `results ${from.toLocaleString()}–${(from + pageSize - 1).toLocaleString()}`
  if (sort === RELEVANCE_SORT) return { text: 'Ranking projects by relevance', detail: rows }
  const [key, dir] = sort.split('_')
  return {
    text: `Sorting by ${SORT_LABELS[key] ?? key}, ${dir === 'asc' ? 'ascending' : 'descending'}`,
    detail: rows,
  }
}

function filterStep(labels: string[], at: number): Timed[] {
  if (labels.length === 0) return []
  return [{ at, text: `Keeping projects that match ${plural(labels.length, 'filter')}`, detail: labels.join(', ') }]
}

export default function SearchProgress({
  semanticQuery,
  accessions,
  filters,
  sort,
  page,
  pageSize,
  reference,
  resolved,
  resolveFailed,
}: {
  semanticQuery: string | null
  accessions: string[] | null
  filters: FilterValues
  sort: string
  page: number
  pageSize: number
  // A DOI or PubMed ID search: the paper's lookup, as it goes.
  reference: Reference | null
  resolved?: ResolvedPublication
  resolveFailed?: boolean
}) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const start = performance.now()
    const id = window.setInterval(() => setElapsed(performance.now() - start), TICK_MS)
    return () => window.clearInterval(id)
  }, [])

  // When the paper was found: the search proper starts from there.
  const [resolvedAt, setResolvedAt] = useState<number | null>(null)
  if (resolved && resolvedAt === null) setResolvedAt(elapsed)

  const labels = filterLabels(filters)
  const sorting = sortStep(sort, page, pageSize)
  const fixed: Step[] = [] // known from the start (or from the lookup)
  let timed: Timed[] = []
  let base = 0

  // Search by meaning: embed the text, then the hybrid search in fused_matches.
  const textSteps = (): Timed[] => [
    { at: 0, text: 'Embedding the text with BioBERT', detail: '768-dimensional vector' },
    { at: 700, text: 'Finding the most similar project descriptions', detail: 'cosine similarity, HNSW index' },
    { at: 1400, text: 'Matching the words in project titles and descriptions', detail: 'full-text search' },
    { at: 2100, text: 'Merging the two rankings', detail: 'reciprocal rank fusion' },
    ...filterStep(labels, 2700),
    { at: labels.length ? 3300 : 2700, ...sorting },
  ]

  if (reference) {
    fixed.push({ text: `Recognised ${referenceLabel(reference)}`, status: 'done' })
    if (resolved) {
      const words = wordCount(resolved.abstract)
      fixed.push(
        {
          text: <>Found “{resolved.title}”</>,
          detail: `via ${resolved.source === 'pubmed' ? 'PubMed' : 'Crossref'}`,
          status: 'done',
        },
        {
          text: words ? 'Using its title and abstract as the search text' : 'Using its title as the search text',
          detail: words ? plural(words, 'word') + ' of abstract' : 'no abstract available',
          status: 'done',
        },
      )
      timed = textSteps()
      base = resolvedAt ?? elapsed
    } else if (resolveFailed) {
      fixed.push({ text: 'Could not look up the paper', status: 'error' })
    } else {
      fixed.push({
        text: 'Looking up the paper in PubMed',
        detail: reference.kind === 'doi' ? 'Crossref as fallback' : undefined,
        status: 'active',
      })
    }
  } else if (semanticQuery) {
    fixed.push({ text: 'Reading your description', detail: plural(wordCount(semanticQuery), 'word'), status: 'done' })
    timed = textSteps()
  } else if (accessions) {
    fixed.push({
      text: `Recognised ${plural(accessions.length, 'accession')}`,
      detail: accessions.join(', '),
      status: 'done',
    })
    timed = [
      { at: 0, text: 'Looking up the BioProject and SRA study records' },
      ...filterStep(labels, 500),
      { at: labels.length ? 1000 : 500, ...sorting },
    ]
  } else {
    timed = [
      ...filterStep(labels, 0),
      { at: 600, text: 'Counting the matching projects' },
      { at: 1200, ...sorting },
    ]
  }

  // Timed steps appear one by one; the newest is the one in progress.
  const shown = timed.filter((t) => elapsed - base >= t.at)
  const steps: Step[] = [
    ...fixed,
    ...shown.map((t, i): Step => ({ ...t, status: i === shown.length - 1 ? 'active' : 'done' })),
  ]

  if (elapsed < SHOW_AFTER_MS) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className="search-progress-in mb-3 rounded-lg border border-solid border-gray-200 bg-gray-50 px-4 py-3"
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-gray-500">
        <span className="search-progress-spark text-sm text-brand-sra" aria-hidden>
          ✦
        </span>
        <span>Working on your search</span>
        <span className="ml-auto tabular-nums text-gray-400">{(elapsed / 1000).toFixed(1)}s</span>
      </div>
      <ol className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
        {steps.map((s, i) => (
          <li key={i} className="search-progress-in flex items-start gap-2">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
              {s.status === 'done' ? (
                <CheckOutlined className="text-xs text-gray-400" />
              ) : s.status === 'error' ? (
                <CloseOutlined className="text-xs text-red-500" />
              ) : (
                <span className="search-progress-dot h-2 w-2 rounded-full bg-brand-sra" />
              )}
            </span>
            <span className="min-w-0">
              <span
                className={
                  s.status === 'active'
                    ? 'search-progress-shimmer font-medium'
                    : s.status === 'error'
                      ? 'text-red-600'
                      : 'text-gray-500'
                }
              >
                {s.text}
                {s.status === 'active' && '…'}
              </span>
              {s.detail && <span className="ml-2 text-xs text-gray-400">{s.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
