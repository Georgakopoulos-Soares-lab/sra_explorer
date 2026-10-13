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
