// Client for NCBI E-utilities' PubMed summaries
// (https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ESummary).
//
// These requests go straight from the user's browser to NCBI, never through
// our backend: NCBI rate-limits per client (3 requests a second without an
// API key), so each user spends their own allowance. NCBI allows this with
// CORS (Access-Control-Allow-Origin: *).

const ESUMMARY = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'
// NCBI asks callers to name their tool.
const TOOL = 'srascout'
// IDs per request; E-utilities accepts a few hundred in a GET.
const BATCH = 200
// Spacing between requests, to stay under 3 a second.
const MIN_GAP_MS = 350

export interface PubmedSummary {
  title: string | null
  // "Smith J et al. · Nature · 2021", the form the app's own citations use.
  citation: string | null
  doi: string | null
  pmc: string | null
}

interface EsummaryRecord {
  title?: string
  source?: string
  pubdate?: string
  authors?: { name: string; authtype?: string }[]
  articleids?: { idtype: string; value: string }[]
  error?: string
}

function toSummary(r: EsummaryRecord): PubmedSummary {
  const authors = (r.authors ?? []).filter((a) => !a.authtype || a.authtype === 'Author').map((a) => a.name)
  const who = authors.length > 2 ? `${authors[0]} et al.` : authors.length ? authors.join(' & ') : null
  const year = r.pubdate?.match(/\d{4}/)?.[0] ?? null
  const parts = [who, r.source, year].filter(Boolean)
  const id = (type: string) => r.articleids?.find((a) => a.idtype === type)?.value ?? null
  return {
    title: r.title?.trim() || null,
    citation: parts.length ? parts.join(' · ') : null,
    doi: id('doi'),
    pmc: id('pmc'),
  }
}

// PMID -> summary (null when PubMed doesn't know the ID). Kept for the
// session, so reopening a project or seeing a paper again asks nothing.
// Failed lookups are forgotten, so the next attempt tries again.
const cache = new Map<string, Promise<PubmedSummary | null>>()
let nextSlot = 0

async function waitForSlot() {
  const now = Date.now()
  const at = Math.max(now, nextSlot)
  nextSlot = at + MIN_GAP_MS
  if (at > now) await new Promise((resolve) => setTimeout(resolve, at - now))
}

async function fetchBatch(pmids: string[]): Promise<Record<string, EsummaryRecord>> {
  await waitForSlot()
  const params = new URLSearchParams({ db: 'pubmed', retmode: 'json', tool: TOOL, id: pmids.join(',') })
  const response = await fetch(`${ESUMMARY}?${params}`)
  if (!response.ok) throw new Error(`PubMed returned ${response.status}`)
  const body = await response.json()
  return body.result ?? {}
}

// Summaries for the given PMIDs, fetching only the ones not seen yet.
export function pubmedSummaries(pmids: string[]): Promise<Map<string, PubmedSummary | null>> {
  const missing = [...new Set(pmids)].filter((id) => !cache.has(id))
  for (let i = 0; i < missing.length; i += BATCH) {
    const batch = missing.slice(i, i + BATCH)
    const request = fetchBatch(batch)
    for (const id of batch) {
      const one = request.then((result) => (result[id] && !result[id].error ? toSummary(result[id]) : null))
      one.catch(() => cache.delete(id))
      cache.set(id, one)
    }
  }
  return Promise.all(
    pmids.map((id) => cache.get(id)!.then((s) => [id, s] as const).catch(() => [id, null] as const)),
  ).then((entries) => new Map(entries))
}
