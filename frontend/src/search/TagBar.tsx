import { CloseOutlined, PlusOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useEffect, useState } from 'react'
import { api, type FacetValue, type SearchParams } from '../api'

// The Tags row above the results: the chosen tags (removable), then tags
// common among the top results as suggestions to add. Suggestions load after
// the results, so they never delay them. Hidden when there's nothing to show.
export default function TagBar({ selected, auto = [], matchAny = false, params, suggest, onAdd, onRemove, onClear }: {
  selected: string[]
  // The chosen tags a deep search added from the search text (marked).
  auto?: string[]
  // Whether a project needs only one of the chosen tags ("Match any of the tags").
  matchAny?: boolean
  // The search's parameters, for the suggestions.
  params: SearchParams
  // False while there are no results to suggest from.
  suggest: boolean
  onAdd: (tag: string) => void
  onRemove: (tag: string) => void
  onClear: () => void
}) {
  const key = suggest ? JSON.stringify(params) : ''
  const [summary, setSummary] = useState<{ key: string; tags: FacetValue[] }>()

  useEffect(() => {
    if (!key) return
    const controller = new AbortController()
    api
      .tagSummary(JSON.parse(key), controller.signal)
      .then((tags) => setSummary({ key, tags }))
      .catch(() => {}) // optional extra; the results don't depend on it
    return () => controller.abort()
  }, [key])

  const suggestions = key && summary?.key === key ? summary.tags : []
  if (selected.length === 0 && suggestions.length === 0) return null

  return (
    <div className="mb-2 flex items-start gap-2 pl-6 text-xs">
      <span className="w-12 shrink-0 pt-1 text-sm text-gray-500">Tags</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 pt-0.5">
        {selected.length > 1 && (
          <span className="mr-1 text-gray-500" title='Change with "Match any of the tags" in the filter panel'>
            {matchAny ? 'any of' : 'all of'}
          </span>
        )}
        {/* Active tags are solid blue; the suggestions after them are light and dashed. */}
        {selected.map((t) => (
          <span
            key={t}
            title={auto.includes(t) ? 'Added by Deep search from your text' : 'Active tag: only projects with it are shown'}
            className="inline-flex items-center gap-1 rounded border border-solid border-brand-sra bg-brand-sra py-0.5 pl-2 pr-1 font-medium text-white shadow-sm"
          >
            {auto.includes(t) && <span className="text-[10px]" aria-hidden>✦</span>}
            {t}
            <button
              type="button"
              aria-label={`Remove tag ${t}`}
              className="flex cursor-pointer border-0 bg-transparent p-0 text-blue-200 hover:text-white"
              onClick={() => onRemove(t)}
            >
              <CloseOutlined className="text-[10px]" />
            </button>
          </span>
        ))}
        {selected.length > 0 && suggestions.length > 0 && <span className="mx-1 h-4 w-px bg-gray-300" />}
        {/* {suggestions.length > 0 && (
          <span
            className="mr-1 text-gray-400"
            title="The most common tags among the top 2,000 results that have tags. Click one to narrow the search."
          >
            Suggestedasd
          </span>
        )} */}
        {suggestions.map((t) => (
          <button
            key={t.value}
            type="button"
            title={[t.group, `${t.count.toLocaleString()} of the top results`].filter(Boolean).join(' · ')}
            className="inline-flex cursor-pointer items-center gap-1 rounded border border-dashed border-sky-300 bg-sky-50 px-1.5 py-px text-xs text-sky-800 hover:border-sky-500 hover:bg-sky-100"
            onClick={() => onAdd(t.value)}
          >
            <PlusOutlined className="text-[9px]" />
            {t.value}
            <span className="text-sky-500">{t.count.toLocaleString()}</span>
          </button>
        ))}
      </div>
      {selected.length > 0 && (
        <Button type="link" size="small" className="shrink-0" onClick={onClear}>
          Clear all
        </Button>
      )}
    </div>
  )
}
