"""Self-retrieval check of the deep search (backend/app/query_tags.py),
reported in docs/search.md under "Deep search".

For N random tagged projects, the project's own title and description is the
search text, and the tags chosen for it are compared with the project's own
tags: a chosen tag counts as right only when the project has it (after the
same normalisation), so a synonym or another spelling of a right tag counts
as wrong. A project is "kept" when it has every chosen tag, that is, when a
deep search with its own description would still find it.

Needs the database and the embedding model; run from backend/ (a few
minutes for 300 projects):

    .venv/bin/python -m tests.evaluate_query_tags [N]
"""

import json
import statistics
import sys
import time

from sqlalchemy import text

from app import query_tags as qt
from app.database import SessionLocal, engine
from app.search import SiteSearchFilters


def sample(n: int) -> list:
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT b.bioproject, b.title, b.description, g.tags
            FROM bioproject_tags g
            JOIN (SELECT DISTINCT ON (bioproject) bioproject, title, description FROM bioprojects) b USING (bioproject)
            WHERE g.tags <> '' AND coalesce(b.description, '') <> ''
              AND g.bioproject IN (SELECT bioproject FROM bioproject_tags TABLESAMPLE SYSTEM (2) WHERE tags <> '')
            LIMIT :n
        """), {"n": n}).all()


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rows = sample(n)
    qt.vectors_of(["warm"])  # load the model before timing
    chosen = right = kept = with_tags = 0
    times = []
    for bioproject, title, description, tags in rows:
        q = ". ".join(p for p in (title or "", description or "") if p)[:1000]
        own = {qt.normalise(t) for t in tags.split("; ")}
        with SessionLocal() as db:
            started = time.perf_counter()
            selected = qt.query_tags(db, SiteSearchFilters(q=q))["selected"]
            times.append(time.perf_counter() - started)
        hits = sum(1 for t in selected if qt.normalise(t) in own)
        chosen += len(selected)
        right += hits
        if selected:
            with_tags += 1
            kept += hits == len(selected)
        print(f"{bioproject}: {selected} ({hits}/{len(selected)} own) {times[-1]:.2f}s", flush=True)
    times.sort()
    print(json.dumps({
        "projects": len(rows),
        "with_chosen_tags": with_tags,
        "tags_per_project": round(chosen / max(len(rows), 1), 2),
        "chosen_tags_among_own": round(right / max(chosen, 1), 3),
        "projects_kept_by_all_chosen_tags": round(kept / max(with_tags, 1), 3),
        "median_seconds": round(statistics.median(times), 2),
        "p90_seconds": round(times[int(0.9 * len(times)) - 1], 2),
    }, indent=1))


if __name__ == "__main__":
    main()
