"""Weekly update of the SRAscout database (see docs/auto-update.md).

Runs the steps of common.STEPS in order, each one a module in steps/ with
`run(ctx) -> dict`. Steps only INSERT and UPDATE rows: nothing is ever
deleted from the data tables, and every step can be rerun after a failure
without redoing or duplicating finished work.

Usage (from Automations/Auto_update, with its .venv):
  update.py                       the whole pipeline (what the systemd timer runs)
  update.py --list                the steps, in order, and the selection
  update.py --from embeddings     that step and the ones after it (resume a failed run)
  update.py --only refresh        one step
  update.py --steps runs,projects a subset, run in canonical order
  update.py --dry-run             compute everything, write nothing to the database
  update.py --limit N --files N --snapshot NAME   small inputs for testing

Exit codes: 0 ok, 1 a step failed, 2 bad arguments, 3 another run holds the lock,
130 interrupted (Ctrl-C or `systemctl stop`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import importlib
import importlib.util
import os
import re
import signal
import sys
import time
import traceback
from pathlib import Path

# `import common` and `import steps.x` resolve relative to this folder, and
# the step modules import the original Automations scripts (create_tables,
# jattr_normalize, ...) from the parent folder, so both go on sys.path
# before anything else is imported.
AUTO_DIR = Path(__file__).resolve().parent
for p in (AUTO_DIR, AUTO_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import common  # noqa: E402

# Step name (as on the command line and in the logs) -> module under steps/.
STEP_MODULES = {
    "download": "download",
    "runs": "load_runs",
    "attributes": "build_attributes",
    "projects": "update_bioprojects",
    "refresh": "refresh",
    "embeddings": "embed",
    "tags": "tag",
    "finish": "finish",
}
assert list(STEP_MODULES) == common.STEPS, "STEP_MODULES must list common.STEPS in order"

LAST_RUN_FILE = common.STATE_DIR / "last_run.json"

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_LOCKED = 0, 1, 2, 3


# ---------------------------------------------------------------- arguments
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="update.py",
        description="Weekly update of the SRAscout database: new runs, projects, attributes, embeddings and tags.",
        epilog="Steps, in order: " + ", ".join(common.STEPS),
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--steps", metavar="A,B", help="run only these steps (comma-separated, in canonical order)")
    which.add_argument("--from", dest="from_step", metavar="STEP", help="run this step and the ones after it")
    which.add_argument("--only", metavar="STEP", help="run a single step")
    parser.add_argument("--dry-run", action="store_true", help="compute everything but write nothing to the database")
    parser.add_argument("--limit", type=int, metavar="N", help="at most N new runs / projects per step (testing)")
    parser.add_argument("--files", type=int, metavar="N", help="only the first N parquet files of the snapshot (testing)")
    parser.add_argument("--snapshot", metavar="NAME", help="use this snapshot folder instead of the newest complete one")
    parser.add_argument("--list", action="store_true", help="list the steps and the selection, then exit")
    args = parser.parse_args(argv)
    for name in ("limit", "files"):
        value = getattr(args, name)
        if value is not None and value < 1:
            parser.error(f"--{name} must be 1 or more (use --dry-run to write nothing)")
    return args


def select_steps(args: argparse.Namespace) -> list[str]:
    """The steps to run, always in canonical order. Raises ValueError on unknown names."""
    def check(name: str) -> str:
        name = name.strip()
        if name not in common.STEPS:
            raise ValueError(f"unknown step {name!r}; the steps are: {', '.join(common.STEPS)}")
        return name

    if args.only:
        return [check(args.only)]
    if args.from_step:
        return common.STEPS[common.STEPS.index(check(args.from_step)):]
    if args.steps:
        wanted = {check(n) for n in args.steps.split(",") if n.strip()}
        if not wanted:
            raise ValueError("--steps needs at least one step name")
        return [s for s in common.STEPS if s in wanted]
    return list(common.STEPS)


def module_exists(step: str) -> bool:
    return importlib.util.find_spec(f"steps.{STEP_MODULES[step]}") is not None


def list_steps(selected: list[str]) -> None:
    print(f"{'':2} {'step':12} {'module':30} {'status'}")
    for step in common.STEPS:
        mark = "*" if step in selected else " "
        module = f"steps/{STEP_MODULES[step]}.py"
        status = "" if module_exists(step) else "MISSING"
        print(f"{mark:2} {step:12} {module:30} {status}")
    print(f"\n* = selected ({len(selected)} of {len(common.STEPS)})")


# ---------------------------------------------------------------- lock
def acquire_lock():
    """One run at a time: the steps share work files and staging tables.

    Returns the open lock file (keep it referenced: closing it releases the
    lock) or None when another process holds it. flock is released by the
    kernel when the process dies, so a crashed run never leaves a stale lock.
    """
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = open(common.LOCK_FILE, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.seek(0)
        holder = f.read().strip()
        f.close()
        print(f"another update is running ({holder or 'pid unknown'}); lock file {common.LOCK_FILE}", file=sys.stderr)
        return None
    f.seek(0)
    f.truncate()
    f.write(f"pid {os.getpid()} since {dt.datetime.now().isoformat(timespec='seconds')}\n")
    f.flush()
    return f


# ---------------------------------------------------------------- running
def mask_password(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def log_configuration(ctx: common.Context, selected: list[str]) -> None:
    cfg = ctx.config
    ctx.log.info("run %s: steps %s", ctx.run_id, ", ".join(selected))
    ctx.log.info("database %s (%s)", cfg.database_name, mask_password(cfg.dsn))
    ctx.log.info(
        "config: threads=%d jattr_workers=%d tag_workers=%d tag_threads=%d tag_backfill=%d keep_downloads=%s keep_snapshots=%d "
        "restart_api=%s api_service=%s hf_home=%s download_concurrency=%d",
        cfg.threads, cfg.jattr_workers, cfg.tag_workers, cfg.tag_threads, cfg.tag_backfill, cfg.keep_downloads, cfg.keep_snapshots,
        cfg.restart_api, cfg.api_service, cfg.hf_home, cfg.download_concurrency,
    )
    opts = ctx.options
    ctx.log.info("options: dry_run=%s limit=%s files=%s snapshot=%s", opts.dry_run, opts.limit, opts.files, opts.snapshot)
    if opts.dry_run:
        ctx.log.info("DRY RUN: nothing is written to the database")


def load_step(step: str):
    """Imports the step's module only now, so --list and runs of a subset work
    while other modules are missing or broken."""
    module = STEP_MODULES[step]
    if not module_exists(step):
        raise RuntimeError(f"step {step!r} has no module: {common.AUTO_DIR / 'steps' / (module + '.py')} is missing")
    mod = importlib.import_module(f"steps.{module}")
    if not callable(getattr(mod, "run", None)):
        raise RuntimeError(f"steps/{module}.py has no run(ctx) function")
    return mod


def write_state(run_id: str, started: dt.datetime, status: str, selected: list[str], ctx: common.Context,
                durations: dict[str, float], failed_step: str | None = None, error: str | None = None) -> None:
    """state/last_run.json: what the last run did, for people and for the docs'
    troubleshooting steps. Written after every step so a crash leaves a record."""
    data = {
        "run_id": run_id,
        "started": started.isoformat(timespec="seconds"),
        "finished": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "dry_run": ctx.options.dry_run,
        "database": ctx.config.database_name,
        "selected": selected,
        "steps": ctx.results,
        "durations": {k: round(v, 1) for k, v in durations.items()},
    }
    if failed_step:
        data["failed_step"] = failed_step
    if error:
        data["error"] = error
    common.write_json(LAST_RUN_FILE, data)


def run_steps(ctx: common.Context, selected: list[str], started: dt.datetime) -> int:
    durations: dict[str, float] = {}
    for step in selected:
        t0 = time.monotonic()
        try:
            mod = load_step(step)
            with ctx.timed(f"step {step}"):
                result = mod.run(ctx)
        except KeyboardInterrupt:
            durations[step] = time.monotonic() - t0
            ctx.log.error("step %s interrupted; rerun with --from %s", step, step)
            write_state(ctx.run_id, started, "interrupted", selected, ctx, durations, failed_step=step)
            return 130
        except Exception as exc:  # noqa: BLE001  (any failure stops the run; the log has the traceback)
            durations[step] = time.monotonic() - t0
            ctx.log.error("step %s failed: %s\n%s", step, exc, traceback.format_exc())
            write_state(ctx.run_id, started, "failed", selected, ctx, durations, failed_step=step,
                        error=f"{type(exc).__name__}: {exc}")
            ctx.log.error("run %s FAILED at step %s; fix the cause and rerun with --from %s", ctx.run_id, step, step)
            return EXIT_FAILED
        durations[step] = time.monotonic() - t0
        ctx.results[step] = result if isinstance(result, dict) else {"result": result}
        ctx.log.info("step %s result: %s", step, ctx.results[step])
        write_state(ctx.run_id, started, "running", selected, ctx, durations)
    write_state(ctx.run_id, started, "ok", selected, ctx, durations)
    ctx.log.info("run %s finished OK in %s", ctx.run_id, common.format_duration(sum(durations.values())))
    for step, seconds in durations.items():
        ctx.log.info("  %-12s %s", step, common.format_duration(seconds))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        selected = select_steps(args)
    except ValueError as exc:
        print(f"update.py: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.list:
        list_steps(selected)
        return EXIT_OK

    lock = acquire_lock()
    if lock is None:
        return EXIT_LOCKED

    # `systemctl stop` sends SIGTERM: treat it like Ctrl-C, so the running
    # step's transaction rolls back and last_run.json says "interrupted".
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)

    # The website runs on the same box: give its API and Postgres priority over
    # us. Child processes (embedding, tagging, wget) inherit the niceness.
    try:
        os.nice(10)
    except OSError:
        pass

    common.ensure_dirs()
    run_id = common.now_id()
    started = dt.datetime.now()
    log = common.setup_logging(run_id)
    try:
        config = common.Config.load()
    except SystemExit as exc:
        log.error("%s", exc)
        return EXIT_USAGE
    ctx = common.Context(
        config=config, log=log, run_id=run_id,
        options=common.Options(dry_run=args.dry_run, limit=args.limit, files=args.files, snapshot=args.snapshot),
    )
    log_configuration(ctx, selected)
    try:
        return run_steps(ctx, selected, started)
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
