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


class SearchResults(BaseModel):
    total: int
    items: list[BioprojectOut]


class FacetValue(BaseModel):
    value: str
    count: int


class Stats(BaseModel):
    bioprojects: int
    studies: int
    organisms: int
    runs: int


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
