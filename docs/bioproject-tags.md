# BioProject tag words

Each BioProject gets a short list of tag words: the organisms, diseases, tissues, organs, cell types, cell lines, chemicals or drugs, and environments mentioned in its title and description. The tags make projects easier to filter and search, for example finding every project about `osteoarthritis` or `macrophage`, whatever words the submitter used.

The tags are built by `Automations/TagWords/extract_tags.py` and loaded into the `bioproject_tags` table. [How search uses the tags](#how-search-uses-the-tags) describes what the website and API do with them.

| File | Purpose |
| --- | --- |
| `Automations/TagWords/extract_tags.py` | The pipeline |
| `Automations/TagWords/run_extract_tags.slurm` | Batch job for a full run on a compute node |
| `Automations/TagWords/bioproject_tags_schema.sql` | Creates and loads the `bioproject_tags` table |
| `Automations/TagWords/requirements.txt` | Python packages for the pipeline's own virtual environment |
| `Automations/TagWords/output/bioproject_tags.tsv` | Output: one row per BioProject |

## Output

A tab-separated file with a header row and three columns:

| Column | Example |
| --- | --- |
| `bioproject` | `PRJNA1100990` |
| `tags` | `Mus musculus; osteoarthritis; synovial fibroblast; keratinocyte; skin; mouse` |
| `labels` | `organism; disease; cell type; cell type; tissue; organism` |

Tags are separated by `"; "`. `labels` gives each tag's type, in the same order as `tags`: one of the kept types in the table under [step 1](#1-entity-recognition). The first tag, copied from `organism_name`, is always `organism`. Each BioProject appears once. A project where nothing was found has an empty `tags` field (about 3% of projects). Projects average about 5 tags, with a maximum of 20.

### Tag order

- **First tag:** the project's `organism_name` from the `bioprojects` table, when the project has one (about 65% of projects). It is copied as is, so it can include a strain, for example `Staphylococcus aureus F46798`.
- **Remaining tags:** ordered by relevance to the project, most relevant first. Relevance is the similarity between the tag and the project's embedding (see step 3 below).

The order does **not** follow the tag type. The second tag is not always a disease, and the third is not always a tissue. Use `labels` for the type.

## How the tags are made

Each BioProject goes through four steps. `bioprojects.csv` repeats a project once per SRA study, so each project is processed only once.

### 1. Entity recognition

[GLiNER](https://github.com/urchade/GLiNER) (`Ihor/gliner-biomed-small-v1.0`) reads the title, name and description (the first 300 words) and marks every span that matches one of these types:

| Type | Kept as a tag |
| --- | --- |
| organism | yes |
| disease | yes |
| tissue | yes |
| organ | yes |
| cell type | yes |
| cell line | yes |
| chemical or drug | yes |
| environment or habitat | yes |
| gene or protein | no |
| geographic location | no |
| sequencing technology | no |

The last three types are recognised and then thrown away. Having them stops gene names, places and sequencers being labelled as one of the kept types.

GLiNER was chosen over scispaCy after comparing both on 300 random projects. scispaCy is faster but much noisier; it tagged `WI` (Wisconsin) as a gene and `HFD` (high-fat diet) as an organism.

### 2. Cleanup

- Whitespace, stray punctuation and leading or trailing words such as `the`, `healthy` and `control` are removed.
- Ordinary words are lowercased. Acronyms and symbols keep their case (`HeLa`, `C57BL/6J`, `CD8+ T cell`), and so do species names (`Mus musculus`, `E. coli`).
- Plurals of organisms, tissues, organs and cell types are made singular (`mice` → `mouse`, `macrophages` → `macrophage`). Latin names are left alone.
- Strain-level organism names are cut to the species: `Bacillus subtilis GXA-28` → `Bacillus subtilis`.
- Dropped entirely:
  - generic words such as `cell`, `tissue`, `patient`, `sample` and `in vitro`
  - accessions and sample IDs (`GSE206468`, `WT_mouse_1`)
  - sequencer names (`Illumina HiSeq 2500`)
  - lone modifiers (`florfenicol-induced`)
  - spans longer than 5 words
- Duplicates within a project are removed, ignoring case and plurals.

### 3. Relevance filter

Each tag is embedded with the same BioBERT model used for the project embeddings (`pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb`). It is then compared, by cosine similarity, with the project's vector in `Automations/output/bioproject_embeddings.tsv`.

- Tags with a similarity below **0.10** are dropped.
- Short acronyms of up to 5 characters, such as `OA`, `AB` or `IS`, need at least **0.25**.

This removes passing mentions and stray abbreviations, such as `humans` in a zebrafish project. A project that is not in the embeddings file keeps all its tags.

### 4. Final list

`organism_name` goes first. The remaining tags follow, sorted by similarity, and the list is cut at 20 tags.

## Running it

### Setup (once)

The pipeline has its own virtual environment, separate from the one used for embeddings:

```bash
cd Automations/TagWords
/usr/bin/python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The models download from Hugging Face on the first run.

### Order of steps

The pipeline reads `bioprojects.csv` and `bioproject_embeddings.tsv`, so run it after those are rebuilt:

1. `Automations/create_tables.py`: writes `output/bioprojects.csv`
2. `Automations/create_embeddings.py`: writes `output/bioproject_embeddings.tsv`
3. `Automations/TagWords/extract_tags.py`: writes `TagWords/output/bioproject_tags.tsv`
4. Load the table: `psql ... -f Automations/TagWords/bioproject_tags_schema.sql`

### Running in the background

Run it on a compute node (idev or sbatch), not a login node.

```bash
cd Automations/TagWords
unset OMP_NUM_THREADS
nohup python3 extract_tags.py > extract_tags.log 2>&1 &
```

The script switches to `TagWords/.venv` automatically. To follow progress:

```bash
tail -f extract_tags.log                          # everything
grep "bioprojects (" extract_tags.log | tail -1   # latest progress line only
```

A progress line looks like this:

```
40,960/669,479 bioprojects (6.1%), 5.1 tags each, 17.7/s, ETA 9h53m
```

When the run finishes, the last line starts with `done: tagged`.

As a batch job: `sbatch run_extract_tags.slurm`. Set your allocation in its `#SBATCH -A` line first.

### Updating with new BioProjects

Run the same command again. Projects already in `bioproject_tags.tsv` are skipped and only new ones are added, so an update with a few thousand new projects takes minutes.

The same mechanism resumes a run that was stopped or killed: rerun the command and it continues where it stopped.

Projects whose text has changed are **not** re-tagged. To rebuild everything, for example after changing the tag types or thresholds, add `--restart`.

### Output files from before the `labels` column

Older versions of the script wrote only `bioproject` and `tags`. When the script finds such a file, it upgrades it in place before continuing: every existing row gets an empty `labels` field, and new rows are written with labels. No tagging work is lost, and the file stays loadable. The old rows have no type until you rebuild them with `--restart` (a full run, about 10 hours on 16 cores). The website works either way: tags without a type are still shown, filtered and counted, just without their type next to them.

### Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--workers N` | cores ÷ threads, capped by free RAM | Worker processes. Each uses about 3 GB of RAM. |
| `--threads-per-worker N` | 2 | CPU threads per worker |
| `--max-tags N` | 20 | Maximum tags per project |
| `--chunk-size N` | 256 | Projects per batch; output is saved after each batch |
| `--limit N` | none | Only process the first N new projects (for testing) |
| `--restart` | off | Delete the output and rebuild it from scratch |
| `--input`, `--embeddings`, `--output` | the paths above | Use other files |

### Run time

| Machine | Setup | Speed | Full run (~670k projects) |
| --- | --- | --- | --- |
| idev VM, 16 cores, ~19 GB free RAM | 5 workers × 3 threads | ~18 projects/s | ~10 hours |
| `normal` node, 128 cores | | Several times faster (not measured) | |

The number of workers is limited by memory. If a worker runs out of memory the run stops with an error. Rerun with fewer `--workers` and it resumes.

## Database

`bioproject_tags_schema.sql` drops and recreates the table, then loads the whole TSV:

```sql
CREATE TABLE bioproject_tags (
    bioproject  TEXT NOT NULL,   -- PRIMARY KEY, join to bioprojects ON bioproject
    tags        TEXT NOT NULL,
    labels      TEXT             -- NULL for rows tagged before labels were kept
);
```

The full-text search view `bioproject_fulltext` reads this table, so the schema file drops that view first. **Run `backend/sql/bioproject_fulltext.sql` after loading the tags**, or text searches fall back to semantic only. The backend model is `BioprojectTags` in `backend/app/models.py`; `Bioproject.tags` gives a project's tags as a list.

It also creates an index for exact tag lookups:

```sql
-- Projects tagged osteoarthritis
SELECT bioproject FROM bioproject_tags
WHERE string_to_array(tags, '; ') @> ARRAY['osteoarthritis'];

-- Projects tagged both mouse and macrophage
SELECT bioproject FROM bioproject_tags
WHERE string_to_array(tags, '; ') @> ARRAY['mouse', 'macrophage'];
```

Tags are matched exactly and are case sensitive, so use the forms described in step 2 above: lowercase common words (`mouse`, `liver`) and capitalised species names (`Mus musculus`).

## How search uses the tags

Only part of the projects have tags (171,671 of 670,720 on the development data, about 26%, from a partial run). Everything below is built so that **projects without tags are searched exactly as before**: tags can add matches and narrow a search when the user asks for it, but never hide an untagged project from a search that doesn't use them.

| Feature | Where | What it does |
| --- | --- | --- |
| Tags under each title | Results table (`frontend/src/search/TagList.tsx`) | Grey chips, without the tag that repeats the organism. The first 5 show; `+N more` shows the rest. |
| Clickable tags | Results table | Clicking a chip adds it to the **Tags** filter and searches at once. Tags already in the filter are blue. |
| **Tags** filter | Filter panel; `tag` parameter of `/search/bioprojects` and `/v1/projects` | Type-ahead over all tags, with project counts and the tag's type when known. A project must have **all** chosen tags (unlike other filters, where several values match any of them), or at least one of them when the **Match any of the tags** switch (`tag_any=true`) is on, because chosen tags usually describe one project from several sides: `liver` + `mouse`. Projects without tags never match, which the panel says. |
| Tags row | Above the results, under the Filters row (`frontend/src/search/TagBar.tsx`) | The chosen tags as blue chips, each removable, with their own **Clear all** (the Filters row's **Clear all** leaves tags alone, and this one leaves filters alone). |
| Suggested tags | In the Tags row; `GET /search/tag-summary` | The 12 most frequent tags among the search's top 2,000 results (most relevant for a text search, otherwise in the chosen sort), each added with one click. Leaves out the organism, tags already chosen, and tags on only one project. Loaded after the results, so it never slows them. |
| Full-text search | `backend/sql/bioproject_fulltext.sql` | Tags are added to each project's searchable text at the lowest weight (D). See [search.md](search.md#2-full-text-list). |

### Checks on the development data

Text searches were compared before and after adding tags to the full-text text, for six queries (`osteoarthritis synovial fibroblasts`, `soil microbiome`, `BRCA1 mutations`, `mouse liver`, `hepatocellular carcinoma`, `Lotus japonicus`):

- Every untagged project in each query's old top 100 is still found (44 to 67 per query).
- Result totals stayed the same or grew slightly from new tag matches (`mouse liver` 1,222 → 1,240, `hepatocellular carcinoma` 868 → 876).
- Untagged projects moved a median of 0–1 places. For two queries a few (6 and 3) moved just below the top 100, pushed by the new matches.

Timings: the tag filter takes about 0.1 seconds per search (it uses the GIN index), the suggested tags 0.03–0.3 seconds, and building the list of 288,262 distinct tags for type-ahead about 4 seconds, once an hour, in the background at startup.

### Next step: merging synonyms

The biggest remaining improvement is mapping tags to standard vocabularies, so that different names for one thing become one tag:

| Type | Vocabulary |
| --- | --- |
| organism | NCBI Taxonomy |
| disease | MONDO or Disease Ontology |
| tissue, organ | UBERON |
| cell type | Cell Ontology |
| cell line | Cellosaurus |
| chemical or drug | ChEBI |

`mouse`, `mice` and `Mus musculus` would then be one filter value, and a vocabulary's hierarchy would let a search for `liver disease` also find `NASH`. The `labels` column is what makes this practical: each tag only needs to be looked up in the vocabulary for its type.

## Known limitations

- Tags tagged before the `labels` column have no type until rebuilt with `--restart`.
- Only about a quarter of projects have tags so far (see above).
- Some tags are still noisy, for example long phrases like `growth chamber` or `freshwater microbial`, and capitalised words taken for species names.
- The same thing can appear under different names, such as `mouse` and `Mus musculus`, or `hepatocellular carcinoma` and `HCC`. No synonyms are merged.
- Only the first 300 words of long descriptions are read.
