"""projects step: new (bioproject, sra_study) pairs and the projects' XML metadata.

bioprojects has one row per (bioproject, sra_study) pair seen in sra_metadata,
enriched with what NCBI's bioproject.xml says about the project (title,
description, publications, dates, organism, ...). Automations/create_tables.py
builds the table from scratch; this step brings it up to date after the runs
step added rows to sra_metadata:

  1. pairs that exist in sra_metadata but not in bioprojects are inserted,
     with their XML metadata when the project is in the XML;
  2. n_experiments is corrected where the runs changed it;
  3. every known project is parsed from the XML again, and rows whose metadata
     differs are updated (publications get added, titles get edited, projects
     that were not in the XML last time appear).

Nothing is ever deleted: a project that disappears from the XML keeps the
metadata it had. The three columns the normalisation page renames
(common.NORMALIZED_COLUMNS) are only filled in when they are NULL, so a
rename is never undone here (normalize apply runs in the refresh step anyway).

Projects whose title, name or description changed, and projects that are new
to the table, are written to state/pending_reembed.txt / pending_retag.txt,
which the embeddings and tags steps pick up.

Everything the database sees happens in one transaction: the staging tables
are created, filled from the parsed XML, applied and dropped, then committed.
A crash leaves nothing behind, and rerunning the step after a successful run
changes 0 rows.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Optional

from lxml import etree

import common

sys.path.insert(0, str(common.AUTOMATIONS_DIR))
from create_tables import COLUMNS, parse_package  # noqa: E402  (the original parser, so formats match)

# The XML the step reads. Tests point this at a smaller file; the pipeline
# uses the one the download step fetched.
XML_PATH: Path = common.ENA_XML

PROJECTS_STAGING = "auto_update_projects_staging"   # one row per project parsed from the XML
PAIRS_STAGING = "auto_update_pairs_staging"         # new pairs and pairs whose count changed

# Postgres type of each XML column, from create_tables.COLUMNS ("DATE", "JSONB", ...).
COLUMN_TYPES = {name: typ.split()[0].lower() for name, typ in COLUMNS}

# What create_tables.read_bioproject_study_pairs() counted from the experiments
# export, computed from sra_metadata instead.
PAIRS_SQL = """
SELECT bioproject, sra_study, count(DISTINCT experiment)
FROM sra_metadata
WHERE experiment IS NOT NULL AND coalesce(bioproject, '') <> '' AND coalesce(sra_study, '') <> ''
GROUP BY 1, 2
"""


# ---------------------------------------------------------------- column helpers
def staging_type(col: str) -> str:
    """JSON stays text in staging (parse_package produces JSON text) and is cast in SQL."""
    typ = COLUMN_TYPES[col]
    return "text" if typ == "jsonb" else typ


def staged(col: str) -> str:
    """The staging column as the bioprojects column's type."""
    return f"s.{col}::jsonb" if COLUMN_TYPES[col] == "jsonb" else f"s.{col}"


def new_value(col: str) -> str:
    """What an existing row's column becomes: the XML value, except that
    normalised columns keep what they have unless it is NULL."""
    return f"COALESCE(b.{col}, {staged(col)})" if col in common.NORMALIZED_COLUMNS else staged(col)


def metadata_differs() -> str:
    """Predicate on bioprojects b and staging s: something would change."""
    parts = ["b.found_in_bioproject_xml IS DISTINCT FROM true"]
    parts += [f"b.{col} IS DISTINCT FROM {new_value(col)}" for col in common.XML_COLUMNS]
    return "(" + " OR ".join(parts) + ")"


def text_differs() -> str:
    return "(" + " OR ".join(f"b.{col} IS DISTINCT FROM {staged(col)}" for col in common.TEXT_COLUMNS) + ")"


def to_staging_value(col: str, value):
    """parse_package returns strings (dates as 'YYYY-MM-DD', ids as digits);
    convert to the staging column's Python type. Unparseable -> NULL."""
    if value is None or value == "":
        return None
    typ = staging_type(col)
    try:
        if typ == "date":
            return dt.date.fromisoformat(value)
        if typ in ("bigint", "integer"):
            return int(value)
    except (TypeError, ValueError):
        return None
    return str(value)


# ---------------------------------------------------------------- reading
def read_pairs(conn) -> dict[tuple[str, str], int]:
    with conn.cursor() as cur:
        cur.execute(PAIRS_SQL)
        return {(bp, study): n for bp, study, n in cur}


def read_existing(conn) -> dict[tuple[str, str], Optional[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT bioproject, sra_study, n_experiments FROM bioprojects")
        return {(bp, study): n for bp, study, n in cur}


def xml_looks_complete(path: Path) -> bool:
    """A finished download ends with the closing root tag. iterparse(recover=True)
    stops quietly at a truncation, so this is the only sign of a partial file."""
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 256))
        return b"</PackageSet>" in f.read()


def parse_xml(ctx: common.Context, wanted: set[str]) -> tuple[dict[str, dict], int]:
    """Stream the XML and parse the wanted projects (like
    create_tables.read_bioproject_xml). Returns {accession: row} and the
    number of packages scanned."""
    if not XML_PATH.is_file() or XML_PATH.stat().st_size == 0:
        raise FileNotFoundError(f"{XML_PATH} is missing or empty; run the download step first")
    if not xml_looks_complete(XML_PATH):
        # iterparse(recover=True) would still emit the package cut in half as
        # a row of NULLs and the update would overwrite that project with it.
        raise RuntimeError(f"{XML_PATH} does not end with </PackageSet>: incomplete download; rerun --from download")
    ctx.log.info("parsing %s (%.1f GB) for %s projects", XML_PATH, XML_PATH.stat().st_size / 1e9, f"{len(wanted):,}")
    info: dict[str, dict] = {}
    failed = 0
    n = 0
    context = etree.iterparse(str(XML_PATH), events=("end",), tag="Package", huge_tree=True, recover=True)
    for n, (_, pkg) in enumerate(context, 1):
        archive = pkg.find("Project/Project/ProjectID/ArchiveID")
        accession = archive.get("accession") if archive is not None else None
        if accession in wanted:
            try:
                info[accession] = parse_package(pkg, accession)
            except Exception as exc:  # one odd record must not lose the run
                failed += 1
                ctx.log.warning("failed to parse %s: %r", accession, exc)
        # free the parsed subtree; otherwise the whole 4 GB document stays in memory
        pkg.clear()
        while pkg.getprevious() is not None:
            del pkg.getparent()[0]
        if n % 100_000 == 0:
            ctx.log.info("  %s packages scanned, %s matched", f"{n:,}", f"{len(info):,}")
    del context
    ctx.log.info("matched %s/%s projects in %s packages (%d failed to parse)",
                 f"{len(info):,}", f"{len(wanted):,}", f"{n:,}", failed)
    return info, n


# ---------------------------------------------------------------- staging
def create_staging(conn) -> None:
    cols = ", ".join(f"{col} {staging_type(col)}" for col in common.XML_COLUMNS)
    with conn.cursor() as cur:
        # DROP first: a leftover from an interrupted run outside a transaction would be stale
        cur.execute(f"DROP TABLE IF EXISTS {PROJECTS_STAGING}")
        cur.execute(f"CREATE UNLOGGED TABLE {PROJECTS_STAGING} (bioproject text PRIMARY KEY, {cols})")
        cur.execute(f"DROP TABLE IF EXISTS {PAIRS_STAGING}")
        cur.execute(f"CREATE UNLOGGED TABLE {PAIRS_STAGING} "
                    "(bioproject text, sra_study text, n_experiments integer, PRIMARY KEY (bioproject, sra_study))")


def fill_staging(conn, info: dict[str, dict], pairs: list[tuple[str, str, int]]) -> None:
    columns = ["bioproject"] + common.XML_COLUMNS
    types = ["text"] + [staging_type(col) for col in common.XML_COLUMNS]
    rows = ([acc] + [to_staging_value(col, row.get(col)) for col in common.XML_COLUMNS]
            for acc, row in info.items())
    common.copy_rows(conn, PROJECTS_STAGING, columns, rows, types)
    common.copy_rows(conn, PAIRS_STAGING, ["bioproject", "sra_study", "n_experiments"], pairs,
                     ["text", "text", "integer"])


def drop_staging(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {PROJECTS_STAGING}")
        cur.execute(f"DROP TABLE IF EXISTS {PAIRS_STAGING}")


# ---------------------------------------------------------------- applying
def text_changed_projects(conn) -> list[str]:
    """Existing projects whose embedding/tag text differs from the XML (computed
    before the metadata update, which makes the two sides equal)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT b.bioproject FROM bioprojects b JOIN {PROJECTS_STAGING} s USING (bioproject)"
                    f" WHERE {text_differs()} ORDER BY 1")
        return [r[0] for r in cur]


def update_metadata(conn, dry_run: bool) -> int:
    """Existing rows whose XML metadata changed (or that were not in the XML before)."""
    where = f"b.bioproject = s.bioproject AND {metadata_differs()}"
    with conn.cursor() as cur:
        if dry_run:
            cur.execute(f"SELECT count(*) FROM bioprojects b, {PROJECTS_STAGING} s WHERE {where}")
            return cur.fetchone()[0]
        sets = ", ".join(["found_in_bioproject_xml = true"] + [f"{col} = {new_value(col)}" for col in common.XML_COLUMNS])
        cur.execute(f"UPDATE bioprojects b SET {sets} FROM {PROJECTS_STAGING} s WHERE {where}")
        return cur.rowcount


def update_counts(conn, dry_run: bool) -> int:
    where = (f"b.bioproject = p.bioproject AND b.sra_study = p.sra_study"
             f" AND b.n_experiments IS DISTINCT FROM p.n_experiments")
    with conn.cursor() as cur:
        if dry_run:
            cur.execute(f"SELECT count(*) FROM bioprojects b, {PAIRS_STAGING} p WHERE {where}")
            return cur.fetchone()[0]
        cur.execute(f"UPDATE bioprojects b SET n_experiments = p.n_experiments FROM {PAIRS_STAGING} p WHERE {where}")
        return cur.rowcount


def insert_pairs(conn, dry_run: bool) -> int:
    """Pairs of the staging table that bioprojects lacks, with the project's XML
    row when there is one. release_date stays NULL: the refresh step fills it."""
    missing = ("NOT EXISTS (SELECT 1 FROM bioprojects b"
               " WHERE b.bioproject = p.bioproject AND b.sra_study = p.sra_study)")
    with conn.cursor() as cur:
        if dry_run:
            cur.execute(f"SELECT count(*) FROM {PAIRS_STAGING} p WHERE {missing}")
            return cur.fetchone()[0]
        columns = ", ".join(["bioproject", "sra_study", "n_experiments", "found_in_bioproject_xml"] + common.XML_COLUMNS)
        values = ", ".join(["p.bioproject", "p.sra_study", "p.n_experiments", "s.bioproject IS NOT NULL"]
                           + [staged(col) for col in common.XML_COLUMNS])
        cur.execute(f"INSERT INTO bioprojects ({columns}) SELECT {values}"
                    f" FROM {PAIRS_STAGING} p LEFT JOIN {PROJECTS_STAGING} s USING (bioproject)"
                    f" WHERE {missing} ON CONFLICT (bioproject, sra_study) DO NOTHING")
        return cur.rowcount


# ---------------------------------------------------------------- the step
def run(ctx: common.Context) -> dict:
    dry_run = ctx.options.dry_run
    with ctx.connect() as conn:
        have = set(common.table_columns(conn, "bioprojects"))
        missing_cols = [c for c in common.XML_COLUMNS if c not in have]
        if missing_cols:
            raise RuntimeError(f"bioprojects lacks columns {missing_cols}; the schema changed")

        with ctx.timed("reading (bioproject, sra_study) pairs"):
            pairs = read_pairs(conn)
            existing = read_existing(conn)
        # End the read transaction now: the XML parse takes a while, and an
        # idle transaction would keep its locks on the tables all that time.
        conn.commit()
        new_pairs = sorted(k for k in pairs if k not in existing)
        if ctx.options.limit is not None:
            new_pairs = new_pairs[: ctx.options.limit]
        changed = [(bp, study, pairs[(bp, study)]) for (bp, study), n in existing.items()
                   if (bp, study) in pairs and pairs[(bp, study)] != n]
        known = {bp for bp, _ in existing}
        new_projects = sorted({bp for bp, _ in new_pairs} - known)
        ctx.log.info("%s pairs in sra_metadata, %s rows in bioprojects: %s new pairs (%s new projects), "
                     "%s changed counts", f"{len(pairs):,}", f"{len(existing):,}", f"{len(new_pairs):,}",
                     f"{len(new_projects):,}", f"{len(changed):,}")
        wanted = known | set(new_projects)
        staged_pairs = [(bp, study, pairs[(bp, study)]) for bp, study in new_pairs] + changed
        n_pairs = len(pairs)
        del pairs, existing

        with ctx.timed("parsing bioproject.xml"):
            info, n_packages = parse_xml(ctx, wanted)
            n_matched = len(info)

        with ctx.timed("applying to bioprojects"):
            create_staging(conn)
            fill_staging(conn, info, staged_pairs)
            del info
            text_changed = text_changed_projects(conn)
            metadata_updates = update_metadata(conn, dry_run)
            count_updates = update_counts(conn, dry_run)
            inserted = insert_pairs(conn, dry_run)
            drop_staging(conn)
            if dry_run:
                conn.rollback()
                ctx.log.info("dry run: would update %s rows' metadata, %s counts and insert %s pairs "
                             "(rolled back, nothing written)", f"{metadata_updates:,}", f"{count_updates:,}", f"{inserted:,}")
                ctx.log.info("dry run: would queue %d projects to re-embed and %d to re-tag",
                             len(text_changed), len(set(text_changed) | set(new_projects)))
            else:
                # Hand the stale/new projects to the embeddings and tags steps
                # before the commit: if the commit then fails, the queue only
                # holds extra work those steps redo harmlessly, whereas queuing
                # after a commit that was followed by a crash would lose the
                # changed-text projects for good (their rows already match the XML).
                ctx.pending_add("reembed", text_changed)
                ctx.pending_add("retag", sorted(set(text_changed) | set(new_projects)))
                conn.commit()
                ctx.log.info("updated %s rows' metadata, %s counts; inserted %s pairs",
                             f"{metadata_updates:,}", f"{count_updates:,}", f"{inserted:,}")

    return {
        "pairs": n_pairs,
        "new_pairs": len(new_pairs),
        "new_bioprojects": len(new_projects),
        "count_updates": count_updates,
        "xml_packages": n_packages,
        "xml_matched": n_matched,
        "metadata_updates": metadata_updates,
        "text_changed": len(text_changed),
    }
