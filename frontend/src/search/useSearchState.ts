import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { SearchParams } from '../api'
import { DEFAULT_SORT, FILTER_PARAM_KEYS, LIST_KEYS, parseAccessions, RELEVANCE_SORT, SORT_KEYS } from './filters'

export const PAGE_SIZES = [10, 25, 50, 100]
const DEFAULT_PAGE_SIZE = 25

export type FilterValues = SearchParams
// null or [] removes the parameter.
export type ParamUpdate = Record<string, string | string[] | null>

// Returns a copy of `values` with `update` applied, dropping empty entries.
export function applyUpdate(values: FilterValues, update: ParamUpdate): FilterValues {
  const next = { ...values }
  for (const [key, value] of Object.entries(update)) {
    if (value === null || value === '' || (Array.isArray(value) && value.length === 0)) delete next[key]
    else next[key] = value
  }
  return next
}

// Stable string for comparing two sets of filter values.
export const filtersKey = (values: FilterValues) =>
  JSON.stringify(Object.keys(values).sort().map((k) => [k, values[k]]))

const isValidSort = (sort: string | null) =>
  !!sort && SORT_KEYS.some((k) => sort === `${k}_asc` || sort === `${k}_desc`)

// The page URL holds the applied search (filters, text, sort, page), so a
// search can be bookmarked or shared and the back button undoes the last change.
// Two more keys belong to the deep search: guided=0 turns the switch off (it
// is on by default; a page setting, like the sort), and auto= lists the tags the last guided
// search added, so they can be marked, removed together and dropped before
// the next text search; each is also in tag=, where the search reads it.
export function useSearchState() {
  const [params, setParams] = useSearchParams()

  const values = useMemo(() => {
    const out: FilterValues = {}
    for (const key of FILTER_PARAM_KEYS) {
      if (LIST_KEYS.has(key)) {
        const list = params.getAll(key)
        if (list.length) out[key] = list
      } else {
        const value = params.get(key)
        if (value) out[key] = value
      }
    }
    return out
  }, [params])

  const query = params.get('q') ?? ''
  const accessions = useMemo(() => parseAccessions(query), [query])
  // Text that isn't accessions is searched by meaning (semantic search).
  const semanticQuery = !accessions && query.trim() ? query.trim() : null

  const guided = params.get('guided') !== '0'
  // The tags the last deep search added, as long as they are still applied.
  const autoTags = useMemo(() => {
    const tags = params.getAll('tag')
    return params.getAll('auto').filter((t) => tags.includes(t))
  }, [params])

  // Text searches are ordered most similar first unless a column is sorted.
  const sortParam = params.get('sort')
  const sort = isValidSort(sortParam) ? sortParam! : semanticQuery ? RELEVANCE_SORT : DEFAULT_SORT
  const page = Math.max(1, Number(params.get('page')) || 1)
  const sizeParam = Number(params.get('size'))
  const pageSize = PAGE_SIZES.includes(sizeParam) ? sizeParam : DEFAULT_PAGE_SIZE

  const update = (changes: ParamUpdate, { keepPage = false } = {}) => {
    // From the live URL, not the updater's argument: react-router gives the
    // updater the params of the render that created it, which are stale when
    // update is called from a callback made earlier (the deep search).
    setParams(() => {
      const next = new URLSearchParams(window.location.search)
      for (const [key, value] of Object.entries(changes)) {
        next.delete(key)
        for (const item of Array.isArray(value) ? value : [value]) {
          if (item) next.append(key, item)
        }
      }
      // Any change other than paging starts again from page 1.
      if (!keepPage) next.delete('page')
      return next
    })
  }

  // Replaces all applied filters (and the text query) in one step. `auto`
  // is the tags among them that a deep search added (none by default:
  // a new search drops the previous ones).
  const apply = (filters: FilterValues, q: string, auto: string[] = []) =>
    update({
      ...Object.fromEntries(FILTER_PARAM_KEYS.map((k) => [k, filters[k] ?? null])),
      q: q.trim() || null,
      auto: auto.filter((t) => (filters.tag ?? []).includes(t)),
    })

  // What the backend receives. Accessions typed in the search box are sent
  // as a filter; other text is sent as q for semantic search. guided marks
  // a search whose tags were added by the deep search (for the usage page).
  const apiParams = useMemo<SearchParams>(
    () => ({
      ...values,
      ...(accessions ? { accession: accessions } : {}),
      ...(semanticQuery ? { q: semanticQuery } : {}),
      ...(autoTags.length ? { guided: 'true' } : {}),
      sort,
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    }),
    [values, accessions, semanticQuery, autoTags, sort, page, pageSize],
  )

  return {
    values,
    sort,
    page,
    pageSize,
    query,
    accessions,
    semanticQuery,
    apiParams,
    guided,
    autoTags,
    update,
    apply,
    // The switch is a setting: changing it doesn't change the applied search.
    setGuided: (on: boolean) => update({ guided: on ? null : '0' }, { keepPage: true }),
    clearFilters: () =>
      update({ ...Object.fromEntries(FILTER_PARAM_KEYS.map((k) => [k, null])), q: null, sort: null, auto: null }),
    // null goes back to the default order. During a text search the default is
    // relevance, so an explicit release_desc is kept in the URL.
    setSort: (next: string | null) =>
      update({ sort: next && (semanticQuery || next !== DEFAULT_SORT) ? next : null }),
    setPage: (nextPage: number, nextSize: number) =>
      nextSize !== pageSize
        ? update({ size: nextSize === DEFAULT_PAGE_SIZE ? null : String(nextSize) })
        : update({ page: nextPage > 1 ? String(nextPage) : null }, { keepPage: true }),
  }
}
