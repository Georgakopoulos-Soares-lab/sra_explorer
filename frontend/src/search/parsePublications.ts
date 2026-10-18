import type { Bioproject } from '../api'

// One entry of bioprojects.publications, as written by Automations/create_tables.py.
interface RawPublication {
  id?: string
  db_type?: string // "Pubmed", "DOI", "PMC", ...
  title?: string
  reference?: string
  journal?: string
  year?: string
  authors?: string[]
}

export interface Publication {
  title: string | null
  citation: string | null
  pmid: string | null
  doi: string | null
  pmc: string | null
}

// DOIs are entered by submitters and come in many shapes ("DOI: 10.1/x",
// "https://doi.org/10.1/x", ...). Keep just the DOI itself.
function cleanDoi(text: string): string | null {
  const match = text.match(/10\.\d{4,9}\/\S+/)
  return match ? match[0].replace(/[.,;)\]]+$/, '') : null
}

function citation(p: RawPublication): string | null {
  const authors = p.authors?.length
    ? p.authors.length > 2
      ? `${p.authors[0]} et al.`
      : p.authors.join(' & ')
    : null
  const parts = [authors, p.journal, p.year].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

function parse(raw: RawPublication): Publication {
  const id = (raw.id ?? '').trim()
  const type = (raw.db_type ?? '').toLowerCase()
  return {
    title: raw.title || raw.reference || null,
    citation: citation(raw),
    pmid: type === 'pubmed' && /^\d+$/.test(id) ? id : null,
    doi: type === 'doi' ? cleanDoi(id) : null,
    pmc: type === 'pmc' && /^(PMC)?\d+$/i.test(id) ? (id.toUpperCase().startsWith('PMC') ? id.toUpperCase() : `PMC${id}`) : null,
  }
}

const splitList = (value: string | null) => (value ? value.split('; ').filter(Boolean) : [])

// Uses the structured publications when present, otherwise the flat
// pubmed_ids and publication_titles columns.
export function projectPublications(p: Bioproject): Publication[] {
  if (Array.isArray(p.publications) && p.publications.length) {
    return (p.publications as RawPublication[]).map(parse).filter((x) => x.title || x.pmid || x.doi || x.pmc)
  }
  const ids = splitList(p.pubmed_ids)
  const titles = splitList(p.publication_titles)
  return Array.from({ length: Math.max(ids.length, titles.length) }, (_, i) => ({
    title: titles[i] ?? null,
    citation: null,
    pmid: ids[i] && /^\d+$/.test(ids[i]) ? ids[i] : null,
    doi: null,
    pmc: null,
  }))
}
