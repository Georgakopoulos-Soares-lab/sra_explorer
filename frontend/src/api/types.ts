// Mirrors backend/app/schemas.py. Dates arrive as ISO strings (YYYY-MM-DD).

export interface Bioproject {
  bioproject: string
  sra_study: string
  n_experiments: number | null
  found_in_bioproject_xml: boolean | null
  bioproject_uid: number | null
  name: string | null
  title: string | null
  description: string | null
  data_types: string | null
  organism_name: string | null
  tax_id: number | null
  supergroup: string | null
  target_material: string | null
  target_capture: string | null
  sample_scope: string | null
  method_type: string | null
  objectives: string | null
  relevance: string | null
  project_release_date: string | null
  // First public run, else project release, else submission (backend/sql/release_date.sql).
  release_date: string | null
  geo_accessions: string | null
  center_ids: unknown
  external_links: unknown
  grants: unknown
  publication_count: number | null
  pubmed_ids: string | null
  first_publication_date: string | null
  journals: string | null
  publication_titles: string | null
  publications: unknown
  submission_id: string | null
  submitted_date: string | null
  last_update_date: string | null
  organization: string | null
  organization_country: string | null
  access: string | null
  parent_projects: string | null
  // From bioproject_tags: organisms, diseases, tissues, cell types, ... most relevant first.
  tags: string[]
}

export interface SraRun {
  acc: string
  assay_type: string | null
  center_name: string | null
  experiment: string | null
  sample_name: string | null
  instrument: string | null
  librarylayout: string | null
  libraryselection: string | null
  librarysource: string | null
  platform: string | null
  sample_acc: string | null
  biosample: string | null
  organism: string | null
  sra_study: string | null
  releasedate: string | null
  bioproject: string | null
  library_name: string | null
  geo_loc_name_country_calc: string | null
}

export interface Pagination {
  limit?: number
  offset?: number
}

export interface BioprojectFilters extends Pagination {
  sra_study?: string
  tax_id?: number
  organism_name?: string
}

export interface RunFilters extends Pagination {
  bioproject?: string
  sra_study?: string
  experiment?: string
  biosample?: string
  organism?: string
}

export interface HealthStatus {
  status: string
}

// Filter values for /search/bioprojects, keyed by backend parameter name.
// List filters are string arrays; everything else is a single string.
export type SearchParams = Record<string, string | string[]>

export interface SearchHit extends Bioproject {
  // Only set for text searches: cosine similarity to the search text (0-1),
  // and whether the project contains all the words.
  similarity?: number | null
  text_match?: boolean | null
}

export interface SearchResults {
  total: number
  items: SearchHit[]
}

export interface FacetValue {
  value: string
  count: number
  // Tags only: the tag's type (organism, disease, tissue, ...), when known.
  group?: string | null
}

export interface Stats {
  bioprojects: number
  studies: number
  organisms: number
  runs: number
  // Distinct publications linked to projects.
  publications: number
  // Distinct run assay types; null when that data isn't loaded.
  assay_types: number | null
  // % of samples (runs) with a tissue, cell type or cell line recorded; null when not loaded.
  tissue_samples: number | null
  tissue_samples_pct: number | null
  cell_type_samples: number | null
  cell_type_samples_pct: number | null
  cell_line_samples: number | null
  cell_line_samples_pct: number | null
}

// One search parameter of the public API (/v1/projects).
export interface PublicApiFilter {
  name: string
  kind: string
  description: string
  values: string | null
}

export interface PublicApiDocs {
  rate_limit_seconds: number
  filters: PublicApiFilter[]
}

// The statistics page (GET /statistics; backend/app/statistics.py).

export interface CategoryCount {
  value: string
  // In the dimension's unit (projects or studies).
  count: number
  // Runs with this value; only for assay type, platform and library source.
  runs?: number | null
}

export interface StatisticsDimension {
  name: 'assay_type' | 'platform' | 'instrument' | 'library_source' | 'library_layout' | 'organism' | 'sample_country' | 'submitter_country'
  label: string
  unit: 'projects' | 'studies'
  // Distinct known values, and units without a known value.
  distinct: number
  unknown: number
  // The most common values (at most 40), most common first.
  values: CategoryCount[]
  // Counts per year of the 20 most common values.
  by_year: { year: number; value: string; count: number }[]
  // Units with a known value, per year: the denominator for shares.
  known_by_year: { year: number; count: number }[]
}

export interface YearCounts {
  year: number
  projects: number
  studies: number
  runs: number
  // Projects released that year with a linked publication / GEO series.
  projects_published: number
  projects_geo: number
}

export interface DatabaseStatistics {
  generated_at: string
  // The latest run release date in the data.
  data_through: string | null
  totals: {
    projects: number
    studies: number
    runs: number
    organisms: number
    assay_types: number
    submitter_countries: number
    sample_countries: number
    projects_published: number
    projects_geo: number
    // Median days from a project's release to its first publication.
    publication_lag_days: number | null
    publication_lag_projects: number
  }
  years: YearCounts[]
  dimensions: StatisticsDimension[]
}

// The search page's results summary (GET /search/summary; backend/app/search_summary.py).

export interface SummaryDimension {
  name: string
  label: string
  unit: 'projects' | 'studies'
  // Units among the results with a known value.
  known: number
  // The search page filter that selects a value; null when there is none.
  filter: string | null
  // The most common values (at most 10), most common first.
  values: { value: string; count: number }[]
}

export interface SearchSummary {
  projects: number
  studies: number
  runs: number
  projects_published: number
  projects_geo: number
  // Projects per release year.
  years: { year: number; count: number }[]
  dimensions: SummaryDimension[]
}

// The deep search (GET /search/query-tags; backend/app/query_tags.py):
// the tag words in the search text, matched with the tags of the search's top results.

export interface QueryTag {
  value: string
  // Projects among the search's top results (the pool) with the tag, and among all tagged projects.
  count: number
  corpus: number
  group: string | null
  // The words of the text it matched (normalised) and how: as they are, a
  // common organism name for the species, or similar by embedding (with the cosine).
  phrase: string
  match: 'exact' | 'alias' | 'similar'
  similarity: number
  selected: boolean
  // Pool projects that have this tag and every tag selected before it (null
  // when it wasn't counted), and why it wasn't selected.
  remaining?: number | null
  reason?: string | null
}

export interface QueryTags {
  // The start of the text the tags were read from, and how many of its words were read.
  text: string
  words: number
  // Top results examined, how many have tags and how many don't, and the
  // fewest tagged ones that must keep every selected tag.
  pool: number
  tagged: number
  untagged: number
  floor: number
  // Every tag considered, selected ones first.
  tags: QueryTag[]
  selected: string[]
}

// A DOI or PubMed ID from the search box, resolved to the paper it stands for.
export interface ResolvedPublication {
  kind: 'doi' | 'pmid'
  id: string
  title: string
  abstract: string
  pmid: string | null
  doi: string | null
  url: string
  source: 'pubmed' | 'crossref'
}

// The tag explorer page (GET /tags/overview and /tags/related; backend/app/tags.py).

export interface TagCount {
  value: string
  count: number
  // The tag's type (organism, disease, tissue, ...), when known.
  group: string | null
  // Whether the tag names an organism (a project's organism name or a common name), known even without types.
  organism: boolean
}

export interface TagOverview {
  generated_at: string
  // Whether any project's tags have types.
  has_labels: boolean
  totals: {
    projects: number
    // Projects with at least one tag, projects the tagger found nothing in, and projects whose tags have types.
    tagged: number
    empty: number
    labelled: number
    distinct_tags: number
    occurrences: number
    tags_per_project_mean: number | null
    tags_per_project_median: number | null
  }
  // How many tags are on at least 1, 2, 10, 100 and 1,000 projects.
  frequency: { min_projects: number; tags: number }[]
  // The most common tags (at most 300), most common first.
  top: TagCount[]
  // Tag occurrences and distinct tags per type; empty without types.
  types: { value: string; count: number; distinct: number }[]
  tags_per_project: { n: number; projects: number }[]
  coverage_by_year: { year: number; projects: number; tagged: number }[]
  // Counts per release year of the 20 most common tags.
  by_year: { year: number; value: string; count: number }[]
  // The most common tags (80) and the pairs among them with at least 20 shared projects.
  network: {
    nodes: TagCount[]
    edges: { source: string; target: string; count: number }[]
  }
}

export interface TagRelated {
  tags: string[]
  tag_any: boolean
  // Projects with the tags.
  projects: number
  // The tags most often found with them (at most 30), with each tag's count over all tagged projects.
  related: (TagCount & { total: number })[]
  // The projects' organisms (at most 10), and how many have one recorded.
  organisms: { value: string; count: number }[]
  organism_known: number
  years: { year: number; count: number }[]
}
