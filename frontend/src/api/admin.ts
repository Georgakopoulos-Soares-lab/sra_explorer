// The admin endpoints behind the normalisation and usage pages (backend/app/admin.py).
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
  // rename: from_value -> to_value. capitalize: every value's first letter (from/to empty).
  action: 'rename' | 'capitalize'
  from_value: string
  to_value: string
  rows: number | null
  created_at: string | null
}

export interface Job {
  id: string
  kind: 'rename' | 'capitalize' | 'apply'
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

// --- App usage (backend/app/usage.py) ---------------------------------------

export type UsageSource = 'site' | 'api'
export type UsagePeriod = 'day' | 'week' | 'month'

export interface UsageCounts {
  // Every recorded request, including paging through results.
  events: number
  // New searches (first page of results).
  searches: number
  visitors: number
  site: number
  api: number
  with_text: number
  no_results: number
}

export interface UsageSummary {
  period: UsageCounts
  today: UsageCounts
  week: UsageCounts
  month: UsageCounts
  first_event: string | null
  last_event: string | null
}

export interface UsageBucket {
  // ISO date the day, week or month starts on.
  bucket: string
  searches: number
  events: number
  visitors: number
  site: number
  api: number
}

export interface UsageHour {
  hour: number
  searches: number
}

export interface UsageQuery {
  query: string
  searches: number
  visitors: number
  last: string
  total: number | null
}

export interface UsageFilters {
  fields: { field: string; searches: number }[]
  values: { field: string; value: string; searches: number }[]
}

export interface UsageEvent {
  id: number
  created_at: string
  source: UsageSource
  kind: 'search' | 'lookup'
  query: string | null
  filters: Record<string, unknown>
  sort: string | null
  total: number | null
  duration_ms: number | null
  visitor: string | null
  client_ip: string | null
  user_agent: string | null
}

export interface UsageVisitor {
  visitor: string
  searches: number
  first: string
  last: string
  client_ip: string | null
  days: number
}

// days: how far back to look; 0 for everything.
export interface UsageRange {
  days: number
  source?: UsageSource
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
    capitalize: (field: string) => apiRequest<Job>('POST', '/admin/capitalize', { body: { field }, headers }),
    apply: () => apiRequest<Job>('POST', '/admin/apply', { headers }),
    jobs: () => apiRequest<Job[]>('GET', '/admin/jobs', { headers }),

    usageSummary: (range: UsageRange) => apiRequest<UsageSummary>('GET', '/admin/usage/summary', { query: range, headers }),
    usageSeries: (range: UsageRange, period: UsagePeriod) =>
      apiRequest<UsageBucket[]>('GET', '/admin/usage/series', { query: { ...range, period }, headers }),
    usageHours: (range: UsageRange) => apiRequest<UsageHour[]>('GET', '/admin/usage/hours', { query: range, headers }),
    usageQueries: (range: UsageRange, limit: number) =>
      apiRequest<UsageQuery[]>('GET', '/admin/usage/queries', { query: { ...range, limit }, headers }),
    usageFilters: (range: UsageRange, limit: number) =>
      apiRequest<UsageFilters>('GET', '/admin/usage/filters', { query: { ...range, limit }, headers }),
    usageRecent: (range: UsageRange, limit: number, offset: number) =>
      apiRequest<{ total: number; items: UsageEvent[] }>('GET', '/admin/usage/recent', {
        query: { ...range, limit, offset },
        headers,
      }),
    usageVisitors: (range: UsageRange, limit: number) =>
      apiRequest<UsageVisitor[]>('GET', '/admin/usage/visitors', { query: { ...range, limit }, headers }),
  }
}
