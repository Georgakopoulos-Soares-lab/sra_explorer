from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class BioprojectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bioproject: str
    sra_study: str
    n_experiments: Optional[int] = None
    found_in_bioproject_xml: Optional[bool] = None
    bioproject_uid: Optional[int] = None
    name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    data_types: Optional[str] = None
    organism_name: Optional[str] = None
    tax_id: Optional[int] = None
    supergroup: Optional[str] = None
    target_material: Optional[str] = None
    target_capture: Optional[str] = None
    sample_scope: Optional[str] = None
    method_type: Optional[str] = None
    objectives: Optional[str] = None
    relevance: Optional[str] = None
    project_release_date: Optional[date] = None
    release_date: Optional[date] = None
    geo_accessions: Optional[str] = None
    center_ids: Optional[Any] = None
    external_links: Optional[Any] = None
    grants: Optional[Any] = None
    publication_count: Optional[int] = None
    pubmed_ids: Optional[str] = None
    first_publication_date: Optional[date] = None
    journals: Optional[str] = None
    publication_titles: Optional[str] = None
    publications: Optional[Any] = None
    submission_id: Optional[str] = None
    submitted_date: Optional[date] = None
    last_update_date: Optional[date] = None
    organization: Optional[str] = None
    organization_country: Optional[str] = None
    access: Optional[str] = None
    parent_projects: Optional[str] = None
    # From bioproject_tags, most relevant first.
    tags: list[str] = []


class SraMetadataOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    acc: str
    assay_type: Optional[str] = None
    center_name: Optional[str] = None
    experiment: Optional[str] = None
    sample_name: Optional[str] = None
    instrument: Optional[str] = None
    librarylayout: Optional[str] = None
    libraryselection: Optional[str] = None
    librarysource: Optional[str] = None
    platform: Optional[str] = None
    sample_acc: Optional[str] = None
    biosample: Optional[str] = None
    organism: Optional[str] = None
    sra_study: Optional[str] = None
    releasedate: Optional[date] = None
    bioproject: Optional[str] = None
    library_name: Optional[str] = None
    geo_loc_name_country_calc: Optional[str] = None


class SearchHit(BioprojectOut):
    # Only set for text searches: cosine similarity to the search text (0-1),
    # and whether the project contains all the words.
    similarity: Optional[float] = None
    text_match: Optional[bool] = None


class SearchResults(BaseModel):
    total: int
    items: list[SearchHit]


class FacetValue(BaseModel):
    value: str
    count: int
    # Tags only: the tag's type (organism, disease, tissue, ...), when known.
    group: Optional[str] = None


class Stats(BaseModel):
    bioprojects: int
    studies: int
    organisms: int
    runs: int
    # Distinct publications linked to projects.
    publications: int
    # Distinct run assay types; None without study_facets.
    assay_types: Optional[int] = None
    # % of runs (samples) with a tissue, cell type or cell line in their
    # attributes; None without bioproject_attributes_coverage.
    tissue_samples: Optional[int] = None
    tissue_samples_pct: Optional[float] = None
    cell_type_samples: Optional[int] = None
    cell_type_samples_pct: Optional[float] = None
    cell_line_samples: Optional[int] = None
    cell_line_samples_pct: Optional[float] = None


# Public API (/v1)


class PublicSearchResults(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[BioprojectOut]


class PublicLookupResults(BaseModel):
    results: list[BioprojectOut]


class FilterInfo(BaseModel):
    name: str
    kind: str
    description: str
    values: Optional[str] = None


class ApiInfo(BaseModel):
    version: str
    rate_limit: str
    endpoints: dict[str, str]


class PublicApiDocs(BaseModel):
    rate_limit_seconds: float
    filters: list[FilterInfo]
