// The admin endpoints behind the normalisation page (backend/app/admin.py).
// Every call carries the admin code, which the backend checks.
import { apiRequest } from './client'

export interface NormalizeField {
  name: string
  label: string
  kind: 'column' | 'run' | 'attribute'
  // What the counts are: projects, studies.
  counts: string
  // What "rows changed" are: project-study rows, runs, projects.
  rows: string
}

export interface ValueCount {
  value: string
  count: number
}

export interface ValueList {
  total: number
  items: ValueCount[]
}

export interface Rule {
  id: number
  field: string
  from_value: string
  to_value: string
  rows: number | null
  created_at: string | null
}

export interface Job {
  id: string
  kind: 'rename' | 'apply'
  field: string | null
  from_values: string[]
  to_value: string | null
  status: 'queued' | 'running' | 'done' | 'failed'
  rows: number
  refreshed: string[]
  message: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export function adminApi(code: string) {
  const headers = { 'X-Admin-Code': code }
  return {
    fields: () => apiRequest<NormalizeField[]>('GET', '/admin/fields', { headers }),
    values: (field: string, q: string, limit: number, offset: number, signal?: AbortSignal) =>
      apiRequest<ValueList>('GET', '/admin/values', { query: { field, q, limit, offset }, headers, signal }),
    rules: (field: string) => apiRequest<Rule[]>('GET', '/admin/rules', { query: { field }, headers }),
    deleteRule: (id: number) => apiRequest<{ deleted: number }>('DELETE', `/admin/rules/${id}`, { headers }),
    rename: (field: string, from_values: string[], to_value: string) =>
      apiRequest<Job>('POST', '/admin/rename', { body: { field, from_values, to_value }, headers }),
    apply: () => apiRequest<Job>('POST', '/admin/apply', { headers }),
    jobs: () => apiRequest<Job[]>('GET', '/admin/jobs', { headers }),
  }
}
