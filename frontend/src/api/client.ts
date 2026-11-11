export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

type QueryScalar = string | number | boolean | null | undefined
type QueryValue = QueryScalar | QueryScalar[]

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url

  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    // Arrays become repeated params (?a=1&a=2), which FastAPI reads as a list.
    for (const item of Array.isArray(value) ? value : [value]) {
      // Skip empty filters so the backend applies its defaults.
      if (item === undefined || item === null || item === '') continue
      params.append(key, String(item))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

// A random id kept by the browser and sent with every request, so the admin
// usage page can count visitors (backend/app/usage.py). It identifies the
// browser, not the person, and is never shown on the site.
const VISITOR_KEY = 'srascout-visitor'
function visitorId(): string | undefined {
  try {
    let id = localStorage.getItem(VISITOR_KEY)
    if (!id) {
      id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36)
      localStorage.setItem(VISITOR_KEY, id)
    }
    return id
  } catch {
    return undefined
  }
}

export interface RequestOptions {
  query?: object
  // Sent as JSON.
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function apiRequest<T>(method: 'GET' | 'POST' | 'DELETE', path: string, options: RequestOptions = {}): Promise<T> {
  const { query, body, headers, signal } = options
  const visitor = visitorId()
  const response = await fetch(buildUrl(path, query as Record<string, QueryValue>), {
    method,
    signal,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(visitor ? { 'X-Visitor-Id': visitor } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    // FastAPI errors look like {"detail": "..."} or {"detail": [validation errors]}.
    const errorBody = await response.json().catch(() => null)
    const detail = errorBody?.detail
    const message = typeof detail === 'string' ? detail : `Request failed with status ${response.status}`
    throw new ApiError(response.status, message, detail)
  }

  return response.json() as Promise<T>
}

export function apiGet<T>(path: string, query?: object, init?: { signal?: AbortSignal }): Promise<T> {
  return apiRequest<T>('GET', path, { query, signal: init?.signal })
}
