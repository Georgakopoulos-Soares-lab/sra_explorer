# BioProject tag words

Each BioProject gets a short list of tag words: the organisms, diseases, tissues, organs, cell types, cell lines, chemicals or drugs, and environments mentioned in its title and description. The tags make projects easier to filter and search, for example finding every project about `osteoarthritis` or `macrophage`, whatever words the submitter used.

The tags are built by `Automations/TagWords/extract_tags.py` and loaded into the `bioproject_tags` table.

| File | Purpose |
| --- | --- |
| `Automations/TagWords/extract_tags.py` | The pipeline |
| `Automations/TagWords/run_extract_tags.slurm` | Batch job for a full run on a compute node |
| `Automations/TagWords/bioproject_tags_schema.sql` | Creates and loads the `bioproject_tags` table |
| `Automations/TagWords/requirements.txt` | Python packages for the pipeline's own virtual environment |
| `Automations/TagWords/output/bioproject_tags.tsv` | Output: one row per BioProject |

## Output

A tab-separated file with a header row and two columns:

| Column | Example |
| --- | --- |
| `bioproject` | `PRJNA1100990` |
| `tags` | `Mus musculus; osteoarthritis; synovial fibroblast; keratinocyte; skin; mouse` |

Tags are separated by `"; "`. Each BioProject appears once. A project where nothing was found has an empty `tags` field (about 3% of projects). Projects average about 5 tags, with a maximum of 20.

### Tag order

- **First tag:** the project's `organism_name` from the `bioprojects` table, when the project has one (about 65% of projects). It is copied as is, so it can include a strain, for example `Staphylococcus aureus F46798`.
- **Remaining tags:** ordered by relevance to the project, most relevant first. Relevance is the similarity between the tag and the project's embedding (see step 3 below).

The order does **not** follow the tag type. The second tag is not always a disease, and the third is not always a tissue. The type of each tag is not stored.

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
    tags        TEXT NOT NULL
);
```

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

## Known limitations

- The tag type (organism, disease and so on) is not stored, only the tag text.
- Some tags are still noisy, for example long phrases like `growth chamber` or `freshwater microbial`, and capitalised words taken for species names.
- The same thing can appear under different names, such as `mouse` and `Mus musculus`, or `hepatocellular carcinoma` and `HCC`. No synonyms are merged.
- Only the first 300 words of long descriptions are read.
