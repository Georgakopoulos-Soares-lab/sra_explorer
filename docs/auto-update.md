# The weekly update

Every Sunday at 02:00 the production host brings the database up to date on its own: it downloads the newest SRA metadata snapshot and NCBI's `bioproject.xml`, inserts the new runs and projects, recomputes the sample attributes, refreshes the views, embeds and tags the new projects and restarts the API. It only ever **inserts and updates** rows; nothing is deleted from the data tables.

The pipeline is `Automations/Auto_update/update.py`, run by a systemd timer. [production.md](production.md) describes the objects it maintains; [deployment.md](deployment.md) the host it runs on.

| What | Where |
| --- | --- |
| The pipeline | `Automations/Auto_update/update.py`, one module per step in `Automations/Auto_update/steps/` |
| Shared paths, settings, helpers | `Automations/Auto_update/common.py` |
| Its Python environment | `Automations/Auto_update/.venv` (Python 3.14: pyarrow, lxml, boto3, psycopg, numpy; no torch) |
| Timer and service | `Automations/Auto_update/systemd/srascout-update.timer`, `srascout-update.service`, installed in `/etc/systemd/system` |
| Setup on a new machine | `bash Automations/Auto_update/install.sh` (venvs, folders, units; safe to rerun) |
| Downloads, outputs, work files, state, logs | `Automations/Auto_update/data/`, `work/`, `state/`, `logs/` (all gitignored; see [Folders](#folders-and-state)) |
| `bioproject.xml` download | `Automations/ENA/get_ENA_xml.sh`, into `Automations/ENA/` |

## What runs when

The timer starts `srascout-update.service` every Sunday at 02:00 local time (plus up to 15 minutes of random delay). If the machine was off at that time, the run starts as soon as it is back up (`Persistent=true`). The service runs `update.py` with no arguments, which is all eight steps in this order:

| Step | Reads | Changes | Typical time |
| --- | --- | --- | --- |
| [`download`](#download) | S3 bucket `sra-pub-metadata-us-east-1`, NCBI FTP | Files only: `data/sra_metadata/<snapshot>/*.parquet`, `Automations/ENA/bioproject.xml` | 1–2 hours at this host's bandwidth (13 GB + 4 GB); minutes when nothing changed |
| [`runs`](#runs) | the parquet snapshot, `sra_metadata` | `sra_metadata`: inserts | one pass over the 13 GB snapshot |
| [`attributes`](#attributes) | the snapshot's `jattr` column | `bioproject_attributes`: inserts and updates; `bioproject_attributes_coverage`: its 14 rows | 30–60 minutes |
| [`projects`](#projects) | `sra_metadata`, `bioproject.xml`, `bioprojects` | `bioprojects`: inserts and updates | one pass over the 4 GB XML |
| [`refresh`](#refresh) | the rules in `value_normalizations` | renamed values, the three materialized views, `bioprojects.release_date` | minutes |
| [`embeddings`](#embeddings) | `bioprojects`, `bioproject_embeddings` | `bioproject_embeddings`: inserts and updates | 10–20 projects/s on 4 threads |
| [`tags`](#tags) | `bioprojects`, `bioproject_embeddings`, `bioproject_tags` | `bioproject_tags`: inserts and updates | 5–8 projects/s with 2 workers |
| [`finish`](#finish) | — | `bioproject_fulltext` refreshed, API restarted, old snapshots removed | a minute |

A normal week (100–300k new runs, a few thousand new projects) takes a few hours, most of it downloading. The [first run](#the-first-run) is longer.

The pipeline runs at `nice 10` with best-effort I/O priority, so the website and Postgres, which share the machine, keep priority. One connection setting is raised per session (`work_mem` 256 MB, `maintenance_work_mem` 1 GB); the Postgres container itself is never changed or restarted.

## The steps

Each step is a module in `steps/` with a `run(ctx)` function that returns the counts printed in the log and saved in `state/last_run.json`. Every step is idempotent: running it again on the same input finds nothing new and changes nothing, so a failed run is resumed by rerunning from the failed step ([Resuming](#resuming-a-failed-run)).

### `download`

1. **The SRA snapshot.** The bucket holds a full daily copy of SRA's run metadata as about 30 parquet objects (13 GB, ~44.6 million rows), all named after the snapshot date (`20261104_...`). The step downloads the objects whose local file is missing or has another size, six at a time (one stream alone gets only a few MB/s here; parallel files add up), each to `<name>.parquet.part` and then renamed, with three attempts per file. When every file has the listed size it writes the `COMPLETE` marker (the object list, sizes and a timestamp) into the snapshot folder. A folder with a matching marker is skipped ("already complete"). If the bucket can't be listed but a complete snapshot exists locally, the run continues with that one and logs a warning.
2. **`bioproject.xml`** (4.2 GB) through `Automations/ENA/get_ENA_xml.sh`, which uses `wget -N`: an unchanged file is not downloaded again. A partial file is never resumed: NCBI rewrites the dump every day, and resuming could join the halves of two different dumps into a file that still looks complete, so the script deletes any file that doesn't end with `</PackageSet>` and fetches the dump whole again (`wget` retries a dropped connection within the run). The file must end up over 1 GB and end with `</PackageSet>`; if the download fails but the previous complete file is still there, the run continues with it.

Result: `snapshot`, `parquet_files`, `downloaded`, `xml_bytes`, `xml_mtime`.

### `runs`

New SRA runs into `sra_metadata`. The snapshot has no usable "modified since" column, so the step reads the whole snapshot each week and keeps the rows whose `acc` is not in the table:

1. All accessions already in the table (42.5 million) are read once with `COPY` into a sorted array (about 0.5 GB). Only values shaped like a run accession (`SRR`/`ERR`/`DRR` + digits) count, on both sides: the table holds a few garbage rows from the original TSV load, and the snapshot has rows without an accession.
2. The parquet files are streamed 200,000 rows at a time, reading only the table's 17 columns. Rows with an unseen accession are cleaned like the original load (tabs and newlines become spaces; `releasedate` stays a date) and copied into an unlogged staging table.
3. `INSERT INTO sra_metadata ... ON CONFLICT (acc) DO NOTHING` moves them over, in one transaction with the staging table's drop. The primary key is what rules out duplicates, so the lookup only keeps the staging table small.

Rows already in the table are never changed ([Limitations](#limitations)). Result: `snapshot`, `files`, `rows_read`, `new_runs`, `inserted`.

### `attributes`

`bioproject_attributes` (the sample filters: tissue, sex, cell line, ...) and `bioproject_attributes_coverage` (the home page's "samples with a tissue recorded" counts), recomputed from the snapshot's `jattr` column. A project's record changes whenever a run is added to it, so the step rebuilds every project rather than patching the new runs in. It is the same computation as `Automations/jattr_normalize.py` ([jattr-normalization.md](jattr-normalization.md)), importing that script's field list and cleaning functions, but reading the parquet files instead of the TSV export: one worker process per parquet row group, four at a time, merged in a fixed order so the output doesn't depend on which worker finished first.

It writes `data/output/bioproject_attributes.tsv` and `bioproject_attributes_coverage.tsv` in the format the schema files in `Automations/output/` load, then upserts them. Before the comparison, the rules recorded on the normalisation page for the sample attribute fields are applied to the staged records (the same rewrite `normalize apply` does, in the order the rules were made; a tissue rule also covers `source_name`): the pipeline rebuilds every record from the raw values, so without this the 150,000 projects the tissue rules touch would look changed every week. Then new projects are inserted, projects whose JSON changed are updated (an unchanged record is left alone, so `updated` is the real number of changes), and the 14 coverage rows are updated in place. With `--files` this step only accepts `--dry-run`: a partial snapshot would replace real records with ones built from a fraction of their runs. Result: `rows`, `parse_errors`, `rows_without_bioproject`, `projects`, `inserted`, `updated`.

### `projects`

`bioprojects` has one row per `(bioproject, sra_study)` pair in `sra_metadata`, with the project's metadata from `bioproject.xml`. The step, in one transaction:

1. Computes the pairs and experiment counts from `sra_metadata` (the same grouping `Automations/create_tables.py` did from the experiments export) and compares them with the table: new pairs, and pairs whose `n_experiments` changed.
2. Streams the XML and parses, with `create_tables.parse_package`, every project the table has or needs, so formats match the original load exactly.
3. Updates existing rows whose XML metadata differs (new publications, edited titles, projects that were missing from the XML last time), corrects `n_experiments`, and inserts the new pairs with their XML metadata when the project is in the XML (`found_in_bioproject_xml`). `release_date` of a new row stays NULL until the refresh step fills it.

Three columns are treated differently: `organism_name`, `supergroup` and `organization_country`, the ones the normalisation page renames, are only filled in when NULL and never overwritten, so a rename is not undone here. A project that disappears from the XML keeps the metadata it had.

Projects whose `title`, `name` or `description` changed are queued for re-embedding and re-tagging; projects new to the table are queued for tagging (new projects have no embedding yet, so the embeddings step finds them by itself). The queues are `state/pending_reembed.txt` and `state/pending_retag.txt`. Result: `pairs`, `new_pairs`, `new_bioprojects`, `count_updates`, `xml_packages`, `xml_matched`, `metadata_updates`, `text_changed`.

### `refresh`

Makes the loaded rows visible to the site, in this order:

1. **The normalisation rules** are applied again: `backend/.venv/bin/python -m app.normalize apply`, against the pipeline's database ([normalization.md](normalization.md#rules-and-the-weekly-data-load)). Recomputed attribute lists and new rows come in their original spelling; the rules rename them, and refresh the views whose values changed. A failure here stops the run.
2. **The materialized views** `study_facets`, `bioproject_attribute_values` and `bioproject_fulltext` are refreshed `CONCURRENTLY` (those the rules didn't just refresh), so the site keeps answering from the old contents during the rebuild.
3. **`bioprojects.release_date`** is filled with the same rule as `backend/sql/release_date.sql` (first run release from `study_facets`, else the project's release date unless it lies in the future, else the submission date), but only for rows whose value changes: new rows, and existing ones whose study gained an earlier run or whose dates were corrected in the XML. The index `bioprojects_release_date_idx` is created if missing.
4. `ANALYZE` on the tables written so far and the views.

Result: `rules_applied`, `views_refreshed`, `release_date_updates`.

### `embeddings`

`bioproject_embeddings` for every project without an embedding, plus the `pending_reembed` queue. The text (title, name, organism, description, joined as `Automations/create_embeddings.py` does) is written to `work/embed_input.csv`, and `create_embeddings.py` runs under `backend/.venv` (the venv with torch) with `--threads 4` into `work/embed_output.tsv`, checkpointing every 256 projects. Projects with no text (not in the XML) are skipped. The TSV is upserted through a staging table: an existing embedding is replaced, a missing one added, and the HNSW index picks the new vectors up as they are inserted. Only after the commit are the queue and work files removed. Result: `targets`, `missing`, `changed_text`, `embedded`, `upserted`.

### `tags`

`bioproject_tags` ([bioproject-tags.md](bioproject-tags.md)) for the `pending_retag` queue (new and text-changed projects) and then, because most of the table has never been tagged and tagging is slow, a **backfill** of up to 20,000 untagged old projects per run, newest release date first (`AUTO_UPDATE_TAG_BACKFILL`). Their text and embeddings go to `work/tag_input.csv` and `work/tag_embeddings.tsv`; `Automations/TagWords/extract_tags.py` runs under `TagWords/.venv` with 2 workers of 2 threads (about 3 GB of RAM each) into `work/tag_output.tsv`. The TSV is upserted: a changed project's tags are replaced, new ones added. A project where nothing was found gets an empty tag list, so it isn't queued again every week. Result: `pending`, `backfill`, `targets`, `tagged`, `upserted`.

### `finish`

1. `bioproject_fulltext` is refreshed once more, because tag words feed it and the tags were made after the refresh step; `bioproject_embeddings`, `bioproject_tags` and the view are `ANALYZE`d.
2. **The API is restarted** (`systemctl restart srascout-api`; `AUTO_UPDATE_RESTART_API=false` turns it off). See [How the website picks up the changes](#how-the-website-picks-up-the-changes).
3. Old snapshot folders are removed from `data/sra_metadata/`: each is 13 GB, and only the newest complete one (`AUTO_UPDATE_KEEP_SNAPSHOTS`) and the one this run used are kept. Leftover `.part` files of kept snapshots go too; an incomplete folder newer than the kept ones stays, since the next run resumes it.

Result: `views_refreshed`, `api_restarted`, `snapshots_removed`.

## What is never done

- **No row of a data table is deleted**, ever: not a run that left SRA, not a project that left the XML, not an embedding, tag or attribute record. Every write is `INSERT ... ON CONFLICT DO NOTHING` or an `UPDATE` of rows whose value differs. Staging tables (`auto_update_*_staging`, unlogged) are created and dropped inside each step's transaction.
- **No table is dropped or recreated**, so the search indexes, views and `release_date` column survive; nothing from [production.md's reload instructions](production.md#reloading-data) is needed after a run.
- **`value_normalizations` is never touched**, and the three renamed `bioprojects` columns are never overwritten.
- **Existing runs are not updated** (see [Limitations](#limitations)).
- **The Postgres container** is never restarted or reconfigured. The only process restarted is `srascout-api`, at the end.

## Folders and state

All under `Automations/Auto_update/` and gitignored:

| Folder | Holds | Cleaned up |
| --- | --- | --- |
| `data/sra_metadata/<snapshot>/` | the snapshot's parquet files and its `COMPLETE` marker | by the finish step (older snapshots) |
| `data/output/` | `bioproject_attributes.tsv`, `bioproject_attributes_coverage.tsv` of the last attributes step | overwritten each run |
| `work/` | `embed_input.csv`, `embed_output.tsv` (+ `.progress`), `tag_input.csv`, `tag_embeddings.tsv`, `tag_output.tsv` | by the step, after its upsert is committed; files of an interrupted run stay so it can resume |
| `state/` | `pending_reembed.txt`, `pending_retag.txt` (one accession per line, written by the projects step, removed by the step that consumed them), `last_run.json`, `update.lock` | — |
| `logs/` | `update-<run id>.log`, one per run; the same lines go to journald under systemd | not cleaned; delete old ones by hand |

`state/last_run.json` is rewritten after every step: `run_id`, `started`, `finished`, `status` (`running`, `ok`, `failed`, `interrupted`), `database`, `selected` steps, each finished step's result under `steps`, `durations` in seconds, and on failure `failed_step` and `error`. It is the first thing to look at after a run.

The pending files are what lets the pipeline hand work between steps and across runs: if the embeddings or tags step fails, its queue stays on disk and the next run (or a rerun with `--from`) picks it up. Duplicates in them are harmless.

## Running by hand

Always from the pipeline's own venv. `--list` shows the steps and which are selected without running anything:

```bash
cd /root/sra_explorer/Automations/Auto_update
.venv/bin/python update.py --list
.venv/bin/python update.py --dry-run          # compute everything, write nothing (no downloads either)
.venv/bin/python update.py                    # the whole pipeline, as the timer runs it
.venv/bin/python update.py --from embeddings  # that step and the ones after it
.venv/bin/python update.py --only refresh     # one step
```

| Option | Meaning |
| --- | --- |
| `--steps A,B` | only these steps, always run in canonical order |
| `--from STEP` | that step and all the following ones (how a failed run is resumed) |
| `--only STEP` | a single step |
| `--dry-run` | every step reads and computes, but writes nothing to the database: downloads are listed, not made; `normalize apply`, the view refreshes, the embedding and tag scripts and the API restart are skipped; the log says what would be written |
| `--limit N` | at most N new runs (runs step), new pairs (projects step), projects (embeddings and tags steps; what the queue holds beyond the limit stays queued). For testing |
| `--files N` | only the first N parquet files of the snapshot, for the runs and attributes steps (attributes then needs `--dry-run`). For testing |
| `--snapshot NAME` | use `data/sra_metadata/NAME` instead of the newest complete snapshot (the download step then keeps it even if the bucket holds a newer one) |
| `--list` | print the steps and the selection, then exit |

Exit codes: 0 ok, 1 a step failed, 2 bad arguments, 3 another run holds the lock.

A test against the test database, on one parquet file, without touching anything:

```bash
DATABASE_URL=postgresql+psycopg://postgres:...@localhost:5432/srascout_test \
  .venv/bin/python update.py --snapshot 20261104 --files 1 --limit 1000 --dry-run --steps runs,attributes
```

The service runs the same `update.py`, so a run started by hand and the timer's run are identical; the lock keeps them from overlapping.

## The timer and the service

```bash
systemctl list-timers srascout-update.timer        # next and last run
systemctl status srascout-update.service           # running? last result
journalctl -u srascout-update -f                   # follow a run
journalctl -u srascout-update --since "last sunday" # last week's run
systemctl start srascout-update.service            # run now, in the background (the full pipeline)
systemctl stop srascout-update.service             # interrupt a run; rerun with --from later
systemctl disable --now srascout-update.timer      # pause the weekly runs
```

The service is `Type=oneshot` with no timeout and no automatic retry: a failure shows in `systemctl status` and in `state/last_run.json`, and the timer runs the pipeline again the next Sunday regardless. Both unit files are in `Automations/Auto_update/systemd/`; after editing one, `bash install.sh` (or `install -m 644 ... /etc/systemd/system/ && systemctl daemon-reload`) installs it.

## Tunables

Settings come from the environment first, then `Automations/Auto_update/.env` (optional, not in git; the service reads it too), then `backend/.env`. The defaults fit this host (8 CPUs, 23 GB RAM, no GPU).

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | the backend's, from `backend/.env` | The database the pipeline writes. Set it in the environment to run against another database (tests) |
| `AUTO_UPDATE_THREADS` | 4 | CPU threads for the embedding script |
| `AUTO_UPDATE_JATTR_WORKERS` | 4 | Processes reading `jattr` in the attributes step |
| `AUTO_UPDATE_TAG_WORKERS` | 2 | GLiNER worker processes, about 3 GB of RAM each |
| `AUTO_UPDATE_TAG_THREADS` | 2 | Torch threads per GLiNER worker |
| `AUTO_UPDATE_TAG_BACKFILL` | 20000 | Untagged old projects tagged per run, besides the new and changed ones. 0 turns the backfill off |
| `AUTO_UPDATE_KEEP_SNAPSHOTS` | 1 | Complete snapshots kept on disk after a run (13 GB each) |
| `AUTO_UPDATE_RESTART_API` | true | Restart the API at the end |
| `AUTO_UPDATE_API_SERVICE` | `srascout-api` | The systemd service to restart |
| `AUTO_UPDATE_DOWNLOAD_CONCURRENCY` | 6 | Parquet files downloaded at once |
| `HF_HOME` | `/root/.cache/huggingface` | Model cache for the embedding and tag scripts (shared with the API) |

Example `Automations/Auto_update/.env`:

```
AUTO_UPDATE_TAG_BACKFILL=40000
AUTO_UPDATE_KEEP_SNAPSHOTS=2
```

## The first run

The database was loaded from a May 2026 export, so the first run catches up on half a year and is much longer than a normal week:

| Step | Expected | Time |
| --- | --- | --- |
| `download` | 13 GB of parquet, 4.2 GB of XML | 1–2 hours |
| `runs` | about 2–3 million new runs | one pass over the snapshot |
| `attributes` | every project recomputed; most records change (they gain runs) | 30–60 minutes |
| `projects` | tens of thousands of new pairs; many existing rows updated (publications, dates) | one pass over the XML |
| `embeddings` | about 84,000 projects: those without an embedding plus those whose text changed | 1–2.5 hours at 10–20 projects/s |
| `tags` | the new and changed projects, plus the 20,000 backfill | an hour and more at 5–8 projects/s |

Expect a day rather than hours. Later runs embed and tag only the week's new projects plus the backfill slice, so the untagged backlog (hundreds of thousands of projects) shrinks by 20,000 a week; raise `AUTO_UPDATE_TAG_BACKFILL` to work it off faster, at the cost of longer runs.

Before the first scheduled run it is worth a dry run of everything (`update.py --dry-run`, after a complete download exists) and reading its counts in the log.

## How the website picks up the changes

| Change | Seen by the site when |
| --- | --- |
| New runs, projects, attributes, `release_date` | the refresh step has refreshed `study_facets`, `bioproject_attribute_values` and `bioproject_fulltext`; before that, searches still answer from the old view contents (the refreshes are concurrent) |
| Renamed values (normalisation rules) | the refresh step; `normalize apply` also clears the API's cached filter values |
| New embeddings | at once: semantic search queries the table and the HNSW index directly |
| New tags | the finish step's second `bioproject_fulltext` refresh (full-text search) and the API restart (the Tags type-ahead list is built hourly) |
| Home page counts, statistics page | the API restart: both are computed at startup and cached for a week ([running.md](running.md#search-api)) |
| Dropdown and type-ahead values | within an hour (cached), or at once after the restart |

So with the default `AUTO_UPDATE_RESTART_API=true` everything is current as soon as the run finishes; the restart takes the two uvicorn workers down for a few seconds and the first text search afterwards waits for the model to load. With the restart turned off, the home page and the statistics page keep last week's numbers until the API is restarted by hand (`systemctl restart srascout-api`).

## Resuming a failed run

A failed step stops the run; the log ends with `run ... FAILED at step X; fix the cause and rerun with --from X`, and `state/last_run.json` has `status: failed`, `failed_step` and `error`. Steps before it finished and committed; the failed step's transaction rolled back. Fix the cause and:

```bash
cd /root/sra_explorer/Automations/Auto_update
.venv/bin/python update.py --from <failed step>
```

What resuming looks like per step:

| Step | After a crash |
| --- | --- |
| `download` | finished parquet files are kept, `.part` files are discarded, only the missing files are fetched; an incomplete `bioproject.xml` is deleted and downloaded again whole |
| `runs`, `attributes`, `projects` | nothing was committed; the rerun repeats the step from the start (the same input gives the same result) |
| `refresh` | repeats; every part is idempotent |
| `embeddings` | the script's checkpoint is honoured: when `work/embed_input.csv` and its progress file still cover the same targets, embedding continues where it stopped |
| `tags` | `extract_tags.py` skips the projects already in `work/tag_output.tsv` and continues |
| `finish` | repeats |

Rerunning the whole pipeline instead of `--from` is also safe, only slower: each step finds its work already done (0 new runs, 0 changed projects, "already complete" snapshot) and moves on.

## Troubleshooting

- **`another update is running (pid ...)`, exit code 3.** The lock in `state/update.lock` is held by a live process (a timer run, or one started by hand). Wait for it, or `systemctl stop srascout-update.service`. The lock is released by the kernel when the process dies, so a crashed run never leaves it stale.
- **`no complete snapshot under data/sra_metadata`** from a step other than `download`: the download didn't finish (no `COMPLETE` marker). Run `update.py --only download`, or point at a folder with `--snapshot NAME` for a test. A folder without the marker is never picked up automatically.
- **`parquet files have the wrong size after downloading`**: an object changed under the download (every object in the bucket is replaced each day, and a run that overlaps the replacement can see two days). Rerun the download step; it fetches only the files that differ.
- **`bioproject.xml is missing, smaller than 1 GB or truncated`**: the FTP download was interrupted and no previous complete file exists. Rerun `--from download`: the script deletes the incomplete file and downloads the dump again from the start (a partial file is never resumed, so two daily dumps never get mixed).
- **The tags step dies without a Python error** (a worker was killed): out of memory. Set `AUTO_UPDATE_TAG_WORKERS=1` in `.env` and rerun `--from tags`; the finished part of the output is kept.
- **`normalize apply` failed** in the refresh step: see the lines prefixed `|` in the log (the backend's own output); it fails only when a view can't be refreshed. Fix and rerun `--from refresh`.
- **Only some of the week's work is wanted**, for example tags after a config change: `--only tags`. The pending queues are consumed by the step that handles them whichever way it was started.
- **Checking a run after the fact**: `cat state/last_run.json`, then `logs/update-<run_id>.log` (`grep "result:"` for the per-step counts).

## Limitations

- **Existing runs are not updated.** The snapshot has no reliable change marker, so the runs step only adds accessions it hasn't seen. A run whose metadata NCBI later corrected keeps its old row. (Projects, attributes, embeddings and tags are updated when they change.)
- **Tags come in slices.** Only the new and changed projects plus `AUTO_UPDATE_TAG_BACKFILL` old ones are tagged per run, so the backlog from the original partial run takes many weeks to clear; the Tags filter and suggested tags see only tagged projects, as before.
- **A changed title, name or description costs a re-embedding and a re-tagging** of that project. Upstream edits are rare, but a week with many edited records makes the embeddings and tags steps longer.
- **The three normalised columns are never overwritten** (`organism_name`, `supergroup`, `organization_country`): an upstream correction of a project's organism only reaches the table when the column was NULL. Values in the other columns and in the recomputed attribute lists are renamed again by the rules each week, which is why `normalize apply` is part of every run.
- **Nothing is deleted**, by design: a run or project withdrawn from SRA stays in the database.
- **One run at a time**, on this machine only: the steps share the work files, the staging tables and the pending queues.
