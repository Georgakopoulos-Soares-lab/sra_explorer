"""LLM relevance judging for Table S2, blinded to the methods, and the human validation sample.

    python llm_judge.py prepare     # one blinded input file per query  -> llm_judging/input/
    (judges write one output file per query                              -> llm_judging/output/)
    python llm_judge.py merge       # write C/D/E into Table S2, build the "Validation" sheet

Blinding: the input files hold only the query (Table S1: text, type, expected
organism and assay type) and each project's title, organism and description
(Table S2 F, G, I), in a random order per query. Column H (Found by) and
Table S3 are never exported, so the judge cannot tell which method found a project.
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKBOOK = HERE / "SRAscout_benchmark_supplementary_1.xlsx"
INPUT, OUTPUT = HERE / "llm_judging" / "input", HERE / "llm_judging" / "output"
FIRST_ROW = 4
ORDER_SEED = 2026        # shuffles each query's pairs
VALIDATION_SEED = 7
VALIDATION_N = 200


def queries(wb):
    ws = wb["Table S1"]
    return {str(ws.cell(r, 1).value).strip(): {"query": ws.cell(r, 2).value, "type": ws.cell(r, 3).value,
                                               "expected_organism": ws.cell(r, 5).value,
                                               "expected_assay_type": ws.cell(r, 6).value}
            for r in range(FIRST_ROW, ws.max_row + 1) if ws.cell(r, 1).value}


def pairs(wb):
    """Table S2 rows as dicts, without column H."""
    ws = wb["Table S2"]
    out = []
    for r in range(FIRST_ROW, ws.max_row + 1):
        qid, bp = ws.cell(r, 1).value, ws.cell(r, 2).value
        if qid and bp:
            out.append({"row": r, "query_id": str(qid).strip(), "bioproject": str(bp).strip(),
                        "title": ws.cell(r, 6).value or "", "organism": ws.cell(r, 7).value or "",
                        "description": ws.cell(r, 9).value or ""})
    return out


def cmd_prepare(args):
    import openpyxl
    wb = openpyxl.load_workbook(args.workbook)
    qs, by_query = queries(wb), defaultdict(list)
    for p in pairs(wb):
        by_query[p["query_id"]].append({k: p[k] for k in ("bioproject", "title", "organism", "description")})
    INPUT.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for qid, items in by_query.items():
        random.Random(f"{ORDER_SEED}-{qid}").shuffle(items)
        (INPUT / f"{qid}.json").write_text(json.dumps({"query_id": qid, **qs[qid], "projects": items},
                                                      indent=1, ensure_ascii=False))
    print(f"{len(by_query)} query files, {sum(map(len, by_query.values()))} pairs -> {INPUT}")


def load_outputs(by_query):
    """query_id -> {bioproject: (label, note)}; checks every pair is judged exactly once."""
    done, problems = {}, []
    for qid, expected in by_query.items():
        f = OUTPUT / f"{qid}.json"
        if not f.exists():
            problems.append(f"{qid}: no output file")
            continue
        got = {}
        for j in json.loads(f.read_text())["judgments"]:
            label, note = j.get("relevant"), (j.get("note") or "").strip()
            if label not in (0, 1):
                problems.append(f"{qid} {j.get('bioproject')}: label {label!r}")
            if label == 0 and not note:
                problems.append(f"{qid} {j.get('bioproject')}: 0 without a note")
            if len(note.split()) > 15:
                problems.append(f"{qid} {j.get('bioproject')}: note longer than 15 words")
            got[j["bioproject"]] = (label, note)
        missing, extra = set(expected) - set(got), set(got) - set(expected)
        if missing or extra:
            problems.append(f"{qid}: {len(missing)} pairs missing, {len(extra)} unknown")
        done[qid] = got
    return done, problems


def cmd_merge(args):
    import openpyxl
    wb = openpyxl.load_workbook(args.workbook)
    qs, rows = queries(wb), pairs(wb)
    by_query = defaultdict(list)
    for p in rows:
        by_query[p["query_id"]].append(p["bioproject"])
    done, problems = load_outputs(by_query)
    if problems:
        print("STOPPED: the judgments are incomplete or invalid:\n  " + "\n  ".join(problems[:40]))
        sys.exit(1)

    # Table S2: C, D, E only; saved after each query.
    ws = wb["Table S2"]
    for qid in by_query:
        for p in (p for p in rows if p["query_id"] == qid):
            label, note = done[qid][p["bioproject"]]
            ws.cell(p["row"], 3).value = label
            ws.cell(p["row"], 4).value = "LLM"
            ws.cell(p["row"], 5).value = note or None
        if not args.no_incremental_save:
            wb.save(args.workbook)
    print(f"Table S2: {len(rows)} pairs written (C = label, D = LLM, E = note)")

    # Validation sheet: 200 pairs, stratified by query type (proportional, largest remainder), seed 7.
    rng = random.Random(VALIDATION_SEED)
    strata = defaultdict(list)
    for p in rows:
        strata[qs[p["query_id"]]["type"]].append(p)
    quota = {t: VALIDATION_N * len(ps) / len(rows) for t, ps in strata.items()}
    n = {t: int(q) for t, q in quota.items()}
    for t in sorted(quota, key=lambda t: quota[t] - n[t], reverse=True)[:VALIDATION_N - sum(n.values())]:
        n[t] += 1
    sample = []
    for t in sorted(strata):
        sample += rng.sample(sorted(strata[t], key=lambda p: p["row"]), n[t])
    rng.shuffle(sample)

    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation
    if "Validation" in wb.sheetnames:
        old = wb["Validation"]
        kept = {(old.cell(r, 1).value, old.cell(r, 3).value): old.cell(r, 7).value for r in range(4, old.max_row + 1)}
        del wb["Validation"]
    else:
        kept = {}
    vs = wb.create_sheet("Validation")
    vs["A1"] = "Validation of the LLM relevance judgments"
    vs["A1"].font = Font(bold=True, size=12)
    vs["A2"] = (f"{VALIDATION_N} pairs from Table S2, drawn at random (seed {VALIDATION_SEED}), stratified by query type. "
                "Judge each with the criteria in 'Judging guide' without looking at Table S2: Human label 1 or 0.")
    headers = ["Query ID", "Query", "BioProject", "Title", "Organism", "Description", "Human label"]
    for c, (h, w) in enumerate(zip(headers, [9, 45, 14, 50, 22, 70, 12]), 1):
        vs.cell(3, c).value = h
        vs.cell(3, c).font = Font(bold=True)
        vs.column_dimensions[vs.cell(3, c).column_letter].width = w
    for i, p in enumerate(sample, FIRST_ROW):
        values = [p["query_id"], qs[p["query_id"]]["query"], p["bioproject"], p["title"], p["organism"],
                  p["description"], kept.get((p["query_id"], p["bioproject"]))]
        for c, v in enumerate(values, 1):
            vs.cell(i, c).value = v
            if c in (2, 4, 6):
                vs.cell(i, c).alignment = Alignment(wrap_text=True, vertical="top")
    dv = DataValidation(type="list", formula1='"1,0"', allow_blank=True)
    dv.add(f"G{FIRST_ROW}:G{FIRST_ROW + VALIDATION_N - 1}")
    vs.add_data_validation(dv)
    vs.freeze_panes = "A4"
    wb.save(args.workbook)
    print(f"Validation sheet: {len(sample)} pairs ({', '.join(f'{t} {n[t]}' for t in sorted(n))})")

    # Summary for checking.
    labels = {(p["query_id"], p["bioproject"]): done[p["query_id"]][p["bioproject"]][0] for p in rows}
    ones = sum(labels.values())
    print(f"\nPairs: {len(labels)}; judged 1: {ones} ({ones / len(labels):.1%})")
    by_type = defaultdict(list)
    for (qid, _), v in labels.items():
        by_type[qs[qid]["type"]].append(v)
    for t in sorted(by_type):
        print(f"  {t}: {sum(by_type[t]) / len(by_type[t]):.1%} of {len(by_type[t])} pairs are 1")
    print("Queries to check (more than 90% or fewer than 5% of pairs judged 1):")
    flagged = 0
    for qid in by_query:
        vals = [labels[(qid, bp)] for bp in by_query[qid]]
        share = sum(vals) / len(vals)
        if share > 0.9 or share < 0.05:
            flagged += 1
            print(f"  {qid} {share:.0%} of {len(vals)}: {qs[qid]['query'][:90]}")
    if not flagged:
        print("  none")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("prepare", "merge"):
        s = sub.add_parser(name)
        s.add_argument("--workbook", type=Path, default=WORKBOOK)
        if name == "merge":
            s.add_argument("--no-incremental-save", action="store_true", help="save once at the end")
    args = p.parse_args()
    {"prepare": cmd_prepare, "merge": cmd_merge}[args.command](args)


if __name__ == "__main__":
    main()
