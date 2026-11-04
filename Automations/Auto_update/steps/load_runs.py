"""Step "runs": new SRA runs from the parquet snapshot into sra_metadata.

The S3 snapshot is a full copy of SRA's run metadata (~44.6M rows, 13 GB of
parquet) and has no usable "modified since" column, so every run of this step
reads the whole snapshot and keeps the rows whose accession is not yet in
sra_metadata. Rows already in the table are never changed and never deleted:
the table only grows (docs/auto-update.md).

How the new rows are found without holding the snapshot in memory:

1. The accessions already in the table (~42.5M) are read once with COPY,
   padded by Postgres to a fixed width, and kept as one sorted fixed-width
   numpy array (about 11 bytes per accession, ~0.5 GB). A sorted array with
   np.searchsorted answers a 200k-row batch in under a second, whereas
   pyarrow's is_in rebuilds its hash table for every call (nearly a minute
   per batch at this size) and a Python set would take several GB.
2. The parquet files are streamed in batches of 200k rows reading only the
   table's columns. Rows with an unseen, non-null accession are cleaned with
   common.clean_cell (tabs and newlines to spaces, as the original TSV load)
   and written straight into an UNLOGGED staging table with binary COPY.
3. INSERT ... ON CONFLICT (acc) DO NOTHING moves the staging rows into
   sra_metadata. The membership test above only keeps the staging table
   small; the primary key is what guarantees no duplicates, so a stale or
   imprecise lookup can never corrupt the table.

Everything from the staging table on happens in one transaction: a crash
rolls it back and leaves the table exactly as it was, so the step can simply
be rerun. A second run over the same snapshot finds nothing new and inserts 0.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import psycopg

import common
from common import Context

TABLE = "sra_metadata"
STAGING = "auto_update_runs_staging"
BATCH_SIZE = 200_000
# A run accession: SRR/ERR/DRR followed by digits. Rows with anything else
# (there are a few garbage rows in the table, and null accessions in the
# snapshot) are neither looked up nor loaded.
ACCESSION_SQL_REGEX = "^[SED]RR[0-9]+$"
ACCESSION_RE = r"^[SED]RR[0-9]+$"
MAX_ACCESSION_LENGTH = 20
# COPY types for the staging table: everything is text except releasedate.
COLUMN_TYPES = ["date" if c == "releasedate" else "text" for c in common.RUN_COLUMNS]


# ---------------------------------------------------------------- existing accessions
class AccessionSet:
    """The accessions already in sra_metadata, as a sorted fixed-width byte array.

    Accessions are ASCII (SRR/ERR/DRR + digits), so a numpy "S<width>" array
    sorts and compares bytewise; the padding is spaces on both sides, so a
    padded lookup key equals a padded stored value exactly when the
    accessions are equal.
    """

    def __init__(self, values: np.ndarray, width: int):
        self.values = values      # sorted, dtype S<width>
        self.width = width

    def __len__(self) -> int:
        return len(self.values)

    def contains(self, accs: pa.Array) -> np.ndarray:
        """A boolean numpy mask: True where the accession is already in the table.

        Nulls, accessions longer than the stored width and anything that is
        not a plain run accession (see valid_accessions) cannot be in the set
        and get False.
        """
        if len(self.values) == 0:
            return np.zeros(len(accs), dtype=bool)
        accs = accs.cast(pa.large_string())
        accs = pc.if_else(valid_accessions(accs, self.width), accs, "")
        padded = pc.utf8_rpad(accs, self.width, padding=" ")
        data = padded.buffers()[2]
        if len(data) != len(accs) * self.width:
            # Only ASCII keys pad to width bytes; a multibyte accession would
            # shift every key after it. valid_accessions() excludes them, so
            # this can only be a pyarrow change: fail loudly rather than skip rows.
            raise RuntimeError("padded accession buffer has an unexpected length")
        keys = np.frombuffer(data, dtype=f"S{self.width}", count=len(accs))
        pos = np.searchsorted(self.values, keys)
        pos[pos == len(self.values)] = 0          # past the end: compare with any element, it won't match
        return self.values[pos] == keys


def valid_accessions(accs: pa.Array, width: Optional[int] = None) -> pa.Array:
    """A boolean array: True where the value is a run accession (non-null,
    ASCII SRR/ERR/DRR + digits, and at most `width` characters when given)."""
    ok = pc.match_substring_regex(accs, ACCESSION_RE)
    ok = pc.fill_null(ok, False)
    if width is not None:
        ok = pc.and_(ok, pc.less_equal(pc.binary_length(accs), width))
    return ok


def read_existing_accessions(ctx: Context, conn: psycopg.Connection) -> AccessionSet:
    """All acc values of sra_metadata, via COPY, into a sorted AccessionSet.

    Postgres pads each accession to the longest length in the table, so each
    line of the COPY output has the same number of bytes and the temporary
    file is read into numpy directly, without parsing. Peak memory is about
    twice the padded size (the raw lines, then the array sorted in place).
    """
    t0 = time.monotonic()
    # Only real run accessions count. The table holds a few garbage rows from
    # the original TSV load whose acc is a 500-1300 character fragment of
    # other columns; padding every accession to that width would mean a
    # 50 GB buffer. Such rows are treated as absent, which is harmless: the
    # snapshot never carries those keys, and the primary key catches any clash.
    width = common.scalar(conn, f"SELECT coalesce(max(length(acc)), 0) FROM {TABLE} WHERE acc ~ %s",
                          (ACCESSION_SQL_REGEX,)) or 0
    if width == 0:
        ctx.log.info("%s is empty: every snapshot row is new", TABLE)
        return AccessionSet(np.empty(0, dtype="S1"), 1)
    if width > MAX_ACCESSION_LENGTH:
        raise RuntimeError(f"an accession of {width} characters matched {ACCESSION_SQL_REGEX}; refusing to pad to that width")

    common.WORK_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="existing_accs_", suffix=".txt", dir=common.WORK_DIR) as tmp:
        with conn.cursor() as cur:
            with cur.copy(f"COPY (SELECT rpad(acc, {width}, ' ') FROM {TABLE} WHERE acc ~ '{ACCESSION_SQL_REGEX}') TO STDOUT") as copy:
                for data in copy:
                    tmp.write(data)
        tmp.flush()
        tmp.seek(0)
        raw = np.fromfile(tmp, dtype=np.uint8)
    line = width + 1                               # the padded accession plus "\n"
    if raw.size % line:
        raise RuntimeError(f"unexpected COPY output ({raw.size} bytes, line width {line}): an accession contains a byte COPY escapes")
    values = np.ascontiguousarray(raw.reshape(-1, line)[:, :width]).view(f"S{width}").reshape(-1)
    del raw
    values.sort()
    ctx.log.info("existing accessions: %s (width %d, %s)", f"{len(values):,}", width,
                 common.format_duration(time.monotonic() - t0))
    return AccessionSet(values, width)


# ---------------------------------------------------------------- scanning the snapshot
def clean_row(row: Sequence) -> tuple:
    """A staging row: text columns through clean_cell, the date kept as a date."""
    return tuple(v if t == "date" else common.clean_cell(v) for v, t in zip(row, COLUMN_TYPES))


def new_rows(ctx: Context, files: Sequence[Path], existing: AccessionSet, stats: dict) -> Iterator[tuple]:
    """Yields the cleaned rows of the snapshot whose accession is not in the table.

    Rows are read 200k at a time, only the table's columns. An accession seen
    earlier in this snapshot (duplicates do occur between files) is skipped.
    Honors ctx.options.limit (stop after that many new rows) and keeps
    stats["rows_read"] / stats["new_runs"] up to date for the summary.
    """
    limit = ctx.options.limit
    seen: set[str] = set()
    acc_index = common.RUN_COLUMNS.index("acc")
    for n, path in enumerate(files, 1):
        t0 = time.monotonic()
        file_rows = file_new = 0
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=BATCH_SIZE, columns=common.RUN_COLUMNS):
            file_rows += batch.num_rows
            accs = batch.column("acc")
            keep = pc.and_(valid_accessions(accs), pa.array(~existing.contains(accs)))
            candidates = batch.filter(keep)
            if candidates.num_rows == 0:
                continue
            columns = [candidates.column(c).to_pylist() for c in common.RUN_COLUMNS]
            for row in zip(*columns):
                acc = row[acc_index]
                if not acc or acc in seen:
                    continue
                seen.add(acc)
                file_new += 1
                stats["new_runs"] += 1
                yield clean_row(row)
                if limit is not None and stats["new_runs"] >= limit:
                    break
            if limit is not None and stats["new_runs"] >= limit:
                break
        stats["rows_read"] += file_rows
        elapsed = time.monotonic() - t0
        ctx.log.info("file %d/%d %s: %s rows, %s new (%s rows/s)", n, len(files), path.name,
                     f"{file_rows:,}", f"{file_new:,}", f"{file_rows / elapsed:,.0f}" if elapsed else "-")
        if limit is not None and stats["new_runs"] >= limit:
            ctx.log.info("limit of %d new runs reached, stopping the scan", limit)
            return


# ---------------------------------------------------------------- loading
def check_columns(conn: psycopg.Connection) -> None:
    """The staging COPY relies on the table's column order being RUN_COLUMNS."""
    columns = common.table_columns(conn, TABLE)
    if columns != common.RUN_COLUMNS:
        raise RuntimeError(f"{TABLE} columns {columns} differ from common.RUN_COLUMNS {common.RUN_COLUMNS}")


def load_into_staging(conn: psycopg.Connection, rows: Iterator[tuple]) -> int:
    """Copies the rows into a fresh staging table (created in the transaction)."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE UNLOGGED TABLE IF NOT EXISTS {STAGING} (LIKE {TABLE})")
        cur.execute(f"TRUNCATE {STAGING}")
    return common.copy_rows(conn, STAGING, common.RUN_COLUMNS, rows, types=COLUMN_TYPES)


def insert_from_staging(conn: psycopg.Connection) -> int:
    """Moves the staging rows into the table, skipping accessions that are
    already there, and drops the staging table. Returns the rows inserted."""
    cols = ", ".join(common.RUN_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {TABLE} ({cols}) SELECT {cols} FROM {STAGING} ON CONFLICT (acc) DO NOTHING")
        inserted = cur.rowcount
        cur.execute(f"DROP TABLE {STAGING}")
    return inserted


# ---------------------------------------------------------------- the step
def run(ctx: Context) -> dict:
    snapshot = ctx.snapshot_dir()
    files = ctx.parquet_files()
    if not files:
        raise FileNotFoundError(f"no parquet files in {snapshot}")
    ctx.log.info("snapshot %s: %d parquet files%s", snapshot.name, len(files),
                 f" (first {ctx.options.files})" if ctx.options.files is not None else "")

    stats = {"rows_read": 0, "new_runs": 0}
    inserted = 0
    t0 = time.monotonic()
    with ctx.connect() as conn:
        check_columns(conn)
        existing = read_existing_accessions(ctx, conn)
        rows = new_rows(ctx, files, existing, stats)
        if ctx.options.dry_run:
            for _ in rows:
                pass
            ctx.log.info("dry run: %s new runs would be inserted into %s", f"{stats['new_runs']:,}", TABLE)
        else:
            with ctx.timed(f"loading new runs into {STAGING}"):
                staged = load_into_staging(conn, rows)
            with ctx.timed(f"inserting {staged:,} staged runs into {TABLE}"):
                inserted = insert_from_staging(conn)
        del existing
    # the connection's `with` committed the transaction (or rolled it back on an exception)

    elapsed = time.monotonic() - t0
    ctx.log.info("runs: %s rows read, %s new, %s inserted (%s rows/s overall)", f"{stats['rows_read']:,}",
                 f"{stats['new_runs']:,}", f"{inserted:,}", f"{stats['rows_read'] / elapsed:,.0f}" if elapsed else "-")
    return {"snapshot": snapshot.name, "files": len(files), "rows_read": stats["rows_read"],
            "new_runs": stats["new_runs"], "inserted": inserted}
