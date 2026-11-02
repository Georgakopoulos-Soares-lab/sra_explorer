# BioProject sample attributes from `jattr`

Every run in `sra_metadata_all.tsv` carries a `jattr` column: a JSON object with the free-form attributes the submitter attached to the sample, experiment and run (`tissue_sam`, `sex_calc`, `chip_antibody_exp`, ...). There are about 99,000 distinct keys across 42.5 million runs, most of them used by a handful of submitters, and the same information is filed under many different names.

Two scripts turn this into a small, consistent record per BioProject:

| File | Purpose |
| --- | --- |
| `Automations/jattr_key_counts.py` | Survey: how many runs use each `jattr` key. Run it to decide what is worth keeping. |
| `Automations/jattr_normalize.py` | The pipeline: picks the useful keys, merges synonyms, cleans values, aggregates per BioProject. |
| `Automations/output/jattr_key_counts.tsv` | Survey output, one row per raw key |
| `Automations/output/jattr_key_counts_normalized.tsv` | Survey output with SRA suffixes stripped (`tissue_sam_ss_dpl145` and `tissue_run` count as `tissue`) |
| `Automations/output/bioproject_attributes.tsv` | **Pipeline output**: one row per BioProject |
| `Automations/output/bioproject_attributes_coverage.tsv` | How many runs and BioProjects have a value for each field |
| `Automations/output/bioproject_attributes_schema.sql` | Creates the `bioproject_attributes` table and loads the pipeline output into it ([below](#loading-into-the-database)) |

## Output

`bioproject_attributes.tsv` is tab-separated with a header row and two columns:

| Column | Example |
| --- | --- |
| `bioproject` | `PRJDB10518` |
| `attributes` | `{"n_runs": 2, "organism": ["Mus musculus"], "cell_type": ["Lymphocyte"], "tissue": ["thymus"], "genotype_or_strain": ["CNS3KO", "C57BL/6"], "assay_type": ["ATAC-seq", "Hi-C"], "molecular_target": ["H3K27ac"], "sex": ["male"], "age": ["8"]}` |

A BioProject usually contains many samples, so each field holds a **list of distinct values, most frequent first**, at most 10 per field. A field that has no value in any run of the project is omitted. `n_runs` is the number of runs in the project. Runs with an empty `bioproject` column (about 1.3%) are skipped.

The fields:

| Field | Source keys in `jattr` (priority order, suffixes stripped) |
| --- | --- |
| `organism` | the top-level `organism` column |
| `host` | `host`, `host_scientific_name`, `host_common_name` |
| `cell_line` | `cell_line` |
| `cell_type` | `cell_type` |
| `tissue` | `tissue`, `organism_part`, `tissue_type`, `body_site`, `host_tissue_sampled`, `host_body_site` |
| `source_name` | `source_name` (GEO's free-text sample description) |
| `genotype_or_strain` | `genotype`, `strain`, `cultivar`, `breed`, `ecotype`, `genetic_background`, `variety`, `host_genotype` |
| `treatment_or_growth_condition` | `treatment`, `growth_condition`, `growth_protocol`, `condition`, `stimulus`, `compound`, `agent`, `treatment_protocol` |
| `disease_state` | `disease`, `disease_state`, `disease_status`, `diagnosis`, `host_disease`, `host_health_state`, `health_state`, `host_disease_stat`, `health_status`, `clinical_status` |
| `assay_type` | the top-level `assay_type` column |
| `molecular_target` | `chip_antibody`, `antibody`, `chip_target`, `antibody_target`, `histone_mark`, `target`, `ip_antibody`, `chip_antibody_target` |
| `sex` | `sex`, `host_sex`, `gender`, `host_gender` |
| `developmental_stage` | `dev_stage`, `developmental_stage`, `development_stage`, `host_life_stage`, `life_stage`, `host_dev_stage`, `age_group`, `host_age_group` |
| `age` | `age`, `host_age` |

The `host_*` keys describe the host of a pathogen or microbiome sample. They are merged into the same fields because, for those projects, the host is what a user searching for "human, blood, female" is after. `host` itself is kept as a separate field so the two can be told apart.

## Methodology

### 1. Survey the keys

`jattr_key_counts.py` reads the whole file once and counts, for every key, the number of runs it appears in. It also writes a second table where SRA's source suffixes are stripped, so that variants of one attribute are counted together:

- `_sam`, `_exp`, `_run`, `_calc`, `_study` say where the attribute came from (sample, experiment, run, computed).
- `_ss_dplNN` and `_s_dplNN` are de-duplication suffixes SRA adds when the same name occurs several times.

On the May 2026 file: 42.5 million runs, 99,295 raw keys, 95,582 after stripping. Only 145 keys occur in at least 1% of runs and 579 in at least 0.1%. The long tail is ignored.

### 2. Choose fields and synonyms

A field is kept when its combined sources cover a meaningful share of runs: everything above is at or over 5% of runs, except `molecular_target` (about 1%), which is kept because it is the only way to tell ChIP-seq experiments apart. Within a field, synonyms are listed in priority order, with the most common and most specific key first. When one run has several of them, the first non-empty one wins. Keys that looked tempting but were left out:

- `isolate` (34% of runs): almost always a per-sample identifier, not a strain name.
- `collection_date`, `lat_lon`, `geo_loc_name`, `isolation_source`, `env_*`: location and environment, not sample biology. Country is already a top-level column.
- `phenotype` (1%): too heterogeneous to merge with `disease_state`.

The coverage of each field is written to `bioproject_attributes_coverage.tsv` after every run, so the choice can be revisited when the data changes. On the May 2026 file (42.5 million runs, 669,697 BioProjects):

| Field | Runs with a value | BioProjects with a value |
| --- | --- | --- |
| `organism` | 98.6% | 100.0% |
| `assay_type` | 91.8% | 91.4% |
| `host` | 36.0% | 15.7% |
| `tissue` | 28.6% | 35.4% |
| `sex` | 25.1% | 13.0% |
| `genotype_or_strain` | 23.2% | 49.1% |
| `age` | 18.6% | 14.1% |
| `source_name` | 17.1% | 23.1% |
| `disease_state` | 13.9% | 4.6% |
| `developmental_stage` | 7.9% | 11.2% |
| `treatment_or_growth_condition` | 7.7% | 13.5% |
| `cell_type` | 7.6% | 12.6% |
| `cell_line` | 4.8% | 8.9% |
| `molecular_target` | 0.9% | 2.3% |

Run and project percentages differ because a few very large pathogen-surveillance projects (COVID-19, COG-UK) hold millions of runs. Most projects have 2 to 6 fields; the average JSON is about 180 characters.

### 3. Clean the values

- Lists (`["female"]`) are unwrapped to their first non-empty element.
- Whitespace is collapsed. Values that mean "no information" are dropped: `NA`, `N/A`, `none`, `missing`, `not collected`, `not provided`, `not applicable`, `unknown`, `restricted access`, anything starting with `missing:` and about 40 similar spellings (`NULL_VALUES` in the script).
- `sex` is mapped to `male`, `female`, `mixed`, `hermaphrodite`, `intersex`, `neuter` or `asexual`. Abbreviations (`M`, `F`), plurals and combinations (`male and female`) are handled. A bare number is dropped.
- `age` keeps the submitted text, except that `78.0`, `78 years`, `78 yo` become `78`. Values such as `P56`, `E14.5`, `3 months`, `>=50` or `adult` are kept as they are.
- `molecular_target` keeps only the part before the first comma, semicolon or bracket, so vendor and catalogue details are removed (`H3K27ac, Abcam, ab4729, Lot: ...` becomes `H3K27ac`). A leading `anti-` is removed and histone marks are written in one form (`H3K27Ac` becomes `H3K27ac`).
- Other fields are kept verbatim. The original case is preserved, but within a project spellings that differ only in case are merged and the most common spelling is shown (`Adult` and `adult` become one value).

### 4. Aggregate per BioProject

The file is split into 256 MB byte ranges handled by parallel workers. Each worker counts, per project and field, how many runs carry each value (up to 200 distinct values per project and field; beyond that new values are counted as overflow). The parent process merges the counts and writes the 10 most frequent values per field.

## Loading into the database

`Automations/output/bioproject_attributes_schema.sql` drops and recreates the `bioproject_attributes` table and loads `bioproject_attributes.tsv` into it. Update the `\copy` path in it for your machine first, then:

```bash
psql -d <db> -f Automations/output/bioproject_attributes_schema.sql
# or, into the development container (copy the TSV into it first):
docker cp Automations/output/bioproject_attributes.tsv sra_explorer_dev:/tmp/
docker exec -i sra_explorer_dev psql -U postgres -d postgres < Automations/output/bioproject_attributes_schema.sql
```

```sql
CREATE TABLE bioproject_attributes (
    bioproject  TEXT NOT NULL,   -- PRIMARY KEY, join to bioprojects ON bioproject
    attributes  JSONB NOT NULL   -- the JSON object described under Output
);
```

The JSON is loaded as CSV with a quote character that never occurs in the file (`QUOTE E'\x01'`). The default CSV quote `"` would break on the JSON's own quotes, and the text format would turn escapes such as `\"` and `\\` into other characters and so invalidate the JSON. With the unused quote character each line is split on the tab only and the JSON is stored exactly as written. This was tested with values containing quotes, backslashes, escaped tabs and newlines, and non-ASCII text.

The file also creates a GIN index (`jsonb_path_ops`) for containment queries:

```sql
-- Projects with female samples from the liver
SELECT bioproject FROM bioproject_attributes
WHERE attributes @> '{"sex": ["female"], "tissue": ["liver"]}';

-- One field's values for a project
SELECT attributes->'tissue' FROM bioproject_attributes WHERE bioproject = 'PRJDB10518';
```

Containment matches values exactly, including case, so `"tissue": ["Liver"]` and `["liver"]` are different. The file loads only the per-BioProject output; the optional per-run file (`--per-run`, about 5 GB) has no table. The backend doesn't use this table yet.

## Running it again

Both scripts read `Automations/output/sra_metadata_all.tsv` by default and need nothing but Python 3 (no packages). They are CPU-bound and use every core by default (`--workers`). On the 16-core VM the survey takes about 20 minutes and the pipeline about 25 minutes for the 98 GB file; the pipeline's main process needs about 1.5 GB of RAM, the workers much less.

After `sra_metadata_all.tsv` has been refreshed:

```bash
cd /work/11795/dgrigor/ls6/projects/sra_explorer/Automations

# 1. Optional: re-survey the keys. Look at jattr_key_counts_normalized.tsv for new
#    high-coverage keys and add them to FIELDS in jattr_normalize.py if they fit a field.
python3 jattr_key_counts.py

# 2. Rebuild bioproject_attributes.tsv (full rebuild; there is no incremental mode).
python3 jattr_normalize.py
```

Useful options:

```bash
python3 jattr_normalize.py --workers 8                     # fewer processes
python3 jattr_normalize.py --input other.tsv --out-dir d/  # another file or destination
python3 jattr_normalize.py --per-run output/run_attributes.tsv
    # also write one row per run (acc, bioproject, JSON with scalar values); about 5 GB
```

Both scripts print progress every 20 chunks and a summary at the end. The pipeline's summary lists each field's coverage; a field whose coverage drops sharply after a refresh usually means a key was renamed upstream, and `jattr_key_counts_normalized.tsv` will show the new name.

To add a new field or synonym, edit `FIELDS` in `jattr_normalize.py`: the key is the output field name, `keys` the list of source keys (without `_sam`/`_exp`/... suffixes) in priority order. Value cleaning rules live in `NULL_VALUES`, `SEX_MAP` and the `normalize_*` functions.

To test a change quickly, run on a slice of the file:

```bash
head -c 1000000000 output/sra_metadata_all.tsv | head -n -1 > /tmp/sample.tsv
python3 jattr_normalize.py --input /tmp/sample.tsv --out-dir /tmp/sample_out --per-run /tmp/sample_out/runs.tsv
```
