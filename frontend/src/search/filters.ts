// One definition per filter. The keys are the backend's query parameter names
// (backend/app/search.py) and are also used as-is in the page URL.

export type FilterDef =
  // Multi-select with options from /search/facets.
  | { kind: 'select'; key: string; label: string }
  // Multi-select that searches /search/suggest as the user types.
  | { kind: 'suggest'; key: string; label: string }
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
    key: 'organism',
    title: 'Organism',
    filters: [
      { kind: 'suggest', key: 'organism', label: 'Organism' },
      { kind: 'select', key: 'supergroup', label: 'Supergroup' },
    ],
  },
  {
    key: 'project',
    title: 'Project type',
    filters: [
      { kind: 'select', key: 'data_types', label: 'Data types' },
      { kind: 'select', key: 'objectives', label: 'Objectives' },
      { kind: 'select', key: 'relevance', label: 'Relevance' },
      { kind: 'select', key: 'target_material', label: 'Target material' },
      { kind: 'select', key: 'target_capture', label: 'Target capture' },
      { kind: 'select', key: 'sample_scope', label: 'Sample scope' },
      { kind: 'select', key: 'method_type', label: 'Method' },
      { kind: 'select', key: 'access', label: 'Access' },
    ],
  },
  {
    key: 'sequencing',
    title: 'Sequencing runs',
    hint: 'Shows projects that have runs matching each of these.',
    filters: [
      { kind: 'select', key: 'assay_type', label: 'Assay type' },
      { kind: 'select', key: 'platform', label: 'Platform' },
      { kind: 'select', key: 'instrument', label: 'Instrument' },
      { kind: 'select', key: 'librarysource', label: 'Library source' },
      { kind: 'select', key: 'librarylayout', label: 'Library layout' },
      { kind: 'select', key: 'libraryselection', label: 'Library selection' },
      { kind: 'suggest', key: 'run_organism', label: 'Run organism' },
      { kind: 'select', key: 'sample_country', label: 'Sample country' },
      { kind: 'suggest', key: 'center_name', label: 'Sequencing center' },
      { kind: 'dateRange', key: 'run_release', label: 'Run released' },
    ],
  },
  {
    key: 'dates',
    title: 'Dates',
    filters: [
      { kind: 'dateRange', key: 'release', label: 'Project released' },
      { kind: 'dateRange', key: 'submitted', label: 'Submitted' },
      { kind: 'dateRange', key: 'updated', label: 'Last updated' },
      { kind: 'dateRange', key: 'first_publication', label: 'First publication' },
    ],
  },
  {
    key: 'size',
    title: 'Size and publications',
    filters: [
      { kind: 'numberRange', key: 'experiments', label: 'Number of experiments' },
      { kind: 'min', key: 'publications', label: 'Minimum publications' },
      { kind: 'flag', key: 'has_publications', label: 'Has publications' },
      { kind: 'flag', key: 'has_geo', label: 'Has GEO data' },
      { kind: 'flag', key: 'has_grants', label: 'Has grants' },
    ],
  },
  {
    key: 'submitter',
    title: 'Submitter',
    filters: [
      { kind: 'suggest', key: 'organization', label: 'Organization' },
      { kind: 'select', key: 'organization_country', label: 'Country' },
      { kind: 'suggest', key: 'journals', label: 'Journal' },
    ],
  },
]

// Columns the backend can sort by; the sort parameter is <key>_asc or <key>_desc.
export const SORT_KEYS = ['release', 'experiments', 'publications', 'bioproject', 'organism'] as const
export type SortKey = (typeof SORT_KEYS)[number]
export const DEFAULT_SORT = 'release_desc'

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
