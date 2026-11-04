"""finish step: the last things a run does once the data is in place.

  1. bioproject_fulltext is refreshed once more: the refresh step rebuilt it
     before the tags step ran, and tag words feed the view (backend/sql/
     bioproject_fulltext.sql), so the new projects' tags only become
     searchable now. The tables the embeddings and tags steps wrote are
     ANALYZEd.
  2. The API is restarted (AUTO_UPDATE_RESTART_API, on by default): it caches
     filter values and statistics for up to an hour and checks only once a
     minute which views exist, so a restart is how the site shows the new
     week at once. systemd restarts the two uvicorn workers in seconds.
  3. Old S3 snapshots are removed from data/sra_metadata/: each one is 13 GB,
     and only the newest complete ones (AUTO_UPDATE_KEEP_SNAPSHOTS, default 1)
     and the snapshot this run used are kept. Half-downloaded files of kept
     snapshots are removed too. Folders newer than the kept ones are left
     alone even when incomplete, so the download step can resume them.

Nothing here deletes database rows. Everything is idempotent.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import common
from steps.refresh import analyze_relations

ANALYZE_RELATIONS = ["bioproject_embeddings", "bioproject_tags", "bioproject_fulltext"]

# Snapshot folders are named after the S3 snapshot date (download step); only
# folders of that shape are ever removed, so a stray folder is at most logged.
SNAPSHOT_NAME = re.compile(r"^\d{8}$")


def run(ctx: common.Context) -> dict:
    refreshed = refresh_fulltext(ctx)
    analyze_relations(ctx, ANALYZE_RELATIONS)
    restarted = restart_api(ctx)
    removed = remove_old_snapshots(ctx)
    return {"views_refreshed": refreshed, "api_restarted": restarted, "snapshots_removed": removed}


def refresh_fulltext(ctx: common.Context) -> list[str]:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext, if it exists.

    CONCURRENTLY needs autocommit and the view's unique index, and keeps the
    old contents readable while it rebuilds (about a minute on the full data).
    """
    view = "bioproject_fulltext"
    with ctx.connect(autocommit=True) as conn:
        if not common.relation_exists(conn, view):
            ctx.log.warning("materialized view %s does not exist; skipped (see docs/production.md)", view)
            return []
        if ctx.options.dry_run:
            ctx.log.info("dry run: would REFRESH MATERIALIZED VIEW CONCURRENTLY %s", view)
            return []
        with ctx.timed(f"refresh {view}"):
            conn.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
    return [view]


def restart_api(ctx: common.Context) -> bool:
    """`systemctl restart <api_service>`; returns whether it succeeded.

    A failed restart is logged, not raised: the data is loaded and the API
    picks the changes up by itself within an hour, so the run still counts
    as successful.
    """
    service = ctx.config.api_service
    if not ctx.config.restart_api:
        ctx.log.info("API restart disabled (AUTO_UPDATE_RESTART_API); %s keeps its caches up to an hour", service)
        return False
    if ctx.options.dry_run:
        ctx.log.info("dry run: would systemctl restart %s", service)
        return False
    systemctl = shutil.which("systemctl")
    if not systemctl:
        ctx.log.warning("systemctl not found; %s not restarted", service)
        return False
    code = common.run_logged(ctx, [systemctl, "restart", service], check=False)
    if code != 0:
        ctx.log.warning("systemctl restart %s exited with %s; the API shows the new data within an hour", service, code)
        return False
    ctx.log.info("restarted %s", service)
    return True


def remove_old_snapshots(ctx: common.Context) -> list[str]:
    """Deletes snapshot folders older than the ones kept; returns their names.

    Kept: the ctx.config.keep_snapshots newest complete snapshots (those with
    the COMPLETE marker) and the snapshot this run read, whatever its state.
    Anything newer than the oldest kept folder stays too: an incomplete newer
    folder is a download the next run resumes. Leftover *.part* files inside
    kept, complete folders are junk from an interrupted download and go.
    """
    folders = sorted(p for p in common.SNAPSHOTS_DIR.glob("*") if p.is_dir())
    complete = [p for p in folders if (p / common.SNAPSHOT_COMPLETE_MARKER).exists()]
    n_keep = ctx.config.keep_snapshots
    keep = {p.name for p in complete[-n_keep:]} if n_keep > 0 else set()
    try:
        current = ctx.snapshot_dir().name
        keep.add(current)
    except FileNotFoundError:
        current = None  # no snapshot at all (e.g. --only finish before any download)
    removed = []
    oldest_kept = min(keep) if keep else None
    for folder in folders:
        if folder.name in keep or (oldest_kept is not None and folder.name > oldest_kept):
            continue
        if not SNAPSHOT_NAME.match(folder.name):
            ctx.log.warning("not a snapshot folder, left alone: %s", folder)
            continue
        if ctx.options.dry_run:
            ctx.log.info("dry run: would remove snapshot folder %s", folder)
            continue
        with ctx.timed(f"remove snapshot {folder.name}"):
            shutil.rmtree(folder)
        removed.append(folder.name)
    remove_partial_files(ctx, [p for p in complete if p.name in keep])
    ctx.log.info("snapshots kept: %s; removed: %s", ", ".join(sorted(keep)) or "none", ", ".join(removed) or "none")
    return removed


def remove_partial_files(ctx: common.Context, folders: list[Path]) -> int:
    """Removes *.part* files (interrupted downloads) from complete snapshot folders."""
    n = 0
    for folder in folders:
        for part in folder.glob("*.part*"):
            if ctx.options.dry_run:
                ctx.log.info("dry run: would remove %s", part)
                continue
            part.unlink()
            n += 1
    if n:
        ctx.log.info("removed %d partial download file(s)", n)
    return n
