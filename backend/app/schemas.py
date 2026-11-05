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


# Statistics page (statistics.py)


class CategoryCount(BaseModel):
    value: str
    # In the dimension's unit (projects or studies).
    count: int
    # Runs with this value; only for assay type, platform and library source.
    runs: Optional[int] = None


class YearCount(BaseModel):
    year: int
    count: int


class YearValueCount(BaseModel):
    year: int
    value: str
    count: int


class Dimension(BaseModel):
    name: str
    label: str
    unit: str  # projects, studies
    # Distinct known values, and units without a known value.
    distinct: int
    unknown: int
    # The most common values (at most 40), most common first.
    values: list[CategoryCount]
    # Counts per year of the 20 most common values.
    by_year: list[YearValueCount]
    # Units with a known value, per year: the denominator for shares.
    known_by_year: list[YearCount]


class YearCounts(BaseModel):
    year: int
    projects: int
    studies: int
    runs: int
    # Projects released that year with a linked publication / GEO series.
    projects_published: int
    projects_geo: int


class StatisticsTotals(BaseModel):
    projects: int
    studies: int
    runs: int
    organisms: int
    assay_types: int
    submitter_countries: int
    sample_countries: int
    projects_published: int
    projects_geo: int
    # Median days from a project's release to its first publication.
    publication_lag_days: Optional[float] = None
    publication_lag_projects: int


class DatabaseStatistics(BaseModel):
    generated_at: str
    # The latest run release date in the data.
    data_through: Optional[date] = None
    totals: StatisticsTotals
    years: list[YearCounts]
    dimensions: list[Dimension]


# Search result summary (search_summary.py)


class SummaryDimension(BaseModel):
    name: str
    label: str
    unit: str  # projects, studies
    # Units among the results with a known value.
    known: int
    # The search page filter that selects a value; None when there is none.
    filter: Optional[str] = None
    # The most common values (at most 10), most common first.
    values: list[CategoryCount]


class SearchSummary(BaseModel):
    projects: int
    studies: int
    runs: int
    projects_published: int
    projects_geo: int
    # Projects per release year.
    years: list[YearCount]
    dimensions: list[SummaryDimension]
