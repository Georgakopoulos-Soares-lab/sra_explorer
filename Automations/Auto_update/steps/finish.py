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
  3. The downloads are removed: every snapshot folder under data/sra_metadata/
     (13-15 GB each) and Automations/ENA/bioproject.xml (4 GB). Both are
     rewritten by NCBI every day, so nothing on disk is worth keeping once
     its rows are in the database, and the host's disk is the constraint.
     Only a run that actually loaded them deletes them: the snapshot goes
     when the runs and attributes steps ran in this invocation, the XML when
     the projects step did, so `--only finish` or `--from refresh` after a
     failure leaves the files for the rerun. AUTO_UPDATE_KEEP_DOWNLOADS=true
     keeps them instead (then the AUTO_UPDATE_KEEP_SNAPSHOTS newest complete
     snapshots and the current one stay, as before).

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
    removed = remove_downloads(ctx)
    return {"views_refreshed": refreshed, "api_restarted": restarted,
            "snapshots_removed": removed["snapshots"], "xml_removed": removed["xml"]}


def remove_downloads(ctx: common.Context) -> dict:
    """Frees the disk once this run's data is in the database.

    Returns {"snapshots": [folder names removed], "xml": whether bioproject.xml
    was removed}. With AUTO_UPDATE_KEEP_DOWNLOADS the old policy applies
    (remove_old_snapshots; the XML stays). Otherwise everything downloaded is
    deleted, but only by a run that consumed it: ctx.results lists the steps
    that finished in this invocation, so a partial rerun (--only finish,
    --from refresh) keeps the files the next --from run still needs.
    """
    if ctx.config.keep_downloads:
        ctx.log.info("AUTO_UPDATE_KEEP_DOWNLOADS is on: keeping bioproject.xml and the newest snapshot(s)")
        return {"snapshots": remove_old_snapshots(ctx), "xml": False}
    done = set(ctx.results)
    snapshots: list[str] = []
    if {"runs", "attributes"} <= done:
        snapshots = remove_all_snapshots(ctx)
    else:
        ctx.log.info("snapshot folders kept: the runs and attributes steps did not run in this invocation")
    xml = False
    if "projects" in done:
        xml = remove_xml(ctx)
    else:
        ctx.log.info("bioproject.xml kept: the projects step did not run in this invocation")
    return {"snapshots": snapshots, "xml": xml}


def remove_all_snapshots(ctx: common.Context) -> list[str]:
    """Deletes every snapshot folder (complete or not); returns their names.
    The lock guarantees no download is in progress, and the next run lists the
    bucket again anyway, since the objects are replaced daily."""
    removed = []
    for folder in sorted(p for p in common.SNAPSHOTS_DIR.glob("*") if p.is_dir()):
        if not SNAPSHOT_NAME.match(folder.name):
            ctx.log.warning("not a snapshot folder, left alone: %s", folder)
            continue
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        if ctx.options.dry_run:
            ctx.log.info("dry run: would remove snapshot folder %s (%.1f GB)", folder, size / 1e9)
            continue
        with ctx.timed(f"remove snapshot {folder.name} ({size / 1e9:.1f} GB)"):
            shutil.rmtree(folder)
        removed.append(folder.name)
    ctx.log.info("snapshots removed: %s", ", ".join(removed) or "none")
    return removed


def remove_xml(ctx: common.Context) -> bool:
    """Deletes Automations/ENA/bioproject.xml and any leftover partial file
    next to it (bioproject.xml.new, .part); returns whether the XML was removed."""
    xml = common.ENA_XML
    candidates = [xml] + sorted(p for p in xml.parent.glob(xml.name + ".*") if p.is_file())
    removed = False
    for path in candidates:
        if not path.exists():
            continue
        size = path.stat().st_size
        if ctx.options.dry_run:
            ctx.log.info("dry run: would remove %s (%.2f GB)", path, size / 1e9)
            continue
        path.unlink()
        ctx.log.info("removed %s (%.2f GB)", path, size / 1e9)
        removed = removed or path == xml
    return removed


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
    if not complete or oldest_kept is None:
        # Nothing complete to keep means the only folders are downloads in
        # progress (e.g. before the first run finished): leave them alone.
        ctx.log.info("no complete snapshot on disk; removing nothing")
        return removed
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
