"""Shared pieces of the weekly update pipeline (see docs/auto-update.md).

Every step module in steps/ exposes `run(ctx: Context) -> dict` and gets this
module's Context: configuration, a logger, the database connection factory,
the run's command-line options and the small on-disk state that lets steps
hand work to each other (pending_* files) and resume after a failure.

Nothing here touches the database on import.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

import psycopg

# ---------------------------------------------------------------- paths
AUTO_DIR = Path(__file__).resolve().parent                 # Automations/Auto_update
AUTOMATIONS_DIR = AUTO_DIR.parent                           # Automations
ROOT_DIR = AUTOMATIONS_DIR.parent                           # repository root
BACKEND_DIR = ROOT_DIR / "backend"
BACKEND_ENV = BACKEND_DIR / ".env"
BACKEND_PYTHON = BACKEND_DIR / ".venv" / "bin" / "python"
TAGWORDS_DIR = AUTOMATIONS_DIR / "TagWords"
TAGWORDS_PYTHON = TAGWORDS_DIR / ".venv" / "bin" / "python"
CREATE_EMBEDDINGS_SCRIPT = AUTOMATIONS_DIR / "create_embeddings.py"
EXTRACT_TAGS_SCRIPT = TAGWORDS_DIR / "extract_tags.py"
GET_ENA_XML_SCRIPT = AUTOMATIONS_DIR / "ENA" / "get_ENA_xml.sh"
ENA_XML = AUTOMATIONS_DIR / "ENA" / "bioproject.xml"

DATA_DIR = AUTO_DIR / "data"                                # downloads (gitignored)
SNAPSHOTS_DIR = DATA_DIR / "sra_metadata"                   # one folder per S3 snapshot
OUTPUT_DIR = DATA_DIR / "output"                            # TSVs the steps write before loading
WORK_DIR = AUTO_DIR / "work"                                # inputs/outputs of the embedding and tag runs
STATE_DIR = AUTO_DIR / "state"                              # pending_*.txt, last_run.json, lock
LOG_DIR = AUTO_DIR / "logs"
LOCK_FILE = STATE_DIR / "update.lock"
SNAPSHOT_COMPLETE_MARKER = "COMPLETE"                       # written in a snapshot folder once every file is there

S3_BUCKET = "sra-pub-metadata-us-east-1"
S3_PREFIX = "sra/metadata/"
S3_REGION = "us-east-1"

# The steps, in the order update.py runs them.
STEPS = ["download", "runs", "attributes", "projects", "refresh", "embeddings", "tags", "finish"]

# sra_metadata's columns, in table order (Automations/output/sra_metadata_schema.sql).
# The parquet files hold the same names.
RUN_COLUMNS = [
    "acc", "assay_type", "center_name", "experiment", "sample_name", "instrument",
    "librarylayout", "libraryselection", "librarysource", "platform", "sample_acc",
    "biosample", "organism", "sra_study", "releasedate", "bioproject", "library_name",
    "geo_loc_name_country_calc",
]

# bioprojects columns the XML provides (Automations/create_tables.py COLUMNS minus
# the pair columns bioproject, sra_study, n_experiments, found_in_bioproject_xml).
# Kept in create_tables.COLUMNS order.
XML_COLUMNS = [
    "bioproject_uid", "name", "title", "description", "data_types", "organism_name", "tax_id",
    "supergroup", "target_material", "target_capture", "sample_scope", "method_type", "objectives",
    "relevance", "project_release_date", "geo_accessions", "center_ids", "external_links", "grants",
    "publication_count", "pubmed_ids", "first_publication_date", "journals", "publication_titles",
    "publications", "submission_id", "submitted_date", "last_update_date", "organization",
    "organization_country", "access", "parent_projects",
]
# Columns the normalisation page renames (backend/app/normalize.py FIELDS of kind
# "column"). On existing rows they are only filled in when NULL, never overwritten,
# so the weekly update doesn't undo renames (normalize apply runs afterwards anyway).
NORMALIZED_COLUMNS = ["organism_name", "supergroup", "organization_country"]
# Columns whose change means the project's embedding and tags are stale.
TEXT_COLUMNS = ["title", "name", "description"]

# Materialized views, in the order they are refreshed (backend/sql/*.sql).
VIEWS = ["study_facets", "bioproject_attribute_values", "bioproject_fulltext"]


# ---------------------------------------------------------------- config
def _read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; quotes around the value are stripped. Missing file -> {}."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _env(name: str, default: str, files: Sequence[dict[str, str]]) -> str:
    """The process environment wins, then the env files in order, then the default."""
    if name in os.environ:
        return os.environ[name]
    for values in files:
        if name in values:
            return values[name]
    return default


@dataclass
class Config:
    database_url: str
    threads: int = 4            # CPU threads for pyarrow / embedding
    jattr_workers: int = 4      # processes reading jattr from the parquet files
    tag_workers: int = 2        # GLiNER worker processes (~3 GB RAM each)
    tag_threads: int = 2        # torch threads per GLiNER worker
    tag_backfill: int = 20000   # untagged old projects tagged per run, besides new/changed ones
    keep_snapshots: int = 1     # downloaded S3 snapshots kept after a successful run
    restart_api: bool = True    # systemctl restart srascout-api at the end
    api_service: str = "srascout-api"
    hf_home: str = "/root/.cache/huggingface"
    download_concurrency: int = 4

    @classmethod
    def load(cls) -> "Config":
        """Settings from the environment, Automations/Auto_update/.env, then backend/.env.

        DATABASE_URL is the backend's by default, so the pipeline writes the
        database the API serves. Override it (e.g. for a test database) with
        DATABASE_URL in the environment or in Auto_update/.env.
        """
        files = [_read_env_file(AUTO_DIR / ".env"), _read_env_file(BACKEND_ENV)]
        url = _env("DATABASE_URL", "", files)
        if not url:
            raise SystemExit("DATABASE_URL is not set (backend/.env or Automations/Auto_update/.env)")

        def num(name: str, default: int) -> int:
            return int(_env(name, str(default), files))

        def flag(name: str, default: bool) -> bool:
            return _env(name, "true" if default else "false", files).strip().lower() in ("1", "true", "yes", "on")

        return cls(
            database_url=url,
            threads=num("AUTO_UPDATE_THREADS", 4),
            jattr_workers=num("AUTO_UPDATE_JATTR_WORKERS", 4),
            tag_workers=num("AUTO_UPDATE_TAG_WORKERS", 2),
            tag_threads=num("AUTO_UPDATE_TAG_THREADS", 2),
            tag_backfill=num("AUTO_UPDATE_TAG_BACKFILL", 20000),
            keep_snapshots=num("AUTO_UPDATE_KEEP_SNAPSHOTS", 1),
            restart_api=flag("AUTO_UPDATE_RESTART_API", True),
            api_service=_env("AUTO_UPDATE_API_SERVICE", "srascout-api", files),
            hf_home=_env("HF_HOME", "/root/.cache/huggingface", files),
            download_concurrency=num("AUTO_UPDATE_DOWNLOAD_CONCURRENCY", 4),
        )

    @property
    def dsn(self) -> str:
        """The SQLAlchemy URL (postgresql+psycopg://...) as a plain libpq URL."""
        return re.sub(r"^postgresql\+psycopg(2)?://", "postgresql://", self.database_url)

    @property
    def database_name(self) -> str:
        return self.dsn.rsplit("/", 1)[-1].split("?", 1)[0]


# ---------------------------------------------------------------- logging
def setup_logging(run_id: str) -> logging.Logger:
    """Logs to logs/update-<run_id>.log and to stderr (journald under systemd)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("auto_update")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.StreamHandler(sys.stderr), logging.FileHandler(LOG_DIR / f"update-{run_id}.log")):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------- context
@dataclass
class Options:
    """Command-line options that steps care about (update.py fills them)."""
    dry_run: bool = False           # read and compute, but write nothing to the database
    limit: Optional[int] = None     # at most this many new runs / projects per step (testing)
    files: Optional[int] = None     # only the first N parquet files of the snapshot (testing)
    snapshot: Optional[str] = None  # use this snapshot folder name instead of the newest complete one


@dataclass
class Context:
    config: Config
    log: logging.Logger
    run_id: str
    options: Options = field(default_factory=Options)
    results: dict = field(default_factory=dict)   # step name -> counts returned by the step

    # ---- database
    def connect(self, autocommit: bool = False) -> psycopg.Connection:
        """A new connection; the caller closes it (use `with ctx.connect() as conn`).

        Sets the session up for the pipeline's bulk work: a larger work_mem
        and maintenance_work_mem (the server's defaults are 4 MB and 64 MB),
        and no statement timeout.
        """
        conn = psycopg.connect(self.config.dsn, autocommit=autocommit, application_name="srascout-update")
        with conn.cursor() as cur:
            cur.execute("SET work_mem = '256MB'")
            cur.execute("SET maintenance_work_mem = '1GB'")
            cur.execute("SET statement_timeout = 0")
            cur.execute("SET lock_timeout = 0")
        if not autocommit:
            conn.commit()
        return conn

    # ---- snapshots
    def snapshot_dir(self) -> Path:
        """The newest downloaded S3 snapshot that is complete (or --snapshot)."""
        if self.options.snapshot:
            path = SNAPSHOTS_DIR / self.options.snapshot
            if not path.is_dir():
                raise FileNotFoundError(f"snapshot folder {path} not found")
            return path
        complete = sorted(p for p in SNAPSHOTS_DIR.glob("*") if (p / SNAPSHOT_COMPLETE_MARKER).exists())
        if not complete:
            raise FileNotFoundError(f"no complete snapshot under {SNAPSHOTS_DIR}; run the download step first")
        return complete[-1]

    def parquet_files(self) -> list[Path]:
        """The snapshot's parquet files, sorted; only the first --files of them if set."""
        files = sorted(self.snapshot_dir().glob("*.parquet"))
        if self.options.files is not None:
            files = files[: self.options.files]
        return files

    # ---- pending work handed between steps (one bioproject accession per line)
    def _pending_path(self, name: str) -> Path:
        return STATE_DIR / f"pending_{name}.txt"

    def pending_add(self, name: str, ids: Iterable[str]) -> int:
        """Appends accessions to state/pending_<name>.txt (duplicates are harmless)."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ids = [i.strip() for i in ids if i and i.strip()]
        if ids:
            with open(self._pending_path(name), "a", encoding="utf-8") as f:
                f.write("\n".join(ids) + "\n")
        return len(ids)

    def pending_read(self, name: str) -> list[str]:
        """The accessions in state/pending_<name>.txt, deduplicated, in order."""
        path = self._pending_path(name)
        if not path.exists():
            return []
        return list(dict.fromkeys(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()))

    def pending_clear(self, name: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._pending_path(name).unlink()

    # ---- bookkeeping
    @contextlib.contextmanager
    def timed(self, what: str) -> Iterator[None]:
        """Logs how long a block took."""
        t0 = time.monotonic()
        self.log.info("%s ...", what)
        try:
            yield
        finally:
            self.log.info("%s: %s", what, format_duration(time.monotonic() - t0))


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- database helpers
def ensure_dirs() -> None:
    for d in (DATA_DIR, SNAPSHOTS_DIR, OUTPUT_DIR, WORK_DIR, STATE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def copy_rows(conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence],
              types: Optional[Sequence[str]] = None) -> int:
    """COPY rows (sequences of Python values; None is NULL) into table.

    Binary COPY, so values are sent as their Postgres types: pass `types` (one
    libpq type name per column, e.g. "text", "date", "jsonb", "vector") when
    a column isn't text. Returns the number of rows written.
    """
    n = 0
    cols = ", ".join(columns)
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN (FORMAT binary)") as copy:
            if types:
                copy.set_types(list(types))
            for row in rows:
                copy.write_row(row)
                n += 1
    return n


def copy_text_file(conn: psycopg.Connection, table: str, columns: Sequence[str], path: Path,
                   header: bool = True, delimiter: str = "\t", quote: Optional[str] = "\x01") -> None:
    """COPY a TSV/CSV file into table, in the CSV format the schema files use:
    with QUOTE E'\\x01' (the default here) values are taken literally and empty
    fields become NULL. quote=None uses CSV's normal double quote."""
    cols = ", ".join(columns)
    opts = ["FORMAT csv", "DELIMITER E'\\t'" if delimiter == "\t" else f"DELIMITER '{delimiter}'"]
    if header:
        opts.append("HEADER true")
    if quote == "\x01":
        opts.append("QUOTE E'\\x01'")
    elif quote is not None:
        opts.append(f"QUOTE '{quote}'")
    with conn.cursor() as cur, open(path, "rb") as f:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN ({', '.join(opts)})") as copy:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                copy.write(chunk)


def table_columns(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def relation_exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
        return bool(cur.fetchone()[0])


def scalar(conn: psycopg.Connection, sql: str, params: Sequence = ()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def clean_cell(value) -> Optional[str]:
    """A string for a text column: None for None/empty; tabs, newlines and NULs
    replaced by spaces (they would break the TSV outputs and \\copy loads)."""
    if value is None:
        return None
    s = str(value)
    if not s:
        return None
    if "\t" in s or "\n" in s or "\r" in s or "\x00" in s:
        s = s.replace("\t", " ").replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\x00", "")
    return s


# ---------------------------------------------------------------- subprocesses
def run_logged(ctx: Context, cmd: Sequence[str], env: Optional[dict] = None, cwd: Optional[Path] = None,
               check: bool = True) -> int:
    """Runs a command, forwarding each output line to the log. Returns the exit code."""
    ctx.log.info("$ %s", " ".join(str(c) for c in cmd))
    full_env = dict(os.environ)
    full_env.update(env or {})
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=full_env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            ctx.log.info("  | %s", line)
    code = proc.wait()
    if check and code != 0:
        raise RuntimeError(f"{cmd[0]} exited with {code}")
    return code


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
