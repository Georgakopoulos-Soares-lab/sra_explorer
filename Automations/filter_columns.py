"""
Create a copy of sra_metadata_all.tsv keeping only the columns listed in headers.txt.

Inputs (in Automations/output/):
  sra_metadata_all.tsv  -> full SRA metadata (~100 GB, streamed line by line)
  headers.txt           -> one column name per line; output keeps this order

Output (in Automations/output/):
  sra_metadata_filtered.tsv

Usage:
  python filter_columns.py [input.tsv] [headers.txt] [output.tsv]
"""

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_TSV = BASE_DIR / "output" / "sra_metadata_all.tsv"
HEADERS_TXT = BASE_DIR / "output" / "headers.txt"
OUTPUT_TSV = BASE_DIR / "output" / "sra_metadata_filtered.tsv"


def main():
    args = sys.argv[1:]
    input_tsv = Path(args[0]) if len(args) > 0 else INPUT_TSV
    headers_txt = Path(args[1]) if len(args) > 1 else HEADERS_TXT
    output_tsv = Path(args[2]) if len(args) > 2 else OUTPUT_TSV

    wanted = [h.strip() for h in headers_txt.read_text().splitlines() if h.strip()]

    start = time.time()
    with open(input_tsv, encoding="utf-8", errors="replace", newline="") as fin, \
         open(output_tsv, "w", encoding="utf-8", newline="") as fout:
        header = fin.readline().rstrip("\r\n").split("\t")
        missing = [h for h in wanted if h not in header]
        if missing:
            sys.exit(f"Columns not found in {input_tsv.name}: {', '.join(missing)}")
        idx = [header.index(h) for h in wanted]

        fout.write("\t".join(wanted) + "\n")
        n = 0
        for line in fin:
            fields = line.rstrip("\r\n").split("\t")
            fout.write("\t".join(fields[i] if i < len(fields) else "" for i in idx) + "\n")
            n += 1
            if n % 10_000_000 == 0:
                print(f"{n:,} rows ({time.time() - start:.0f}s)", flush=True)

    print(f"Done: {n:,} rows, {len(wanted)} columns -> {output_tsv} ({time.time() - start:.0f}s)")


if __name__ == "__main__":
    main()
