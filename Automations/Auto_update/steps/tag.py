"""Step "tags": bioproject_tags for new or changed projects, plus a capped backfill of old ones.

Targets are the accessions the projects step queued in state/pending_retag.txt
(new projects and projects whose title/name/description changed) and, after
them, up to config.tag_backfill projects that have no tags yet, newest first
(most of the table was never tagged: tagging is slow, ~4 projects/s per
worker, so the backlog is worked off a slice per week). Their text and
embeddings are written to work/tag_*.{csv,tsv} and
Automations/TagWords/extract_tags.py (run under TagWords/.venv, which has
GLiNER) tags them into work/tag_output.tsv. The TSV is upserted through a
staging table: a changed project's tags are replaced, new ones added, nothing
deleted. A project where nothing was found gets an empty tag list, so it isn't
queued again every week (the website shows empty tags as none).

Resuming: extract_tags.py appends to its output and skips the projects
already in it, so when the work files of an interrupted run still cover
today's targets they are reused and the run continues; otherwise it starts
over. Work files and the pending list go only after the upsert is committed.
"""

from __future__ import annotations

import contextlib
import csv
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable

import common

# The columns extract_tags.py reads from its input (bioprojects.csv).
INPUT_COLUMNS = ["bioproject", "title", "name", "description", "organism_name"]
# Bioprojects per task and output flush (the script's default is 256): with few
# workers a smaller chunk means less lost work when the run is interrupted.
CHUNK_SIZE = 128

csv.field_size_limit(sys.maxsize)


# ---------------------------------------------------------------- work files
def work_paths() -> tuple[Path, Path, Path]:
    """(input csv, embeddings tsv, output tsv)."""
    return (common.WORK_DIR / "tag_input.csv", common.WORK_DIR / "tag_embeddings.tsv",
            common.WORK_DIR / "tag_output.tsv")


def input_bioprojects(path: Path) -> set[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["bioproject"] for row in csv.DictReader(f)}


def can_resume(ctx: common.Context, targets: list[str]) -> bool:
    """True when an interrupted run left an input and a (partial) output that
    cover today's targets. If the targets grew meanwhile (the projects step
    ran again), the partial output is given up and the run starts over."""
    in_path, emb_path, out_path = work_paths()
    if not (in_path.exists() and emb_path.exists() and out_path.exists()):
        return False
    missing = set(targets) - input_bioprojects(in_path)
    if missing:
        ctx.log.info("previous work files don't cover %d of today's targets; starting over", len(missing))
        return False
    ctx.log.info("resuming the previous run: %d bioprojects already in %s", count_output(out_path), out_path.name)
    return True


def write_input(path: Path, rows: Iterable[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def write_embeddings(path: Path, vectors: Iterable[tuple[str, str]]) -> None:
    """Same layout as Automations/output/bioproject_embeddings.tsv, which
    extract_tags.read_embeddings streams: "bioproject\\t[0.1,...]"."""
    tmp = path.with_suffix(".tsv.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("bioproject\tembedding\n")
        for bioproject, vec in vectors:
            f.write(f"{bioproject}\t{vec}\n")
    tmp.replace(path)


def remove_work_files() -> None:
    for path in work_paths():
        path.unlink(missing_ok=True)


def count_output(path: Path) -> int:
    """Complete data lines in the output TSV (a half-written last line is dropped by the script)."""
    if not path.exists():
        return 0
    with open(path, "rb") as f:
        return max(0, sum(1 for line in f if line.endswith(b"\n")) - 1)


# ---------------------------------------------------------------- targets
def backfill_targets(ctx: common.Context, conn, exclude: list[str]) -> list[str]:
    """Untagged bioprojects, newest first, at most config.tag_backfill.

    Newest by the site's release_date (filled by the refresh step; falls back to
    the XML's project_release_date on a database where it doesn't exist yet).
    """
    date_col = "release_date" if "release_date" in common.table_columns(conn, "bioprojects") else "project_release_date"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT bioproject, max({date_col}) AS newest FROM bioprojects b"
            " WHERE NOT EXISTS (SELECT 1 FROM bioproject_tags t WHERE t.bioproject = b.bioproject)"
            "   AND NOT (bioproject = ANY(%s))"
            " GROUP BY bioproject ORDER BY newest DESC NULLS LAST, bioproject LIMIT %s",
            (exclude, ctx.config.tag_backfill),
        )
        return [r[0] for r in cur]


def fetch_text(conn, targets: list[str]) -> list[dict]:
    """One row of text per target (first study's row), in target order."""
    cols = ", ".join(INPUT_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT ON (bioproject) {cols} FROM bioprojects"
                    " WHERE bioproject = ANY(%s) ORDER BY bioproject, sra_study", (targets,))
        by_id = {r[0]: dict(zip(INPUT_COLUMNS, r)) for r in cur}
    return [by_id[t] for t in targets if t in by_id]


def fetch_embeddings(conn, targets: list[str]) -> list[tuple[str, str]]:
    """(bioproject, "[0.1,...]") for the targets that have an embedding; the
    script keeps all tags of a project without one (no relevance filter)."""
    with conn.cursor() as cur:
        cur.execute("SELECT bioproject, embedding::text FROM bioproject_embeddings WHERE bioproject = ANY(%s)",
                    (targets,))
        return cur.fetchall()


# ---------------------------------------------------------------- load
def upsert(ctx: common.Context, out_path: Path) -> int:
    """Loads the TSV into a staging table and merges it; returns rows upserted."""
    staging = "auto_update_tags_staging"
    with ctx.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {staging}")  # left over from a crashed run
            cur.execute(f"CREATE UNLOGGED TABLE {staging} (bioproject text, tags text, labels text)")
        # Loaded like bioproject_tags_schema.sql does: CSV with a header; the
        # script keeps tabs, quotes and newlines out of the fields.
        common.copy_text_file(conn, staging, ["bioproject", "tags", "labels"], out_path,
                              header=True, delimiter="\t", quote=None)
        with conn.cursor() as cur:
            # An empty tags field is NULL after the CSV load; the column is NOT NULL.
            cur.execute(
                "INSERT INTO bioproject_tags (bioproject, tags, labels)"
                f" SELECT bioproject, coalesce(tags, ''), labels FROM {staging} WHERE bioproject IS NOT NULL"
                " ON CONFLICT (bioproject) DO UPDATE SET tags = EXCLUDED.tags, labels = EXCLUDED.labels"
            )
            n = cur.rowcount
            cur.execute(f"DROP TABLE {staging}")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("ANALYZE bioproject_tags")
        conn.commit()
    return n


def run_in_own_group(ctx: common.Context, cmd: list, env: dict, cwd: Path) -> None:
    """Like common.run_logged, but the command gets its own process group that
    is killed once the command itself has exited.

    extract_tags.py spawns worker processes that inherit its stdout pipe. If
    the script dies while a worker is still running (OOM kill of the parent,
    a stray kill), the worker keeps the pipe open and a plain read of it would
    block the pipeline forever. Here the output is pumped by a thread, the
    main thread waits for the script, and whatever is left of its process
    group is terminated afterwards.
    """
    ctx.log.info("$ %s", " ".join(str(c) for c in cmd))
    full_env = dict(os.environ)
    full_env.update(env)
    # The script sets torch's thread count per worker itself; an inherited
    # OMP_NUM_THREADS would override it (docs/bioproject-tags.md says to unset it).
    full_env.pop("OMP_NUM_THREADS", None)
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=full_env, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    def pump():
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                ctx.log.info("  | %s", line)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    code = proc.wait()
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)  # leftover workers, if any
    reader.join(timeout=60)
    if code != 0:
        raise RuntimeError(f"{cmd[0]} exited with {code}")


def run_extract_tags(ctx: common.Context, in_path: Path, emb_path: Path, out_path: Path) -> None:
    cmd = [common.TAGWORDS_PYTHON, common.EXTRACT_TAGS_SCRIPT, "--input", in_path, "--embeddings", emb_path,
           "--output", out_path, "--workers", ctx.config.tag_workers,
           "--threads-per-worker", ctx.config.tag_threads, "--chunk-size", CHUNK_SIZE]
    run_in_own_group(ctx, cmd, env={"HF_HOME": ctx.config.hf_home}, cwd=common.TAGWORDS_DIR)


# ---------------------------------------------------------------- step
def run(ctx: common.Context) -> dict:
    common.WORK_DIR.mkdir(parents=True, exist_ok=True)
    pending = ctx.pending_read("retag")
    with ctx.connect() as conn:
        backfill = backfill_targets(ctx, conn, pending)
        targets = pending + backfill
        if ctx.options.limit is not None:
            targets = targets[: ctx.options.limit]
        rows = fetch_text(conn, targets)  # drops queued accessions that aren't in bioprojects
        targets = [r["bioproject"] for r in rows]
        vectors = fetch_embeddings(conn, targets) if targets and not ctx.options.dry_run else []
    result = {"pending": len(pending), "backfill": len(backfill), "targets": len(targets), "tagged": 0, "upserted": 0}
    ctx.log.info("%d bioprojects to tag: %d queued (new or changed text), %d backfill (cap %d)",
                 len(targets), len(pending), len(backfill), ctx.config.tag_backfill)

    if ctx.options.dry_run:
        ctx.log.info("dry run: would tag %d bioprojects and upsert them into bioproject_tags", len(targets))
        return result
    if not targets:
        ctx.pending_clear("retag")
        remove_work_files()
        return result

    in_path, emb_path, out_path = work_paths()
    if not can_resume(ctx, targets):
        remove_work_files()
        write_input(in_path, rows)
        write_embeddings(emb_path, vectors)
    ctx.log.info("%d of %d targets have an embedding (tags of the others are not relevance-filtered)",
                 len(vectors), len(targets))

    run_extract_tags(ctx, in_path, emb_path, out_path)

    result["tagged"] = count_output(out_path)
    result["upserted"] = upsert(ctx, out_path)
    ctx.log.info("upserted %d tag rows", result["upserted"])
    # Only now is the work consumed: a crash above reruns from the output file.
    # Under --limit the queue keeps what this run left out.
    done = set(targets)
    leftover = [p for p in pending if p not in done]
    ctx.pending_clear("retag")
    if leftover:
        ctx.pending_add("retag", leftover)
        ctx.log.info("%d queued projects left for the next run (--limit)", len(leftover))
    remove_work_files()
    return result
