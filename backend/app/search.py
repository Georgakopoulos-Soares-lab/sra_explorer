"""Filtered search over bioprojects, with run-level filters from sra_metadata.

Run filters use the study_facets materialized view (backend/sql/study_facets.sql)
when it exists, and fall back to querying sra_metadata directly, which is much
slower on the full table.

Text search (the q parameter) is hybrid. A semantic search embeds the text
with the model that built bioproject_embeddings (see embeddings.py) and keeps
projects whose cosine similarity to it is at least SEMANTIC_MIN_SIMILARITY. A
full-text search (backend/sql/bioproject_fulltext.sql) finds projects
containing all the words. The two ranked
lists are merged with reciprocal rank fusion, so projects found by both come
first.
"""

import logging
import os
import time
from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, Date, MetaData, Table, and_, case, exists, false, func, literal_column, or_, select, text, true,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from . import embeddings, models, schemas
from .database import engine, get_db

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

B = models.Bioproject
R = models.SraMetadata
E = models.BioprojectEmbedding

# Projects less similar than this to the search text are left out. On the
# real data, relevant projects score about 0.55-0.85 and nonsense queries at
# most about 0.55 (against very short titles).
SEMANTIC_MIN_SIMILARITY = float(os.getenv("SEMANTIC_MIN_SIMILARITY", "0.5"))
# The nearest projects found through the HNSW index, before filters and the
# threshold are applied; at most 1000, the index's ef_search limit.
SEMANTIC_CANDIDATES = 1000
# The best full-text matches considered, before filters are applied.
TEXT_CANDIDATES = 1000
# Text matches outside the semantic list must still be at least this similar,
# which drops projects that only mention a word in passing.
TEXT_MIN_SIMILARITY = float(os.getenv("TEXT_MIN_SIMILARITY", "0.3"))
# Reciprocal rank fusion: a project scores 1 / (RRF_K + rank) in each list it
# is in. 60 is the usual value; larger values flatten the gap between ranks.
RRF_K = 60

# Filter name -> (column, stores several values joined by "; ").
PROJECT_FIELDS = {
    "organism": (B.organism_name, False),
    "supergroup": (B.supergroup, False),
    "data_types": (B.data_types, True),
    "objectives": (B.objectives, True),
    "relevance": (B.relevance, True),
    "target_material": (B.target_material, False),
    "target_capture": (B.target_capture, False),
    "sample_scope": (B.sample_scope, False),
    "method_type": (B.method_type, False),
    "access": (B.access, False),
    "organization_country": (B.organization_country, False),
    "organization": (B.organization, False),
    "journals": (B.journals, True),
}

# Filter name -> (sra_metadata column, study_facets array column). A project
# matches a run filter when any of its runs has one of the selected values.
RUN_FIELDS = {
    "assay_type": (R.assay_type, "assay_types"),
    "platform": (R.platform, "platforms"),
    "instrument": (R.instrument, "instruments"),
    "librarylayout": (R.librarylayout, "library_layouts"),
    "librarysource": (R.librarysource, "library_sources"),
    "libraryselection": (R.libraryselection, "library_selections"),
    "run_organism": (R.organism, "run_organisms"),
    "sample_country": (R.geo_loc_name_country_calc, "sample_countries"),
    "center_name": (R.center_name, "center_names"),
}

# Not part of models.Base, so create_all never tries to create it.
F = Table(
    "study_facets",
    MetaData(),
    Column("sra_study", Text, primary_key=True),
    *(Column(name, ARRAY(Text)) for _, name in RUN_FIELDS.values()),
    Column("first_run_release", Date),
    Column("last_run_release", Date),
)

# Not part of models.Base either; see backend/sql/bioproject_fulltext.sql.
T = Table(
    "bioproject_fulltext",
    MetaData(),
    Column("bioproject", Text, primary_key=True),
    Column("document", TSVECTOR),
)

_relations_checked: dict[str, tuple[float, bool]] = {}


def has_relation(name: str) -> bool:
    """Whether a table or view exists; rechecked every minute."""
    checked_at, exists_ = _relations_checked.get(name, (None, False))
    if checked_at is None or time.monotonic() - checked_at > 60:
        with engine.connect() as conn:
            exists_ = conn.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name})
        _relations_checked[name] = (time.monotonic(), exists_)
    return exists_


def has_study_facets() -> bool:
    return has_relation("study_facets")

# Filter prefix -> date column; used as <prefix>_from / <prefix>_to.
DATE_FIELDS = {
    "release": B.project_release_date,
    "submitted": B.submitted_date,
    "updated": B.last_update_date,
    "first_publication": B.first_publication_date,
}

# Sortable columns; the sort parameter is <name>_asc or <name>_desc.
SORT_COLUMNS = {
    "release": B.project_release_date,
    "experiments": B.n_experiments,
    "publications": B.publication_count,
    "bioproject": B.bioproject,
    "organism": B.organism_name,
}
SORTS = {
    f"{name}_{direction}": getattr(column, direction)().nulls_last()
    for name, column in SORT_COLUMNS.items()
    for direction in ("asc", "desc")
}


class SearchFilters(BaseModel):
    # BioProject (PRJNA…) or SRA study (SRP…) accessions; a project matches either.
    accession: list[str] = Field(default_factory=list)

    organism: list[str] = Field(default_factory=list)
    supergroup: list[str] = Field(default_factory=list)
    data_types: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    relevance: list[str] = Field(default_factory=list)
    target_material: list[str] = Field(default_factory=list)
    target_capture: list[str] = Field(default_factory=list)
    sample_scope: list[str] = Field(default_factory=list)
    method_type: list[str] = Field(default_factory=list)
    access: list[str] = Field(default_factory=list)
    organization_country: list[str] = Field(default_factory=list)
    organization: list[str] = Field(default_factory=list)
    journals: list[str] = Field(default_factory=list)

    release_from: Optional[date] = None
    release_to: Optional[date] = None
    submitted_from: Optional[date] = None
    submitted_to: Optional[date] = None
    updated_from: Optional[date] = None
    updated_to: Optional[date] = None
    first_publication_from: Optional[date] = None
    first_publication_to: Optional[date] = None

    min_experiments: Optional[int] = Field(None, ge=0)
    max_experiments: Optional[int] = Field(None, ge=0)
    min_publications: Optional[int] = Field(None, ge=0)

    has_publications: Optional[bool] = None
    has_geo: Optional[bool] = None
    has_grants: Optional[bool] = None

    assay_type: list[str] = Field(default_factory=list)
    platform: list[str] = Field(default_factory=list)
    instrument: list[str] = Field(default_factory=list)
    librarylayout: list[str] = Field(default_factory=list)
    librarysource: list[str] = Field(default_factory=list)
    libraryselection: list[str] = Field(default_factory=list)
    run_organism: list[str] = Field(default_factory=list)
    sample_country: list[str] = Field(default_factory=list)
    center_name: list[str] = Field(default_factory=list)
    run_release_from: Optional[date] = None
    run_release_to: Optional[date] = None

    sort: Literal[tuple(SORTS)] = "release_desc"  # type: ignore[valid-type]
    limit: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0)


class SiteSearchFilters(SearchFilters):
    """The website's search: the public filters plus free-text search."""

    q: Optional[str] = Field(None, max_length=1000)
    # Defaults to "relevance" with q, and to "release_desc" without.
    sort: Optional[Literal[tuple(SORTS) + ("relevance",)]] = None  # type: ignore[valid-type]


def split_values(column):
    return func.string_to_array(column, "; ", type_=ARRAY(Text))


def build_conditions(f: SearchFilters) -> list:
    conditions = []

    if f.accession:
        accessions = [a.strip().upper() for a in f.accession if a.strip()]
        conditions.append(or_(B.bioproject.in_(accessions), B.sra_study.in_(accessions)))

    for name, (column, multivalue) in PROJECT_FIELDS.items():
        values = getattr(f, name)
        if not values:
            continue
        if multivalue:
            conditions.append(split_values(column).overlap(values))
        else:
            conditions.append(column.in_(values))

    for prefix, column in DATE_FIELDS.items():
        start, end = getattr(f, f"{prefix}_from"), getattr(f, f"{prefix}_to")
        if start:
            conditions.append(column >= start)
        if end:
            conditions.append(column <= end)

    if f.min_experiments is not None:
        conditions.append(B.n_experiments >= f.min_experiments)
    if f.max_experiments is not None:
        conditions.append(B.n_experiments <= f.max_experiments)
    if f.min_publications is not None:
        conditions.append(B.publication_count >= f.min_publications)

    flags = {
        "has_publications": func.coalesce(B.publication_count, 0) > 0,
        "has_geo": func.coalesce(B.geo_accessions, "") != "",
        # jsonb_array_length errors on non-array JSON, so check the type first.
        "has_grants": case(
            (func.jsonb_typeof(B.grants) == "array", func.jsonb_array_length(B.grants)),
            else_=0,
        ) > 0,
    }
    for name, condition in flags.items():
        value = getattr(f, name)
        if value is not None:
            conditions.append(condition if value else ~condition)

    selected = {name: getattr(f, name) for name in RUN_FIELDS if getattr(f, name)}
    if has_study_facets():
        # Each run filter can be met by a different run of the study. For the
        # date range, the study's runs must have been released within it.
        run_conditions = [F.c[RUN_FIELDS[name][1]].overlap(v) for name, v in selected.items()]
        if f.run_release_from:
            run_conditions.append(F.c.last_run_release >= f.run_release_from)
        if f.run_release_to:
            run_conditions.append(F.c.first_run_release <= f.run_release_to)
        if run_conditions:
            conditions.append(exists().where(F.c.sra_study == B.sra_study, *run_conditions))
    else:
        run_conditions = [RUN_FIELDS[name][0].in_(v) for name, v in selected.items()]
        if f.run_release_from:
            run_conditions.append(R.releasedate >= f.run_release_from)
        if f.run_release_to:
            run_conditions.append(R.releasedate <= f.run_release_to)
        if run_conditions:
            conditions.append(exists().where(R.sra_study == B.sra_study, *run_conditions))

    return conditions


@router.get("/bioprojects", response_model=schemas.SearchResults)
def search_bioprojects(
    filters: Annotated[SiteSearchFilters, Query()],
    db: Session = Depends(get_db),
):
    where = and_(true(), *build_conditions(filters))
    q = (filters.q or "").strip()
    if q:
        return hybrid_search(db, q, where, filters)

    sort = SORTS[filters.sort if filters.sort in SORTS else "release_desc"]
    total = db.scalar(select(func.count()).select_from(B).where(where))
    stmt = (
        select(B)
        .where(where)
        .order_by(sort, B.bioproject, B.sra_study)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return {"total": total, "items": db.scalars(stmt).all()}


def hybrid_search(db: Session, q: str, where, filters: SiteSearchFilters) -> dict:
    """Projects similar to q or containing its words, that also match the filters.

    Only the SEMANTIC_CANDIDATES nearest and TEXT_CANDIDATES best text
    matches are considered, so a broad query reports at most their sum.
    """
    try:
        query_vec = embeddings.embed(q)
    except Exception:
        logger.exception("Could not embed the search text")
        raise HTTPException(status_code=503, detail="Searching by description is unavailable right now.")

    # Semantic list. The ORDER BY ... LIMIT form lets Postgres use the HNSW
    # index; ef_search must be at least the LIMIT to return that many rows.
    db.execute(text(f"SET LOCAL hnsw.ef_search = {SEMANTIC_CANDIDATES}"))
    distance = E.embedding.cosine_distance(query_vec)
    nearest = (
        select(E.bioproject, distance.label("distance"))
        .order_by(distance)
        .limit(SEMANTIC_CANDIDATES)
        .subquery()
    )
    # Vectors are normalised, so similarity = 1 - cosine distance.
    semantic = (
        select(nearest.c.bioproject, func.row_number().over(order_by=nearest.c.distance).label("rank"))
        .where(nearest.c.distance <= 1 - SEMANTIC_MIN_SIMILARITY)
        .subquery()
    )

    # Text list. websearch_to_tsquery needs every word (stemmed, stop words
    # dropped) and also accepts "quoted phrases", OR, and -excluded words.
    # Normalisation 1 divides the rank by the log of the text's length, so
    # long descriptions that repeat a word don't crowd out focused projects.
    tsquery = func.websearch_to_tsquery(literal_column("'english'::regconfig"), q)
    text_score = func.ts_rank_cd(T.c.document, tsquery, 1)
    text_best = (
        select(T.c.bioproject, text_score.label("score"))
        .where(T.c.document.op("@@")(tsquery))
        .order_by(text_score.desc(), T.c.bioproject)
        .limit(TEXT_CANDIDATES)
    )
    if not has_relation("bioproject_fulltext"):
        text_best = text_best.where(false())  # semantic only
    text_best = text_best.subquery()
    # The similarity floor is checked only for these few rows: in the same
    # query as the text match, Postgres computes it for every embedding first.
    text_ranked = (
        select(
            text_best.c.bioproject,
            func.row_number().over(order_by=(text_best.c.score.desc(), text_best.c.bioproject)).label("rank"),
        )
        .join(E, E.bioproject == text_best.c.bioproject)
        .where(distance <= 1 - TEXT_MIN_SIMILARITY)
        .subquery()
    )

    # Fusion: projects in either list, scored by their ranks in both.
    fused = (
        select(
            func.coalesce(semantic.c.bioproject, text_ranked.c.bioproject).label("bioproject"),
            (
                func.coalesce(1.0 / (RRF_K + semantic.c.rank), 0)
                + func.coalesce(1.0 / (RRF_K + text_ranked.c.rank), 0)
            ).label("score"),
            text_ranked.c.rank.is_not(None).label("text_match"),
        )
        .select_from(
            semantic.join(text_ranked, semantic.c.bioproject == text_ranked.c.bioproject, full=True)
        )
        .subquery()
    )
    joined = B.__table__.join(fused, fused.c.bioproject == B.bioproject)

    total = db.scalar(select(func.count()).select_from(joined).where(where))
    order = [fused.c.score.desc()] if filters.sort in (None, "relevance") else [SORTS[filters.sort]]
    # Shown in the results; also set for text matches outside the semantic list.
    similarity = 1 - E.embedding.cosine_distance(query_vec)
    stmt = (
        select(B, similarity.label("similarity"), fused.c.text_match)
        .select_from(joined.outerjoin(E, E.bioproject == B.bioproject))
        .where(where)
        .order_by(*order, B.bioproject, B.sra_study)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    items = [
        {
            **schemas.BioprojectOut.model_validate(p).model_dump(),
            "similarity": None if sim is None else round(sim, 4),
            "text_match": text_match,
        }
        for p, sim, text_match in db.execute(stmt)
    ]
    return {"total": total, "items": items}


@router.get("/latest", response_model=list[schemas.BioprojectOut])
def latest_bioprojects(
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """The most recently released projects, for the search page's first view.

    No filters and no total count, so it stays fast on the full table (uses
    bioprojects_release_date_idx from backend/sql/search_indexes.sql).
    """
    stmt = (
        select(B)
        .order_by(SORTS["release_desc"], B.bioproject, B.sra_study)
        .limit(limit)
    )
    return db.scalars(stmt).all()


# Fields with few distinct values are sent whole as dropdown options. The rest
# have too many values for a dropdown and are searched through /suggest.
FACET_FIELDS = [
    "supergroup", "data_types", "objectives", "relevance", "target_material",
    "target_capture", "sample_scope", "method_type", "access", "organization_country",
    "assay_type", "platform", "instrument", "librarylayout", "librarysource",
    "libraryselection", "sample_country",
]
SUGGEST_FIELDS = ["organism", "organization", "journals", "run_organism", "center_name"]

CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}


def distinct_values(name: str) -> tuple[tuple[str, int], ...]:
    """All values of a filter field with their counts, most common first.

    Counts are projects for project fields, and studies (or runs, without
    study_facets) for run fields. Results are cached for an hour. Empty
    results are not cached, so values appear as soon as data is loaded.
    """
    cached = _cache.get(name)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    if name in RUN_FIELDS and has_study_facets():
        column = F.c[RUN_FIELDS[name][1]]
        value = func.unnest(column)
    elif name in RUN_FIELDS:
        column = RUN_FIELDS[name][0]
        value = column
    else:
        column, multivalue = PROJECT_FIELDS[name]
        value = func.unnest(split_values(column)) if multivalue else column

    sub = select(value.label("value")).where(column.is_not(None)).subquery()
    n = func.count().label("n")
    stmt = (
        select(sub.c.value, n)
        .where(sub.c.value != "")
        .group_by(sub.c.value)
        .order_by(n.desc(), sub.c.value)
    )
    with engine.connect() as conn:
        values = tuple((row.value, row.n) for row in conn.execute(stmt))
    if values:
        _cache[name] = (time.monotonic() + CACHE_SECONDS, values)
    return values


def warm_cache() -> None:
    """Compute every field's values ahead of the first request.

    Run in a background thread at startup. Without study_facets, run fields
    are skipped: each one is a full scan of sra_metadata, so they load on
    first use instead.
    """
    try:
        names = FACET_FIELDS + SUGGEST_FIELDS
        if not has_study_facets():
            names = [n for n in names if n not in RUN_FIELDS]
    except Exception:
        logger.exception("Could not load filter values")
        return
    for name in names:
        try:
            distinct_values(name)
        except Exception:
            logger.exception("Could not load filter values for %s", name)


@router.get("/facets/{field}", response_model=list[schemas.FacetValue])
def facet(field: Literal[tuple(FACET_FIELDS)]):  # type: ignore[valid-type]
    return [{"value": v, "count": n} for v, n in distinct_values(field)]


@router.get("/suggest", response_model=list[schemas.FacetValue])
def suggest(
    field: Literal[tuple(SUGGEST_FIELDS)],  # type: ignore[valid-type]
    q: str = "",
    limit: int = Query(20, ge=1, le=100),
):
    needle = q.strip().lower()
    matches = (
        {"value": v, "count": n}
        for v, n in distinct_values(field)
        if needle in v.lower()
    )
    return [m for _, m in zip(range(limit), matches)]


@router.get("/stats", response_model=schemas.Stats)
def stats(db: Session = Depends(get_db)):
    projects, studies, organisms = db.execute(
        select(
            func.count(func.distinct(B.bioproject)),
            func.count(func.distinct(B.sra_study)),
            func.count(func.distinct(B.tax_id)),
        )
    ).one()
    # sra_metadata is large, so use the planner's estimate once the table has
    # been analyzed (reltuples is -1 before that).
    runs = db.scalar(
        text("SELECT reltuples::bigint FROM pg_class WHERE relname = 'sra_metadata'")
    )
    # 0 can also mean the table wasn't analyzed since loading, so count to be sure.
    if runs is None or runs <= 0:
        runs = db.scalar(select(func.count()).select_from(R))
    return {"bioprojects": projects, "studies": studies, "organisms": organisms, "runs": runs}
