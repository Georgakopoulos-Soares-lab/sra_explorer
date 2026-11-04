"""Step "embeddings": bioproject_embeddings for projects that have none, or whose text changed.

Targets are the accessions the projects step queued in state/pending_reembed.txt
(title/name/description changed in the XML) plus every bioproject row without
an embedding. Their text is written to work/embed_input.csv and
Automations/create_embeddings.py (run under backend/.venv, the venv that has
torch) embeds it into work/embed_output.tsv, checkpointing every CHUNK_SIZE
rows. The TSV is then upserted through a staging table, so an existing
embedding is replaced and a missing one added; nothing is deleted.

Resuming: the script's checkpoint (embed_output.tsv.progress) is honoured.
When the work files of an interrupted run are still there and still cover
today's targets, the step reuses them and the script continues where it
stopped; otherwise it starts over. The work files and the pending list are
removed only after the upsert is committed, so a crash anywhere before that
simply reruns.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Iterable

import common

# What the embedding is computed from, in the order create_embeddings.py joins
# them (short, high-signal fields first: the description's tail is what gets
# truncated at max_seq_length).
TEXT_COLUMNS = ["title", "name", "organism_name", "description"]
INPUT_COLUMNS = ["bioproject", *TEXT_COLUMNS]

# Input rows per checkpoint of create_embeddings.py (its default is 2048). A
# smaller chunk loses less work when the run is interrupted; the per-chunk
# cost is one fsync and a small JSON file.
CHUNK_SIZE = 256

csv.field_size_limit(sys.maxsize)


def build_text(row: dict) -> str:
    """Same as create_embeddings.build_text (not imported: that module loads torch
    at import time, which the pipeline's venv doesn't have). Only used here to
    skip projects with no text at all, which the script would skip as well."""
    parts = []
    for col in TEXT_COLUMNS:
        value = (row.get(col) or "").strip()
        if value and value not in parts:  # name often repeats title
            parts.append(value)
    return ". ".join(parts)


# ---------------------------------------------------------------- work files
def work_paths() -> tuple[Path, Path, Path]:
    """(input csv, output tsv, the script's progress file)."""
    out = common.WORK_DIR / "embed_output.tsv"
    return common.WORK_DIR / "embed_input.csv", out, out.with_name(out.name + ".progress")


def input_bioprojects(path: Path) -> set[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return {row["bioproject"] for row in csv.DictReader(f)}


def can_resume(ctx: common.Context, targets: list[dict]) -> bool:
    """True when an interrupted run left work files that cover today's targets.

    The script refuses an input file that changed since its checkpoint, so the
    input is only reused as is. If the targets grew meanwhile (the projects
    step ran again), the partial output is given up and the run starts over.
    """
    in_path, out_path, progress = work_paths()
    if not (in_path.exists() and progress.exists()):
        return False
    try:
        state = json.loads(progress.read_text())
    except ValueError:
        return False
    missing = {t["bioproject"] for t in targets} - input_bioprojects(in_path)
    if missing:
        ctx.log.info("previous work files don't cover %d of today's targets; starting over", len(missing))
        return False
    ctx.log.info("resuming the previous run: %s input rows done, %s written%s",
                 f"{state.get('rows_done', 0):,}", f"{state.get('projects_written', 0):,}",
                 " (already complete)" if state.get("done") else "")
    return True


def write_input(path: Path, targets: Iterable[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(targets)
    tmp.replace(path)


def remove_work_files() -> None:
    for path in work_paths():
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------- targets
def fetch_targets(ctx: common.Context, pending: list[str]) -> tuple[list[dict], int, int]:
    """(rows with text to embed, n without an embedding, n queued for re-embedding).

    One row per bioproject: a project is repeated once per sra_study with the
    same XML text, so the first study's row is taken (DISTINCT ON, as
    create_embeddings.py takes the first occurrence in bioprojects.csv).
    """
    cols = ", ".join(INPUT_COLUMNS)
    sql = (
        f"SELECT DISTINCT ON (bioproject) {cols},"
        "   NOT EXISTS (SELECT 1 FROM bioproject_embeddings e WHERE e.bioproject = b.bioproject) AS missing"
        " FROM bioprojects b"
        " WHERE b.bioproject = ANY(%s)"
        "    OR NOT EXISTS (SELECT 1 FROM bioproject_embeddings e WHERE e.bioproject = b.bioproject)"
        " ORDER BY bioproject, sra_study"
    )
    rows, missing, changed = [], 0, 0
    queued = set(pending)
    with ctx.connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (pending,))
        for rec in cur:
            row = dict(zip(INPUT_COLUMNS, rec))
            if rec[-1]:
                missing += 1
            elif row["bioproject"] in queued:
                changed += 1
            if build_text(row):  # projects not in the XML have no text: nothing to embed
                rows.append(row)
    # Queued (changed-text) projects first: they are the ones the site already
    # shows with stale vectors, and a --limit test then includes them.
    rows.sort(key=lambda r: r["bioproject"] not in queued)
    if ctx.options.limit is not None:
        rows = rows[: ctx.options.limit]
    return rows, missing, changed


# ---------------------------------------------------------------- load
def count_output(path: Path) -> int:
    """Complete data lines in the output TSV (the script fsyncs whole chunks)."""
    with open(path, "rb") as f:
        return max(0, sum(1 for line in f if line.endswith(b"\n")) - 1)


def upsert(ctx: common.Context, out_path: Path) -> int:
    """Loads the TSV into a staging table and merges it; returns rows upserted."""
    staging = "auto_update_embeddings_staging"
    with ctx.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {staging}")  # left over from a crashed run
            cur.execute(f"CREATE UNLOGGED TABLE {staging} (bioproject text, embedding vector(768))")
        # The script writes "bioproject\tembedding" with no quotes anywhere, so
        # CSV with its normal quote character is fine.
        common.copy_text_file(conn, staging, ["bioproject", "embedding"], out_path,
                              header=True, delimiter="\t", quote=None)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bioproject_embeddings (bioproject, embedding)"
                f" SELECT bioproject, embedding FROM {staging} WHERE bioproject IS NOT NULL"
                " ON CONFLICT (bioproject) DO UPDATE SET embedding = EXCLUDED.embedding"
            )
            n = cur.rowcount
            cur.execute(f"DROP TABLE {staging}")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("ANALYZE bioproject_embeddings")
        conn.commit()
    return n


# ---------------------------------------------------------------- step
def run(ctx: common.Context) -> dict:
    common.WORK_DIR.mkdir(parents=True, exist_ok=True)
    pending = ctx.pending_read("reembed")
    targets, missing, changed = fetch_targets(ctx, pending)
    result = {"targets": len(targets), "missing": missing, "changed_text": changed, "embedded": 0, "upserted": 0}
    ctx.log.info("%d bioprojects to embed: %d without an embedding, %d with changed text (%d queued)",
                 len(targets), missing, changed, len(pending))

    if ctx.options.dry_run:
        ctx.log.info("dry run: would embed %d bioprojects and upsert them into bioproject_embeddings", len(targets))
        return result
    if not targets:
        ctx.pending_clear("reembed")
        remove_work_files()
        return result

    in_path, out_path, _ = work_paths()
    if not can_resume(ctx, targets):
        remove_work_files()
        write_input(in_path, targets)

    cmd = [common.BACKEND_PYTHON, common.CREATE_EMBEDDINGS_SCRIPT, "--input", in_path, "--output", out_path,
           "--threads", ctx.config.threads, "--chunk-size", CHUNK_SIZE]
    common.run_logged(ctx, cmd, env={"HF_HOME": ctx.config.hf_home}, cwd=common.AUTOMATIONS_DIR)

    result["embedded"] = count_output(out_path)
    result["upserted"] = upsert(ctx, out_path)
    ctx.log.info("upserted %d embeddings", result["upserted"])
    # Only now is the work consumed: a crash above reruns from the checkpoint.
    # Under --limit the queue keeps what this run left out.
    done = {t["bioproject"] for t in targets}
    leftover = [p for p in pending if p not in done]
    ctx.pending_clear("reembed")
    if leftover:
        ctx.pending_add("reembed", leftover)
        ctx.log.info("%d queued projects left for the next run (--limit)", len(leftover))
    remove_work_files()
    return result
