"""SRAscout retrieval benchmark: fills the supplementary workbook with real results.

    backend/.venv/bin/python benchmark/benchmark.py run      # search, pool, write the workbook
    backend/.venv/bin/python benchmark/benchmark.py report   # after judging: print the numbers

"run" gets the top 20 BioProjects of every query in Table S1 from four methods,
writes them to Table S3, pools them into Table S2 for relevance judging, and
builds Table S7 (a sample of harmonized attributes with their raw jattr values)
for the attribute accuracy check. Results are cached per query in
benchmark/cache.json, so a rerun only does what is missing.

The SRAscout methods use the backend's own code (backend/app/search.py and
embeddings.py), database settings (backend/.env, as the API service loads it)
and model, so they return what the site returns. Nothing in the app changes.

The raw jattr values are not in the database; they are read from the newest
complete parquet snapshot of the auto-update pipeline
(Automations/Auto_update/data/sra_metadata/<date>/). pyarrow is installed only
in the auto-update venv, so that part runs as a child process under that venv
(the hidden "_jattr" subcommand below).
"""

import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
AUTOMATIONS = ROOT / "Automations"
SNAPSHOTS = AUTOMATIONS / "Auto_update" / "data" / "sra_metadata"
AUTO_UPDATE_PYTHON = AUTOMATIONS / "Auto_update" / ".venv" / "bin" / "python"

WORKBOOK = HERE / "SRAscout_benchmark_supplementary.xlsx"
CACHE = HERE / "cache.json"

TOP_N = 20
METHODS = ["Hybrid", "Semantic only", "Full-text only", "NCBI BioProject search"]
SEED = 42                # random seed of the Table S7 sample
S7_PER_FIELD = 10        # projects sampled per harmonized field
S7_RAW_CHARS = 500       # "Original key-value pairs" are cut to this length
FIRST_ROW = 4            # data start at row 4 in every table (header in row 3)
S2_LAST, S3_LAST = 20003, 9603   # last rows the template's formulas cover

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
SRA_FILTER = ' AND "bioproject sra"[filter]'

# Set to False only to smoke-test without an email address.
REQUIRE_EMAIL = True


# ---------------------------------------------------------------- setup
def load_backend():
    """Imports the backend the way the API service runs it: backend/.env in the
    environment (systemd EnvironmentFile), backend/ on the path."""
    env_file = BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    os.environ.setdefault("HF_HOME", "/root/.cache/huggingface")  # as in srascout-api.service
    sys.path.insert(0, str(BACKEND))
    from app import database, embeddings, search  # noqa: E402
    return database, embeddings, search


def load_cache(path):
    if path.exists():
        return json.loads(path.read_text())
    return {"meta": {}, "queries": {}}


def save_cache(cache, path):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    tmp.replace(path)  # atomic: a crash never leaves half a cache


def read_queries(wb):
    ws = wb["Table S1"]
    rows = []
    for r in range(FIRST_ROW, ws.max_row + 1):
        qid, text = ws.cell(r, 1).value, ws.cell(r, 2).value
        if qid and text:
            rows.append({"id": str(qid).strip(), "query": str(text).strip(),
                         "type": ws.cell(r, 3).value, "domain": ws.cell(r, 4).value})
    return rows


def stop(message):
    print(f"\nSTOPPED: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- SRAscout methods
def has_hnsw_index(db):
    from sqlalchemy import text
    return bool(db.scalar(text(
        "SELECT count(*) FROM pg_indexes WHERE tablename = 'bioproject_embeddings' "
        "AND indexdef ILIKE '%USING hnsw%'")))


def hybrid_top(db, S, q):
    """The app's fused list (search.fused_matches, unchanged), best first, limited
    to projects in bioprojects as hybrid_search's join does. Ties are broken by
    accession, as hybrid_search orders them."""
    from sqlalchemy import exists, select
    _, fused = S.fused_matches(db, q)
    stmt = (select(fused.c.bioproject, fused.c.score)
            .where(exists().where(S.B.bioproject == fused.c.bioproject))
            .order_by(fused.c.score.desc(), fused.c.bioproject)
            .limit(TOP_N))
    return [(bp, round(float(score), 6)) for bp, score in db.execute(stmt)]


def semantic_top(db, S, q, vec):
    """The semantic branch of fused_matches alone: the SEMANTIC_CANDIDATES nearest
    projects, similarity >= SEMANTIC_MIN_SIMILARITY, most similar first."""
    from sqlalchemy import exists, select, text
    db.execute(text(f"SET LOCAL hnsw.ef_search = {S.SEMANTIC_CANDIDATES}"))
    distance = S.E.embedding.cosine_distance(vec)
    nearest = (select(S.E.bioproject, distance.label("distance"))
               .order_by(distance).limit(S.SEMANTIC_CANDIDATES).subquery())
    stmt = (select(nearest.c.bioproject, nearest.c.distance)
            .where(nearest.c.distance <= 1 - S.SEMANTIC_MIN_SIMILARITY,
                   exists().where(S.B.bioproject == nearest.c.bioproject))
            .order_by(nearest.c.distance, nearest.c.bioproject)
            .limit(TOP_N))
    return [(bp, round(1 - float(d), 4)) for bp, d in db.execute(stmt)]


def semantic_ties(db, S, vec):
    """Projects in the app's semantic list that share their exact distance with another one."""
    from sqlalchemy import select, text
    db.execute(text(f"SET LOCAL hnsw.ef_search = {S.SEMANTIC_CANDIDATES}"))
    distance = S.E.embedding.cosine_distance(vec)
    nearest = (select(S.E.bioproject, distance.label("distance"))
               .order_by(distance).limit(S.SEMANTIC_CANDIDATES).subquery())
    rows = db.execute(select(nearest.c.bioproject, nearest.c.distance)
                      .where(nearest.c.distance <= 1 - S.SEMANTIC_MIN_SIMILARITY)).all()
    counts = Counter(d for _, d in rows)
    return {bp for bp, d in rows if counts[d] > 1}


def fulltext_top(db, S, q, vec):
    """The full-text branch of fused_matches alone: every word must match,
    ts_rank_cd(..., 1), best TEXT_CANDIDATES, then similarity >= TEXT_MIN_SIMILARITY."""
    from sqlalchemy import exists, func, literal_column, select
    tsquery = func.websearch_to_tsquery(literal_column("'english'::regconfig"), q)
    score = func.ts_rank_cd(S.T.c.document, tsquery, 1)
    best = (select(S.T.c.bioproject, score.label("score"))
            .where(S.T.c.document.op("@@")(tsquery))
            .order_by(score.desc(), S.T.c.bioproject)
            .limit(S.TEXT_CANDIDATES).subquery())
    distance = S.E.embedding.cosine_distance(vec)
    stmt = (select(best.c.bioproject, best.c.score)
            .join(S.E, S.E.bioproject == best.c.bioproject)
            .where(distance <= 1 - S.TEXT_MIN_SIMILARITY,
                   exists().where(S.B.bioproject == best.c.bioproject))
            .order_by(best.c.score.desc(), best.c.bioproject)
            .limit(TOP_N))
    return [(bp, round(float(s), 6)) for bp, s in db.execute(stmt)]


def run_sra_methods(q, entry, database, embeddings, S, index_present):
    """Fills entry with the three SRAscout methods and the hybrid timings."""
    from sqlalchemy import and_, true

    qtext = S.query_text(q)  # q itself unless it is a DOI or PubMed ID

    # Timed: the search exactly as the API runs it (embedding, then
    # hybrid_search's count and first page), with the embedding cache cleared.
    embeddings.embed.cache_clear()
    t0 = time.perf_counter()
    vec = embeddings.embed(qtext)
    t1 = time.perf_counter()
    with database.SessionLocal() as db:
        filters = S.SiteSearchFilters(q=q)
        where = and_(true(), *S.build_conditions(filters))
        page = S.hybrid_search(db, q, where, filters)
        db.rollback()
    t2 = time.perf_counter()
    entry["embedding_seconds"] = round(t1 - t0, 4)
    entry["hybrid_seconds"] = round(t2 - t0, 4)
    entry["hnsw_index"] = index_present

    # Each list in its own read-only transaction (SET LOCAL needs one).
    lists = {}
    for method, fn in (("Hybrid", lambda db: hybrid_top(db, S, q)),
                       ("Semantic only", lambda db: semantic_top(db, S, qtext, vec)),
                       ("Full-text only", lambda db: fulltext_top(db, S, qtext, vec))):
        with database.SessionLocal() as db:
            lists[method] = fn(db)
            db.rollback()

    # Check: the app's own first page, one row per project and SRA study, must
    # list the same projects in the same order as our hybrid top 20.
    page_projects = list(dict.fromkeys(item["bioproject"] for item in page["items"]))
    ours = [bp for bp, _ in lists["Hybrid"]]
    n = min(len(page_projects), len(ours))
    if page_projects[:n] != ours[:n]:
        # The app ranks projects with exactly the same semantic distance in no
        # fixed order (search.py's row_number has no tie-breaker), so their RRF
        # scores, and the projects around them, can move between two calls.
        # Accepted only when that explains the whole difference: with the tied
        # projects removed, one list must be a prefix of the other (others can
        # only drop off or come in at the end of the top 20).
        with database.SessionLocal() as db:
            tied = semantic_ties(db, S, vec)
            db.rollback()
        rest_app = [bp for bp in page_projects[:n] if bp not in tied]
        rest_ours = [bp for bp in ours[:n] if bp not in tied]
        k = min(len(rest_app), len(rest_ours))
        if not tied or rest_app[:k] != rest_ours[:k]:
            stop(f"hybrid top 20 differs from the app's hybrid_search for {q!r}, beyond tied projects:\n"
                 f"  app:  {page_projects[:n]}\n  ours: {ours[:n]}\n  tied: {sorted(tied)}")
        first = next(i for i, (a, b) in enumerate(zip(page_projects, ours), 1) if a != b)
        entry["tie_note"] = {"first_differing_rank": first, "tied_projects": sorted(tied),
                             "app_order": page_projects[:n]}
        print(f"      note: order differs from rank {first} because of {len(tied)} projects with tied "
              "semantic distance (the app's own, non-reproducible order); recorded in cache.json")

    for method, results in lists.items():
        entry[method] = [{"rank": i, "bioproject": bp, "score": s} for i, (bp, s) in enumerate(results, 1)]


# ---------------------------------------------------------------- NCBI
def ncbi_get(endpoint, params):
    """One E-utilities request (JSON), with the email/API key and the pause NCBI asks for."""
    params = {**params, "retmode": "json", "tool": "srascout_benchmark"}
    if os.getenv("NCBI_EMAIL"):
        params["email"] = os.environ["NCBI_EMAIL"]
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    url = EUTILS + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = json.load(resp)
            time.sleep(0.15 if os.getenv("NCBI_API_KEY") else 0.4)
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == 3:
                raise RuntimeError(f"NCBI {endpoint} failed 4 times: {e}") from e
            time.sleep(2 ** (attempt + 1))  # 2, 4, 8 s, then give up


def ncbi_search(term):
    """esearch (top 20, NCBI's order) then esummary -> list of (Project_Acc, summary)."""
    found = ncbi_get("esearch.fcgi", {"db": "bioproject", "term": term, "retmax": TOP_N})["esearchresult"]
    if found.get("ERROR") or found.get("errorlist", {}).get("phrasesnotfound") == [term]:
        raise RuntimeError(f"NCBI esearch error for {term!r}: {found}")
    ids = found.get("idlist", [])
    if not ids:
        return int(found.get("count", 0)), []
    summary = ncbi_get("esummary.fcgi", {"db": "bioproject", "id": ",".join(ids)})["result"]
    out = []
    for uid in ids:  # esearch order
        doc = summary.get(uid)
        if not doc or not doc.get("project_acc"):
            raise RuntimeError(f"NCBI esummary returned no Project_Acc for uid {uid}")
        out.append((doc["project_acc"], {"title": doc.get("project_title", ""),
                                         "organism": doc.get("organism_name", ""),
                                         "description": doc.get("project_description", "")}))
    return int(found.get("count", 0)), out


def choose_ncbi_filter(cache):
    """Tests the SRA filter once and remembers the choice, so every query uses the same term."""
    meta = cache["meta"]
    if "ncbi_filter" not in meta:
        plain, _ = ncbi_search("liver cancer")
        filtered, results = ncbi_search("liver cancer" + SRA_FILTER)
        works = 0 < filtered < plain and bool(results)
        meta["ncbi_filter"] = SRA_FILTER if works else ""
        meta["ncbi_filter_test"] = {"liver cancer": plain, "liver cancer + filter": filtered}
        print(f"NCBI filter test: 'liver cancer' {plain} hits, with SRA filter {filtered} hits")
    if meta["ncbi_filter"]:
        print(f"NCBI option: query text + {meta['ncbi_filter'].strip()} (only projects with SRA data)")
    else:
        print("NCBI option: query text only (the SRA filter did not work)")
    return meta["ncbi_filter"]


# ---------------------------------------------------------------- Table S7 (raw jattr)
def latest_snapshot():
    complete = sorted(p for p in SNAPSHOTS.glob("*") if (p / "COMPLETE").exists())
    if not complete:
        stop(f"no complete parquet snapshot in {SNAPSHOTS}; the raw jattr values are only there")
    return complete[-1]


def jattr_child():
    """Runs under the auto-update venv (pyarrow). stdin: {"snapshot", "projects"};
    stdout: {project: {key: {value: runs}}} over every jattr key plus the
    organism and assay_type columns, for those projects' runs only."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    job = json.load(sys.stdin)
    wanted = pa.array(sorted(set(job["projects"])))
    out = defaultdict(lambda: defaultdict(Counter))
    files = sorted(Path(job["snapshot"]).glob("*.parquet"))
    for i, path in enumerate(files, 1):
        pf = pq.ParquetFile(path)
        for g in range(pf.metadata.num_row_groups):
            # Read the bioproject column first; the rest only when a sampled project is in this group.
            mask = pc.is_in(pf.read_row_group(g, columns=["bioproject"]).column(0), value_set=wanted)
            if not pc.any(mask).as_py():
                continue
            table = pf.read_row_group(g, columns=["bioproject", "organism", "assay_type", "jattr"]).filter(mask)
            for bp, organism, assay, jattr in zip(*(table.column(c).to_pylist() for c in table.column_names)):
                proj = out[bp]
                for col, val in (("organism", organism), ("assay_type", assay)):
                    if val:
                        proj["[column] " + col][val] += 1
                try:
                    obj = json.loads(jattr) if jattr else {}
                except ValueError:
                    obj = {}
                for key, val in (obj.items() if isinstance(obj, dict) else ()):
                    val = "; ".join(map(str, val)) if isinstance(val, list) else str(val)
                    proj[key][val] += 1
        print(f"  jattr: {i}/{len(files)} parquet files read", file=sys.stderr, flush=True)
    json.dump(out, sys.stdout)


def build_s7(database, cache):
    """140 rows: 10 random projects (seeded) per harmonized field, from the
    bioproject_attributes table the app's filters read, with the raw values."""
    if cache.get("table_s7"):
        print(f"Table S7: using cached sample ({len(cache['table_s7']['rows'])} rows)")
        return cache["table_s7"]["rows"]
    from sqlalchemy import text
    sys.path.insert(0, str(AUTOMATIONS))
    from jattr_normalize import FIELDS
    from jattr_key_counts import normalize_key

    print(f"Table S7: sampling {S7_PER_FIELD} projects for each of {len(FIELDS)} fields (seed {SEED})")
    sample = []  # (field, bioproject, harmonized values)
    with database.SessionLocal() as db:
        for field in FIELDS:
            # Projects with a value for the field and shown by the app (in bioprojects).
            candidates = db.scalars(text(
                "SELECT a.bioproject FROM bioproject_attributes a "
                "WHERE jsonb_typeof(a.attributes -> :f) = 'array' AND jsonb_array_length(a.attributes -> :f) > 0 "
                "AND EXISTS (SELECT 1 FROM bioprojects b WHERE b.bioproject = a.bioproject) "
                "ORDER BY a.bioproject"), {"f": field}).all()
            if len(candidates) < S7_PER_FIELD:
                stop(f"only {len(candidates)} projects have a value for {field}")
            picked = random.Random(f"{SEED}-{field}").sample(candidates, S7_PER_FIELD)
            for bp in picked:
                values = db.scalar(text("SELECT attributes -> :f FROM bioproject_attributes WHERE bioproject = :b"),
                                   {"f": field, "b": bp})
                sample.append((field, bp, "; ".join(map(str, values))))
            print(f"  {field}: {len(candidates):,} projects with a value, {S7_PER_FIELD} sampled")

    snapshot = latest_snapshot()
    if not AUTO_UPDATE_PYTHON.exists():
        stop(f"{AUTO_UPDATE_PYTHON} not found; it provides pyarrow to read the parquet snapshot")
    print(f"Table S7: reading raw jattr of {len({bp for _, bp, _ in sample})} projects from snapshot {snapshot.name}")
    job = json.dumps({"snapshot": str(snapshot), "projects": [bp for _, bp, _ in sample]})
    proc = subprocess.run([str(AUTO_UPDATE_PYTHON), str(Path(__file__).resolve()), "_jattr"],
                          input=job, stdout=subprocess.PIPE, text=True)  # child's progress goes to our stderr
    if proc.returncode != 0:
        stop("reading the parquet snapshot failed (see the error above)")
    raw = json.loads(proc.stdout)

    rows, no_runs = [], 0
    for i, (field, bp, harmonized) in enumerate(sample, 1):
        spec = FIELDS[field]
        pairs = Counter()
        for key, values in raw.get(bp, {}).items():
            if spec.get("column"):
                match = key == "[column] " + spec["column"]
            else:
                match = not key.startswith("[column] ") and normalize_key(key) in spec["keys"]
            if match:
                for value, runs in values.items():
                    pairs[(key.removeprefix("[column] "), value)] += runs
        text_ = "; ".join(f"{k}={v} ({n} runs)" for (k, v), n in pairs.most_common())
        if len(text_) > S7_RAW_CHARS:
            text_ = text_[:S7_RAW_CHARS - 1] + "…"
        no_runs += bp not in raw
        rows.append({"row_id": f"A{i:03d}", "bioproject": bp, "field": field,
                     "harmonized": harmonized, "original": text_})
    if no_runs:
        print(f"  WARNING: {no_runs} sampled rows have no runs in snapshot {snapshot.name}; "
              "their 'Original key-value pairs' are empty")
    cache["table_s7"] = {"seed": SEED, "snapshot": snapshot.name, "rows": rows}
    return rows


# ---------------------------------------------------------------- workbook writing
def put(ws, row, col, value):
    """Writes a plain value; text is never turned into a formula."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
    cell = ws.cell(row, col)
    cell.value = value
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"


def clear(ws, columns, first, last):
    for r in range(first, last + 1):
        for c in columns:
            cell = ws.cell(r, c)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                continue  # never touch formulas
            cell.value = None


def project_info(database, projects):
    """bioproject -> (title, organism, description) from the bioprojects table."""
    from sqlalchemy import text
    info = {}
    with database.SessionLocal() as db:
        for bp, title, organism, desc in db.execute(text(
                "SELECT DISTINCT ON (bioproject) bioproject, title, organism_name, description "
                "FROM bioprojects WHERE bioproject = ANY(:p) ORDER BY bioproject, sra_study"),
                {"p": list(projects)}):
            info[bp] = (title or "", organism or "", desc or "")
    return info


def write_s3(wb, queries, cache):
    ws = wb["Table S3"]
    clear(ws, [1, 2, 3, 4, 7], FIRST_ROW, max(ws.max_row, S3_LAST))
    r = FIRST_ROW
    for q in queries:
        entry = cache["queries"][q["id"]]
        for method in METHODS:
            for item in entry[method]:
                put(ws, r, 1, q["id"])
                put(ws, r, 2, method)
                put(ws, r, 3, item["rank"])
                put(ws, r, 4, item["bioproject"])
                put(ws, r, 7, item["score"])  # None for NCBI
                r += 1
    if r - 1 > S3_LAST:
        stop(f"Table S3 needs {r - FIRST_ROW} rows, more than its formulas cover")
    return r - FIRST_ROW


def write_s2(wb, queries, cache, database):
    """Pools every (query, project) pair found by any method; keeps judgments
    (C, D, E) already entered, and keeps rows added by hand."""
    ws = wb["Table S2"]
    old = {}          # (qid, bp) -> [A..I values]
    for r in range(FIRST_ROW, ws.max_row + 1):
        qid, bp = ws.cell(r, 1).value, ws.cell(r, 2).value
        if qid and bp:
            old[(str(qid).strip(), str(bp).strip())] = [ws.cell(r, c).value for c in range(1, 10)]

    pooled = {}       # (qid, bp) -> {"methods": [...], "best": rank}
    ncbi_info = {}
    for q in queries:
        entry = cache["queries"][q["id"]]
        ncbi_info.update(entry.get("ncbi_summaries", {}))
        for method in METHODS:
            for item in entry[method]:
                p = pooled.setdefault((q["id"], item["bioproject"]), {"methods": [], "best": item["rank"]})
                p["methods"].append(method)
                p["best"] = min(p["best"], item["rank"])

    info = project_info(database, {bp for _, bp in pooled})
    missing = {bp for _, bp in pooled if bp not in info}
    rows = []
    for q in queries:
        mine = sorted(((bp, p) for (qid, bp), p in pooled.items() if qid == q["id"]),
                      key=lambda x: (-len(x[1]["methods"]), x[1]["best"], x[0]))
        for bp, p in mine:
            if bp in info:
                title, organism, desc = info[bp]
            else:  # not in SRAscout's table (only NCBI found it): use NCBI's own summary
                s = ncbi_info.get(bp, {})
                title, organism, desc = s.get("title", ""), s.get("organism", ""), s.get("description", "")
            kept = old.pop((q["id"], bp), [None] * 9)
            rows.append([q["id"], bp, kept[2], kept[3], kept[4], title, organism,
                         "; ".join(p["methods"]), " ".join(desc.split())[:300]])
        # Rows added by hand (or no longer found) for this query stay, below the pool.
        for key in [k for k in old if k[0] == q["id"]]:
            rows.append(old.pop(key))
    rows.extend(old.values())  # rows for query IDs not in Table S1, kept as they were

    if FIRST_ROW + len(rows) - 1 > S2_LAST:
        stop(f"Table S2 needs {len(rows)} rows, more than its formulas cover")
    clear(ws, range(1, 10), FIRST_ROW, ws.max_row)
    for i, row in enumerate(rows):
        for c, value in enumerate(row, 1):
            put(ws, FIRST_ROW + i, c, value)
    return rows, missing


def header_sheet(wb, name, title, description, headers, widths):
    from openpyxl.styles import Alignment, Font
    ws = wb[name] if name in wb.sheetnames else wb.create_sheet(name)
    put(ws, 1, 1, title)
    ws.cell(1, 1).font = Font(bold=True, size=12)
    put(ws, 2, 1, description)
    ws.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top")
    for c, (h, w) in enumerate(zip(headers, widths), 1):
        put(ws, 3, c, h)
        ws.cell(3, c).font = Font(bold=True)
        ws.column_dimensions[ws.cell(3, c).column_letter].width = w
    ws.freeze_panes = "A4"
    return ws


def write_guide(wb):
    from openpyxl.styles import Alignment, Font
    if "Judging guide" in wb.sheetnames:
        del wb["Judging guide"]  # our own sheet: rebuilt every run
    ws = wb.create_sheet("Judging guide")
    lines = [
        ("Judging guide for Table S2 (relevance) and Table S7 (attribute accuracy)", True),
        ("", False),
        ("Table S2: relevance of a BioProject to a query", True),
        ("Enter 1 in 'Relevant (1/0)' if the project's data could reasonably be used to answer the query: "
         "the right organism or sample type, the right kind of experiment, and on topic.", False),
        ("Enter 0 otherwise.", False),
        ("Judge from the title and description shown. Open the BioProject page "
         "(https://www.ncbi.nlm.nih.gov/bioproject/<accession>) only when unsure.", False),
        ("Be consistent across methods: the 'Found by' column is there for bookkeeping only; "
         "judge every project the same way, whichever method found it.", False),
        ("When unsure, decide anyway and write a short note in 'Notes'.", False),
        ("Put your initials in 'Annotator'.", False),
        ("", False),
        ("Table S7: accuracy of the harmonized attributes", True),
        ("Compare 'Harmonized values' with 'Original key-value pairs' (the submitters' raw values; "
         "run counts in brackets) and enter one label:", False),
        ("correct: the harmonized values say the same as the original values.", False),
        ("partly correct: some values are right, but some are missing, wrong or badly normalised.", False),
        ("incorrect: the harmonized values misrepresent the original values.", False),
        ("Leave a note when unsure. Put your initials in 'Annotator'.", False),
    ]
    for r, (line, bold) in enumerate(lines, 1):
        put(ws, r, 1, line)
        ws.cell(r, 1).font = Font(bold=bold, size=12 if r == 1 else 11)
        ws.cell(r, 1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 120


def write_s7(wb, rows):
    """Keeps labels, annotators and notes already entered for the same project and field."""
    from openpyxl.styles import Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    name = "Table S7"
    kept = {}
    if name in wb.sheetnames:
        old = wb[name]
        for r in range(FIRST_ROW, old.max_row + 1):
            bp, field = old.cell(r, 2).value, old.cell(r, 3).value
            if bp and field:
                kept[(bp, field)] = [old.cell(r, c).value for c in (6, 7, 8)]
    ws = header_sheet(
        wb, name, "Supplementary Table S7. Accuracy of harmonized sample attributes",
        f"Random sample (seed {SEED}) of {S7_PER_FIELD} BioProjects for each of the 14 harmonized fields, "
        "among projects with a value for that field. Harmonized values are those in SRAscout; original "
        "key-value pairs are the submitters' raw attributes (jattr) of the project's runs for that field's "
        f"source keys, with the number of runs, cut to {S7_RAW_CHARS} characters. Label: correct, partly "
        "correct or incorrect.",
        ["Row ID", "BioProject", "Field", "Harmonized values", "Original key-value pairs",
         "Label", "Annotator", "Notes"],
        [8, 14, 26, 45, 80, 14, 11, 30])
    for rng in ("A1:H1", "A2:H2"):
        if rng not in {str(m) for m in ws.merged_cells.ranges}:
            ws.merge_cells(rng)
    ws.row_dimensions[2].height = 60
    clear(ws, range(1, 9), FIRST_ROW, ws.max_row)
    for i, row in enumerate(rows):
        r = FIRST_ROW + i
        label = kept.get((row["bioproject"], row["field"]), [None] * 3)
        for c, value in enumerate([row["row_id"], row["bioproject"], row["field"], row["harmonized"],
                                   row["original"], *label], 1):
            put(ws, r, c, value)
        for c in (4, 5):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
    if not ws.data_validations.dataValidation:
        dv = DataValidation(type="list", formula1='"correct,partly correct,incorrect"', allow_blank=True)
        dv.add(f"F{FIRST_ROW}:F{FIRST_ROW + 999}")
        ws.add_data_validation(dv)


def save_workbook(wb, path):
    import shutil
    backup = path.with_name(path.stem + ".orig.xlsx")
    if not backup.exists():
        shutil.copy2(path, backup)  # the untouched template, once
        print(f"Backup of the template: {backup}")
    wb.calculation.fullCalcOnLoad = True  # Excel recomputes the formulas when opening
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)

    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        print("LibreOffice is not installed: open the workbook once in Excel and save it, "
              "so the formula columns are calculated.")
        return
    # Recalculate by converting to xlsx (LibreOffice recalculates on load).
    outdir = path.parent / "recalc"
    outdir.mkdir(exist_ok=True)
    res = subprocess.run([office, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(outdir), str(path)],
                         capture_output=True, text=True, timeout=600)
    out = outdir / path.name
    if res.returncode == 0 and out.exists():
        out.replace(path)
        outdir.rmdir()
        print("Recalculated with LibreOffice.")
    else:
        print(f"LibreOffice recalculation failed ({res.stderr.strip()}); open the workbook once in Excel.")


# ---------------------------------------------------------------- run
def cmd_run(args):
    import openpyxl

    if REQUIRE_EMAIL and not os.getenv("NCBI_EMAIL"):
        stop("set NCBI_EMAIL (your email address, sent to NCBI with each request), e.g.\n"
             "  export NCBI_EMAIL=you@example.org")
    database, embeddings, S = load_backend()
    wb = openpyxl.load_workbook(args.workbook)
    queries = read_queries(wb)
    if args.limit:
        queries = queries[:args.limit]
    cache = load_cache(args.cache)
    print(f"{len(queries)} queries in Table S1; cache {args.cache} has {len(cache['queries'])}")

    todo = [q for q in queries
            if not all(m in cache["queries"].get(q["id"], {}) for m in METHODS)
            or cache["queries"][q["id"]].get("query") != q["query"]]
    if todo:
        with database.SessionLocal() as db:
            index_present = has_hnsw_index(db)
        if not index_present and not args.allow_seqscan:
            stop("bioproject_embeddings has no HNSW index, so semantic search is an exact sequential scan "
                 "(about 5 s per scan): timings would not be the app's normal ones. Build the index first "
                 "(docs: memory note / production.md), or pass --allow-seqscan to run anyway.")
        print(f"HNSW index on bioproject_embeddings: {'present' if index_present else 'MISSING (exact scan)'}")
        ncbi_filter = choose_ncbi_filter(cache)
        save_cache(cache, args.cache)
        print(f"Loading the embedding model {embeddings.MODEL_NAME} ...")
        embeddings.embed("warm up")  # model load is not part of a search's time
        cache["meta"].update({"model": embeddings.MODEL_NAME, "rrf_k": S.RRF_K,
                              "semantic_min_similarity": S.SEMANTIC_MIN_SIMILARITY,
                              "text_min_similarity": S.TEXT_MIN_SIMILARITY,
                              "semantic_candidates": S.SEMANTIC_CANDIDATES,
                              "text_candidates": S.TEXT_CANDIDATES})

    for n, q in enumerate(queries, 1):
        entry = cache["queries"].get(q["id"])
        if entry and entry.get("query") != q["query"]:
            entry = None  # query text changed in the workbook: redo it
        if entry and all(m in entry for m in METHODS):
            continue
        entry = entry or {"query": q["query"]}
        try:
            if not all(m in entry for m in METHODS[:3]):
                run_sra_methods(q["query"], entry, database, embeddings, S, index_present)
                cache["queries"][q["id"]] = entry
                save_cache(cache, args.cache)  # keep the SRAscout part if NCBI fails next
            if METHODS[3] not in entry:
                count, found = ncbi_search(q["query"] + ncbi_filter)
                entry["ncbi_count"] = count
                entry[METHODS[3]] = [{"rank": i, "bioproject": acc, "score": None}
                                     for i, (acc, _) in enumerate(found, 1)]
                entry["ncbi_summaries"] = {acc: s for acc, s in found}
        except RuntimeError as e:
            stop(f"{q['id']}: {e}")
        cache["queries"][q["id"]] = entry
        save_cache(cache, args.cache)
        print(f"[{n:3d}/{len(queries)}] {q['id']} hybrid {len(entry['Hybrid']):2d} ({entry['hybrid_seconds']:.2f} s) "
              f"| semantic {len(entry['Semantic only']):2d} | full-text {len(entry['Full-text only']):2d} "
              f"| NCBI {len(entry[METHODS[3]]):2d} of {entry['ncbi_count']}")

    s7_rows = build_s7(database, cache)
    save_cache(cache, args.cache)

    print("Writing the workbook ...")
    n_s3 = write_s3(wb, queries, cache)
    s2_rows, missing = write_s2(wb, queries, cache, database)
    write_guide(wb)
    write_s7(wb, s7_rows)
    save_workbook(wb, args.workbook)

    unjudged = sum(1 for row in s2_rows if row[2] in (None, ""))
    print("\nSummary")
    print(f"  queries done:              {len(queries)}")
    for m in METHODS:
        print(f"  results, {m + ':':24s} {sum(len(cache['queries'][q['id']][m]) for q in queries)}")
    print(f"  Table S3 rows:             {n_s3}")
    print(f"  Table S2 pairs:            {len(s2_rows)} ({unjudged} still to judge)")
    if missing:
        print(f"  ({len(missing)} projects found only by NCBI are not in the bioprojects table; "
              "their title/organism/description come from NCBI's esummary)")
    print(f"  Table S7 rows:             {len(s7_rows)}")
    print(f"  workbook: {args.workbook}")


# ---------------------------------------------------------------- report
def as_judgment(value):
    if value in (None, ""):
        return None
    try:
        v = int(float(str(value).strip()))
    except ValueError:
        return "bad"
    return v if v in (0, 1) else "bad"


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def cmd_report(args):
    import openpyxl
    wb = openpyxl.load_workbook(args.workbook)
    queries = read_queries(wb)
    cache = load_cache(args.cache)
    out, warnings = [], []

    # Table S2 judgments, Table S3 top 20s.
    judged = {}
    s2 = wb["Table S2"]
    for r in range(FIRST_ROW, s2.max_row + 1):
        qid, bp = s2.cell(r, 1).value, s2.cell(r, 2).value
        if qid and bp:
            judged[(str(qid).strip(), str(bp).strip())] = as_judgment(s2.cell(r, 3).value)
    top = defaultdict(list)  # (qid, method) -> [bp]
    s3 = wb["Table S3"]
    for r in range(FIRST_ROW, s3.max_row + 1):
        qid, method, bp = s3.cell(r, 1).value, s3.cell(r, 2).value, s3.cell(r, 4).value
        if qid and method and bp:
            top[(str(qid).strip(), method)].append(str(bp).strip())

    empty = sum(1 for v in judged.values() if v is None)
    bad = sum(1 for v in judged.values() if v == "bad")
    not_in_s2 = {(q, bp) for (q, _), bps in top.items() for bp in bps if (q, bp) not in judged}
    judgments_ok = judged and not (empty or bad or not_in_s2)
    if empty:
        warnings.append(f"{empty} pairs in Table S2 have no relevance judgment")
    if bad:
        warnings.append(f"{bad} judgments in Table S2 are not 1 or 0")
    if not_in_s2:
        warnings.append(f"{len(not_in_s2)} results in Table S3 have no row in Table S2")

    out.append("SRAscout benchmark")
    out.append(f"Queries: {len(queries)}; results in Table S3 for {len({q for q, _ in top})}")
    out.append(f"Judged pairs: {sum(v in (0, 1) for v in judged.values())}; "
               f"relevant: {sum(v == 1 for v in judged.values())}")

    if judgments_ok:
        relevant = defaultdict(set)
        for (qid, bp), v in judged.items():
            if v == 1:
                relevant[qid].add(bp)
        recall = {}  # (qid, method) -> recall@20
        for q in queries:
            rel = relevant.get(q["id"])
            if rel:
                for m in METHODS:
                    recall[(q["id"], m)] = len(rel & set(top[(q["id"], m)][:TOP_N])) / len(rel)
        scored = [q for q in queries if relevant.get(q["id"])]
        out.append(f"Queries with at least one relevant project: {len(scored)} of {len(queries)}")
        out.append("")
        out.append("Mean recall@20       " + " | ".join(f"{m}" for m in METHODS))

        def line(label, qs):
            vals = [f"{mean([recall[(q['id'], m)] for q in qs]):.3f}" for m in METHODS]
            return f"{label} (n={len(qs)}): " + " | ".join(vals)
        out.append(line("All", scored))
        for key, title in (("type", "By query type"), ("domain", "By domain")):
            out.append(title)
            for group in sorted({q[key] for q in scored}):
                out.append("  " + line(group, [q for q in scored if q[key] == group]))

        # Relevant projects found by Hybrid: publications and GEO series.
        database, _, _ = load_backend()
        from sqlalchemy import text
        hyb = {bp for q in scored for bp in top[(q["id"], "Hybrid")] if bp in relevant[q["id"]]}
        with database.SessionLocal() as db:
            rows = db.execute(text(
                "SELECT bioproject, bool_or(coalesce(publication_count, 0) > 0 OR coalesce(pubmed_ids, '') <> ''), "
                "bool_or(coalesce(geo_accessions, '') ~ 'GSE') FROM bioprojects "
                "WHERE bioproject = ANY(:p) GROUP BY bioproject"), {"p": list(hyb)}).all()
        out.append("")
        if hyb:
            out.append(f"Relevant projects found by Hybrid (unique BioProjects): {len(hyb)}")
            out.append(f"  without a linked publication: {sum(not r[1] for r in rows) / len(rows):.1%}")
            out.append(f"  without a GEO series:         {sum(not r[2] for r in rows) / len(rows):.1%}")

        out.append("")
        out.append("Largest Hybrid minus NCBI recall@20, per query type")
        for group in sorted({q["type"] for q in scored}):
            best = max((q for q in scored if q["type"] == group),
                       key=lambda q: recall[(q["id"], "Hybrid")] - recall[(q["id"], METHODS[3])])
            h, n = recall[(best["id"], "Hybrid")], recall[(best["id"], METHODS[3])]
            out.append(f"  {group}: {best['id']} \"{best['query'][:90]}\" Hybrid {h:.2f}, NCBI {n:.2f} (+{h - n:.2f})")
    else:
        out.append("Recall, publication/GEO shares and examples: NOT computed (judgments missing, see warnings)")

    # Timings from cache.json.
    times = [e["hybrid_seconds"] for e in cache["queries"].values() if "hybrid_seconds" in e]
    embeds = [e["embedding_seconds"] for e in cache["queries"].values() if "embedding_seconds" in e]
    out.append("")
    if times:
        out.append(f"Hybrid search time (embedding + database, n={len(times)}): median {statistics.median(times):.2f} s, "
                   f"min {min(times):.2f} s, max {max(times):.2f} s; median embedding {statistics.median(embeds) * 1000:.0f} ms")
        if any(not e.get("hnsw_index", True) for e in cache["queries"].values() if "hybrid_seconds" in e):
            warnings.append("some timings were measured WITHOUT the HNSW index (exact sequential scan)")

    # Table S7 labels.
    out.append("")
    if "Table S7" in wb.sheetnames:
        s7 = wb["Table S7"]
        labels = []
        for r in range(FIRST_ROW, s7.max_row + 1):
            if s7.cell(r, 2).value:
                label = s7.cell(r, 6).value
                labels.append((s7.cell(r, 3).value, str(label).strip().lower() if label not in (None, "") else None))
        kinds = ["correct", "partly correct", "incorrect"]
        unlabelled = sum(1 for _, l in labels if l is None)
        unknown = sum(1 for _, l in labels if l is not None and l not in kinds)
        out.append(f"Table S7: {len(labels)} rows, {unlabelled} unlabelled")
        if unlabelled or unknown:
            if unlabelled:
                warnings.append(f"{unlabelled} rows in Table S7 have no label")
            if unknown:
                warnings.append(f"{unknown} labels in Table S7 are not correct / partly correct / incorrect")
            out.append("  attribute accuracy: NOT computed (labels missing or invalid, see warnings)")
        else:
            def shares(ls):
                c = Counter(ls)
                return ", ".join(f"{k} {c[k] / len(ls):.0%}" for k in kinds)
            out.append(f"  overall (n={len(labels)}): {shares([l for _, l in labels])}")
            for field in dict.fromkeys(f for f, _ in labels):
                ls = [l for f, l in labels if f == field]
                out.append(f"  {field} (n={len(ls)}): {shares(ls)}")
    else:
        warnings.append("no Table S7 sheet; run 'run' first")

    # Validation: human labels for a sample of Table S2 pairs, against Table S2's labels.
    out.append("")
    if "Validation" in wb.sheetnames:
        vs = wb["Validation"]
        sample = []  # (human, judged-in-Table-S2)
        for r in range(FIRST_ROW, vs.max_row + 1):
            qid, bp = vs.cell(r, 1).value, vs.cell(r, 3).value
            if qid and bp:
                sample.append((as_judgment(vs.cell(r, 7).value), judged.get((str(qid).strip(), str(bp).strip()))))
        filled = [(h, j) for h, j in sample if h in (0, 1)]
        if not filled:
            out.append(f"Validation: {len(sample)} pairs, human labels not filled in yet")
        elif len(filled) < len(sample) or any(j not in (0, 1) for _, j in filled):
            warnings.append(f"Validation sheet: {len(filled)} of {len(sample)} human labels filled, or pairs "
                            "without a valid Table S2 label")
            out.append("Validation: agreement NOT computed (human labels missing or invalid, see warnings)")
        else:
            n = len(filled)
            tp = sum(1 for h, j in filled if h == 1 and j == 1)
            tn = sum(1 for h, j in filled if h == 0 and j == 0)
            fp = sum(1 for h, j in filled if h == 0 and j == 1)
            fn = sum(1 for h, j in filled if h == 1 and j == 0)
            po = (tp + tn) / n
            # Cohen's kappa: observed agreement against agreement expected by chance.
            pe = ((tp + fn) / n) * ((tp + fp) / n) + ((tn + fp) / n) * ((tn + fn) / n)
            kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
            annot = Counter(str(wb["Table S2"].cell(r, 4).value) for r in range(FIRST_ROW, wb["Table S2"].max_row + 1)
                            if wb["Table S2"].cell(r, 1).value)
            out.append(f"Validation (n={n}; Table S2 annotators: "
                       + ", ".join(f"{a} {c}" for a, c in annot.most_common()) + "), human labels as truth:")
            out.append(f"  agreement {po:.1%}, Cohen's kappa {kappa:.2f}")
            out.append(f"  Table S2 precision {tp / (tp + fp):.1%} ({tp}/{tp + fp}), "
                       f"recall {tp / (tp + fn):.1%} ({tp}/{tp + fn})" if tp + fp and tp + fn else
                       "  precision/recall undefined (no positives)")
            out.append(f"  confusion: both 1 {tp}, both 0 {tn}, Table S2 1 / human 0 {fp}, Table S2 0 / human 1 {fn}")
    else:
        out.append("Validation: no Validation sheet")

    # Plausibility: pooled benchmarks are never almost all relevant (or all irrelevant).
    vals = [v for v in judged.values() if v in (0, 1)]
    if vals and not 0.05 <= sum(vals) / len(vals) <= 0.95:
        warnings.append(f"{sum(vals) / len(vals):.1%} of Table S2 judgments are 1; check they were judged one by one")

    if warnings:
        print("WARNINGS:\n" + "\n".join(f"  ! {w}" for w in warnings) + "\n")
    print("\n".join(out))


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["_jattr"]:  # child process, see jattr_child
        return jattr_child()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="search, pool and write the workbook")
    run.add_argument("--limit", type=int, help="only the first N queries (for testing)")
    run.add_argument("--allow-seqscan", action="store_true",
                     help="run even when the HNSW index is missing (timings will be slow)")
    report = sub.add_parser("report", help="print the results after judging")
    for p in (run, report):
        p.add_argument("--workbook", type=Path, default=WORKBOOK)
        p.add_argument("--cache", type=Path, default=CACHE)
    args = parser.parse_args(argv)
    {"run": cmd_run, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()
