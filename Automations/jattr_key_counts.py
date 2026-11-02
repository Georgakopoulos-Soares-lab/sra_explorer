"""
Count how many rows of sra_metadata_all.tsv contain each JSON key in the `jattr` column.

The file is ~100 GB, so it is split into byte ranges that are processed in parallel
(one process per CPU by default). Each worker splits lines on tabs, pulls the jattr
field by its header position, un-quotes it (TSV-style doubled quotes) and parses the JSON.

Outputs (in Automations/output/ by default):
  jattr_key_counts.tsv             one row per raw key:
                                     key, rows, pct, list_values, example
  jattr_key_counts_normalized.tsv  same, but with SRA suffixes stripped
                                     (_sam, _exp, _run, _calc, _ss_dplNN, ...) so that
                                     e.g. cell_type_sam_ss_dpl37 and cell_type_sam count
                                     together as `cell_type`. `raw_keys` lists the merged keys.

Usage:
  python jattr_key_counts.py [--input FILE] [--workers N] [--chunk-mb MB] [--out-dir DIR]
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_TSV = BASE_DIR / "output" / "sra_metadata_all.tsv"
OUT_DIR = BASE_DIR / "output"
COLUMN = "jattr"

# Strip SRA's per-source suffixes:  foo_sam, foo_exp, foo_run, foo_calc, foo_sam_ss_dpl37, foo_sam_s
SUFFIX_RE = re.compile(r"(_(sam|exp|run|calc|study))?(_ss?_dpl\d+|_s)?$")


def normalize_key(key: str) -> str:
    base = SUFFIX_RE.sub("", key).rstrip("_")
    return base or key


def _unquote(field: bytes) -> bytes:
    if len(field) >= 2 and field[:1] == b'"' and field[-1:] == b'"':
        return field[1:-1].replace(b'""', b'"')
    return field


def process_chunk(args):
    """Process lines whose start offset lies in [start, end)."""
    path, start, end, from_end = args
    key_rows = Counter()       # key -> number of rows containing it
    key_lists = Counter()      # key -> number of rows where the value is a list
    examples = {}              # key -> first value seen (truncated)
    rows = empty = errors = 0

    with open(path, "rb") as f:
        if start == 0:
            f.readline()  # skip header
        else:
            f.seek(start - 1)
            f.readline()  # discard partial line (the previous chunk owns it)
        while True:
            pos = f.tell()
            if pos >= end:
                break
            line = f.readline()
            if not line:
                break
            rows += 1
            parts = line.rstrip(b"\r\n").rsplit(b"\t", from_end)
            if len(parts) <= from_end:
                errors += 1
                continue
            field = _unquote(parts[-from_end])
            if not field:
                empty += 1
                continue
            try:
                obj = json.loads(field)
            except ValueError:
                errors += 1
                continue
            if not isinstance(obj, dict):
                errors += 1
                continue
            for k, v in obj.items():
                key_rows[k] += 1
                if isinstance(v, list):
                    key_lists[k] += 1
                if k not in examples:
                    examples[k] = repr(v)[:120]

    return rows, empty, errors, key_rows, key_lists, examples


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=INPUT_TSV)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--chunk-mb", type=int, default=256)
    a = ap.parse_args()

    with open(a.input, "rb") as f:
        header = f.readline().rstrip(b"\r\n").split(b"\t")
    names = [h.decode() for h in header]
    if COLUMN not in names:
        sys.exit(f"column {COLUMN!r} not in header: {names}")
    from_end = len(names) - names.index(COLUMN)  # 1 = last column, 2 = second to last, ...

    size = a.input.stat().st_size
    chunk = a.chunk_mb * 1024 * 1024
    tasks = [(str(a.input), s, min(s + chunk, size), from_end) for s in range(0, size, chunk)]
    print(f"{a.input} : {size/1e9:.1f} GB, {len(tasks)} chunks, {a.workers} workers", flush=True)

    t0 = time.time()
    tot_rows = tot_empty = tot_err = 0
    key_rows, key_lists, examples = Counter(), Counter(), {}
    with Pool(a.workers) as pool:
        for i, (rows, empty, errors, kr, kl, ex) in enumerate(pool.imap_unordered(process_chunk, tasks), 1):
            tot_rows += rows; tot_empty += empty; tot_err += errors
            key_rows.update(kr); key_lists.update(kl)
            for k, v in ex.items():
                examples.setdefault(k, v)
            if i % 20 == 0 or i == len(tasks):
                el = time.time() - t0
                print(f"  {i}/{len(tasks)} chunks, {tot_rows:,} rows, {len(key_rows):,} keys, "
                      f"{el:.0f}s (eta {el/i*(len(tasks)-i):.0f}s)", flush=True)

    parsed = tot_rows - tot_empty - tot_err
    a.out_dir.mkdir(parents=True, exist_ok=True)

    out_raw = a.out_dir / "jattr_key_counts.tsv"
    with open(out_raw, "w") as f:
        f.write("key\trows\tpct\tlist_values\texample\n")
        for k, n in key_rows.most_common():
            f.write(f"{k}\t{n}\t{100*n/max(parsed,1):.3f}\t{key_lists[k]}\t{examples[k]}\n")

    # Normalised view: merge suffix variants of the same attribute name.
    norm_rows, norm_lists, norm_members = Counter(), Counter(), {}
    for k, n in key_rows.items():
        b = normalize_key(k)
        norm_rows[b] += n
        norm_lists[b] += key_lists[k]
        norm_members.setdefault(b, []).append((n, k))
    out_norm = a.out_dir / "jattr_key_counts_normalized.tsv"
    with open(out_norm, "w") as f:
        f.write("key\trows\tpct\tlist_values\tn_raw_keys\traw_keys\texample\n")
        for b, n in norm_rows.most_common():
            members = sorted(norm_members[b], reverse=True)
            raw = ";".join(f"{k}({c})" for c, k in members[:10]) + (";..." if len(members) > 10 else "")
            f.write(f"{b}\t{n}\t{100*n/max(parsed,1):.3f}\t{norm_lists[b]}\t{len(members)}\t{raw}\t{examples[members[0][1]]}\n")

    print(f"\nrows: {tot_rows:,}   parsed: {parsed:,}   empty jattr: {tot_empty:,}   parse errors: {tot_err:,}")
    print(f"distinct raw keys: {len(key_rows):,}   normalized keys: {len(norm_rows):,}")
    print(f"wrote {out_raw}\nwrote {out_norm}\n({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
