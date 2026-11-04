"""refresh step: make the rows the earlier steps loaded visible to the site.

After `runs`, `attributes` and `projects` have inserted and updated rows, the
database still shows the old picture to the API: the search filters and the
text search read materialized views, release_date (the column the search
page sorts on) is NULL for the new project rows, and values renamed on the
normalisation page come back from the pipeline in their original spelling.
This step, in order:

  1. applies the recorded normalisation rules again (`python -m app.normalize
     apply` from the backend, which also refreshes the views whose values it
     changed),
  2. refreshes the remaining materialized views CONCURRENTLY, so the site
     keeps answering from the old contents while a view is rebuilt,
  3. fills release_date (same rule as backend/sql/release_date.sql) for the
     rows whose value changes: new rows, and existing ones whose study got
     an earlier run or whose project dates were corrected in the XML,
  4. ANALYZEs the tables and views, so the planner sees the new row counts.

Everything here is idempotent: rerunning it after a crash repeats work but
never changes the result. Nothing is deleted.
"""

from __future__ import annotations

import os
import re
import subprocess

import common

# ANALYZEd at the end, when they exist: the tables the earlier steps wrote and
# the views refreshed here.
ANALYZE_RELATIONS = ["bioprojects", "sra_metadata", "bioproject_attributes", "bioproject_attributes_coverage",
                     *common.VIEWS]

# The summary line `app.normalize apply` prints, e.g.
#   applied 39 rules, changed 1,234 rows, refreshed study_facets, bioproject_fulltext
#   applied 39 rules, changed 0 rows, refreshed no views
NORMALIZE_SUMMARY = re.compile(r"^applied (\d+) rules, changed ([\d,]+) rows, refreshed (.*)$")

# backend/sql/release_date.sql, restricted to the rows whose value changes:
# the first run's release from study_facets, else project_release_date unless
# it is a placeholder in the future, else submitted_date.
RELEASE_DATE_VALUE = """
    SELECT b2.bioproject, b2.sra_study, coalesce(
        (SELECT f.first_run_release FROM study_facets f WHERE f.sra_study = b2.sra_study),
        CASE WHEN b2.project_release_date <= current_date THEN b2.project_release_date END,
        b2.submitted_date) AS v
    FROM bioprojects b2
"""
RELEASE_DATE_UPDATE = f"""
    UPDATE bioprojects b SET release_date = x.v
    FROM ({RELEASE_DATE_VALUE}) x
    WHERE x.bioproject = b.bioproject AND x.sra_study = b.sra_study
      AND b.release_date IS DISTINCT FROM x.v
"""
RELEASE_DATE_PENDING = f"""
    SELECT count(*) FROM bioprojects b JOIN ({RELEASE_DATE_VALUE}) x
      ON x.bioproject = b.bioproject AND x.sra_study = b.sra_study
    WHERE b.release_date IS DISTINCT FROM x.v
"""
RELEASE_DATE_INDEX = """
    CREATE INDEX IF NOT EXISTS bioprojects_release_date_idx
        ON bioprojects (release_date DESC NULLS LAST, bioproject, sra_study)
"""


def run(ctx: common.Context) -> dict:
    rules, refreshed = apply_normalizations(ctx)
    refreshed = refreshed + refresh_views(ctx, skip=refreshed)
    updates = update_release_dates(ctx)
    analyze(ctx)
    return {"rules_applied": rules, "views_refreshed": refreshed, "release_date_updates": updates}


def apply_normalizations(ctx: common.Context) -> tuple[int | None, list[str]]:
    """Runs `python -m app.normalize apply` with the backend's interpreter.

    Returns (rules applied, views it refreshed). The backend reads
    DATABASE_URL from its environment only (backend/app/database.py), so
    passing the pipeline's URL makes it work on the same database as the
    other steps, e.g. a test database. The command exits non-zero only when a
    view failed to refresh; that must not pass silently, because the filters
    would then show stale values until the next run.
    """
    cmd = [str(common.BACKEND_PYTHON), "-m", "app.normalize", "apply"]
    if ctx.options.dry_run:
        ctx.log.info("dry run: would run %s (cwd %s)", " ".join(cmd), common.BACKEND_DIR)
        return None, []
    env = dict(os.environ, DATABASE_URL=ctx.config.database_url)
    ctx.log.info("$ %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=str(common.BACKEND_DIR), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout is not None
    rules, refreshed, summary_seen = None, [], False
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        ctx.log.info("  | %s", line)
        m = NORMALIZE_SUMMARY.match(line)
        if m:
            summary_seen = True
            rules = int(m.group(1))
            refreshed = [] if m.group(3).strip() == "no views" else [v.strip() for v in m.group(3).split(",")]
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"normalize apply exited with {code}; see the log lines above")
    if not summary_seen:
        # The output format changed; refreshing every view below is harmless.
        ctx.log.warning("normalize apply printed no summary line; refreshing every view")
    ctx.log.info("normalize apply: %s rules, refreshed %s", rules, ", ".join(refreshed) or "no views")
    return rules, refreshed


def refresh_views(ctx: common.Context, skip: list[str]) -> list[str]:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY for each view in common.VIEWS that
    exists and isn't in `skip` (just refreshed by normalize apply).

    CONCURRENTLY needs autocommit (it can't run inside a transaction) and the
    view's unique index (backend/sql/*.sql create one). It keeps the old
    contents readable while rebuilding, so searches keep working meanwhile.
    """
    refreshed = []
    with ctx.connect(autocommit=True) as conn:
        for view in common.VIEWS:
            if view in skip:
                continue
            if not common.relation_exists(conn, view):
                ctx.log.warning("materialized view %s does not exist; skipped (see docs/production.md)", view)
                continue
            if ctx.options.dry_run:
                ctx.log.info("dry run: would REFRESH MATERIALIZED VIEW CONCURRENTLY %s", view)
                continue
            with ctx.timed(f"refresh {view}"):
                conn.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
            refreshed.append(view)
    return refreshed


def update_release_dates(ctx: common.Context) -> int:
    """Fills bioprojects.release_date where its value changed; returns the rows updated.

    Only rows whose value differs are written: an UPDATE of every row (as
    release_date.sql does) would rewrite ~700k rows and bloat the table each
    week for nothing. study_facets must be fresh (refresh_views ran before),
    since the first run's release date comes from it. The index the search
    page's first view uses is created if a fresh database lacks it.
    """
    with ctx.connect() as conn:
        if not common.relation_exists(conn, "study_facets"):
            raise RuntimeError("study_facets does not exist; release_date can't be computed (backend/sql/study_facets.sql)")
        if ctx.options.dry_run:
            if "release_date" not in common.table_columns(conn, "bioprojects"):
                n = common.scalar(conn, "SELECT count(*) FROM bioprojects")
                ctx.log.info("dry run: would add bioprojects.release_date and fill it for all %s rows", f"{n:,}")
            else:
                n = common.scalar(conn, RELEASE_DATE_PENDING)
                ctx.log.info("dry run: would update release_date on %s rows", f"{n:,}")
            return n
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE bioprojects ADD COLUMN IF NOT EXISTS release_date date")
            with ctx.timed("release_date update"):
                cur.execute(RELEASE_DATE_UPDATE)
                n = cur.rowcount
            cur.execute(RELEASE_DATE_INDEX)
        conn.commit()
    ctx.log.info("release_date: %s rows updated", f"{n:,}")
    return n


def analyze(ctx: common.Context) -> None:
    """ANALYZE the tables and views this run changed (those that exist)."""
    analyze_relations(ctx, ANALYZE_RELATIONS)


def analyze_relations(ctx: common.Context, names: list[str]) -> list[str]:
    """ANALYZE each relation that exists; returns the ones analyzed (shared with finish.py)."""
    done = []
    with ctx.connect(autocommit=True) as conn:
        for name in names:
            if not common.relation_exists(conn, name):
                continue
            if ctx.options.dry_run:
                ctx.log.info("dry run: would ANALYZE %s", name)
                continue
            conn.execute(f"ANALYZE {name}")
            done.append(name)
    if done:
        ctx.log.info("analyzed %s", ", ".join(done))
    return done
