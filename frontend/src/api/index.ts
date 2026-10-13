import { apiGet } from './client'
import type { Bioproject, BioprojectFilters, HealthStatus, RunFilters, SraRun } from './types'

export { ApiError } from './client'
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
}
