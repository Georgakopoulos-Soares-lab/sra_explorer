import { FilterOutlined, ReadOutlined, SearchOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import type { ParamUpdate } from './useSearchState'

// Example searches shown before the first search, one per way of searching.
// Keep them in step with the data: each should return a useful result list.
export interface SearchExample {
  icon: ReactNode
  title: string
  query: string
  filters?: ParamUpdate
  // What the example adds on top of the query, shown under it.
  extra?: string
  text: string
}

export const SEARCH_EXAMPLES: SearchExample[] = [
  {
    icon: <SearchOutlined />,
    title: 'Describe the data',
    query: 'single-cell RNA-seq of human lung tumours',
    text: 'Free text search. Results match by meaning.',
  },
  {
    icon: <ReadOutlined />,
    title: 'Start from a paper',
    // Cancer Res. paper "KLF4 Promotes a KRT13+ Hillock-Like State in Lung Squamous Cell Carcinoma" (PMID 42314152).
    query: '10.1158/0008-5472.CAN-26-0531',
    text: "A DOI or PubMed ID resolves the paper's title and abstract and uses them to search for relevant data.",
  },
  {
    icon: <FilterOutlined />,
    title: 'Combine with filters',
    query: 'tamoxifen resistance in breast cancer',
    filters: { assay_type: 'RNA-Seq', organism: 'Homo sapiens' },
    extra: 'RNA-Seq · Homo sapiens',
    text: 'Add filters to the description.',
  },
]

export default function SearchExamples({ onRun }: { onRun: (example: SearchExample) => void }) {
  return (
    <section className="mx-auto mt-8 max-w-4xl" aria-labelledby="search-examples">
      <h2 id="search-examples" className="mb-2 text-base font-semibold text-gray-800">
        Try example searches:
      </h2>
      <div className="flex flex-col gap-3">
        {SEARCH_EXAMPLES.map((ex) => (
          <button
            key={ex.title}
            type="button"
            onClick={() => onRun(ex)}
            className="group flex cursor-pointer items-center gap-3 rounded-lg border border-solid border-gray-200 bg-white px-3 py-2 text-left transition hover:border-blue-400 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <span className="text-base text-blue-600">{ex.icon}</span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-sm font-semibold text-gray-900">{ex.title}</span>
                <span className="rounded border border-solid border-sky-200 bg-sky-50 px-1.5 text-sm text-sky-800">
                  “{ex.query}”
                </span>
                {ex.extra && <span className="text-xs text-gray-500">+ {ex.extra}</span>}
              </span>
              <span className="block text-xs text-gray-500">{ex.text}</span>
            </span>
            <span className="shrink-0 text-md text-blue-700 group-hover:underline">Run →</span>
          </button>
        ))}
      </div>
    </section>
  )
}
