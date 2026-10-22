"""
Build the `bioproject_embeddings` table for semantic search (CPU, resumable).

Reads output/bioprojects.csv (written by create_tables.py), embeds the text of
name + title + description + organism_name with the sentence-transformers model
pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb, and writes
output/bioproject_embeddings.tsv with two columns:
  bioproject  e.g. PRJNA559273
  embedding   pgvector literal, e.g. [0.0123,-0.0456,...]
Load it with output/bioproject_embeddings_schema.sql.

One row per bioproject: bioprojects.csv repeats a project once per sra_study
with identical text, so only the first occurrence is embedded. Projects with
no text at all are skipped. Embeddings are L2-normalised, so cosine distance
(<=>) and inner product (<#>) rank results identically.

Resuming: input rows are processed in chunks; after each chunk is flushed to
disk a checkpoint (<output>.progress) records the input rows consumed and the
output size. If the script is killed, rerunning it truncates any half-written
chunk and continues from the last checkpoint. Use --restart to start over.

Setup (once): python3 -m venv .venv && .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && .venv/bin/pip install sentence-transformers numpy

Usage:
  python3 create_embeddings.py [--chunk-size 2048] [--batch-size 32] [--threads N]
                               [--max-seq-length 512] [--limit N] [--restart]

Run on a compute node (idev / sbatch), not a login node: it uses every core.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# torch / sentence-transformers live in the project venv (sra_explorer/.venv);
# re-launch under it when started with another interpreter.
VENV_PYTHON = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
IN_CSV = BASE_DIR / "output" / "bioprojects.csv"
OUT_TSV = BASE_DIR / "output" / "bioproject_embeddings.tsv"

MODEL_NAME = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
EMBEDDING_DIM = 768
# Order matters: when the text is truncated to max_seq_length, the end of the
# description is what gets cut, so the short, high-signal fields go first.
TEXT_COLUMNS = ["title", "name", "organism_name", "description"]

csv.field_size_limit(sys.maxsize)


def build_text(row):
    """Join the non-empty text fields into one passage."""
    parts = []
    for col in TEXT_COLUMNS:
        value = (row.get(col) or "").strip()
        if value and value not in parts:  # name often repeats title
            parts.append(value)
    return ". ".join(parts)


def to_pgvector(vec):
    return "[" + ",".join(f"{x:.6g}" for x in vec.tolist()) + "]"


# ---------------------------------------------------------------- checkpoint
def input_signature(path):
    st = path.stat()
    return {"input": str(path), "input_size": st.st_size, "input_mtime": int(st.st_mtime)}


def load_checkpoint(progress_path, signature, max_seq_length):
    if not progress_path.exists():
        return None
    state = json.loads(progress_path.read_text())
    for key, value in signature.items():
        if state.get(key) != value:
            sys.exit(f"{progress_path}: input file changed since the last run ({key}). "
                     f"Rerun with --restart.")
    if state.get("max_seq_length") != max_seq_length:
        sys.exit(f"{progress_path}: previous run used --max-seq-length "
                 f"{state.get('max_seq_length')}. Use the same value or --restart.")
    return state


def save_checkpoint(progress_path, state):
    tmp = progress_path.with_name(progress_path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, progress_path)


# ---------------------------------------------------------------- embedding
def embed_chunk(model, projects, batch_size):
    """projects: [(bioproject, text)] -> [(bioproject, pgvector string)]."""
    if not projects:
        return []
    order = sorted(range(len(projects)), key=lambda i: len(projects[i][1]))  # less padding
    vecs = model.encode([projects[i][1] for i in order], batch_size=batch_size,
                        normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False).astype(np.float32)
    assert vecs.shape[1] == EMBEDDING_DIM, vecs.shape
    out = [None] * len(projects)
    for i, vec in zip(order, vecs):
        out[i] = (projects[i][0], to_pgvector(vec))
    return out


def format_eta(seconds):
    h, rem = divmod(int(seconds), 3600)
    return f"{h}h{rem // 60:02d}m"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=IN_CSV)
    parser.add_argument("--output", type=Path, default=OUT_TSV)
    parser.add_argument("--chunk-size", type=int, default=2048, help="input rows per checkpoint")
    parser.add_argument("--batch-size", type=int, default=32, help="texts per forward pass")
    parser.add_argument("--threads", type=int, default=os.cpu_count(), help="torch CPU threads")
    parser.add_argument("--max-seq-length", type=int, default=512,
                        help="token limit per text (model default is 100; BERT max is 512)")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N rows (testing)")
    parser.add_argument("--restart", action="store_true", help="ignore any checkpoint and start over")
    args = parser.parse_args()

    progress_path = args.output.with_name(args.output.name + ".progress")
    signature = input_signature(args.input)
    state = None if args.restart else load_checkpoint(progress_path, signature, args.max_seq_length)
    if state and state.get("done"):
        print(f"{args.output} is already complete ({state['projects_written']:,} bioprojects). "
              f"Use --restart to rebuild it.")
        return

    torch.set_num_threads(args.threads)
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    model.max_seq_length = args.max_seq_length
    model.eval()
    print(f"model on cpu, {torch.get_num_threads()} threads, max_seq_length={model.max_seq_length}",
          flush=True)

    with open(args.input, newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        seen = set()  # bioprojects already embedded (or skipped for having no text)

        if state:
            rows_done = state["rows_done"]
            out = open(args.output, "r+", encoding="utf-8")
            out.truncate(state["output_bytes"])  # drop a half-written chunk, if any
            out.seek(state["output_bytes"])
            for _ in range(rows_done):
                seen.add(next(reader)["bioproject"])
            print(f"resuming after input row {rows_done:,}", flush=True)
        else:
            rows_done = 0
            out = open(args.output, "w", encoding="utf-8")
            out.write("bioproject\tembedding\n")
            state = {**signature, "max_seq_length": args.max_seq_length, "projects_written": 0}

        total = state.get("total_rows")
        if total is None:  # count once; cheap next to the embedding itself
            with open(args.input, newline="", encoding="utf-8") as f:
                total = sum(1 for _ in csv.reader(f)) - 1
            state["total_rows"] = total
        if args.limit is not None:
            total = min(total, args.limit)

        t0, rows_at_start = time.time(), rows_done
        with out:
            while rows_done < total:
                rows = []
                for row in reader:
                    rows.append(row)
                    if len(rows) >= min(args.chunk_size, total - rows_done):
                        break
                if not rows:
                    break

                projects = []
                for row in rows:
                    bioproject = row["bioproject"]
                    if bioproject in seen:
                        continue
                    seen.add(bioproject)
                    text = build_text(row)
                    if text:
                        projects.append((bioproject, text))

                for bioproject, vec in embed_chunk(model, projects, args.batch_size):
                    out.write(f"{bioproject}\t{vec}\n")
                out.flush()
                os.fsync(out.fileno())

                rows_done += len(rows)
                state.update(rows_done=rows_done, output_bytes=out.tell(),
                             projects_written=state["projects_written"] + len(projects))
                save_checkpoint(progress_path, state)

                rate = (rows_done - rows_at_start) / (time.time() - t0)
                print(f"{rows_done:,}/{total:,} input rows ({100 * rows_done / total:.1f}%), "
                      f"{state['projects_written']:,} bioprojects written, "
                      f"{rate:.1f} rows/s, ETA {format_eta((total - rows_done) / rate)}", flush=True)

    if rows_done >= state["total_rows"]:
        state["done"] = True
        save_checkpoint(progress_path, state)
        print(f"done: wrote {state['projects_written']:,} bioprojects to {args.output}", flush=True)
    else:
        print(f"stopped at row {rows_done:,} (--limit); rerun to continue", flush=True)


if __name__ == "__main__":
    main()
