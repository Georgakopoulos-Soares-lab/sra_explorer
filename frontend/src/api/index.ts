import { apiGet } from './client'
import type {
  Bioproject,
  BioprojectFilters,
  DatabaseStatistics,
  FacetValue,
  HealthStatus,
  PublicApiDocs,
  ResolvedPublication,
  RunFilters,
  SearchHit,
  SearchParams,
  SearchResults,
  SearchSummary,
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

  // The paper a DOI or PubMed ID in the search box stands for (the search runs on its title and abstract).
  resolvePublication: (q: string, signal?: AbortSignal) =>
    apiGet<ResolvedPublication>('/search/resolve', { q }, { signal }),

  // The most common tags among a search's top results; takes the search's own parameters.
  tagSummary: (params: SearchParams, signal?: AbortSignal) =>
    apiGet<FacetValue[]>('/search/tag-summary', params, { signal }),

  // Counts over everything a search matches (not just the page shown); takes the search's own parameters.
  searchSummary: (params: SearchParams, signal?: AbortSignal) =>
    apiGet<SearchSummary>('/search/summary', params, { signal }),

  // The projects most similar in description to this one, most similar first.
  similarBioprojects: (bioproject: string, limit = 10, signal?: AbortSignal) =>
    apiGet<SearchHit[]>(`/search/similar/${encodeURIComponent(bioproject)}`, { limit }, { signal }),

  stats: (signal?: AbortSignal) => apiGet<Stats>('/search/stats', undefined, { signal }),

  // Everything on the statistics page; computed by the backend in the background.
  statistics: (signal?: AbortSignal) => apiGet<DatabaseStatistics>('/statistics', undefined, { signal }),

  // The public API's rate limit and parameters, for the API documentation page.
  publicApiDocs: (signal?: AbortSignal) => apiGet<PublicApiDocs>('/search/public-api-docs', undefined, { signal }),
}
