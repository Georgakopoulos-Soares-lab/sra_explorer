"""Normalising the values the search filters use.

Values come from submitters and are spelled many ways ("Liver", "liver",
"LIVER"; "WT", "wild type"). The admin page (/admin/normalize) lets one
rename a value, which changes it at once in every row where it is stored, and
records the rename as a rule in value_normalizations. The weekly data load
drops and recreates the data tables, so after a load the rules are applied
again (apply_all, or `python -m app.normalize apply`), and the normalisation
done so far is kept. See docs/normalization.md.

Each field says where its values live:
  column     a bioprojects column (organism_name, supergroup, organization_country)
  run        sra_metadata.assay_type, summarised per study in study_facets
  attribute  a list in bioproject_attributes.attributes (tissue, sex, ...),
             summarised in bioproject_attribute_values

Besides renames, a rule can capitalise the first letter of every value of a
field ("liver" -> "Liver", "eWAT tissue" -> "EWAT tissue"; the rest of the
value is kept). It is recorded once and replayed in order with the renames.

Renames and re-applies run as background jobs, one at a time: a run field
rename updates sra_metadata (42 million rows), and refreshing a materialized
view afterwards takes seconds to minutes. The admin page polls the job.
"""

import logging
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import search, statistics
from .database import engine

logger = logging.getLogger(__name__)

ATTRIBUTE_REFRESH = ["bioproject_attribute_values"]

# Field name (as the search API's parameter) -> where its values are stored.
# "refresh" lists the materialized views built from that storage, refreshed
# after a change so the filters see it.
FIELDS: dict[str, dict] = {
    "organism": {
        "label": "Organism", "kind": "column", "column": "organism_name", "counts": "projects",
        # bioproject_fulltext embeds organism_name in the searchable text.
        "refresh": ["bioproject_fulltext"],
    },
    "supergroup": {"label": "Supergroup", "kind": "column", "column": "supergroup", "counts": "projects", "refresh": []},
    "organization_country": {
        "label": "Country", "kind": "column", "column": "organization_country", "counts": "projects", "refresh": [],
    },
    "assay_type": {
        "label": "Assay type", "kind": "run", "column": "assay_type", "facet": "assay_types", "counts": "studies",
        "refresh": ["study_facets"],
    },
    "cell_line": {"label": "Cell line", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH},
    "cell_type": {"label": "Cell type", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH},
    "tissue": {
        "label": "Tissue", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH,
        # GEO source names stand in as the tissue of projects without one
        # (bioproject_attribute_values.sql), so they are renamed too.
        "also": ["source_name"],
    },
    "sex": {"label": "Sex", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH},
    "disease_state": {"label": "Disease", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH},
    "genotype_or_strain": {
        "label": "Genotype or strain", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH,
    },
    "treatment_or_growth_condition": {
        "label": "Treatment or condition", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH,
    },
    "molecular_target": {
        "label": "ChIP target", "kind": "attribute", "counts": "projects", "refresh": ATTRIBUTE_REFRESH,
    },
}

# What one row of a field's storage is, for the "rows changed" numbers.
ROW_NAMES = {"column": "project-study rows", "run": "runs", "attribute": "projects"}


def _like_pattern(q: str) -> str:
    """A LIKE pattern matching q anywhere, with q's own wildcards escaped."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_values(name: str, q: str = "", limit: int = 100, offset: int = 0) -> dict:
    """A field's distinct values with their counts, most common first.

    Exact spellings are listed separately ("Liver" and "liver"), since each
    is renamed on its own. q narrows to values containing it, ignoring case.
    Returns {"total": number of distinct values, "items": [{value, count}]}.
    """
    spec = FIELDS[name]
    params: dict = {"limit": limit, "offset": offset}
    where = ""
    if q:
        where = "AND v ILIKE :pattern"
        params["pattern"] = _like_pattern(q)
    if spec["kind"] == "column":
        col = spec["column"]
        source = f"(SELECT {col} AS v, bioproject FROM bioprojects WHERE {col} IS NOT NULL) s"
        count = "count(DISTINCT bioproject)"
    elif spec["kind"] == "run":
        if not search.has_study_facets():
            raise RuntimeError("study_facets has not been created, so run values can't be listed.")
        source = f"(SELECT unnest({spec['facet']}) AS v FROM study_facets) s"
        count = "count(*)"
    else:
        params["field"] = name
        source = (
            "(SELECT v FROM bioproject_attributes a, jsonb_array_elements_text("
            " CASE WHEN jsonb_typeof(a.attributes -> CAST(:field AS text)) = 'array'"
            " THEN a.attributes -> CAST(:field AS text) ELSE '[]'::jsonb END) AS v) s"
        )
        count = "count(*)"
    sql = f"""
        SELECT v AS value, {count} AS n, count(*) OVER () AS total
        FROM {source}
        WHERE v <> '' {where}
        GROUP BY v
        ORDER BY n DESC, v
        LIMIT :limit OFFSET :offset
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    return {"total": rows[0].total if rows else 0, "items": [{"value": r.value, "count": r.n} for r in rows]}


RENAME = "rename"
CAPITALIZE = "capitalize"
ACTIONS = (RENAME, CAPITALIZE)


def _capitalized(value_sql: str) -> str:
    """SQL for value_sql with its first character upper-cased, the rest kept."""
    return f"upper(left({value_sql}, 1)) || substr({value_sql}, 2)"


def _starts_lowercase(value_sql: str) -> str:
    """SQL: true when capitalising would change the value."""
    return f"left({value_sql}, 1) <> upper(left({value_sql}, 1))"


def apply_rule(conn: Connection, name: str, action: str, from_value: str = "", to_value: str = "") -> int:
    """Applies one rule to the field's storage; returns the rows changed.

    rename: from_value -> to_value. capitalize: every value's first letter
    (from_value and to_value unused). Runs in the caller's transaction.
    Doesn't record a rule or refresh views.
    """
    spec = FIELDS[name]
    params = {"from": from_value, "to": to_value}
    if spec["kind"] in ("column", "run"):
        table = "bioprojects" if spec["kind"] == "column" else "sra_metadata"
        col = spec["column"]
        if action == RENAME:
            sql = f"UPDATE {table} SET {col} = :to WHERE {col} = :from"
        else:
            sql = f"UPDATE {table} SET {col} = {_capitalized(col)} WHERE {_starts_lowercase(col)}"
        return conn.execute(text(sql), params).rowcount
    # A list in bioproject_attributes; projects changed, each counted once even
    # if several of its lists changed.
    if action == RENAME:
        new_value, needs_change = "CASE WHEN e = :from THEN :to ELSE e END", "jsonb_exists(a.attributes -> CAST(:field AS text), :from)"
    else:
        new_value = _capitalized("e")
        needs_change = (
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.attributes -> CAST(:field AS text)) AS l(e)"
            f" WHERE {_starts_lowercase('e')})"
        )
    changed: set[str] = set()
    for key in [name, *spec.get("also", [])]:
        changed |= _rewrite_list(conn, key, new_value, needs_change, params)
    return len(changed)


def rename_rows(conn: Connection, name: str, from_value: str, to_value: str) -> int:
    """Changes from_value to to_value in the field's storage; returns the rows changed."""
    return apply_rule(conn, name, RENAME, from_value, to_value)


def _rewrite_list(conn: Connection, key: str, new_value: str, needs_change: str, params: dict) -> set[str]:
    """Rewrites each element e of the list under key in bioproject_attributes.attributes
    to new_value (SQL over e), in the projects where needs_change (SQL over a.attributes)
    holds. Keeps the list's order and drops duplicates the rewrite creates.
    Returns the projects changed."""
    return set(conn.execute(text(f"""
            UPDATE bioproject_attributes a
            SET attributes = jsonb_set(a.attributes, ARRAY[CAST(:field AS text)], (
                SELECT coalesce(jsonb_agg(x ORDER BY first_ord), '[]'::jsonb)
                FROM (
                    SELECT x, min(ord) AS first_ord
                    FROM (
                        SELECT {new_value} AS x, ord
                        FROM jsonb_array_elements_text(a.attributes -> CAST(:field AS text)) WITH ORDINALITY AS t(e, ord)
                    ) rewritten
                    GROUP BY x
                ) deduped
            ))
            WHERE jsonb_typeof(a.attributes -> CAST(:field AS text)) = 'array'
              AND {needs_change}
            RETURNING a.bioproject
        """), {**params, "field": key}).scalars())


def ensure_schema() -> None:
    """Adds the action column to a value_normalizations table made before it
    existed (create_all doesn't alter tables). Existing rules are renames."""
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE value_normalizations ADD COLUMN IF NOT EXISTS action text NOT NULL DEFAULT 'rename'"
        ))


def record_rule(conn: Connection, name: str, from_value: str, to_value: str, rows: int, action: str = RENAME) -> int:
    return conn.execute(text("""
        INSERT INTO value_normalizations (field, action, from_value, to_value, rows)
        VALUES (:field, :action, :from, :to, :rows) RETURNING id
    """), {"field": name, "action": action, "from": from_value, "to": to_value, "rows": rows}).scalar_one()


def list_rules(name: Optional[str] = None) -> list[dict]:
    """The recorded renames, oldest first (the order they are applied in)."""
    sql = "SELECT id, field, action, from_value, to_value, rows, created_at FROM value_normalizations"
    params = {}
    if name:
        sql += " WHERE field = :field"
        params["field"] = name
    sql += " ORDER BY id"
    with engine.connect() as conn:
        return [
            {**row._mapping, "created_at": row.created_at.isoformat() if row.created_at else None}
            for row in conn.execute(text(sql), params)
        ]


def delete_rule(rule_id: int) -> bool:
    """Forgets a rule, so it isn't applied after the next data load. Rows
    already changed stay as they are."""
    with engine.begin() as conn:
        return conn.execute(text("DELETE FROM value_normalizations WHERE id = :id"), {"id": rule_id}).rowcount > 0


def refresh_views(views: list[str]) -> tuple[list[str], list[str]]:
    """Refreshes the materialized views that exist, outside any transaction
    (REFRESH ... CONCURRENTLY can't run inside one).

    Existence is checked now, not through has_relation's one-minute cache,
    since a data load may just have dropped a view. A view that fails to
    refresh doesn't stop the others; the data change before it is already
    committed. Returns (views refreshed, "view: error" for those that failed).
    """
    refreshed, failed = [], []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for view in dict.fromkeys(views):
            if not conn.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": view}):
                continue
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
                refreshed.append(view)
            except Exception as e:  # noqa: BLE001 - reported in the job
                logger.exception("Could not refresh %s", view)
                failed.append(f"{view}: {type(e).__name__}: {str(e).splitlines()[0]}")
    return refreshed, failed


def _after_change(views: list[str]) -> dict:
    """Refreshes the views after a committed change, and forgets cached filter
    values both before (so the change shows at once where no view is involved)
    and after (so values read during the refresh aren't kept)."""
    search.clear_value_caches()
    try:
        refreshed, failed = refresh_views(views)
    finally:
        search.clear_value_caches()
        statistics.mark_stale()
    return {"refreshed": refreshed, "refresh_failed": failed}


def run_rename(name: str, from_values: list[str], to_value: str) -> dict:
    """Renames each from_value to to_value, records the rules, refreshes the
    field's views, and forgets cached filter values."""
    rows = 0
    with engine.begin() as conn:
        for from_value in from_values:
            changed = rename_rows(conn, name, from_value, to_value)
            # Renaming back (A -> B, then B -> A): the earlier rule would turn
            # A into B on every reload only for this one to turn it back, and
            # with both kept the rules never settle. B -> A alone has the net
            # effect, so the earlier rule goes.
            conn.execute(text("""
                DELETE FROM value_normalizations
                WHERE field = :field AND action = 'rename' AND from_value = :to AND to_value = :from
            """), {"field": name, "from": from_value, "to": to_value})
            record_rule(conn, name, from_value, to_value, changed)
            rows += changed
    return {"rows": rows, **_after_change(FIELDS[name]["refresh"])}


def run_capitalize(name: str) -> dict:
    """Capitalises the first letter of every value of the field, records the
    rule, refreshes the field's views, and forgets cached filter values."""
    with engine.begin() as conn:
        rows = apply_rule(conn, name, CAPITALIZE)
        record_rule(conn, name, "", "", rows, CAPITALIZE)
    return {"rows": rows, **_after_change(FIELDS[name]["refresh"])}


def apply_all() -> dict:
    """Applies every recorded rule again, in the order they were made, so a
    newly loaded table ends up normalised like the old one. Chains (A -> B
    recorded, then B -> C) resolve because B -> C runs after A -> B."""
    rules = list_rules()
    rows = 0
    touched: set[str] = set()
    with engine.begin() as conn:
        for rule in rules:
            if rule["field"] not in FIELDS:
                logger.warning("Skipping rule %s for unknown field %s", rule["id"], rule["field"])
                continue
            if rule["action"] not in ACTIONS:
                logger.warning("Skipping rule %s with unknown action %s", rule["id"], rule["action"])
                continue
            changed = apply_rule(conn, rule["field"], rule["action"], rule["from_value"], rule["to_value"])
            rows += changed
            if changed:
                touched.add(rule["field"])
    return {
        "rules": len(rules),
        "rows": rows,
        **_after_change([view for name in touched for view in FIELDS[name]["refresh"]]),
    }


# ---------------------------------------------------------------- jobs
@dataclass
class Job:
    id: str
    kind: str  # "rename", "capitalize" or "apply"
    field: Optional[str] = None
    from_values: list[str] = dc_field(default_factory=list)
    to_value: Optional[str] = None
    status: str = "queued"  # queued, running, done, failed
    rows: int = 0
    refreshed: list[str] = dc_field(default_factory=list)
    message: str = ""
    created_at: float = dc_field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("created_at", "started_at", "finished_at"):
            if d[key] is not None:
                d[key] = datetime.fromtimestamp(d[key], timezone.utc).isoformat()
        return d


JOBS_KEPT = 50
_jobs: list[Job] = []
_queue: "queue.Queue[tuple[Job, object]]" = queue.Queue()
_worker: Optional[threading.Thread] = None
_lock = threading.Lock()


def _work() -> None:
    while True:
        job, fn = _queue.get()
        job.status, job.started_at = "running", time.time()
        try:
            result = fn()
            job.rows, job.refreshed, job.status = result["rows"], result.get("refreshed", []), "done"
            notes = [f"{result['rules']} rules applied."] if job.kind == "apply" else []
            if result.get("refresh_failed"):
                # The rows are changed and the rules recorded; only the views
                # lag. Re-applying the rules refreshes them.
                notes.append("The values were changed, but refreshing failed for "
                              + "; ".join(result["refresh_failed"])
                              + ". Re-apply all rules to retry the refresh.")
            job.message = " ".join(notes)
        except Exception as e:  # noqa: BLE001 - reported to the admin page
            logger.exception("Normalisation job %s failed", job.id)
            job.status, job.message = "failed", f"{type(e).__name__}: {e}"
        job.finished_at = time.time()


def submit(job: Job, fn) -> Job:
    """Queues a job; jobs run one at a time in a background thread."""
    global _worker
    with _lock:
        _jobs.append(job)
        # Drop the oldest finished jobs beyond JOBS_KEPT; never a queued or
        # running one, which the page may be polling.
        finished = [j for j in _jobs if j.status in ("done", "failed")]
        for old in finished[: max(0, len(_jobs) - JOBS_KEPT)]:
            _jobs.remove(old)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="normalize-jobs")
            _worker.start()
    _queue.put((job, fn))
    return job


def submit_rename(name: str, from_values: list[str], to_value: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind="rename", field=name, from_values=from_values, to_value=to_value)
    return submit(job, lambda: run_rename(name, from_values, to_value))


def submit_capitalize(name: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind="capitalize", field=name)
    return submit(job, lambda: run_capitalize(name))


def submit_apply() -> Job:
    return submit(Job(id=uuid.uuid4().hex[:12], kind="apply"), apply_all)


def list_jobs() -> list[dict]:
    """Recent jobs, newest first."""
    return [job.to_dict() for job in reversed(_jobs)]


def main(argv: list[str]) -> int:
    """`python -m app.normalize apply`: apply all rules, e.g. after a data load."""
    if argv[1:] != ["apply"]:
        print("usage: python -m app.normalize apply", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from . import models  # noqa: F401 - registers ValueNormalization
    from .database import Base

    # The rules table, if the API has never started on this database.
    Base.metadata.create_all(bind=engine, tables=[models.ValueNormalization.__table__])
    ensure_schema()
    result = apply_all()
    print(f"applied {result['rules']} rules, changed {result['rows']:,} rows, "
          f"refreshed {', '.join(result['refreshed']) or 'no views'}")
    for failure in result["refresh_failed"]:
        print(f"refresh failed: {failure}", file=sys.stderr)
    # This process can't reach a running API's caches; it shows the new
    # values within an hour, or at once after a restart.
    print("A running API shows the changes within an hour, or at once after a restart.")
    return 1 if result["refresh_failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
