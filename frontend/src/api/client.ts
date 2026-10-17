const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

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

export async function apiGet<T>(
  path: string,
  query?: object,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildUrl(path, query as Record<string, QueryValue>), {
    ...init,
    method: 'GET',
    headers: { Accept: 'application/json', ...init?.headers },
  })

  if (!response.ok) {
    // FastAPI errors look like {"detail": "..."} or {"detail": [validation errors]}.
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : `Request failed with status ${response.status}`
    throw new ApiError(response.status, message, detail)
  }

  return response.json() as Promise<T>
}
