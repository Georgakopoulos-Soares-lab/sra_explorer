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

// What to tell the person when the backend's answer carries no message of its own.
function messageForStatus(status: number): string {
  if (status === 400 || status === 422) return "The request couldn't be understood. Please check the search text and filters."
  if (status === 404) return 'Nothing was found for this request.'
  if (status === 413 || status === 414) return 'The search text is too long. Please shorten it.'
  if (status === 429) return 'Too many requests at once. Please wait a moment and try again.'
  if (status === 502 || status === 503 || status === 504) return 'The server is busy or restarting. Please try again in a moment.'
  if (status >= 500) return 'Something went wrong on the server. Please try again in a moment.'
  return 'The request failed. Please try again.'
}

export async function apiRequest<T>(method: 'GET' | 'POST' | 'DELETE', path: string, options: RequestOptions = {}): Promise<T> {
  const { query, body, headers, signal } = options
  const visitor = visitorId()
  let response: Response
  try {
    response = await fetch(buildUrl(path, query as Record<string, QueryValue>), {
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
  } catch (err) {
    if (signal?.aborted || (err instanceof DOMException && err.name === 'AbortError')) throw err
    // The server could not be reached at all (offline, or the backend is down).
    throw new ApiError(0, "Couldn't reach the server. Check your connection and try again.", err)
  }

  if (!response.ok) {
    // FastAPI errors look like {"detail": "..."}: the backend words its
    // own errors (and validation errors, main.py) for people, and the
    // page shows them as they are. Anything else gets a plain message by
    // status; the status itself is kept on the error, never shown.
    const errorBody = await response.json().catch(() => null)
    const detail = errorBody?.detail
    const message = typeof detail === 'string' && detail ? detail : messageForStatus(response.status)
    throw new ApiError(response.status, message, detail)
  }

  return response.json() as Promise<T>
}

export function apiGet<T>(path: string, query?: object, init?: { signal?: AbortSignal }): Promise<T> {
  return apiRequest<T>('GET', path, { query, signal: init?.signal })
}
