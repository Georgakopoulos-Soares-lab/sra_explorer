"""Step 1 of the weekly update: fetch this week's inputs.

1. The SRA metadata snapshot: ~30 parquet objects (13 GB) under
   s3://sra-pub-metadata-us-east-1/sra/metadata/, replaced every day. Every
   object name starts with the snapshot date, which names the local folder
   (common.SNAPSHOTS_DIR/<date>/<object>.parquet). Objects are downloaded
   concurrently, each to <name>.parquet.part and renamed when complete, so a
   rerun after a crash only fetches what is missing or has the wrong size.
   Once every file is present with the listed size, a COMPLETE marker (the
   object list, sizes and a timestamp as JSON) is written: that is what the
   later steps and Context.snapshot_dir() look for.
2. bioproject.xml (4 GB): Automations/ENA/get_ENA_xml.sh runs `wget -N`, so an
   unchanged file is not downloaded again. The file must then exist, be over
   1 GB and end with the closing root tag; a download failure is tolerated when
   a complete older copy is there (the projects step then works on last week's
   XML, which is logged as a warning).

--dry-run lists the bucket and says what would be downloaded, but downloads
nothing and does not run the XML script. --snapshot pins a local snapshot
folder: when the bucket already holds a newer day, it is left alone.
--files does not apply here: a snapshot is only marked complete when every
object is present.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import boto3
from boto3.s3.transfer import TransferConfig
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig

import common

RETRIES = 3                       # download attempts per object
RETRY_DELAY = 15                  # seconds between attempts (grows with the attempt)
PART_SUFFIX = ".part"             # <name>.parquet.part while a file is being written
MIN_XML_BYTES = 1 << 30           # bioproject.xml is ~4 GB; anything under 1 GB is a failed download
XML_ROOT = "PackageSet"           # bioproject.xml's root element; a complete file ends with </PackageSet>


# ---------------------------------------------------------------- S3 listing
def s3_client(concurrency: int):
    """An anonymous client (the bucket is public). The pool must hold the
    connections of every concurrent file transfer (4 parts each)."""
    config = BotoConfig(signature_version=UNSIGNED, max_pool_connections=max(10, concurrency * 4 + 2),
                        retries={"max_attempts": 5, "mode": "standard"})
    return boto3.client("s3", region_name=common.S3_REGION, config=config)


def list_objects(ctx: common.Context, s3) -> Optional[list[dict]]:
    """The bucket's objects as {"key", "name", "size"}; None when the listing fails."""
    try:
        objects = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=common.S3_BUCKET, Prefix=common.S3_PREFIX):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name:  # the prefix itself can be listed as an empty "folder" object
                    objects.append({"key": obj["Key"], "name": name, "size": int(obj["Size"])})
        return objects
    except Exception as exc:  # botocore raises many types (endpoint, timeout, client errors)
        ctx.log.warning("listing s3://%s/%s failed: %s", common.S3_BUCKET, common.S3_PREFIX, exc)
        return None


def pick_snapshot(ctx: common.Context, objects: list[dict]) -> tuple[str, list[dict]]:
    """The snapshot name (the leading 8 digits of the object names) and its objects.

    All objects of a day share it; if the bucket is caught between two days,
    the most common one wins and the rest are skipped."""
    counts = Counter(obj["name"][:8] for obj in objects)
    name = counts.most_common(1)[0][0]
    if len(counts) > 1:
        ctx.log.warning("objects from several snapshots in the bucket (%s); using %s", dict(counts), name)
    return name, [obj for obj in objects if obj["name"][:8] == name]


# ---------------------------------------------------------------- local files
def local_path(folder: Path, obj: dict) -> Path:
    return folder / f"{obj['name']}.parquet"


def file_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def is_present(folder: Path, obj: dict) -> bool:
    """A finished download: the final name with exactly the listed size.
    Anything else (missing, truncated, still a .part file) is downloaded."""
    return file_size(local_path(folder, obj)) == obj["size"]


def marker_path(folder: Path) -> Path:
    return folder / common.SNAPSHOT_COMPLETE_MARKER


def read_marker(folder: Path) -> Optional[dict]:
    try:
        return json.loads(marker_path(folder).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def marker_matches(folder: Path, objects: list[dict]) -> bool:
    """True when the marker lists exactly these objects and the files are still there."""
    marker = read_marker(folder)
    if not marker:
        return False
    listed = {(f["name"], f["size"]) for f in marker.get("files", [])}
    wanted = {(obj["name"], obj["size"]) for obj in objects}
    return listed == wanted and all(is_present(folder, obj) for obj in objects)


def write_marker(folder: Path, snapshot: str, objects: list[dict]) -> None:
    common.write_json(marker_path(folder), {
        "snapshot": snapshot,
        "completed": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "files": [{"name": obj["name"], "key": obj["key"], "size": obj["size"]} for obj in objects],
        "bytes": sum(obj["size"] for obj in objects),
    })


def stale_parts(folder: Path) -> list[Path]:
    """Leftovers of interrupted downloads (<name>.parquet.part, and the
    <name>.parquet.part.XXXX that boto3 writes before renaming)."""
    return sorted(p for p in folder.iterdir() if f".parquet{PART_SUFFIX}" in p.name)


# ---------------------------------------------------------------- downloading
def download_one(ctx: common.Context, s3, folder: Path, obj: dict) -> int:
    """Fetches one object to <name>.parquet.part, renames it, returns its size.

    Up to RETRIES attempts; the .part file is overwritten on each. Raises
    after the last failed attempt so the caller can report it (the other
    files keep downloading, and a rerun picks this one up again)."""
    path = local_path(folder, obj)
    part = path.with_name(path.name + PART_SUFFIX)
    transfer = TransferConfig(max_concurrency=4, multipart_chunksize=64 * 1024 * 1024)
    for attempt in range(1, RETRIES + 1):
        t0 = time.monotonic()
        try:
            s3.download_file(common.S3_BUCKET, obj["key"], str(part), Config=transfer)
            size = file_size(part)
            if size != obj["size"]:
                raise OSError(f"got {size} bytes, expected {obj['size']}")
            os.replace(part, path)
            secs = max(time.monotonic() - t0, 1e-3)
            ctx.log.info("downloaded %s (%.0f MB, %.1f MB/s)", path.name, size / 1e6, size / 1e6 / secs)
            return size
        except Exception as exc:  # network errors come in many botocore flavours
            ctx.log.warning("%s: attempt %d/%d failed: %s", path.name, attempt, RETRIES, exc)
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"{path.name}: giving up after {RETRIES} attempts")


def download_missing(ctx: common.Context, s3, folder: Path, todo: list[dict]) -> int:
    """Downloads the objects concurrently; raises if any of them failed."""
    failed = []
    with ThreadPoolExecutor(max_workers=ctx.config.download_concurrency) as pool:
        futures = {pool.submit(download_one, ctx, s3, folder, obj): obj for obj in todo}
        for future, obj in futures.items():
            try:
                future.result()
            except Exception as exc:
                failed.append(obj["name"])
                ctx.log.error("%s: %s", obj["name"], exc)
    if failed:
        raise RuntimeError(f"{len(failed)} of {len(todo)} parquet files failed to download: {failed[:5]}")
    return len(todo)


def keep_local_snapshot(ctx: common.Context, why: str) -> dict:
    """Falls back to the newest complete local snapshot (or --snapshot) when the
    bucket cannot be used. Raises when there is none: later steps need one."""
    folder = ctx.snapshot_dir()
    marker = read_marker(folder)
    if not marker:
        raise RuntimeError(f"{why}, and the local snapshot {folder} is not complete (no {common.SNAPSHOT_COMPLETE_MARKER} marker)")
    ctx.log.warning("%s; keeping the local snapshot %s (completed %s)", why, folder.name, marker.get("completed"))
    return {"snapshot": folder.name, "parquet_files": len(marker.get("files", [])), "downloaded": 0}


def download_snapshot(ctx: common.Context) -> dict:
    s3 = s3_client(ctx.config.download_concurrency)
    objects = list_objects(ctx, s3)
    if not objects:
        return keep_local_snapshot(ctx, "the S3 listing failed or is empty")
    snapshot, objects = pick_snapshot(ctx, objects)
    total_bytes = sum(obj["size"] for obj in objects)
    ctx.log.info("bucket snapshot %s: %d objects, %.1f GB", snapshot, len(objects), total_bytes / 1e9)

    if ctx.options.snapshot and ctx.options.snapshot != snapshot:
        return keep_local_snapshot(ctx, f"--snapshot {ctx.options.snapshot} is pinned but the bucket holds {snapshot}")

    folder = common.SNAPSHOTS_DIR / snapshot
    folder.mkdir(parents=True, exist_ok=True)
    result = {"snapshot": snapshot, "parquet_files": len(objects), "downloaded": 0}
    if marker_matches(folder, objects):
        ctx.log.info("snapshot %s already complete in %s", snapshot, folder)
        return result

    todo = [obj for obj in objects if not is_present(folder, obj)]
    parts = stale_parts(folder)
    ctx.log.info("%s: %d files present with the listed size, %d to download (%.1f GB), %d partial file(s) ignored",
                 folder, len(objects) - len(todo), len(todo), sum(o["size"] for o in todo) / 1e9, len(parts))
    if ctx.options.dry_run:
        for obj in todo:
            ctx.log.info("would download %s (%.0f MB)", obj["name"], obj["size"] / 1e6)
        ctx.log.info("dry run: not downloading, not writing the %s marker", common.SNAPSHOT_COMPLETE_MARKER)
        result["would_download"] = len(todo)
        return result

    if todo:
        result["downloaded"] = download_missing(ctx, s3, folder, todo)
    bad = [obj["name"] for obj in objects if not is_present(folder, obj)]
    if bad:  # a file changed under us (e.g. another downloader); the next run fixes it
        raise RuntimeError(f"{len(bad)} parquet files have the wrong size after downloading: {bad[:5]}")
    write_marker(folder, snapshot, objects)
    ctx.log.info("snapshot %s complete: %d files, %.1f GB", snapshot, len(objects), total_bytes / 1e9)
    return result


# ---------------------------------------------------------------- bioproject.xml
def xml_is_complete(path: Path) -> bool:
    """Over 1 GB and ending with the root's closing tag: a partial download
    (wget killed, disk full) has neither. The same check is in get_ENA_xml.sh."""
    size = file_size(path)
    if size is None or size < MIN_XML_BYTES:
        return False
    with open(path, "rb") as f:
        f.seek(size - 256)
        return f"</{XML_ROOT}>".encode() in f.read()


def xml_info(path: Path) -> dict:
    st = path.stat()
    return {"xml_bytes": st.st_size,
            "xml_mtime": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds")}


def fetch_xml(ctx: common.Context) -> dict:
    xml = common.ENA_XML
    had_complete = xml_is_complete(xml)
    if ctx.options.dry_run:
        ctx.log.info("dry run: would run %s (current file: %s)", common.GET_ENA_XML_SCRIPT,
                     xml_info(xml) if xml.exists() else "missing")
        return xml_info(xml) if xml.exists() else {"xml_bytes": 0, "xml_mtime": None}

    try:
        common.run_logged(ctx, ["bash", common.GET_ENA_XML_SCRIPT], cwd=common.GET_ENA_XML_SCRIPT.parent)
    except RuntimeError as exc:
        if not (had_complete and xml_is_complete(xml)):
            raise RuntimeError(f"bioproject.xml download failed ({exc}) and no complete copy exists at {xml}") from exc
        ctx.log.warning("bioproject.xml download failed (%s); continuing with the existing file from %s",
                        exc, xml_info(xml)["xml_mtime"])
    if not xml_is_complete(xml):
        raise RuntimeError(f"{xml} is missing, smaller than 1 GB or truncated (no </{XML_ROOT}> at the end)")
    info = xml_info(xml)
    ctx.log.info("bioproject.xml: %.2f GB, modified %s", info["xml_bytes"] / 1e9, info["xml_mtime"])
    return info


# ---------------------------------------------------------------- entry point
def run(ctx: common.Context) -> dict:
    common.ensure_dirs()
    result = download_snapshot(ctx)
    result.update(fetch_xml(ctx))
    return result
