"""Public search API, version 1.

Stable URLs for scripts and other tools: /v1/... Breaking changes go into a
new version (/v2) instead of changing these. Every endpoint is rate-limited to
one request per 5 seconds per client IP (see rate_limit.py).

It uses the same search logic as the website (search.py), so results match.
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from . import schemas
from .database import get_db
from .rate_limit import WINDOW_SECONDS, rate_limit
from .search import (
    B,
    DATE_FIELDS,
    FACET_FIELDS,
    SORTS,
    SUGGEST_FIELDS,
    SearchFilters,
    build_conditions,
    distinct_values,
)

router = APIRouter(prefix="/v1", tags=["Public API v1"], dependencies=[Depends(rate_limit)])

# For the website's API documentation page. Not rate-limited, so reading the
# docs doesn't use up the visitor's allowance for trying the API.
docs_router = APIRouter(prefix="/search", tags=["search"])

ACCESSION_PATTERN = r"^(PRJ(NA|EB|DB)\d+|[SED]RP\d+)$"

# What /v1/filters reports, so clients can discover the parameters of /v1/projects.
LIST_FILTER_HELP = {
    "organism": "Project organism name",
    "supergroup": "Broad group, e.g. Eukaryotes, Bacteria, Viruses",
    "data_types": "Project data types",
    "objectives": "Project objectives",
    "relevance": "e.g. Medical, ModelOrganism",
    "target_material": "e.g. genomic, transcriptome",
    "target_capture": "e.g. whole, exome",
    "sample_scope": "e.g. monoisolate, environment",
    "method_type": "e.g. sequencing, array",
    "access": "e.g. public, controlled",
    "organization_country": "Country of the submitting organisation",
    "organization": "Submitting organisation",
    "journals": "Journal of a linked publication",
    "tag": "Tag word (organism, disease, tissue, cell type, ...); a project must have all given tags",
    "assay_type": "Run assay type, e.g. RNA-Seq, WGS",
    "platform": "Run platform, e.g. ILLUMINA, OXFORD_NANOPORE",
    "instrument": "Run instrument model",
    "librarylayout": "Run library layout: SINGLE or PAIRED",
    "librarysource": "Run library source, e.g. TRANSCRIPTOMIC",
    "libraryselection": "Run library selection, e.g. cDNA, PCR",
    "run_organism": "Organism of a run",
    "sample_country": "Country where a run's sample was collected",
    "center_name": "Sequencing center",
}


def describe_filters() -> list[dict]:
    filters = [
        {
            "name": "accession",
            "kind": "list",
            "description": "BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accession",
        }
    ]
    for name, help_text in LIST_FILTER_HELP.items():
        filters.append({
            "name": name,
            "kind": "list",
            "description": help_text,
            "values": f"/v1/filters/{name}" + ("?q=..." if name in SUGGEST_FIELDS else ""),
        })
    for prefix in DATE_FIELDS:
        for suffix in ("from", "to"):
            filters.append({"name": f"{prefix}_{suffix}", "kind": "date", "description": "YYYY-MM-DD"})
    filters += [
        {"name": "run_release_from", "kind": "date", "description": "Runs released on or after (YYYY-MM-DD)"},
        {"name": "run_release_to", "kind": "date", "description": "Runs released on or before (YYYY-MM-DD)"},
        {"name": "min_experiments", "kind": "integer", "description": "Minimum number of experiments"},
        {"name": "max_experiments", "kind": "integer", "description": "Maximum number of experiments"},
        {"name": "min_publications", "kind": "integer", "description": "Minimum number of publications"},
        {"name": "has_publications", "kind": "boolean", "description": "true or false"},
        {"name": "has_geo", "kind": "boolean", "description": "Has GEO accessions: true or false"},
        {"name": "has_grants", "kind": "boolean", "description": "Has grants: true or false"},
        {"name": "sort", "kind": "string", "description": "One of: " + ", ".join(SORTS)},
        {"name": "limit", "kind": "integer", "description": "Results per page, 1-100 (default 25)"},
        {"name": "offset", "kind": "integer", "description": "Results to skip (default 0)"},
    ]
    return filters


@router.get("", response_model=schemas.ApiInfo, summary="API information")
def api_info():
    return {
        "version": "v1",
        "rate_limit": f"1 request per {WINDOW_SECONDS:g} seconds per IP",
        "endpoints": {
            "search": "/v1/projects",
            "lookup": "/v1/projects/{accession}",
            "filters": "/v1/filters",
            "filter_values": "/v1/filters/{name}",
            "semantic_search": "/v1/projects/semantic (not available yet)",
        },
    }


@router.get("/projects", response_model=schemas.PublicSearchResults, summary="Search projects")
def search_projects(
    filters: Annotated[SearchFilters, Query()],
    db: Session = Depends(get_db),
):
    """Search BioProject/SRA study pairs. Within one filter, several values
    match any of them (repeat the parameter: `?platform=ILLUMINA&platform=PACBIO_SMRT`).
    Different filters must all match. See `/v1/filters` for every parameter."""
    where = and_(true(), *build_conditions(filters))
    total = db.scalar(select(func.count()).select_from(B).where(where))
    stmt = (
        select(B)
        .where(where)
        .order_by(SORTS[filters.sort], B.bioproject, B.sra_study)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return {
        "total": total,
        "limit": filters.limit,
        "offset": filters.offset,
        "results": db.scalars(stmt).all(),
    }


# Declared before /projects/{accession} so "semantic" isn't read as an accession.
@router.get(
    "/projects/semantic",
    summary="Semantic search (not available yet)",
    responses={501: {"description": "Semantic search is not available yet"}},
)
def semantic_search(q: str = Query(..., description="Natural-language description of the data")):
    raise HTTPException(status_code=501, detail="Semantic search is not available yet.")


@router.get(
    "/projects/{accession}",
    response_model=schemas.PublicLookupResults,
    summary="Look up a project by accession",
    responses={404: {"description": "No project with this accession"}},
)
def get_project(
    accession: Annotated[str, Path(description="BioProject or SRA study accession", pattern=ACCESSION_PATTERN)],
    db: Session = Depends(get_db),
):
    """A BioProject can have several SRA studies, so this returns a list."""
    acc = accession.upper()
    rows = db.scalars(
        select(B).where(or_(B.bioproject == acc, B.sra_study == acc)).order_by(B.bioproject, B.sra_study)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No project with accession {acc}")
    return {"results": rows}


@router.get("/filters", response_model=list[schemas.FilterInfo], summary="List search filters")
def list_filters():
    return describe_filters()


@router.get(
    "/filters/{name}",
    response_model=list[schemas.FacetValue],
    summary="Values of a list filter",
)
def filter_values(
    name: Literal[tuple(FACET_FIELDS + SUGGEST_FIELDS)],  # type: ignore[valid-type]
    q: Optional[str] = Query(None, description="Only values containing this text"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Values with their counts, most common first: projects for project
    filters, studies for run filters."""
    needle = (q or "").strip().lower()
    matches = ({"value": v, "count": n} for v, n in distinct_values(name) if needle in v.lower())
    return [m for _, m in zip(range(limit), matches)]


@docs_router.get("/public-api-docs", response_model=schemas.PublicApiDocs, include_in_schema=False)
def public_api_docs():
    return {"rate_limit_seconds": WINDOW_SECONDS, "filters": describe_filters()}
