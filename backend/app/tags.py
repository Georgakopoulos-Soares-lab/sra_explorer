"""The tag explorer page (/tags): what the tag words cover, the most common
tags, how they go together, and projects found through tags.

Two endpoints:

- GET /tags/overview: everything on the page that doesn't depend on a chosen
  tag. Counting over all tags takes several seconds (each project's tag list
  is unnested, and the top tags are joined with themselves for co-occurrence),
  so it is computed in the background at startup and cached for a week, like
  the statistics page (statistics.py). The admin pages mark it stale after
  changing data; a request then gets the cached numbers and starts a new
  computation.
- GET /tags/related: for one or more chosen tags, how many projects have them,
  the tags most often found with them, the projects' organisms and release
  years. Fast (the GIN index on the tag arrays finds the projects), and
  cached per request for an hour.

Tags are described in docs/bioproject-tags.md. The data is the bioproject_tags
table: one row per project, tags "; "-separated, most relevant first, with the
tag types ("labels") in the same order where the tagging run kept them.
"""

import logging
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import schemas, search
from .database import engine

router = APIRouter(prefix="/tags", tags=["tags"])
logger = logging.getLogger(__name__)

CACHE_SECONDS = 7 * 24 * 3600
# Tags listed with their counts, most common first.
TOP_TAGS = 300
# Tags in the co-occurrence network (the most common ones), and the fewest
# shared projects an edge needs. Enough nodes are kept that the network is
# still full after the page hides organism names.
NETWORK_TAGS = 80
NETWORK_MIN_SHARED = 20
# Tags with a count per release year, for the chart over time.
TOP_BY_YEAR = 20
# Years before this have a handful of projects with odd dates.
FIRST_YEAR = 2007
# Bands of the "how many tags are on at least N projects" summary.
FREQUENCY_BANDS = [1, 2, 10, 100, 1000]

# Common names of organisms, which are tags but never a project's organism
# name, so the organism flag can still leave them out of the other tags.
COMMON_ORGANISM_WORDS = {
    "mouse", "mice", "human", "humans", "rat", "rats", "bacteria", "bacterium", "fungi", "fungus", "virus",
    "viruses", "yeast", "zebrafish", "archaea", "phage", "bacteriophage", "nematode", "fly", "fruit fly",
    "pig", "chicken", "cattle", "cow", "sheep", "dog", "cat", "horse", "monkey", "macaque", "frog", "worm",
    "plant", "plants", "animal", "mammal", "primate", "rodent", "insect", "fish", "bird", "algae", "microalgae",
    "cyanobacteria", "protist", "parasite", "pathogen",
}

# /tags/related
RELATED_TAGS = 30
RELATED_ORGANISMS = 10
RELATED_CACHE_SIZE = 500
RELATED_TIMEOUT_MS = 15000
RELATED_MAX_TAGS = 10

_lock = threading.Lock()
_cache: tuple[float, Optional[dict]] = (0, None)
# Bumped by mark_stale, so a refresh that was already computing when the data
# changed stores its (older) numbers as stale instead of as fresh.
_generation = 0
_related: dict[str, tuple[float, dict]] = {}


def year(column: str) -> str:
    return f"extract(year FROM {column})::int"


# The tags of each project as an array; the separator is inlined so the GIN
# index on this exact expression is used (see search.tag_array).
TAGS = "string_to_array(g.tags, '; ')"


def has_labels(conn) -> bool:
    """Whether bioproject_tags has a labels column with any types in it."""
    column = conn.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'bioproject_tags' AND column_name = 'labels')"
    ))
    if not column:
        return False
    return bool(conn.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM bioproject_tags WHERE coalesce(labels, '') <> '')"
    )))


def organism_tags(conn, tags: list[str]) -> set[str]:
    """The given tags that name an organism: a project's organism name, or a
    common name (COMMON_ORGANISM_WORDS). So organisms are known even where the
    tag types aren't."""
    if not tags:
        return set()
    rows = conn.execute(text(
        "SELECT DISTINCT organism_name FROM bioprojects WHERE organism_name = ANY(:tags)"
    ), {"tags": tags})
    return {r.organism_name for r in rows} | {t for t in tags if t.lower() in COMMON_ORGANISM_WORDS}


def compute() -> dict:
    started = time.monotonic()
    # Every tag with its project count and type, most common first; shared
    # with the Tags filter's type-ahead.
    values = search.tag_values()
    labels = {t: label for t, _, label in values}
    top = [t for t, _, _ in values[:max(TOP_TAGS, NETWORK_TAGS)]]
    with engine.connect() as conn:
        labelled = has_labels(conn)
        organisms = organism_tags(conn, top)

        def group(tag: str) -> Optional[str]:
            return labels.get(tag) or ("organism" if tag in organisms else None)

        projects = conn.scalar(text("SELECT count(DISTINCT bioproject) FROM bioprojects"))
        totals = conn.execute(text("""
            SELECT count(*) AS tagged,
                   count(*) FILTER (WHERE tags = '') AS empty,
                   count(*) FILTER (WHERE coalesce(labels, '') <> '') AS labelled,
                   avg(cardinality(string_to_array(tags, '; '))) FILTER (WHERE tags <> '') AS mean,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY cardinality(string_to_array(tags, '; ')))
                       FILTER (WHERE tags <> '') AS median
            FROM bioproject_tags g
        """ if labelled else """
            SELECT count(*) AS tagged,
                   count(*) FILTER (WHERE tags = '') AS empty,
                   0 AS labelled,
                   avg(cardinality(string_to_array(tags, '; '))) FILTER (WHERE tags <> '') AS mean,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY cardinality(string_to_array(tags, '; ')))
                       FILTER (WHERE tags <> '') AS median
            FROM bioproject_tags g
        """)).one()
        per_project = conn.execute(text(f"""
            SELECT cardinality({TAGS}) AS n, count(*) AS projects
            FROM bioproject_tags g WHERE tags <> '' GROUP BY 1 ORDER BY 1
        """)).all()
        # Tagged and all projects per release year (a project's first release).
        coverage = conn.execute(text(f"""
            SELECT p.year, count(*) AS projects, count(g.bioproject) FILTER (WHERE g.tags <> '') AS tagged
            FROM (SELECT bioproject, {year('min(release_date)')} AS year FROM bioprojects GROUP BY bioproject) p
            LEFT JOIN bioproject_tags g USING (bioproject)
            WHERE p.year IS NOT NULL GROUP BY p.year ORDER BY p.year
        """)).all()
        by_year_tags = [t for t, _, _ in values[:TOP_BY_YEAR]]
        by_year = conn.execute(text(f"""
            SELECT p.year, u.tag, count(*) AS n
            FROM bioproject_tags g,
                 unnest({TAGS}) AS u(tag),
                 (SELECT bioproject, {year('min(release_date)')} AS year FROM bioprojects GROUP BY bioproject) p
            WHERE p.bioproject = g.bioproject AND u.tag = ANY(:tags) AND p.year IS NOT NULL
            GROUP BY 1, 2
        """), {"tags": by_year_tags}).all()
        # Projects shared by each pair of the most common tags.
        network = top[:NETWORK_TAGS]
        edges = conn.execute(text(f"""
            WITH p AS (
                SELECT g.bioproject, u.tag FROM bioproject_tags g, unnest({TAGS}) AS u(tag)
                WHERE u.tag = ANY(:tags)
            )
            SELECT a.tag AS source, b.tag AS target, count(*) AS n
            FROM p a JOIN p b ON a.bioproject = b.bioproject AND a.tag < b.tag
            GROUP BY 1, 2 HAVING count(*) >= :min ORDER BY n DESC
        """), {"tags": network, "min": NETWORK_MIN_SHARED}).all()
        types = []
        if labelled:
            types = conn.execute(text("""
                SELECT u.label AS value, count(*) AS n, count(DISTINCT u.tag) AS distinct_tags
                FROM bioproject_tags g,
                     unnest(string_to_array(g.tags, '; '), string_to_array(g.labels, '; ')) AS u(tag, label)
                WHERE coalesce(g.labels, '') <> '' AND coalesce(u.label, '') <> '' AND u.tag <> ''
                GROUP BY 1 ORDER BY n DESC
            """)).all()

    counts = [n for _, n, _ in values]
    logger.info("Computed the tag overview in %.0f s", time.monotonic() - started)
    tagged = totals.tagged - totals.empty
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "has_labels": labelled,
        "totals": {
            "projects": projects,
            "tagged": tagged,
            "empty": totals.empty,
            "labelled": totals.labelled,
            "distinct_tags": len(values),
            "occurrences": sum(counts),
            "tags_per_project_mean": float(totals.mean) if totals.mean is not None else None,
            "tags_per_project_median": float(totals.median) if totals.median is not None else None,
        },
        "frequency": [
            {"min_projects": band, "tags": sum(1 for n in counts if n >= band)} for band in FREQUENCY_BANDS
        ],
        "top": [
            {"value": t, "count": n, "group": group(t), "organism": t in organisms}
            for t, n, _ in values[:TOP_TAGS]
        ],
        "types": [{"value": r.value, "count": r.n, "distinct": r.distinct_tags} for r in types],
        "tags_per_project": [{"n": r.n, "projects": r.projects} for r in per_project],
        "coverage_by_year": [
            {"year": r.year, "projects": r.projects, "tagged": r.tagged} for r in coverage if r.year >= FIRST_YEAR
        ],
        "by_year": [{"year": r.year, "value": r.tag, "count": r.n} for r in by_year if r.year >= FIRST_YEAR],
        "network": {
            "nodes": [
                {"value": t, "count": n, "group": group(t), "organism": t in organisms}
                for t, n, _ in values[:NETWORK_TAGS]
            ],
            "edges": [{"source": r.source, "target": r.target, "count": r.n} for r in edges],
        },
    }


def refresh() -> None:
    """Computes the overview and caches it; does nothing if a computation is
    already running."""
    global _cache
    if not _lock.acquire(blocking=False):
        return
    try:
        generation = _generation
        data = compute()
        _cache = (time.monotonic() + CACHE_SECONDS if generation == _generation else 0, data)
    except Exception:
        logger.exception("Could not compute the tag overview")
    finally:
        _lock.release()


def mark_stale() -> None:
    """After the data changed: the next request still gets the cached numbers
    and starts computing new ones."""
    global _cache, _generation
    _generation += 1
    _cache = (0, _cache[1])
    _related.clear()


@router.get("/overview", response_model=schemas.TagOverview)
def overview():
    global _cache
    expires, data = _cache
    if data is None:
        # Before the startup computation is done: wait for it (or run it).
        with _lock:
            if _cache[1] is None:
                try:
                    generation = _generation
                    data = compute()
                    _cache = (time.monotonic() + CACHE_SECONDS if generation == _generation else 0, data)
                except Exception as e:
                    logger.exception("Could not compute the tag overview")
                    raise HTTPException(status_code=503, detail=f"The tag overview can't be computed: {e}")
        return _cache[1]
    if expires <= time.monotonic():
        threading.Thread(target=refresh, daemon=True).start()
    return data


class RelatedQuery(BaseModel):
    tag: list[str] = Field(default_factory=list, max_length=RELATED_MAX_TAGS)
    # Projects with at least one of the tags instead of all of them.
    tag_any: bool = False


def related(tags: list[str], tag_any: bool) -> dict:
    """What the projects with the given tags look like. See /tags/related."""
    tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if not tags:
        raise HTTPException(status_code=422, detail="Give at least one tag.")
    key = f"{'any' if tag_any else 'all'}:{chr(0).join(tags)}"
    cached = _related.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    match = f"{TAGS} && :tags" if tag_any else f"{TAGS} @> :tags"
    params = {"tags": tags}
    with engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL statement_timeout = {RELATED_TIMEOUT_MS}"))
        projects = conn.scalar(text(f"SELECT count(*) FROM bioproject_tags g WHERE {match}"), params)
        rows = conn.execute(text(f"""
            SELECT u.tag, count(*) AS n
            FROM bioproject_tags g, unnest({TAGS}) AS u(tag)
            WHERE {match} AND u.tag <> '' AND u.tag <> ALL(:tags)
            GROUP BY u.tag ORDER BY n DESC, u.tag LIMIT {RELATED_TAGS}
        """), params).all()
        # One row per project (a project has one row per SRA study), read
        # once and counted here: a few thousand rows for most tags.
        per_project = conn.execute(text(f"""
            SELECT min(nullif(trim(b.organism_name), '')) AS organism, {year('min(b.release_date)')} AS year
            FROM bioproject_tags g JOIN bioprojects b ON b.bioproject = g.bioproject
            WHERE {match} GROUP BY b.bioproject
        """), params).all()
        organism_names = organism_tags(conn, [r.tag for r in rows])

    organisms: Counter[str] = Counter(r.organism for r in per_project if r.organism)
    years: Counter[int] = Counter(r.year for r in per_project if r.year is not None and r.year >= FIRST_YEAR)
    labels = search.tag_labels()
    totals = {t: n for t, n, _ in search.tag_values()}
    result = {
        "tags": tags,
        "tag_any": tag_any,
        "projects": projects,
        "related": [
            {
                "value": r.tag,
                "count": r.n,
                # The tag's count over all tagged projects, for its lift among these.
                "total": totals.get(r.tag, r.n),
                "group": labels.get(r.tag) or ("organism" if r.tag in organism_names else None),
                "organism": r.tag in organism_names,
            }
            for r in rows
        ],
        "organisms": [
            {"value": v, "count": n} for v, n in sorted(organisms.items(), key=lambda x: (-x[1], x[0]))[:RELATED_ORGANISMS]
        ],
        "organism_known": sum(organisms.values()),
        "years": [{"year": y, "count": n} for y, n in sorted(years.items())],
    }
    if len(_related) >= RELATED_CACHE_SIZE:
        _related.clear()
    _related[key] = (time.monotonic() + search.CACHE_SECONDS, result)
    return result


@router.get("/related", response_model=schemas.TagRelated)
def related_tags(query: Annotated[RelatedQuery, Query()]):
    """The projects with the given tags: how many there are, which other tags
    they most often have (the tags given are left out), their organisms and
    their release years. A project must have every tag, or at least one with
    tag_any=true, as in the search's Tags filter."""
    try:
        return related(query.tag, query.tag_any)
    except Exception as e:
        if "statement timeout" in str(e):
            raise HTTPException(status_code=503, detail="These tags match too many projects to summarise quickly.")
        raise
