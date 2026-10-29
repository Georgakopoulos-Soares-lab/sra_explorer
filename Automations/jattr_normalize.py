"""
Extract a small, normalized JSON of sample attributes from the `jattr` column of
sra_metadata_all.tsv and aggregate it per BioProject.

Only attributes present in a meaningful share of runs are kept (see FIELDS below).
Keys that mean the same thing but were submitted under different names
(sex_calc, host_sex_sam, gender_sam, ...) are merged into one field. SRA's source
suffixes (_sam, _exp, _run, _calc, _ss_dplNN) are stripped before matching, using
normalize_key() from jattr_key_counts.py. See docs/jattr-normalization.md.

Output (Automations/output/ by default):
  bioproject_attributes.tsv          bioproject <TAB> JSON  (one row per BioProject)
  bioproject_attributes_coverage.tsv per-field coverage: runs and BioProjects with a value

Per-BioProject JSON: every field maps to a list of distinct values, most frequent first,
at most MAX_VALUES_OUT values. `n_runs` is the number of runs in the project.

  {"n_runs": 24, "organism": ["Bos taurus"], "tissue": ["Lactating mammary"],
   "sex": ["female"], "age": ["78"], "assay_type": ["ChIP-Seq"], "molecular_target": ["H3K4me1"]}

Usage:
  python jattr_normalize.py [--input FILE] [--out-dir DIR] [--workers N] [--chunk-mb MB]
                            [--per-run FILE]   # also write one row per run: acc, bioproject, JSON
"""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jattr_key_counts import normalize_key  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
INPUT_TSV = BASE_DIR / "output" / "sra_metadata_all.tsv"
OUT_DIR = BASE_DIR / "output"

MAX_VALUES_OUT = 10       # values listed per field in the per-BioProject JSON
MAX_VALUES_TRACK = 200    # distinct values tracked per (project, field) while counting

# Target field -> source keys (after normalize_key), in priority order. When a run has
# several of these, the first non-null one in this list wins.
# Fields marked column=True are read from a top-level TSV column, not from jattr.
FIELDS = {
    "organism":                      {"column": "organism"},
    "host":                          {"keys": ["host", "host_scientific_name", "host_common_name"]},
    "cell_line":                     {"keys": ["cell_line"]},
    "cell_type":                     {"keys": ["cell_type"]},
    "tissue":                        {"keys": ["tissue", "organism_part", "tissue_type", "body_site",
                                               "host_tissue_sampled", "host_body_site"]},
    "source_name":                   {"keys": ["source_name"]},
    "genotype_or_strain":            {"keys": ["genotype", "strain", "cultivar", "breed", "ecotype",
                                               "genetic_background", "variety", "host_genotype"]},
    "treatment_or_growth_condition": {"keys": ["treatment", "growth_condition", "growth_protocol",
                                               "condition", "stimulus", "compound", "agent",
                                               "treatment_protocol"]},
    "disease_state":                 {"keys": ["disease", "disease_state", "disease_status", "diagnosis",
                                               "host_disease", "host_health_state", "health_state",
                                               "host_disease_stat", "health_status", "clinical_status"]},
    "assay_type":                    {"column": "assay_type"},
    "molecular_target":              {"keys": ["chip_antibody", "antibody", "chip_target", "antibody_target",
                                               "histone_mark", "target", "ip_antibody", "chip_antibody_target"]},
    "sex":                           {"keys": ["sex", "host_sex", "gender", "host_gender"]},
    "developmental_stage":           {"keys": ["dev_stage", "developmental_stage", "development_stage",
                                               "host_life_stage", "life_stage", "host_dev_stage",
                                               "age_group", "host_age_group"]},
    "age":                           {"keys": ["age", "host_age"]},
}

# Values that mean "no information" (compared lower-cased, after trimming).
NULL_VALUES = {
    "", "na", "n/a", "n.a.", "nan", "null", "none", "no", "nd", "n.d.", "-", "--", ".", "?", "unknown",
    "unspecified", "not specified", "not provided", "not collected", "not applicable", "not available",
    "not determined", "not recorded", "not reported", "not known", "missing", "restricted access",
    "no data", "not given", "undetermined", "unidentified", "other", "others", "n/a (not applicable)",
    "not applicable (n/a)", "missing: not provided", "missing: not collected", "missing: restricted access",
    "missing: control sample", "missing: sample group", "missing: synthetic construct",
    "missing: lab stock", "missing: third party data", "missing: data agreement established pre-2023",
    "missing: endangered species", "missing: human-identifiable",
}

SEX_MAP = {
    "male": "male", "m": "male", "males": "male", "man": "male", "boy": "male", "xy": "male",
    "female": "female", "f": "female", "females": "female", "woman": "female", "girl": "female", "xx": "female",
    "pooled male and female": "mixed", "male and female": "mixed", "mixed": "mixed", "mixed sex": "mixed",
    "pooled": "mixed", "both": "mixed", "pool": "mixed", "male/female": "mixed", "female/male": "mixed",
    "mixture": "mixed", "pooled male and female": "mixed", "pooled male and female samples": "mixed",
    "hermaphrodite": "hermaphrodite", "intersex": "intersex", "asexual": "asexual",
    "neuter": "neuter", "not applicable": None, "n/a": None, "unknown": None, "not determined": None,
}

_WS = re.compile(r"\s+")


def clean_value(v):
    """Scalar or list -> trimmed string, or None if it means 'no information'."""
    if isinstance(v, list):
        for item in v:
            s = clean_value(item)
            if s is not None:
                return s
        return None
    if v is None or isinstance(v, bool):
        return None
    s = _WS.sub(" ", str(v)).strip()
    if s.lower() in NULL_VALUES or s.lower().startswith("missing:"):
        return None
    return s


def normalize_sex(s):
    low = s.lower().strip()
    if low in SEX_MAP:
        return SEX_MAP[low]
    has_m = re.search(r"\bmales?\b|\bm\b", low) is not None
    has_f = re.search(r"\bfemales?\b|\bf\b", low) is not None
    if has_m and has_f:
        return "mixed"
    if has_f:
        return "female"
    if has_m:
        return "male"
    if re.fullmatch(r"[\d.\s]+", low):   # a number is not a sex
        return None
    return low


def normalize_age(s):
    """'78', '78.0', '78 years' -> '78'; '10M', 'P7', 'E14.5' are kept as submitted."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|y|yo|year old|years old)?", s, re.I)
    if m:
        n = m.group(1)
        return n[:-2] if n.endswith(".0") else n
    return s


_HISTONE = re.compile(r"^(h[1-4][a-z]?)k(\d+)(me[1-3]|ac|ub|bio|cr|su)$", re.I)


def normalize_target(s):
    """'H3K27ac, Abcam, ab4729, Lot: ...' -> 'H3K27ac'; 'H3K27Ac(CST, #8173S)' -> 'H3K27ac'."""
    s = re.split(r"[,;(\[]|\s+-\s+|\s+\(", s, 1)[0].strip()
    s = re.sub(r"^(anti[- ]?)", "", s, flags=re.I).strip()
    m = _HISTONE.match(s)
    if m:
        s = f"{m.group(1).upper()}K{m.group(2)}{m.group(3).lower()}"
    return clean_value(s)


POST = {"sex": normalize_sex, "age": normalize_age, "molecular_target": normalize_target}


def _unquote(field: bytes) -> bytes:
    if len(field) >= 2 and field[:1] == b'"' and field[-1:] == b'"':
        return field[1:-1].replace(b'""', b'"')
    return field


def build_lookup():
    """Normalized key -> (field, priority)."""
    lookup = {}
    for field, spec in FIELDS.items():
        for prio, k in enumerate(spec.get("keys", [])):
            lookup.setdefault(k, (field, prio))
    return lookup


def extract(obj, columns, lookup, key_cache):
    """One run's jattr dict + top-level columns -> {field: value} (nulls omitted)."""
    best = {}  # field -> (prio, value)
    for raw_key, raw_val in obj.items():
        hit = key_cache.get(raw_key)
        if hit is None:
            hit = lookup.get(normalize_key(raw_key), False)
            key_cache[raw_key] = hit
        if not hit:
            continue
        field, prio = hit
        cur = best.get(field)
        if cur is not None and cur[0] <= prio:
            continue
        val = clean_value(raw_val)
        if val is None:
            continue
        post = POST.get(field)
        if post:
            val = post(val)
            if val is None:
                continue
        best[field] = (prio, val)
    out = {f: v for f, (_, v) in best.items()}
    for field, spec in FIELDS.items():
        col = spec.get("column")
        if col:
            val = clean_value(columns.get(col))
            if val is not None:
                out[field] = val
    return out


def process_chunk(args):
    path, start, end, idx, per_run_path = args
    lookup = build_lookup()
    key_cache = {}
    # project -> field -> Counter(value -> runs); plus "__overflow__" count when capped
    agg = defaultdict(lambda: defaultdict(Counter))
    n_runs = Counter()
    field_runs = Counter()
    rows = errors = no_project = 0
    per_run = open(f"{per_run_path}.part{start}", "w", encoding="utf-8") if per_run_path else None

    with open(path, "rb") as f:
        if start == 0:
            f.readline()
        else:
            f.seek(start - 1)
            f.readline()
        while f.tell() < end:
            line = f.readline()
            if not line:
                break
            rows += 1
            parts = line.rstrip(b"\r\n").split(b"\t")
            if len(parts) <= idx["jattr"]:
                errors += 1
                continue
            field = _unquote(parts[idx["jattr"]])
            try:
                obj = json.loads(field) if field else {}
            except ValueError:
                errors += 1
                continue
            if not isinstance(obj, dict):
                obj = {}
            columns = {c: parts[i].decode("utf-8", "replace") for c, i in idx.items() if c != "jattr"}
            rec = extract(obj, columns, lookup, key_cache)
            project = columns["bioproject"].strip()

            if per_run:
                per_run.write(f"{columns['acc']}\t{project}\t{json.dumps(rec, ensure_ascii=False)}\n")
            if not project:
                no_project += 1
                continue
            n_runs[project] += 1
            proj = agg[project]
            for fld, val in rec.items():
                field_runs[fld] += 1
                c = proj[fld]
                if val in c or len(c) < MAX_VALUES_TRACK:
                    c[val] += 1
                else:
                    c["__overflow__"] += 1
    if per_run:
        per_run.close()
    # Convert to plain dicts for pickling.
    agg = {p: {f: dict(c) for f, c in fs.items()} for p, fs in agg.items()}
    return rows, errors, no_project, dict(n_runs), dict(field_runs), agg


def top_values(c: Counter):
    """Most frequent values, merging spellings that differ only by case (keeps the common spelling)."""
    by_lower = {}
    for v, n in c.most_common():
        if v == "__overflow__":
            continue
        key = v.lower()
        if key in by_lower:
            by_lower[key][1] += n
        else:
            by_lower[key] = [v, n]
    ranked = sorted(by_lower.values(), key=lambda x: -x[1])
    return [v for v, _ in ranked[:MAX_VALUES_OUT]]


def merge_counter(dst: Counter, src: dict):
    for v, n in src.items():
        if v in dst or len(dst) < MAX_VALUES_TRACK or v == "__overflow__":
            dst[v] += n
        else:
            dst["__overflow__"] += n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=INPUT_TSV)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--chunk-mb", type=int, default=256)
    ap.add_argument("--per-run", type=Path, default=None,
                    help="also write one row per run (acc, bioproject, JSON) to this file")
    a = ap.parse_args()

    with open(a.input, "rb") as f:
        names = f.readline().rstrip(b"\r\n").decode().split("\t")
    needed = ["acc", "bioproject", "jattr"] + [s["column"] for s in FIELDS.values() if "column" in s]
    missing = [c for c in needed if c not in names]
    if missing:
        sys.exit(f"columns missing from {a.input}: {missing}")
    idx = {c: names.index(c) for c in needed}

    size = a.input.stat().st_size
    chunk = a.chunk_mb * 1024 * 1024
    per_run_path = str(a.per_run) if a.per_run else None
    tasks = [(str(a.input), s, min(s + chunk, size), idx, per_run_path) for s in range(0, size, chunk)]
    print(f"{a.input} : {size/1e9:.1f} GB, {len(tasks)} chunks, {a.workers} workers", flush=True)

    t0 = time.time()
    tot_rows = tot_err = tot_noproj = 0
    n_runs, field_runs = Counter(), Counter()
    agg = defaultdict(lambda: defaultdict(Counter))
    with Pool(a.workers) as pool:
        for i, (rows, errors, noproj, nr, fr, part) in enumerate(pool.imap_unordered(process_chunk, tasks), 1):
            tot_rows += rows; tot_err += errors; tot_noproj += noproj
            n_runs.update(nr); field_runs.update(fr)
            for p, fields in part.items():
                proj = agg[p]
                for fld, c in fields.items():
                    merge_counter(proj[fld], c)
            if i % 20 == 0 or i == len(tasks):
                el = time.time() - t0
                print(f"  {i}/{len(tasks)} chunks, {tot_rows:,} rows, {len(agg):,} projects, "
                      f"{el:.0f}s (eta {el/i*(len(tasks)-i):.0f}s)", flush=True)

    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / "bioproject_attributes.tsv"
    field_projects = Counter()
    with open(out, "w", encoding="utf-8") as f:
        f.write("bioproject\tattributes\n")
        for project in sorted(agg):
            rec = {"n_runs": n_runs[project]}
            for fld in FIELDS:
                c = agg[project].get(fld)
                if not c:
                    continue
                vals = top_values(c)
                if vals:
                    rec[fld] = vals
                    field_projects[fld] += 1
            f.write(f"{project}\t{json.dumps(rec, ensure_ascii=False)}\n")

    parsed = tot_rows - tot_err
    cov = a.out_dir / "bioproject_attributes_coverage.tsv"
    with open(cov, "w") as f:
        f.write("field\truns\truns_pct\tbioprojects\tbioprojects_pct\n")
        for fld in FIELDS:
            f.write(f"{fld}\t{field_runs[fld]}\t{100*field_runs[fld]/max(parsed,1):.2f}\t"
                    f"{field_projects[fld]}\t{100*field_projects[fld]/max(len(agg),1):.2f}\n")

    if per_run_path:
        parts = sorted((Path(per_run_path).parent).glob(Path(per_run_path).name + ".part*"),
                       key=lambda p: int(p.name.rsplit("part", 1)[1]))
        with open(per_run_path, "w", encoding="utf-8") as fout:
            fout.write("acc\tbioproject\tattributes\n")
            for p in parts:
                with open(p, encoding="utf-8") as fin:
                    for line in fin:
                        fout.write(line)
                p.unlink()
        print(f"wrote {per_run_path}")

    print(f"\nrows: {tot_rows:,}   parse errors: {tot_err:,}   rows without bioproject: {tot_noproj:,}")
    print(f"bioprojects: {len(agg):,}")
    print("field coverage (runs % / bioprojects %):")
    for fld in FIELDS:
        print(f"  {fld:30s} {100*field_runs[fld]/max(parsed,1):6.2f}  {100*field_projects[fld]/max(len(agg),1):6.2f}")
    print(f"wrote {out}\nwrote {cov}\n({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
