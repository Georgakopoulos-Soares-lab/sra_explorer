// One definition per filter. The keys are the backend's query parameter names
// (backend/app/search.py) and are also used as-is in the page URL.

export type FilterDef =
  // Multi-select with options from /search/facets.
  | { kind: 'select'; key: string; label: string }
  // Multi-select that searches /search/suggest as the user types. `scopedBy`
  // names another filter whose selected values narrow the suggestions.
  | { kind: 'suggest'; key: string; label: string; scopedBy?: string }
  // Date range, sent as <key>_from / <key>_to.
  | { kind: 'dateRange'; key: string; label: string }
  // Min/max numbers, sent as min_<key> / max_<key>.
  | { kind: 'numberRange'; key: string; label: string }
  // Single minimum, sent as min_<key>.
  | { kind: 'min'; key: string; label: string }
  // Any / Yes / No, sent as true or false.
  | { kind: 'flag'; key: string; label: string }

export interface FilterSection {
  key: string
  title: string
  hint?: string
  filters: FilterDef[]
}

export const FILTER_SECTIONS: FilterSection[] = [
  {
    // Kept as 'organism' so the panel still opens on it.
    key: 'organism',
    title: 'Organism, samples and sequencing',
    hint: 'Run filters (assay type, platform to sequencing center) need one run matching them all. Sample filters (cell line to ChIP target) match when the project\'s samples include each value, not necessarily in the same sample.',
    filters: [
      { kind: 'select', key: 'supergroup', label: 'Supergroup' },
      { kind: 'suggest', key: 'organism', label: 'Organism', scopedBy: 'supergroup' },
      { kind: 'select', key: 'assay_type', label: 'Assay type' },
      // Sample attributes, from bioproject_attributes (the runs' jattr, summarised per project).
      { kind: 'suggest', key: 'cell_line', label: 'Cell line' },
      { kind: 'suggest', key: 'cell_type', label: 'Cell type' },
      { kind: 'suggest', key: 'tissue', label: 'Tissue' },
      { kind: 'select', key: 'sex', label: 'Sex' },
      { kind: 'suggest', key: 'disease_state', label: 'Disease' },
      { kind: 'suggest', key: 'genotype_or_strain', label: 'Genotype or strain' },
      { kind: 'suggest', key: 'treatment_or_growth_condition', label: 'Treatment or condition' },
      { kind: 'suggest', key: 'molecular_target', label: 'ChIP target' },
      // Run filters (study_facets).
      { kind: 'select', key: 'platform', label: 'Platform' },
      { kind: 'select', key: 'instrument', label: 'Instrument' },
      { kind: 'select', key: 'librarylayout', label: 'Library layout' },
      { kind: 'select', key: 'libraryselection', label: 'Library selection' },
      { kind: 'suggest', key: 'center_name', label: 'Sequencing center' },
      // Same date as the results table's Released column.
      { kind: 'dateRange', key: 'release', label: 'Released' },
    ],
  },
  {
    key: 'tags',
    title: 'Tags',
    hint: 'Projects with all the chosen tags. Only some projects have tags so far, so this leaves out projects without them.',
    filters: [{ kind: 'suggest', key: 'tag', label: 'Tag' }],
  },
  {
    key: 'submitter',
    title: 'Submitter, size and publications',
    filters: [
      { kind: 'suggest', key: 'organization', label: 'Organization' },
      { kind: 'select', key: 'organization_country', label: 'Country' },
      { kind: 'numberRange', key: 'experiments', label: 'Number of experiments' },
      { kind: 'flag', key: 'has_publications', label: 'Has publications' },
      { kind: 'suggest', key: 'journals', label: 'Journal' },
    ],
  },
]

// Columns the backend can sort by; the sort parameter is <key>_asc or <key>_desc.
export const SORT_KEYS = ['release', 'experiments', 'publications', 'bioproject', 'organism'] as const
export type SortKey = (typeof SORT_KEYS)[number]
export const DEFAULT_SORT = 'release_desc'
// Most similar first; the default for text (semantic) searches.
export const RELEVANCE_SORT = 'relevance'

// The URL parameters each filter owns.
export function paramKeys(def: FilterDef): string[] {
  switch (def.kind) {
    case 'dateRange':
      return [`${def.key}_from`, `${def.key}_to`]
    case 'numberRange':
      return [`min_${def.key}`, `max_${def.key}`]
    case 'min':
      return [`min_${def.key}`]
    default:
      return [def.key]
  }
}

export const ALL_FILTERS = FILTER_SECTIONS.flatMap((s) => s.filters)
export const LIST_KEYS = new Set(
  ALL_FILTERS.filter((f) => f.kind === 'select' || f.kind === 'suggest').map((f) => f.key),
)
export const FILTER_PARAM_KEYS = ALL_FILTERS.flatMap(paramKeys)

// BioProject (PRJNA/PRJEB/PRJDB) and SRA study (SRP/ERP/DRP) accessions.
const ACCESSION_RE = /^(PRJ(NA|EB|DB)\d+|[SED]RP\d+)$/i

// The accessions in the search box text, or null when the text is something
// else (left for semantic search). Accepts several, separated by spaces or commas.
export function parseAccessions(text: string): string[] | null {
  const tokens = text.split(/[\s,;]+/).filter(Boolean)
  if (tokens.length === 0 || !tokens.every((t) => ACCESSION_RE.test(t))) return null
  return [...new Set(tokens.map((t) => t.toUpperCase()))]
}
