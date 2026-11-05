// A paper reference typed in the search box. The backend replaces it with the
// paper's title and abstract before searching (backend/app/publications.py);
// the page only needs to recognise it, to show which paper is searched for.
// Keep these patterns in sync with DOI_RE and PMID_RE there.

const DOI_RE = /^(?:(?:https?:\/\/)?(?:dx\.)?doi\.org\/|doi:\s*)?(10\.\d{4,9}\/\S+)$/i
const PMID_RE = /^(?:(?:https?:\/\/)?pubmed\.ncbi\.nlm\.nih\.gov\/|pmid:?\s*)?(\d{1,8})\/?$/i

export interface Reference {
  kind: 'doi' | 'pmid'
  id: string
}

export function parseReference(text: string): Reference | null {
  const trimmed = text.trim()
  const doi = DOI_RE.exec(trimmed)
  if (doi) return { kind: 'doi', id: doi[1].replace(/[.,;]+$/, '') }
  const pmid = PMID_RE.exec(trimmed)
  if (pmid) return { kind: 'pmid', id: pmid[1].replace(/^0+(?=\d)/, '') }
  return null
}

export const referenceLabel = (ref: Reference) => (ref.kind === 'doi' ? `DOI ${ref.id}` : `PubMed ID ${ref.id}`)
