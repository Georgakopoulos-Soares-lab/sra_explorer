// Links and helpers shared by the tag explorer page's sections.
import type { TagCount } from '../api'

// The search page with these tags in its Tags filter (all of them, or any
// with `any`), plus any other filter values.
export function searchUrl(tags: string[], any = false, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams()
  for (const t of tags) params.append('tag', t)
  if (any && tags.length > 1) params.set('tag_any', 'true')
  for (const [k, v] of Object.entries(extra)) params.set(k, v)
  return `/search?${params}`
}

// This page with these tags chosen in the workbench.
export function tagsUrl(tags: string[], any = false): string {
  const params = new URLSearchParams()
  for (const t of tags) params.append('tag', t)
  if (any && tags.length > 1) params.set('any', 'true')
  const qs = params.toString()
  return qs ? `/tags?${qs}` : '/tags'
}

// Whether a tag names an organism: its type when known, else whether it is
// a project's organism name or a common name (decided by the backend).
export const isOrganism = (t: Pick<TagCount, 'group' | 'organism'>) => t.organism || t.group === 'organism'

// The most tags the workbench combines (RELATED_MAX_TAGS in backend/app/tags.py).
export const MAX_TAGS = 10

// The workbench's anchor, scrolled to when a tag is picked elsewhere on the page.
export const WORKBENCH_ID = 'find'

export function scrollToWorkbench() {
  document.getElementById(WORKBENCH_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export const formatRatio = (n: number) => (n >= 10 ? n.toFixed(0) : n.toFixed(1))
