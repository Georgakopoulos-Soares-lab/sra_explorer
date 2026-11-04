"""Database statistics for the statistics page (/statistics).

Everything is computed in one go and cached for a week. Counting runs per
year, assay type, platform and library source reads all of sra_metadata
(about 40 s on 42 million runs), so the numbers are computed at startup in
the background, and refreshed in the background once they are a week old:
requests get the cached numbers meanwhile and only the very first request,
before the startup computation is done, waits for it.

Counting units, stated on the page for each chart:
- projects: distinct BioProjects, dated by their earliest release_date
  (backend/sql/release_date.sql);
- studies: SRA studies (study_facets), dated by the release of their first run;
- runs: SRA runs, dated by their own release date.
Run attributes (assay type, platform, ...) are lists per study, so a study
with RNA-Seq and ChIP-Seq runs counts once for each.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from . import schemas, search
from .database import engine

router = APIRouter(prefix="/statistics", tags=["statistics"])
logger = logging.getLogger(__name__)

# The data is loaded weekly, and the admin pages mark the cache stale after
# their own changes (mark_stale), so a week.
CACHE_SECONDS = 7 * 24 * 3600
# Values listed per dimension, most common first; the rest are only counted in totals.
TOP_VALUES = 40
# Values with a count per year, for the charts over time.
TOP_BY_YEAR = 20
# Years before this have a handful of projects with odd dates.
FIRST_YEAR = 2007

# Dimension name -> (label, study_facets array column, values meaning "not known").
STUDY_DIMENSIONS = {
    "assay_type": ("Assay type", "assay_types", set()),
    "platform": ("Sequencing platform", "platforms", set()),
    "instrument": ("Instrument", "instruments", set()),
    "library_source": ("Library source", "library_sources", set()),
    "library_layout": ("Library layout", "library_layouts", set()),
    "organism": ("Organism", "run_organisms", set()),
    "sample_country": ("Sample origin country", "sample_countries", {"uncalculated"}),
}
# Run dimensions also counted in runs: dimension -> sra_metadata column.
RUN_COLUMNS = {
    "assay_type": "assay_type",
    "platform": "platform",
    "library_source": "librarysource",
}
UNKNOWN_COUNTRIES = {"Unknown or unspecified country"}

_lock = threading.Lock()
_cache: tuple[float, Optional[dict]] = (0, None)


def year(column: str) -> str:
    return f"extract(year FROM {column})::int"


def study_dimension(conn, name: str) -> dict:
    label, column, unknown_values = STUDY_DIMENSIONS[name]
    rows = conn.execute(text(f"""
        SELECT v AS value, count(*) AS n
        FROM study_facets, unnest({column}) v
        GROUP BY v ORDER BY n DESC, v
    """)).all()
    # Studies without a known value: an empty list, or only "unknown" values.
    known = column
    for i in range(len(unknown_values)):
        known = f"array_remove({known}, :unknown{i})"
    params = {f"unknown{i}": v for i, v in enumerate(sorted(unknown_values))}
    unknown = conn.scalar(text(f"SELECT count(*) FROM study_facets WHERE cardinality({known}) = 0"), params)
    values = [(r.value, r.n) for r in rows if r.value not in unknown_values]
    top = [v for v, _ in values[:TOP_BY_YEAR]]
    by_year = conn.execute(text(f"""
        SELECT {year('first_run_release')} AS year, v AS value, count(*) AS n
        FROM study_facets, unnest({column}) v
        WHERE v = ANY(:top) AND first_run_release IS NOT NULL
        GROUP BY 1, 2
    """), {"top": top}).all()
    known_by_year = conn.execute(text(f"""
        SELECT {year('first_run_release')} AS year, count(*) AS n
        FROM study_facets WHERE cardinality({known}) > 0 AND first_run_release IS NOT NULL
        GROUP BY 1
    """), params).all()
    return {
        "name": name,
        "label": label,
        "unit": "studies",
        "distinct": len(values),
        "unknown": unknown,
        "values": [{"value": v, "count": n} for v, n in values[:TOP_VALUES]],
        "by_year": [
            {"year": r.year, "value": r.value, "count": r.n} for r in by_year if r.year >= FIRST_YEAR
        ],
        "known_by_year": [{"year": r.year, "count": r.n} for r in known_by_year if r.year >= FIRST_YEAR],
    }


# One row per BioProject: its first release year and its submitter's country
# (NULL when not known). A project spans several rows when it has several
# studies; they share the country.
PROJECT_COUNTRIES = f"""
    SELECT bioproject, {year('min(release_date)')} AS year,
           min(nullif(trim(organization_country), '')) FILTER (WHERE organization_country <> ALL(:unknown)) AS value
    FROM bioprojects GROUP BY bioproject
"""


def submitter_countries(conn) -> dict:
    """Projects per submitting organisation's country (a BioProject field)."""
    params = {"unknown": list(UNKNOWN_COUNTRIES)}
    rows = conn.execute(text(f"""
        SELECT value, count(*) AS n FROM ({PROJECT_COUNTRIES}) p GROUP BY 1 ORDER BY n DESC, value
    """), params).all()
    unknown = sum(r.n for r in rows if r.value is None)
    values = [(r.value, r.n) for r in rows if r.value is not None]
    top = [v for v, _ in values[:TOP_BY_YEAR]]
    by_year = conn.execute(text(f"""
        SELECT year, value, count(*) AS n FROM ({PROJECT_COUNTRIES}) p
        WHERE value = ANY(:top) AND year IS NOT NULL GROUP BY 1, 2
    """), {**params, "top": top}).all()
    known_by_year = conn.execute(text(f"""
        SELECT year, count(*) AS n FROM ({PROJECT_COUNTRIES}) p
        WHERE value IS NOT NULL AND year IS NOT NULL GROUP BY 1
    """), params).all()
    return {
        "name": "submitter_country",
        "label": "Submitter country",
        "unit": "projects",
        "distinct": len(values),
        "unknown": unknown,
        "values": [{"value": v, "count": n} for v, n in values[:TOP_VALUES]],
        "by_year": [
            {"year": r.year, "value": r.value, "count": r.n} for r in by_year if r.year >= FIRST_YEAR
        ],
        "known_by_year": [{"year": r.year, "count": r.n} for r in known_by_year if r.year >= FIRST_YEAR],
    }


def compute() -> dict:
    if not search.has_study_facets():
        raise RuntimeError("The statistics need the study_facets view (backend/sql/study_facets.sql).")
    started = time.monotonic()
    years: dict[int, dict] = defaultdict(lambda: {
        "projects": 0, "studies": 0, "runs": 0, "projects_published": 0, "projects_geo": 0,
    })
    with engine.connect() as conn:
        # One row per BioProject: its first release and whether any of its
        # studies has a publication or a GEO series.
        projects = conn.execute(text(f"""
            SELECT {year('d')} AS year, count(*) AS n,
                   count(*) FILTER (WHERE published) AS published,
                   count(*) FILTER (WHERE geo) AS geo
            FROM (
                SELECT bioproject, min(release_date) AS d,
                       bool_or(coalesce(publication_count, 0) > 0) AS published,
                       bool_or(coalesce(geo_accessions, '') <> '') AS geo
                FROM bioprojects GROUP BY bioproject
            ) p
            WHERE d IS NOT NULL GROUP BY 1
        """)).all()
        for r in projects:
            years[r.year].update(projects=r.n, projects_published=r.published, projects_geo=r.geo)
        for r in conn.execute(text(f"""
            SELECT {year('first_run_release')} AS year, count(*) AS n
            FROM study_facets WHERE first_run_release IS NOT NULL GROUP BY 1
        """)):
            years[r.year]["studies"] = r.n
        # Days from a project's release to its first publication, for those
        # published after release (earlier dates are older papers the data
        # was attached to).
        lag = conn.execute(text("""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY lag) AS median, count(*) AS n
            FROM (
                SELECT min(first_publication_date) - min(release_date) AS lag
                FROM bioprojects WHERE first_publication_date IS NOT NULL AND release_date IS NOT NULL
                GROUP BY bioproject
            ) p WHERE lag >= 0
        """)).one()
        n_projects, organisms = conn.execute(text("""
            SELECT (SELECT count(DISTINCT bioproject) FROM bioprojects),
                   (SELECT count(DISTINCT v) FROM study_facets, unnest(run_organisms) v)
        """)).one()
        data_through = conn.scalar(text(
            "SELECT max(last_run_release) FROM study_facets WHERE last_run_release <= current_date"
        ))
        dimensions = {name: study_dimension(conn, name) for name in STUDY_DIMENSIONS}
        dimensions["submitter_country"] = submitter_countries(conn)

        # Runs: one pass over sra_metadata. Every run counts once per year
        # and once in each dimension.
        run_counts = {name: defaultdict(int) for name in RUN_COLUMNS}
        runs_total = 0
        for r in conn.execute(text(f"""
            SELECT {year('releasedate')} AS year, {', '.join(f'{c} AS {n}' for n, c in RUN_COLUMNS.items())},
                   count(*) AS n
            FROM sra_metadata GROUP BY 1, {', '.join(str(i + 2) for i in range(len(RUN_COLUMNS)))}
        """)):
            runs_total += r.n
            if r.year is not None:
                years[r.year]["runs"] += r.n
            for name in RUN_COLUMNS:
                value = getattr(r, name)
                if value:
                    run_counts[name][value] += r.n
        for name, counts in run_counts.items():
            for item in dimensions[name]["values"]:
                item["runs"] = counts.get(item["value"], 0)

    logger.info("Computed the database statistics in %.0f s", time.monotonic() - started)
    published = sum(y["projects_published"] for y in years.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through": data_through,
        "totals": {
            "projects": n_projects,
            "studies": sum(y["studies"] for y in years.values()),
            "runs": runs_total,
            "organisms": organisms,
            "assay_types": dimensions["assay_type"]["distinct"],
            "submitter_countries": dimensions["submitter_country"]["distinct"],
            "sample_countries": dimensions["sample_country"]["distinct"],
            "projects_published": published,
            "projects_geo": sum(y["projects_geo"] for y in years.values()),
            "publication_lag_days": lag.median,
            "publication_lag_projects": lag.n,
        },
        "years": [
            {"year": y, **years[y]}
            for y in sorted(years)
            if FIRST_YEAR <= y and (data_through is None or y <= data_through.year)
        ],
        "dimensions": list(dimensions.values()),
    }


def refresh() -> None:
    """Computes the statistics and caches them; does nothing if a computation
    is already running."""
    global _cache
    if not _lock.acquire(blocking=False):
        return
    try:
        _cache = (time.monotonic() + CACHE_SECONDS, compute())
    except Exception:
        logger.exception("Could not compute the database statistics")
    finally:
        _lock.release()


def mark_stale() -> None:
    """After the data changed (normalize.py): the next request still gets the
    cached numbers and starts computing new ones."""
    global _cache
    _cache = (0, _cache[1])


@router.get("", response_model=schemas.DatabaseStatistics)
def statistics():
    global _cache
    expires, data = _cache
    if data is None:
        # Before the startup computation is done: wait for it (or run it).
        with _lock:
            if _cache[1] is None:
                try:
                    _cache = (time.monotonic() + CACHE_SECONDS, compute())
                except RuntimeError as e:
                    raise HTTPException(status_code=503, detail=str(e))
        return _cache[1]
    if expires <= time.monotonic():
        threading.Thread(target=refresh, daemon=True).start()
    return data
