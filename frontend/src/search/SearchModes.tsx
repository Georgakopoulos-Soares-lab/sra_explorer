import { CheckOutlined } from '@ant-design/icons'
import { parseAccessions } from './filters'
import { parseReference } from './reference'

export type SearchMode = 'text' | 'accession' | 'doi' | 'pmid'

// Something that could still become an accession (PRJNA…, SRP…) or a
// reference (digits, 10.…, doi:, PMID:, a URL) as more is typed.
const PARTIAL_ACCESSION = /^(P(R(J([NED](A|B)?\d*)?)?)?|[SED](R(P\d*)?)?)$/i
const PARTIAL_REFERENCE = /^(\d+|10(\.\d*)?(\/\S*)?|d(o(i(:.*)?)?)?|p(m(i(d(:?\s*\d*)?)?)?)?|h(t(t(p(s?(:(\/(\/.*)?)?)?)?)?)?)?)$/i

// The search mode the typed text clearly shows, or null while it could still
// go several ways (empty, or the start of an accession or reference).
export function detectMode(text: string): SearchMode | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  if (parseAccessions(trimmed)) return 'accession'
  const ref = parseReference(trimmed)
  if (ref) return ref.kind
  const tokens = trimmed.split(/[\s,;]+/)
  if (tokens.every((t) => PARTIAL_ACCESSION.test(t))) return null
  if (tokens.length === 1 && PARTIAL_REFERENCE.test(trimmed)) return null
  return 'text'
}

const MODES: { key: SearchMode; label: string; title: string }[] = [
  { key: 'text', label: 'Describe the data', title: 'Finds projects whose descriptions are similar in meaning to the text' },
  { key: 'accession', label: 'BioProject / SRA accessions', title: 'PRJNA, PRJEB, PRJDB, SRP, ERP or DRP accessions, several separated by spaces' },
  { key: 'doi', label: 'DOI', title: "A paper's DOI: searches with its title and abstract" },
  { key: 'pmid', label: 'PubMed ID', title: "A paper's PubMed ID: searches with its title and abstract" },
]

// The ways to search, above the search box. All grey until the typed
// text shows which one it is; that one is then highlighted.
export default function SearchModes({ text }: { text: string }) {
  const mode = detectMode(text)
  return (
    <div className="mb-2 flex flex-wrap items-center justify-center gap-2 text-sm">
      <span className="mr-1 text-gray-500">Search mode:</span>
      {MODES.map((m) => (
        <span
          key={m.key}
          title={m.title}
          aria-current={mode === m.key ? 'true' : undefined}
          className={`inline-flex items-center gap-1.5 rounded-md border border-solid px-3 py-1 transition-colors ${
            mode === m.key
              ? 'border-brand-sra bg-brand-sra font-medium text-white shadow-sm'
              : 'border-gray-200 bg-gray-50 text-gray-400'
          }`}
        >
          {mode === m.key && <CheckOutlined className="text-xs" />}
          {m.label}
        </span>
      ))}
    </div>
  )
}
