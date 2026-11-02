"""
Build the `bioproject_tags` table: biomedical tag words per bioproject (CPU, incremental).

Reads ../output/bioprojects.csv (written by create_tables.py) and
../output/bioproject_embeddings.tsv (written by create_embeddings.py), and
writes output/bioproject_tags.tsv with three columns:
  bioproject  e.g. PRJNA559273
  tags        "; "-separated tag words, e.g. Mus musculus; mouse; osteoarthritis; skin; synovial fibroblast
  labels      each tag's type, in the same order, e.g. organism; organism; disease; tissue; cell type
Load it with bioproject_tags_schema.sql.

Pipeline, per bioproject (one row per bioproject; projects repeated per
sra_study in bioprojects.csv are processed once):
  1. NER: GLiNER-biomed (zero-shot) over title + name + description finds
     organisms, diseases, tissues, organs, cell types, cell lines,
     chemicals/drugs and environments (see LABELS).
  2. Cleanup: whitespace/punctuation trimmed, case normalised (acronyms and
     binomial names keep theirs), simple plurals singularised, strain-level
     organism names cut to the species binomial, generic words dropped
     (STOP_TAGS).
  3. Relevance filter: each tag is embedded with the same model as the project
     embeddings and compared (cosine) with its project's embedding. Off-topic
     mentions and stray abbreviations score low and are dropped. Projects
     missing from the embeddings file keep their tags unfiltered.
  4. The structured organism_name is always added first (type "organism").
  Remaining tags are ordered by relevance and capped at --max-tags.

Incremental: bioprojects already present in the output file are skipped, so
after adding new bioprojects to bioprojects.csv (and their embeddings) just
rerun the script; it appends only the new ones. The same mechanism resumes an
interrupted run (a half-written last line is discarded). Use --restart to
rebuild everything, e.g. after changing LABELS or the thresholds.

An output file from before the labels column (two columns) is upgraded in
place: its rows get an empty labels field and new rows are written with
labels. Rerun with --restart to get labels for the old rows too.

Setup (once, from this folder):
  /usr/bin/python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt

Usage:
  python3 extract_tags.py [--workers N] [--threads-per-worker 2] [--chunk-size 256]
                          [--limit N] [--restart]

Run on a compute node (idev / sbatch, see run_extract_tags.slurm), not a login
node: it uses every core and ~3 GB RAM per worker. A full run over ~670k
bioprojects takes ~10-14h on 16 cores; a 128-core node is several times faster.
"""

import argparse
import csv
import html
import os
import re
import sys
import time
from collections import deque
from pathlib import Path

# GLiNER / torch live in this folder's venv (TagWords/.venv); re-launch under it
# when started with another interpreter.
VENV_PYTHON = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
IN_CSV = BASE_DIR.parent / "output" / "bioprojects.csv"
IN_EMBEDDINGS = BASE_DIR.parent / "output" / "bioproject_embeddings.tsv"
OUT_TSV = BASE_DIR / "output" / "bioproject_tags.tsv"

NER_MODEL = "Ihor/gliner-biomed-small-v1.0"
# Must be the model create_embeddings.py used, so tag and project vectors are comparable.
EMBED_MODEL = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
EMBEDDING_DIM = 768

# GLiNER label prompt -> kept as a tag? The False labels are extracted only so
# that gene symbols, places and sequencers are not mislabelled as one of the
# kept types; their spans are discarded.
LABELS = {
    "organism": True,
    "disease": True,
    "tissue": True,
    "organ": True,
    "cell type": True,
    "cell line": True,
    "chemical or drug": True,
    "environment or habitat": True,
    "gene or protein": False,
    "geographic location": False,
    "sequencing technology": False,
}
TEXT_COLUMNS = ["title", "name", "description"]
MAX_WORDS = 300          # GLiNER sees at most ~384 words; the start of the text carries the topic
MAX_CHARS = 3000         # also cap characters: one huge unspaced "word" can need GBs of RAM
NER_THRESHOLD = 0.5      # GLiNER span score
MIN_SIMILARITY = 0.10    # tag vs project embedding (cosine)
ACRONYM_MIN_SIMILARITY = 0.25  # stricter for short all-caps tags (OA, AB, IS, ...)
MAX_TAG_WORDS = 5
SEP = "; "
HEADER = "bioproject\ttags\tlabels\n"
OLD_HEADER = "bioproject\ttags\n"  # before the labels column
GB_PER_WORKER = 3        # peak RSS of one worker (GLiNER + BioBERT) is ~2.6 GB

STOP_TAGS = {
    "cell", "tissue", "organ", "sample", "organism", "species", "strain", "isolate",
    "patient", "individual", "subject", "donor", "participant", "people", "person",
    "population", "host", "animal", "disease", "infection", "control", "wild type",
    "wildtype", "wt", "mutant", "model", "culture", "cell culture", "cell line",
    "primary cell", "environment", "habitat", "drug", "chemical", "compound",
    "treatment", "medium", "media", "water", "dna", "rna", "genome", "gene",
    "protein", "sequence", "read", "metagenome", "microbe", "microorganism",
    "community", "microbial community", "unknown", "other", "none", "na", "n/a",
    "ctrl", "vitro", "vivo", "in vitro", "in vivo", "ex vivo", "plant", "tumour",
    "uncultured microbe", "uncultured bacterium", "unidentified", "unclassified",
    "environmental",
}
# Dropped from either end of a span ("Healthy donors" -> "donor" -> stop tag).
EDGE_WORDS = {"the", "a", "an", "of", "in", "from", "with", "and", "or", "our", "these",
              "this", "control", "healthy", "normal", "wt", "wild-type"}
# Tags mentioning a sequencer or an accession are metadata, not biology.
JUNK_TAG = re.compile(
    r"illumina|hiseq|miseq|novaseq|nextseq|pacbio|nanopore|ion torrent|bgiseq|dnbseq|"
    r"_|\d{4}|\b(?:GS[EM]|SR[APRSX]|ER[APRSX]|DR[APRSX]|PRJ[A-Z]+|SAM[NED][A-Z]?)\d",
    re.IGNORECASE)
# A lone modifier is not a tag: "florfenicol-induced", "NNS-supplemented".
DANGLING_MODIFIER = re.compile(
    r"^\S+-(?:induced|treated|supplemented|deficient|related|associated|derived|dependent|"
    r"mediated|infected|exposed|fed|based|specific|resistant)$", re.IGNORECASE)
IRREGULAR_PLURALS = {
    "mice": "mouse", "geese": "goose", "teeth": "tooth", "feet": "foot", "children": "child",
    "women": "woman", "men": "man", "leaves": "leaf", "calves": "calf", "lice": "louse",
    "oxen": "ox", "testes": "testis", "ovaries": "ovary", "bodies": "body", "humans": "human",
}
# Plural-looking words that must not lose their final "s".
NO_SINGULAR = (
    "ss", "us", "is", "ous", "ys", "ics", "itis", "osis", "diabetes", "herpes", "measles",
    "rabies", "scabies", "mumps", "rickets", "series", "species", "feces", "faeces",
    "pancreas", "lens", "iris", "bacteria", "fungi", "sepsis", "analysis", "aureus",
    "ans", "iens",  # Latin epithets: agglomerans, sapiens
)
SINGULARISE_LABELS = {"organism", "tissue", "organ", "cell type", "cell line"}

BINOMIAL = re.compile(r"^([A-Z][a-z]+ (?:x )?[a-z][a-z-]+)\b")
ABBREVIATED_BINOMIAL = re.compile(r"^[A-Z]\. [a-z]+$")  # S. aureus
NOT_EPITHET = {"sp", "spp", "cell", "cells", "and", "or", "of", "in", "from", "with", "strain", "species"}
ENGLISH_ADJECTIVE = re.compile(r"(?:al|ic|ed|ing|ous|ary|ful|less)$")  # "Freshwater microbial"
TRIM_CHARS = " \t\"'`.,;:()[]{}<>-_/\\|*+=~!?"

csv.field_size_limit(sys.maxsize)


# ---------------------------------------------------------------- text
def build_text(row):
    """Join the non-empty text fields into one passage, truncated to MAX_WORDS / MAX_CHARS."""
    parts = []
    for col in TEXT_COLUMNS:
        # Some descriptions are HTML-entity encoded ("&#73;&#110;&#32;..." for "In ").
        value = " ".join(html.unescape(row.get(col) or "").split())
        if value and not any(value in p for p in parts):  # name often repeats title
            parts.append(value)
    words = ". ".join(parts).split(" ")
    text = " ".join(words[:MAX_WORDS])
    if len(text) > MAX_CHARS:
        cut = text.rfind(" ", 0, MAX_CHARS)
        text = text[:cut if cut > 0 else MAX_CHARS]
    return text


def singularise(word):
    low = word.lower()
    if low in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[low]
    if not low.endswith("s") or len(low) < 4 or low.endswith(NO_SINGULAR):
        return word
    if low.endswith("uses"):  # viruses
        return word[:-2]
    if low.endswith("ies"):
        return word[:-3] + "y"
    if low.endswith(("ches", "shes", "xes", "sses")):
        return word[:-2]
    return word[:-1]


def normalise_tag(text, label):
    """Clean one GLiNER span; returns the display form or None to drop it."""
    text = " ".join(text.replace("’", "'").split()).strip(TRIM_CHARS)
    words = text.split(" ")
    while words and words[0].lower() in EDGE_WORDS:
        words = words[1:]
    while words and words[-1].lower() in EDGE_WORDS:
        words = words[:-1]
    if not words or len(words) > MAX_TAG_WORDS:
        return None
    text = " ".join(words).strip(TRIM_CHARS)
    if text.count("(") > text.count(")"):
        # "cancer associated fibroblasts (CAFs" -> drop the open aside; "poly(γ-glutamic acid" -> close it
        text = text[:text.rfind(" (")] if " (" in text else text + ")"
    elif text.count(")") > text.count("("):
        text = text.replace(")", "")
    if (len(text) < 2 or len(text) > 60 or not re.search(r"[A-Za-z]{2}", text)
            or JUNK_TAG.search(text) or DANGLING_MODIFIER.match(text)):
        return None
    if text.isupper() and " " in text and len(text) > 12:  # SHOUTED TITLE WORDS
        text = text.lower()

    if label == "organism":
        m = BINOMIAL.match(text)
        epithet = m.group(1).split()[-1] if m else ""
        if m and epithet not in NOT_EPITHET and not ENGLISH_ADJECTIVE.search(epithet):
            species = m.group(1)  # species level: "Bacillus subtilis GXA-28" -> "Bacillus subtilis"
            return None if species.lower() in STOP_TAGS else species
        if ABBREVIATED_BINOMIAL.match(text):
            return text

    # Lowercase ordinary words; keep acronyms, gene-like symbols, mixed case
    # (HeLa, C57BL/6), single capitals (T cell) and abbreviated genera (E. coli).
    latin = label == "organism" and not text.split(" ")[-1].islower()  # Nocardioides, Mycoplasma
    words = [w if (len(w) == 1 or w[1] == "." or any(c.isupper() for c in w[1:])
                   or any(c.isdigit() for c in w))
             else w.lower() for w in text.split(" ")]
    if label in SINGULARISE_LABELS and words[-1].islower() and not latin:
        words[-1] = singularise(words[-1])
    text = " ".join(words).strip(TRIM_CHARS.replace("()", ""))  # "cell/s" -> "cell/" -> "cell"
    if text.lower() in STOP_TAGS or words[0].lower() in {"vivo", "vitro"}:
        return None
    return text


def tag_key(tag):
    """Dedup key: case- and plural-insensitive ("marine environments" == "marine environment")."""
    words = tag.lower().split(" ")
    return " ".join(words[:-1] + [singularise(words[-1])])


def is_acronym(tag):
    return len(tag) <= 3 or (len(tag) <= 5 and not any(c.islower() for c in tag))


# ---------------------------------------------------------------- worker
_worker = {}


def init_worker(threads):
    import torch
    from gliner import GLiNER
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(threads)
    ner = GLiNER.from_pretrained(NER_MODEL)
    ner.eval()
    embedder = SentenceTransformer(EMBED_MODEL, device="cpu")
    embedder.max_seq_length = 32  # tags are a few words
    embedder.eval()
    _worker.update(ner=ner, embedder=embedder, cache={})


def embed_tags(tags):
    """Tag -> unit vector, memoised per worker (frequent tags like 'mouse' recur)."""
    cache = _worker["cache"]
    missing = [t for t in tags if t not in cache]
    if missing:
        if len(cache) > 50_000:
            cache.clear()
        vecs = _worker["embedder"].encode(missing, batch_size=256, normalize_embeddings=True,
                                          convert_to_numpy=True, show_progress_bar=False)
        cache.update(zip(missing, vecs.astype(np.float16)))
    return {t: cache[t] for t in tags}


def tag_chunk(items, batch_size, max_tags):
    """items: [(bioproject, text, organism_name, project vector or None)]
    -> [(bioproject, [(tag, label)])], label being the GLiNER type."""
    import torch

    # Projects without text get only their organism_name; sort by length for less padding.
    order = sorted((i for i in range(len(items)) if items[i][1]), key=lambda i: len(items[i][1]))
    texts = [items[i][1] for i in order]
    ents = [[] for _ in items]
    if texts:
        with torch.inference_mode():
            found = _worker["ner"].inference(texts, list(LABELS), threshold=NER_THRESHOLD,
                                             batch_size=batch_size)
        for i, spans in zip(order, found):
            ents[i] = spans

    candidates = []  # per project: {tag key: (display, label)}
    for spans in ents:
        tags = {}
        for span in spans:
            if not LABELS[span["label"]]:
                continue
            tag = normalise_tag(span["text"], span["label"])
            if tag:
                tags.setdefault(tag_key(tag), (tag, span["label"]))
        candidates.append(tags)
    vectors = embed_tags({t for tags in candidates for t, _ in tags.values()})

    out = []
    for (bioproject, _text, organism, project_vec), tags in zip(items, candidates):
        scored = []
        for tag, label in tags.values():
            sim = float(vectors[tag].astype(np.float32) @ project_vec) if project_vec is not None else 1.0
            min_sim = ACRONYM_MIN_SIMILARITY if is_acronym(tag) else MIN_SIMILARITY
            if sim >= min_sim:
                scored.append((sim, tag, label))
        scored.sort(key=lambda x: -x[0])
        final = [(organism, "organism")] if organism else []
        seen = {tag_key(organism)} if organism else set()
        for _sim, tag, label in scored:
            if tag_key(tag) not in seen:
                seen.add(tag_key(tag))
                final.append((tag, label))
        out.append((bioproject, final[:max_tags]))
    return out


# ---------------------------------------------------------------- io
def clean_tag_field(tag):
    """Tags go into one TSV field joined by SEP (loaded as CSV): keep tabs, newlines, ';' and '"' out."""
    return " ".join(tag.replace(";", ",").replace('"', "'").split())


def upgrade_output(path):
    """Add the labels column to an output file written before it existed.

    Old rows get an empty labels field (loaded as NULL), so the file stays
    loadable and the run can append rows with labels.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    with open(path, encoding="utf-8") as f:
        if f.readline() != OLD_HEADER:
            return
    tmp = path.with_suffix(".upgrading")
    with open(path, encoding="utf-8") as src, open(tmp, "w", encoding="utf-8") as dst:
        next(src)
        dst.write(HEADER)
        for line in src:
            if line.endswith("\n"):  # a half-written last line is dropped, as on resume
                dst.write(line[:-1] + "\t\n")
    tmp.replace(path)
    print(f"upgraded {path} to the three-column format (old rows have no labels; "
          f"use --restart to label them)", flush=True)


def done_bioprojects(path):
    """IDs already in the output; drops a half-written last line from a killed run."""
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with open(path, "rb+") as f:
        data = f.read()
        if not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            f.truncate(cut)
            data = data[:cut]
    lines = data.decode("utf-8").splitlines()
    return {line.split("\t", 1)[0] for line in lines[1:] if line}


def read_projects(path, skip, limit):
    """Unique bioprojects not in `skip`: [(bioproject, text, organism_name)]."""
    projects, seen = [], set(skip)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bioproject = row["bioproject"]
            if bioproject in seen or not bioproject.startswith("PRJ"):
                continue
            seen.add(bioproject)
            organism = clean_tag_field(row.get("organism_name") or "")
            projects.append((bioproject, build_text(row), organism))
            if limit and len(projects) >= limit:
                break
    return projects


def read_embeddings(path, wanted):
    """{bioproject: unit vector (float16)} for the wanted IDs only (streams the multi-GB TSV)."""
    vectors = {}
    if not path.exists():
        print(f"warning: {path} not found; tags will not be relevance-filtered", flush=True)
        return vectors
    with open(path, encoding="utf-8") as f:
        next(f)
        for line in f:
            bioproject, _, vec = line.partition("\t")
            if bioproject in wanted:
                v = np.array(vec.strip()[1:-1].split(","), dtype=np.float32)
                assert v.shape == (EMBEDDING_DIM,), (bioproject, v.shape)
                vectors[bioproject] = v.astype(np.float16)  # ~1 GB for all bioprojects
    return vectors


def available_ram_gb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 2**20
    return 0


def format_eta(seconds):
    h, rem = divmod(int(seconds), 3600)
    return f"{h}h{rem // 60:02d}m"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=IN_CSV)
    parser.add_argument("--embeddings", type=Path, default=IN_EMBEDDINGS)
    parser.add_argument("--output", type=Path, default=OUT_TSV)
    parser.add_argument("--threads-per-worker", type=int, default=2, help="torch threads per worker process")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"worker processes, ~{GB_PER_WORKER} GB RAM each "
                             f"(default: cores / threads-per-worker, capped by free RAM)")
    parser.add_argument("--chunk-size", type=int, default=256, help="bioprojects per task / output flush")
    parser.add_argument("--batch-size", type=int, default=8, help="texts per GLiNER forward pass")
    parser.add_argument("--max-tags", type=int, default=20, help="tags kept per bioproject")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N new bioprojects (testing)")
    parser.add_argument("--restart", action="store_true", help="discard the existing output and rebuild it")
    args = parser.parse_args()

    cores = len(os.sched_getaffinity(0))
    workers = args.workers or max(1, min(cores // args.threads_per_worker,
                                         (available_ram_gb() - 4) // GB_PER_WORKER))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.restart and args.output.exists():
        args.output.unlink()

    t0 = time.time()
    upgrade_output(args.output)
    done = done_bioprojects(args.output)
    projects = read_projects(args.input, done, args.limit)
    print(f"{len(done):,} bioprojects already tagged, {len(projects):,} to do "
          f"({time.time() - t0:.0f}s)", flush=True)
    if not projects:
        return
    vectors = read_embeddings(args.embeddings, {p[0] for p in projects})
    print(f"{len(vectors):,}/{len(projects):,} have project embeddings ({time.time() - t0:.0f}s)", flush=True)

    # Load models in spawned workers (torch + fork do not mix well). Unlike
    # multiprocessing.Pool, the executor fails fast if a worker dies (e.g. OOM)
    # instead of hanging; rerunning then resumes from the output file.
    pool = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"),
                               initializer=init_worker, initargs=(args.threads_per_worker,))
    print(f"{workers} workers x {args.threads_per_worker} threads", flush=True)

    new_file = not args.output.exists() or args.output.stat().st_size == 0
    written = n_tags = 0
    start = time.time()
    pending = deque()
    chunks = (projects[i:i + args.chunk_size] for i in range(0, len(projects), args.chunk_size))
    with open(args.output, "a", encoding="utf-8") as out:
        if new_file:
            out.write(HEADER)
        while True:
            # Keep a bounded window of chunks in flight so memory stays flat.
            while len(pending) < 2 * workers:
                chunk = next(chunks, None)
                if chunk is None:
                    break
                items = [(bp, text, org, None if bp not in vectors else vectors[bp].astype(np.float32))
                         for bp, text, org in chunk]
                pending.append(pool.submit(tag_chunk, items, args.batch_size, args.max_tags))
            if not pending:
                break
            for bioproject, tagged in pending.popleft().result():
                tagged = [(t, label) for t, label in ((clean_tag_field(t), label) for t, label in tagged) if t]
                tags = [t for t, _ in tagged]
                labels = [label for _, label in tagged]
                out.write(f"{bioproject}\t{SEP.join(tags)}\t{SEP.join(labels)}\n")
                n_tags += len(tags)
                written += 1
            out.flush()
            rate = written / (time.time() - start)
            print(f"{written:,}/{len(projects):,} bioprojects ({100 * written / len(projects):.1f}%), "
                  f"{n_tags / written:.1f} tags each, {rate:.1f}/s, "
                  f"ETA {format_eta((len(projects) - written) / rate)}", flush=True)
    pool.shutdown()
    print(f"done: tagged {written:,} new bioprojects in {args.output}", flush=True)


if __name__ == "__main__":
    main()
