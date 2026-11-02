import { CloseOutlined, PlusOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useEffect, useState } from 'react'
import { api, type FacetValue, type SearchParams } from '../api'

// The Tags row above the results: the chosen tags (removable), then tags
// common among the top results as suggestions to add. Suggestions load after
// the results, so they never delay them. Hidden when there's nothing to show.
export default function TagBar({ selected, matchAny = false, params, suggest, onAdd, onRemove, onClear }: {
  selected: string[]
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
    <div className="mb-2 flex items-start gap-2 text-xs">
      <span className="w-12 shrink-0 pt-1 text-sm text-gray-500">Tags</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 pt-0.5">
        {selected.length > 1 && (
          <span className="mr-1 text-gray-500" title='Change with "Match any of the tags" in the filter panel'>
            {matchAny ? 'any of' : 'all of'}
          </span>
        )}
        {selected.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded bg-blue-100 py-0.5 pl-2 pr-1 text-blue-700">
            {t}
            <button
              type="button"
              aria-label={`Remove tag ${t}`}
              className="flex cursor-pointer border-0 bg-transparent p-0 text-blue-400 hover:text-blue-700"
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
            className="inline-flex cursor-pointer items-center gap-1 rounded border border-dashed border-gray-300 bg-white px-1.5 py-px text-xs text-gray-600 hover:border-blue-400 hover:text-blue-600"
            onClick={() => onAdd(t.value)}
          >
            <PlusOutlined className="text-[9px]" />
            {t.value}
            <span className="text-gray-400">{t.count.toLocaleString()}</span>
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
