# Moving to production

What the production database and backend need beyond a plain table load. The development setup is in [running.md](running.md); how search uses these objects is in [search.md](search.md).

## Database checklist

Do these steps in order on the production database. Replace `<db>` with the database name, and run the files with `psql -d <db> -f <file>` (or through `docker exec -i ... psql ... < <file>` as in running.md).

1. **Install pgvector (0.5 or newer)** before starting the API. The plain `postgres` Docker image doesn't include it; use `pgvector/pgvector:pg18` (or install the `postgresql-18-pgvector` package), then:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

   The API creates any missing tables at startup, including `bioproject_embeddings` with its `vector(768)` column, so it fails to start if the extension is missing.

2. **Load the tables** with the schema files written by the scripts in `Automations/`. Each one drops and recreates its table, loads the data, and creates the table's primary key and basic indexes (listed below). Update the `\copy` paths in them for the production machine first.

   | File | Table |
   | --- | --- |
   | `Automations/output/bioprojects_schema.sql` | `bioprojects` |
   | `Automations/output/sra_metadata_schema.sql` | `sra_metadata` |
   | `Automations/output/bioproject_embeddings_schema.sql` | `bioproject_embeddings` |

3. **Create the search objects**, after the tables are loaded:

   | File | Creates | Time on the full data |
   | --- | --- | --- |
   | `backend/sql/search_indexes.sql` | `bioprojects_release_date_idx` | seconds |
   | `backend/sql/study_facets.sql` | `study_facets` view and its indexes | a few minutes |
   | `backend/sql/bioproject_fulltext.sql` | `bioproject_fulltext` view and its indexes | about a minute |

4. **Run `ANALYZE`** so the planner has statistics (`bioproject_fulltext.sql` already analyzes its view):

   ```sql
   ANALYZE bioprojects; ANALYZE sra_metadata; ANALYZE bioproject_embeddings; ANALYZE study_facets;
   ```

5. **Check** that everything in the [index reference](#index-reference) exists:

   ```sql
   SELECT tablename, indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
   FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2;

   SELECT matviewname FROM pg_matviews;  -- study_facets, bioproject_fulltext
   ```

The API checks once a minute whether `study_facets` and `bioproject_fulltext` exist, so they can be created while it runs. Without them it still works, but more slowly or with less: see the last column below.

## Index reference

Sizes are from the development database (670,720 bioproject rows, 669,736 embeddings).

### Created when the tables are loaded (step 2)

| Index | On | Used by | Size |
| --- | --- | --- | --- |
| `bioprojects_pkey` | `bioprojects (bioproject, sra_study)` | Lookups by accession | 26 MB |
| `bioprojects_sra_study_idx` | `bioprojects (sra_study)` | Accession search, joins to runs | 30 MB |
| `bioprojects_tax_id_idx` | `bioprojects (tax_id)` | `/bioprojects?tax_id=` | 7 MB |
| `sra_metadata_pkey` | `sra_metadata (acc)` | `/runs/{acc}` | 1.3 GB |
| `sra_metadata_*_idx` | `sra_metadata` `experiment`, `sra_study`, `bioproject`, `biosample`, `organism` | `/runs` filters; run filters when `study_facets` is missing | 0.3–1.2 GB each |
| `bioproject_embeddings_pkey` | `bioproject_embeddings (bioproject)` | Joining embeddings to projects | 18 MB |
| `bioproject_embeddings_embedding_idx` | `bioproject_embeddings` HNSW (`vector_cosine_ops`) | Semantic search: the nearest projects to the search text | 2.3 GB |

### Created for search (step 3)

| Object | Defined in | Used by | Without it |
| --- | --- | --- | --- |
| `bioprojects_release_date_idx` | `search_indexes.sql` | The search page's first view (latest projects) | The first view scans the whole table |
| `study_facets` view + 11 indexes | `study_facets.sql` | Run filters (assay type, platform, sample country, …) and their dropdown values | Each run filter scans `sra_metadata`: one to two minutes per search |
| `bioproject_fulltext` view | `bioproject_fulltext.sql` | Full-text half of the hybrid text search | Text searches are semantic only |
| `bioproject_fulltext_document_idx` (GIN) | `bioproject_fulltext.sql` | Finding projects that contain the search words (142 MB) | — |
| `bioproject_fulltext_bioproject_idx` (unique) | `bioproject_fulltext.sql` | `REFRESH ... CONCURRENTLY` (20 MB) | The view can't be refreshed without locking it |

Don't create a full-text index directly on `bioprojects`: search reads the stored text from `bioproject_fulltext`, and an expression index on `bioprojects` would only add 145 MB that nothing uses.

## Reloading data

The schema files drop and recreate their tables. Postgres won't drop a table that a view is built on, so drop the view first, then recreate it after the load. Recreating the table also removes its indexes, which the schema file adds back except for the search ones.

| To reload | Before | After |
| --- | --- | --- |
| `bioprojects` | `DROP MATERIALIZED VIEW IF EXISTS bioproject_fulltext;` | Run `search_indexes.sql` and `bioproject_fulltext.sql` |
| `sra_metadata` | `DROP MATERIALIZED VIEW IF EXISTS study_facets;` | Run `study_facets.sql` |
| `bioproject_embeddings` | Nothing | Nothing: the schema file recreates the HNSW index |

Rebuild the embeddings (`Automations/create_embeddings.py`) whenever `bioprojects` gets new projects or changed text; projects without an embedding can only be found through full-text search.

When only the data changed and the tables weren't dropped, refresh the views instead of recreating them:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY study_facets;
REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext;
```

## Database sizing

- **Memory:** semantic search is fast only when the HNSW index (2.3 GB) stays in memory. Give Postgres enough RAM for it plus the GIN index, and set `shared_buffers` and `effective_cache_size` to match (for example 4 GB and 12 GB on a 16 GB machine).
- **Building the HNSW index:** it builds much faster when it fits in `maintenance_work_mem`. The embeddings schema file sets it to 4 GB for the build; lower it on a smaller machine.
- **`hnsw.ef_search`:** the API sets this to 1000 for each text search itself (`SET LOCAL`), so no server setting is needed.

## Backend

- **Python and torch:** the backend needs torch 2.6 or newer to load the embedding model. On a Linux server without a GPU, install the CPU build of torch before the requirements, to avoid downloading CUDA:

  ```bash
  .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
  .venv/bin/pip install -r requirements.txt
  ```

- **Embedding model:** `pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb` (about 440 MB) downloads from Hugging Face on first start, into `~/.cache/huggingface` (or `HF_HOME`). On a server without internet access, copy that cache over, or download it once at build time. Each API worker process loads its own copy of the model: about 450 MB per worker measured in development, so plan for 1 GB per worker. The first text search after a restart may wait a few seconds while the model loads.
- **Search settings** (environment variables, see [running.md](running.md#configuration-optional)): `SEMANTIC_MIN_SIMILARITY` (0.5), `TEXT_MIN_SIMILARITY` (0.3), `EMBEDDING_THREADS` (4). The defaults are tuned on the full data; see [search.md](search.md#tuning).
- **Other settings:** set `DATABASE_URL`, `CORS_ORIGINS`, and `TRUST_FORWARDED_FOR=true` behind a reverse proxy.
