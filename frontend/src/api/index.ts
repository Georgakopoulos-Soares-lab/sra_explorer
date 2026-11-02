import { apiGet } from './client'
import type {
  Bioproject,
  BioprojectFilters,
  FacetValue,
  HealthStatus,
  PublicApiDocs,
  RunFilters,
  SearchParams,
  SearchResults,
  SraRun,
  Stats,
} from './types'

export { API_BASE_URL, ApiError } from './client'
export type * from './types'

export const api = {
  health: (signal?: AbortSignal) => apiGet<HealthStatus>('/health', undefined, { signal }),

  listBioprojects: (filters: BioprojectFilters = {}, signal?: AbortSignal) =>
    apiGet<Bioproject[]>('/bioprojects', filters, { signal }),

  // A bioproject can map to several SRA studies, so this returns a list.
  getBioproject: (bioproject: string, signal?: AbortSignal) =>
    apiGet<Bioproject[]>(`/bioprojects/${encodeURIComponent(bioproject)}`, undefined, { signal }),

  listRuns: (filters: RunFilters = {}, signal?: AbortSignal) =>
    apiGet<SraRun[]>('/runs', filters, { signal }),

  getRun: (acc: string, signal?: AbortSignal) =>
    apiGet<SraRun>(`/runs/${encodeURIComponent(acc)}`, undefined, { signal }),

  searchBioprojects: (params: SearchParams, signal?: AbortSignal) =>
    apiGet<SearchResults>('/search/bioprojects', params, { signal }),

  // The most recently released projects (at most 100), without filters or a total count.
  latestBioprojects: (limit = 100, signal?: AbortSignal) =>
    apiGet<Bioproject[]>('/search/latest', { limit }, { signal }),

  // Dropdown options, with counts, for one filter with a short list of values.
  // `context` is the other selected filters (search parameters): only values
  // found among the projects matching them are returned, with those counts.
  facet: (field: string, context?: SearchParams, signal?: AbortSignal) =>
    apiGet<FacetValue[]>(`/search/facets/${encodeURIComponent(field)}`, context, { signal }),

  // Matching values for filters with too many values for a dropdown; `context` as for facet.
  suggest: (field: string, q: string, signal?: AbortSignal, context?: SearchParams) =>
    apiGet<FacetValue[]>('/search/suggest', { ...context, field, q }, { signal }),

  // The most common tags among a search's top results; takes the search's own parameters.
  tagSummary: (params: SearchParams, signal?: AbortSignal) =>
    apiGet<FacetValue[]>('/search/tag-summary', params, { signal }),

  stats: (signal?: AbortSignal) => apiGet<Stats>('/search/stats', undefined, { signal }),

  // The public API's rate limit and parameters, for the API documentation page.
  publicApiDocs: (signal?: AbortSignal) => apiGet<PublicApiDocs>('/search/public-api-docs', undefined, { signal }),
}
