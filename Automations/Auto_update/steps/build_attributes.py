"""attributes step: rebuild bioproject_attributes from the snapshot's jattr column.

The sample filters (tissue, sex, cell line, ...) read bioproject_attributes, one
JSON record per BioProject aggregated over all of its runs. A project's record
changes whenever a run is added to it, so the step recomputes every project
from the whole snapshot instead of trying to patch the records of the new runs
only; it is the same computation as Automations/jattr_normalize.py, whose
functions it imports, reading the parquet files instead of sra_metadata_all.tsv
(see docs/jattr-normalization.md for the fields and the cleaning rules).

What it writes:
  data/output/bioproject_attributes.tsv           bioproject <TAB> JSON, one row per project
  data/output/bioproject_attributes_coverage.tsv  per-field coverage (runs, BioProjects)
  bioproject_attributes            INSERT new projects, UPDATE the ones whose JSON changed
  bioproject_attributes_coverage   the 14 field rows, upserted

Rows are never deleted: a project that disappears from SRA keeps its last record.
The step is idempotent (same input, same output; an unchanged record is not
rewritten) and a crash leaves nothing behind: the load is one transaction and
the staging table is dropped inside it.

Work is split by parquet row group (about 120 of them, ~380k runs each) over
Config.jattr_workers processes. The result is byte for byte what a single
chunk, single worker run of jattr_normalize.py produces, whatever the number
of row groups or workers: a worker counts every distinct value of its row group
(bounded by the row group's rows) and the parent merges the row groups in file
order, applying the MAX_VALUES_TRACK cap through merge_counter in global row
order. Without this, which values fall into the overflow bucket of a field
with hundreds of distinct values, and the order of values with tied counts,
would change from run to run and count as a change (jsonb compares arrays by
position), rewriting rows that didn't really change.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import common

sys.path.insert(0, str(common.AUTOMATIONS_DIR))
import jattr_normalize as jn  # noqa: E402  (build_lookup, extract, merge_counter, top_values, FIELDS)

# What a worker reads per row: the jattr JSON plus the top-level columns
# jattr_normalize.process_chunk passes to extract() (FIELDS entries with "column").
COLUMNS = ["acc", "bioproject", "organism", "assay_type", "jattr"]
BATCH_ROWS = 50_000             # rows decoded at a time inside a worker (keeps it at a few hundred MB)
STAGING = "auto_update_attributes_staging"
ATTRIBUTES_TSV = common.OUTPUT_DIR / "bioproject_attributes.tsv"
COVERAGE_TSV = common.OUTPUT_DIR / "bioproject_attributes_coverage.tsv"


# ---------------------------------------------------------------- workers
def _init_worker() -> None:
    # One pyarrow thread per worker: the Pool already uses every CPU we want.
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)


def process_row_group(task: tuple[str, int]):
    """One parquet row group -> the same tuple jattr_normalize.process_chunk returns:
    (rows, parse errors, rows without bioproject, n_runs, field_runs, agg) where
    agg is project -> field -> {value: runs}, values in order of first appearance.

    Unlike process_chunk, every distinct value is counted (no "__overflow__"
    bucket here): the parent's merge_counter applies the MAX_VALUES_TRACK cap
    once the row groups are merged in order, which keeps the first 200 values
    seen in the whole snapshot, like a single-chunk run does (see the module
    docstring). A row group has at most ~400k rows, so this stays small."""
    path, index = task
    lookup = jn.build_lookup()
    key_cache: dict = {}
    agg = defaultdict(lambda: defaultdict(Counter))
    n_runs: Counter = Counter()
    field_runs: Counter = Counter()
    rows = errors = no_project = 0

    reader = pq.ParquetFile(path)
    for batch in reader.iter_batches(batch_size=BATCH_ROWS, row_groups=[index], columns=COLUMNS):
        columns = [batch.column(name).to_pylist() for name in COLUMNS]
        for acc, bioproject, organism, assay_type, jattr in zip(*columns):
            rows += 1
            try:
                obj = json.loads(jattr) if jattr else {}
            except ValueError:
                errors += 1
                continue
            if not isinstance(obj, dict):
                obj = {}
            # NULL cells are "" here, as they are in the TSV jattr_normalize reads.
            top = {"acc": acc or "", "bioproject": bioproject or "", "organism": organism or "",
                   "assay_type": assay_type or ""}
            rec = jn.extract(obj, top, lookup, key_cache)
            project = top["bioproject"].strip()
            if not project:
                no_project += 1
                continue
            n_runs[project] += 1
            proj = agg[project]
            for fld, val in rec.items():
                field_runs[fld] += 1
                proj[fld][val] += 1
    # Plain dicts: they pickle faster than nested defaultdicts of Counters.
    plain = {p: {f: dict(c) for f, c in fs.items()} for p, fs in agg.items()}
    return rows, errors, no_project, dict(n_runs), dict(field_runs), plain


def row_group_tasks(files: list[Path]) -> list[tuple[str, int]]:
    return [(str(path), i) for path in files for i in range(pq.ParquetFile(path).metadata.num_row_groups)]


# ---------------------------------------------------------------- aggregation
def aggregate(ctx: common.Context, files: list[Path]) -> dict:
    """Runs the workers over every row group and merges their results like
    jattr_normalize.main() does. Returns the totals and the merged counters."""
    tasks = row_group_tasks(files)
    ctx.log.info("attributes: %d parquet files, %d row groups, %d workers",
                 len(files), len(tasks), ctx.config.jattr_workers)
    t0 = time.monotonic()
    tot_rows = tot_err = tot_noproj = 0
    n_runs: Counter = Counter()
    field_runs: Counter = Counter()
    agg: dict = defaultdict(lambda: defaultdict(Counter))
    with Pool(ctx.config.jattr_workers, initializer=_init_worker) as pool:
        # imap (ordered), not imap_unordered: the merge order decides which values
        # are kept and how ties are ordered (module docstring).
        for i, (rows, errors, noproj, nr, fr, part) in enumerate(pool.imap(process_row_group, tasks), 1):
            tot_rows += rows
            tot_err += errors
            tot_noproj += noproj
            n_runs.update(nr)
            field_runs.update(fr)
            for project, fields in part.items():
                proj = agg[project]
                for fld, c in fields.items():
                    jn.merge_counter(proj[fld], c)
            if i % 4 == 0 or i == len(tasks):
                elapsed = time.monotonic() - t0
                ctx.log.info("  %d/%d row groups, %s rows, %s projects, %.0f rows/s, eta %s",
                             i, len(tasks), f"{tot_rows:,}", f"{len(agg):,}", tot_rows / max(elapsed, 1e-9),
                             common.format_duration(elapsed / i * (len(tasks) - i)))
    return {"rows": tot_rows, "errors": tot_err, "no_project": tot_noproj,
            "n_runs": n_runs, "field_runs": field_runs, "agg": agg}


def write_outputs(totals: dict) -> tuple[int, list[tuple]]:
    """Writes the two TSVs in the format jattr_normalize.main() uses (the same
    files the schema files in Automations/output load). Returns the number of
    projects and the coverage rows (field, runs, runs_pct, bioprojects, bioprojects_pct)."""
    agg, n_runs = totals["agg"], totals["n_runs"]
    field_projects: Counter = Counter()
    common.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ATTRIBUTES_TSV.with_suffix(".tsv.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("bioproject\tattributes\n")
        for project in sorted(agg):
            rec = {"n_runs": n_runs[project]}
            for fld in jn.FIELDS:
                c = agg[project].get(fld)
                if not c:
                    continue
                vals = jn.top_values(c)
                if vals:
                    rec[fld] = vals
                    field_projects[fld] += 1
            f.write(f"{project}\t{json.dumps(rec, ensure_ascii=False)}\n")
    os.replace(tmp, ATTRIBUTES_TSV)

    parsed = totals["rows"] - totals["errors"]
    projects = len(agg)
    coverage = []
    for fld in jn.FIELDS:
        runs = totals["field_runs"][fld]
        coverage.append((fld, runs, f"{100 * runs / max(parsed, 1):.2f}",
                         field_projects[fld], f"{100 * field_projects[fld] / max(projects, 1):.2f}"))
    tmp = COVERAGE_TSV.with_suffix(".tsv.tmp")
    with open(tmp, "w") as f:
        f.write("field\truns\truns_pct\tbioprojects\tbioprojects_pct\n")
        for row in coverage:
            f.write("\t".join(str(v) for v in row) + "\n")
    os.replace(tmp, COVERAGE_TSV)
    return projects, coverage


# ---------------------------------------------------------------- database
UPSERT_ATTRIBUTES = f"""
WITH up AS (
    INSERT INTO bioproject_attributes (bioproject, attributes)
    SELECT bioproject, attributes FROM {STAGING}
    ON CONFLICT (bioproject) DO UPDATE SET attributes = EXCLUDED.attributes
    WHERE bioproject_attributes.attributes IS DISTINCT FROM EXCLUDED.attributes
    RETURNING (xmax = 0) AS inserted
)
SELECT count(*) FILTER (WHERE inserted), count(*) FILTER (WHERE NOT inserted) FROM up
"""

# What the upsert would do, for --dry-run (and for the log before a real load).
PREVIEW_ATTRIBUTES = f"""
SELECT count(*) FILTER (WHERE a.bioproject IS NULL),
       count(*) FILTER (WHERE a.bioproject IS NOT NULL AND a.attributes IS DISTINCT FROM s.attributes)
FROM {STAGING} s LEFT JOIN bioproject_attributes a USING (bioproject)
"""

UPSERT_COVERAGE = """
INSERT INTO bioproject_attributes_coverage (field, runs, runs_pct, bioprojects, bioprojects_pct)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (field) DO UPDATE SET runs = EXCLUDED.runs, runs_pct = EXCLUDED.runs_pct,
    bioprojects = EXCLUDED.bioprojects, bioprojects_pct = EXCLUDED.bioprojects_pct
"""


def stage_tsv(conn, dry_run: bool) -> int:
    """COPY bioproject_attributes.tsv into the staging table; returns its row count.

    A dry run uses a TEMP table, which disappears with the session, so the
    preview query can run without leaving anything in the database."""
    kind = "TEMP" if dry_run else "UNLOGGED"
    with conn.cursor() as cur:
        cur.execute(f"CREATE {kind} TABLE IF NOT EXISTS {STAGING} (bioproject text, attributes jsonb)")
        cur.execute(f"TRUNCATE {STAGING}")
    # QUOTE E'\x01' (copy_text_file's default): the JSON is taken byte for byte,
    # exactly like bioproject_attributes_schema.sql loads the same file.
    common.copy_text_file(conn, STAGING, ["bioproject", "attributes"], ATTRIBUTES_TSV, header=True)
    return common.scalar(conn, f"SELECT count(*) FROM {STAGING}")


# The fields whose values the normalisation page renames (backend/app/normalize.py
# FIELDS of kind "attribute"); a tissue rule also applies to the source_name
# list, which stands in for the tissue of projects without one (its "also").
RULE_FIELDS = {
    "cell_line": [], "cell_type": [], "tissue": ["source_name"], "sex": [], "disease_state": [],
    "genotype_or_strain": [], "treatment_or_growth_condition": [], "molecular_target": [],
}


def apply_rules(ctx: common.Context, conn) -> int:
    """Applies the recorded normalisation rules to the staged records, so the
    upsert only touches projects that really changed.

    The pipeline rebuilds every record from the raw jattr values, so without
    this the ~150k projects a rule touches (tissue capitalised, "Liver" ->
    "liver", ...) would look changed every week, be rewritten, and then be
    renamed again by `normalize apply` in the refresh step. The rewrite is
    the one backend/app/normalize._rewrite_list does on bioproject_attributes:
    each list element e of the field is rewritten, the list keeps its order and
    loses duplicates the rewrite creates, in id (creation) order of the rules.
    `normalize apply` still runs afterwards as the safety net. Returns the
    number of rule applications that changed a staged row.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id, field, action, from_value, to_value FROM value_normalizations"
                    " WHERE field = ANY(%s) ORDER BY id", (list(RULE_FIELDS),))
        rules = cur.fetchall()
    changed = 0
    with conn.cursor() as cur:
        for rule_id, field, action, from_value, to_value in rules:
            if action == "rename":
                new_value = "CASE WHEN e = %(from)s THEN %(to)s ELSE e END"
                needs_change = "jsonb_exists(a.attributes -> %(field)s, %(from)s)"
            elif action == "capitalize":
                new_value = "upper(left(e, 1)) || substr(e, 2)"
                needs_change = ("EXISTS (SELECT 1 FROM jsonb_array_elements_text(a.attributes -> %(field)s) AS l(e)"
                                " WHERE left(e, 1) <> upper(left(e, 1)))")
            else:
                ctx.log.warning("rule %s: unknown action %r skipped", rule_id, action)
                continue
            for key in [field, *RULE_FIELDS[field]]:
                cur.execute(f"""
                    UPDATE {STAGING} a
                    SET attributes = jsonb_set(a.attributes, ARRAY[%(field)s], (
                        SELECT coalesce(jsonb_agg(x ORDER BY first_ord), '[]'::jsonb)
                        FROM (
                            SELECT x, min(ord) AS first_ord
                            FROM (
                                SELECT {new_value} AS x, ord
                                FROM jsonb_array_elements_text(a.attributes -> %(field)s) WITH ORDINALITY AS t(e, ord)
                            ) rewritten
                            GROUP BY x
                        ) deduped
                    ))
                    WHERE jsonb_typeof(a.attributes -> %(field)s) = 'array'
                      AND {needs_change}
                """, {"field": key, "from": from_value, "to": to_value})
                changed += cur.rowcount
    ctx.log.info("attributes: %d normalisation rules applied to the staged records (%s row changes)",
                 len(rules), f"{changed:,}")
    return changed


def load(ctx: common.Context, projects: int, coverage: list[tuple]) -> tuple[int, int]:
    """Upserts the TSVs into the two tables in one transaction. Returns (inserted, updated)."""
    dry = ctx.options.dry_run
    with ctx.connect() as conn:
        # No parallel query in this session: with the 256 MB work_mem the
        # connection sets, a parallel hash join of staging against the table
        # builds its hash table in /dev/shm, which is 64 MB in the Postgres
        # container (Docker's default), and fails with "could not resize shared
        # memory segment ... No space left on device". A single-process join
        # uses private memory and takes seconds here anyway.
        with conn.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather = 0")
        staged = stage_tsv(conn, dry)
        if staged != projects:
            raise RuntimeError(f"staging holds {staged} rows, expected {projects}")
        if common.relation_exists(conn, "value_normalizations"):
            apply_rules(ctx, conn)
        with conn.cursor() as cur:
            cur.execute(PREVIEW_ATTRIBUTES)
            to_insert, to_update = cur.fetchone()
            ctx.log.info("attributes: %s projects staged, %s new, %s changed%s", f"{staged:,}",
                         f"{to_insert:,}", f"{to_update:,}", " (dry run, not written)" if dry else "")
            if dry:
                conn.rollback()
                return to_insert, to_update
            cur.execute(UPSERT_ATTRIBUTES)
            inserted, updated = cur.fetchone()
            cur.executemany(UPSERT_COVERAGE, coverage)
            cur.execute(f"DROP TABLE {STAGING}")
        conn.commit()
    return inserted, updated


# ---------------------------------------------------------------- entry point
def run(ctx: common.Context) -> dict:
    files = ctx.parquet_files()
    if not files:
        raise FileNotFoundError(f"no parquet files in {ctx.snapshot_dir()}")
    if ctx.options.files is not None and not ctx.options.dry_run:
        # Every project is recomputed from what is read: a partial snapshot
        # would replace real records with ones built from a fraction of their
        # runs (n_runs, value lists) and the upsert would write them.
        raise RuntimeError("attributes: --files reads a partial snapshot, which may only be loaded with --dry-run")
    if ctx.options.limit is not None:
        ctx.log.info("attributes: --limit is ignored (every project is recomputed)")

    with ctx.timed("attributes: reading jattr"):
        totals = aggregate(ctx, files)
    projects, coverage = write_outputs(totals)
    ctx.log.info("attributes: %s rows, %s parse errors, %s without bioproject, %s projects -> %s",
                 f"{totals['rows']:,}", f"{totals['errors']:,}", f"{totals['no_project']:,}",
                 f"{projects:,}", ATTRIBUTES_TSV)
    totals["agg"].clear()   # a few GB on the full snapshot; not needed any more

    with ctx.timed("attributes: loading"):
        inserted, updated = load(ctx, projects, coverage)
    return {
        "rows": totals["rows"],
        "parse_errors": totals["errors"],
        "rows_without_bioproject": totals["no_project"],
        "projects": projects,
        "inserted": inserted,
        "updated": updated,
    }
