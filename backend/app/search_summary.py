"""A summary of everything a search matches, for the search page's
"Summarise results" panel: how many projects, studies and runs, when they
were released, and the most common assays, organisms, countries and sample
attributes among them.

Takes the same parameters as /search/bioprojects. The matching project-study
rows are copied once into a temporary table, which every count then reads.
Results are cached for an hour per search.
"""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Boolean, Column, Integer, MetaData, Table, and_, func, insert, select, text, true
from sqlalchemy.types import Text

from . import schemas, search
from .database import engine

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger(__name__)

B = search.B
# Values listed per dimension.
TOP_VALUES = 10
TIMEOUT_MS = 20000
CACHE_SIZE = 200
_cache: dict[str, tuple[float, dict]] = {}

# The search's rows; dropped at the end of the transaction that fills it.
M = Table(
    "search_matched",
    MetaData(),
    Column("bioproject", Text),
    Column("sra_study", Text),
    Column("year", Integer),
    Column("country", Text),
    Column("published", Boolean),
    Column("geo", Boolean),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

# Run attributes, counted in studies: name -> (label, study_facets column,
# the search page's filter for a value or None, values meaning "not known").
STUDY_DIMENSIONS = {
    "assay_type": ("Assay type", "assay_types", "assay_type", set()),
    "organism": ("Organism", "run_organisms", None, set()),
    "library_source": ("Library source", "library_sources", None, set()),
    "instrument": ("Instrument", "instruments", "instrument", set()),
    "sample_country": ("Sample origin country", "sample_countries", None, {"uncalculated"}),
}
# Sample attributes, counted in projects: name -> label. Filter names are the same.
ATTRIBUTE_DIMENSIONS = {
    "tissue": "Tissue",
    "cell_type": "Cell type",
    "cell_line": "Cell line",
    "disease_state": "Disease",
    "sex": "Sex",
    "molecular_target": "ChIP target",
}
UNKNOWN_COUNTRY = "Unknown or unspecified country"


def study_dimension(conn, name: str) -> dict:
    label, column, filter_name, unknown = STUDY_DIMENSIONS[name]
    params = {"unknown": list(unknown) or [""]}
    studies = "(SELECT DISTINCT sra_study FROM search_matched) s JOIN study_facets f USING (sra_study)"
    rows = conn.execute(text(f"""
        SELECT v AS value, count(*) AS n FROM {studies}, unnest(f.{column}) v
        WHERE v <> ALL(:unknown) GROUP BY v ORDER BY n DESC, v LIMIT {TOP_VALUES}
    """), params).all()
    known = conn.scalar(text(f"""
        SELECT count(*) FROM {studies}
        WHERE EXISTS (SELECT 1 FROM unnest(f.{column}) v WHERE v <> ALL(:unknown))
    """), params)
    return {
        "name": name, "label": label, "unit": "studies", "known": known, "filter": filter_name,
        "values": [{"value": r.value, "count": r.n} for r in rows],
    }


def attribute_dimension(conn, name: str) -> dict:
    projects = "(SELECT DISTINCT bioproject FROM search_matched) p JOIN bioproject_attribute_values a USING (bioproject)"
    # Spellings differing only in case count as one value, shown in its most common spelling.
    rows = conn.execute(text(f"""
        SELECT mode() WITHIN GROUP (ORDER BY a.value) AS value, count(*) AS n FROM {projects}
        WHERE a.field = :field AND a.value_key <> '' GROUP BY a.value_key ORDER BY n DESC, a.value_key LIMIT {TOP_VALUES}
    """), {"field": name}).all()
    known = conn.scalar(text(f"SELECT count(DISTINCT p.bioproject) FROM {projects} WHERE a.field = :field"), {"field": name})
    return {
        "name": name, "label": ATTRIBUTE_DIMENSIONS[name], "unit": "projects", "known": known, "filter": name,
        "values": [{"value": r.value, "count": r.n} for r in rows],
    }


def submitter_countries(conn) -> dict:
    per_project = "SELECT bioproject, min(country) AS country FROM search_matched GROUP BY bioproject"
    rows = conn.execute(text(f"""
        SELECT country AS value, count(*) AS n FROM ({per_project}) p
        WHERE country IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT {TOP_VALUES}
    """)).all()
    known = conn.scalar(text(f"SELECT count(*) FROM ({per_project}) p WHERE country IS NOT NULL"))
    return {
        "name": "submitter_country", "label": "Submitter country", "unit": "projects", "known": known,
        "filter": "organization_country", "values": [{"value": r.value, "count": r.n} for r in rows],
    }


def compute(filters: search.SiteSearchFilters) -> dict:
    with engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
        # NULL when not given.
        country = func.nullif(func.nullif(func.trim(B.organization_country), ""), UNKNOWN_COUNTRY)
        rows = select(
            B.bioproject,
            B.sra_study,
            func.extract("year", B.release_date).cast(Integer),
            country,
            func.coalesce(B.publication_count, 0) > 0,
            func.coalesce(B.geo_accessions, "") != "",
        ).where(and_(true(), *search.build_conditions(filters)))
        q = (filters.q or "").strip()
        if q:
            _, fused = search.fused_matches(conn, q)
            rows = rows.join(fused, fused.c.bioproject == B.bioproject)
        M.create(conn)
        conn.execute(insert(M).from_select([c.name for c in M.columns], rows))
        conn.execute(text("ANALYZE search_matched"))

        totals = conn.execute(text("""
            SELECT count(DISTINCT bioproject) AS projects,
                   count(DISTINCT sra_study) AS studies,
                   count(DISTINCT bioproject) FILTER (WHERE published) AS published,
                   count(DISTINCT bioproject) FILTER (WHERE geo) AS geo
            FROM search_matched
        """)).one()
        runs = conn.scalar(text("""
            SELECT coalesce(sum(f.n_runs), 0)
            FROM (SELECT DISTINCT sra_study FROM search_matched) s JOIN study_facets f USING (sra_study)
        """))
        years = conn.execute(text("""
            SELECT year, count(*) AS n
            FROM (SELECT bioproject, min(year) AS year FROM search_matched GROUP BY bioproject) p
            WHERE year IS NOT NULL GROUP BY year ORDER BY year
        """)).all()

        dimensions = [study_dimension(conn, name) for name in STUDY_DIMENSIONS]
        dimensions.insert(2, submitter_countries(conn))
        if search.has_relation("bioproject_attribute_values"):
            dimensions += [attribute_dimension(conn, name) for name in ATTRIBUTE_DIMENSIONS]
    return {
        "projects": totals.projects,
        "studies": totals.studies,
        "runs": runs,
        "projects_published": totals.published,
        "projects_geo": totals.geo,
        "years": [{"year": r.year, "count": r.n} for r in years],
        "dimensions": dimensions,
    }


@router.get("/summary", response_model=schemas.SearchSummary)
def search_summary(filters: Annotated[search.SiteSearchFilters, Query()]):
    if not search.has_study_facets():
        raise HTTPException(status_code=503, detail="Result summaries need the study_facets view.")
    key = filters.model_dump_json(exclude={"sort", "limit", "offset"})
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        summary = compute(filters)
    except Exception as e:
        if "statement timeout" in str(e):
            raise HTTPException(
                status_code=503,
                detail="This search matches too many projects to summarise quickly. Narrow it down and try again.",
            )
        raise
    if len(_cache) >= CACHE_SIZE:
        _cache.clear()
    _cache[key] = (time.monotonic() + search.CACHE_SECONDS, summary)
    return summary
