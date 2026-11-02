# Running SRAscout locally

The project has three parts that run side by side:

| Part     | Tech                         | Address                 |
| -------- | ---------------------------- | ----------------------- |
| Database | PostgreSQL (Docker)          | `localhost:5432`        |
| Backend  | FastAPI + SQLAlchemy         | `http://localhost:8000` |
| Frontend | React + Vite + TypeScript    | `http://localhost:5173` |

## Prerequisites

- Docker
- Python 3.9+
- Node.js 20+ and npm (`brew install node` on macOS)

## 1. Start the database

First time only, create the container:

```bash
docker run --name sra_explorer_dev \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=mydb \
  -p 5432:5432 -d postgres:latest
```

After that, start it with:

```bash
docker start sra_explorer_dev
```

## 2. Start the backend

First time only, create the virtual environment and install dependencies:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The requirements include PyTorch and sentence-transformers for semantic search, which need torch 2.6 or newer. On an Apple Silicon Mac, create the venv with a native arm64 Python (for example `/usr/bin/python3`); an Intel (x86_64) Python only gets torch 2.2, which can't load the model. Check with `.venv/bin/python -c "import platform; print(platform.machine())"`, which should print `arm64`. On a Linux server without a GPU, install the CPU build of torch first to avoid downloading CUDA: `.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu`.

The embedding model (`pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb`, about 440 MB) downloads from Hugging Face the first time the API starts and is cached in `~/.cache/huggingface`. The API loads it in the background at startup, so the first text search may wait a few seconds for it.

Run the API:

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload
```

The backend connects to `postgresql+psycopg://postgres:postgres@localhost:5432/postgres` by default. To use a different database, set `DATABASE_URL` before starting. For example, to load it from `backend/.env`:

```bash
set -a; source .env; set +a
.venv/bin/uvicorn app.main:app --reload
```

Missing tables are created automatically on startup.

Check that it's up: <http://localhost:8000/health> should return `{"status":"ok"}`. Interactive API docs are at <http://localhost:8000/docs>.

## 3. Start the frontend

First time only, install dependencies:

```bash
cd frontend
npm install
```

Run the dev server:

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173>. The home page shows database counts when the frontend can reach the backend.

In development, the frontend calls `/api/...` and Vite forwards those requests to the backend on port 8000, so no extra configuration is needed.

## Configuration (optional)

Edit `frontend/.env` to change these:

| Variable            | Default                 | Purpose                                                  |
| ------------------- | ----------------------- | -------------------------------------------------------- |
| `VITE_API_BASE_URL` | `/api`                  | Base URL the browser uses for API calls                  |
| `API_PROXY_TARGET`  | `http://localhost:8000` | Where the Vite dev server forwards `/api` requests       |

Backend environment variables:

| Variable       | Default                                                     | Purpose                                     |
| -------------- | ----------------------------------------------------------- | ------------------------------------------- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/postgres` | Database connection string                  |
| `CORS_ORIGINS` | `http://localhost:5173`                                     | Comma-separated origins allowed to call the API directly |
| `PUBLIC_API_WINDOW_SECONDS` | `5` | Public API rate limit: one request per this many seconds per IP |
| `TRUST_FORWARDED_FOR` | `false` | Set to `true` behind a reverse proxy you control, so the rate limit uses the client IP from `X-Forwarded-For` |
| `SEMANTIC_MIN_SIMILARITY` | `0.5` | Text searches leave out projects whose cosine similarity to the text is below this, unless they contain all the words |
| `TEXT_MIN_SIMILARITY` | `0.3` | Projects that contain all the words are still left out below this similarity |
| `EMBEDDING_THREADS` | `4` | CPU threads used to embed search text |

## Pages

| Page   | URL       | What it shows                                                        |
| ------ | --------- | -------------------------------------------------------------------- |
| Home   | `/`       | What the app does, database counts, how to cite, data sources        |
| Search | `/search` | Filters for projects and runs, and a results table with links to ENA and NCBI |
| Files  | `/files/<SRA study>` | A study's runs and their FASTQ download links, from ENA     |
| API    | `/docs/api` | How to use the public API, with Python examples                  |

The search page opens with the 100 most recently released BioProjects, which loads quickly. Choose filters and click **Search** to search all projects. Changes you haven't applied yet are flagged above the button. Removing a filter chip above the table applies straight away. Click a table row to see the project's description and details. Column headers sort the results.

The applied search is kept in the URL (e.g. `/search?supergroup=Bacteria&has_publications=true`), so it can be bookmarked or shared, and the back button returns to the previous search.

The text box at the top of the search page finds projects by accession: type one or more BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accessions, separated by spaces or commas, and click **Search**. They combine with any filters.

Any other text runs a hybrid search: a semantic search over the project embeddings and a full-text search for projects containing all the words, merged so projects found by both come first. Results are ordered best match first; the **Match** column shows each project's similarity, with a **Words** tag when it contains all the words. The box also accepts `"quoted phrases"`, `OR`, and `-word`. Clicking a column header sorts by that column instead. See [search.md](search.md) for how it works, its limits and tuning.

### Sequencing files (ENA)

Expanding a row on the search page shows how many runs the study has in ENA, with a **View files** button that opens the files page in a new tab. The files page lists each run with its experiment, sample, library (name, strategy, source, selection, layout), instrument, read and base counts, and its FASTQ links with sizes and MD5 checksums. Clicking a run shows its study, submission and other details. Runs can be narrowed by library strategy, source, selection, layout and instrument, or by text. **Copy links** and **Download** (link list, `wget` script, MD5 checksum file) cover the runs currently shown.

All run and file data comes from the [ENA Portal API](https://www.ebi.ac.uk/ena/portal/api/) and is requested **by the user's browser, not the backend**, because ENA limits requests per client. The code is in `frontend/src/ena/api.ts`.

ENA's file report can't be paged, so the files page loads the first 5,000 runs and offers the rest on request for studies up to 50,000 runs. For larger studies it links to ENA's full file report (TSV), which the browser downloads directly.

### Setting the DOI

When the paper is published, fill in `doi` and `citation` in `frontend/src/config.ts`. The home page then shows the DOI as a link and the citation with a copy button.

## Public API

A rate-limited public API for scripts and other tools is served under `/v1` (code in `backend/app/public_api.py`). The website's **API** page (`/docs/api`) documents it for users; [api.md](api.md) has the same in Markdown.

The rate limit is kept in the API process's memory. If you run several API workers or servers, each keeps its own count, so the effective limit multiplies. A single limit across them would need a shared store such as Redis.

## Search API

The website's search page uses these endpoints, defined in `backend/app/search.py`. They aren't rate-limited, because the page calls several at once; scripts should use the public API instead.

| Endpoint                       | Purpose                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `GET /search/latest`           | The 100 most recently released projects, shown before any search    |
| `GET /search/bioprojects`      | Filtered, sorted, paged projects with a total count. With `q`, a hybrid semantic and full-text search: results carry `similarity` and `text_match`, and sort best match first (`sort=relevance`) unless another sort is given |
| `GET /search/facets/{field}`   | Dropdown options with counts for one filter                          |
| `GET /search/suggest`          | Type-ahead matches for organism, organization, journal, run organism, sequencing center and tag. Tag matches carry their type in `group`; organism matches can be narrowed with `supergroup` |
| `GET /search/tag-summary`      | The most common tags among a search's top results, for the Suggested tags in the Tags row above the results; same parameters as `/search/bioprojects` |
| `GET /search/stats`            | Counts shown on the home page                                         |

All filter parameters are listed at <http://localhost:8000/docs>. Within one filter, several values match any of them, except `tag`, where a project must have all of them. Different filters must all match.

Dropdown and type-ahead values are cached in the API process for an hour. Empty results aren't cached, so values appear as soon as data is loaded.

### Database setup for search

After creating `study_facets` (below), fill `bioprojects.release_date` and its index. The search page needs this column: it is the Released date the table shows, sorts and filters on, and the index makes the first view load in milliseconds. Run it again after reloading `bioprojects` or `sra_metadata` (about 35 seconds):

```bash
docker exec -i sra_explorer_dev psql -U postgres -d postgres < backend/sql/release_date.sql
```

### Tags need the `bioproject_tags` table

Tag words under each result, the Tags filter and the Tags row above the results come from `bioproject_tags`, loaded with `Automations/TagWords/bioproject_tags_schema.sql`. That file drops `bioproject_fulltext`, so run `bioproject_fulltext.sql` (below) after it. Without the table the API creates it empty at startup, and the site works without tags. See [bioproject-tags.md](bioproject-tags.md).

### Sample filters need the `bioproject_attribute_values` view

The sample filters (cell line, tissue, sex, ...) read `bioproject_attribute_values`, a materialized view built from `bioproject_attributes`. Load the table with `Automations/output/bioproject_attributes_schema.sql`, then create the view (about 15 seconds):

```bash
docker exec -i sra_explorer_dev psql -U postgres -d postgres < backend/sql/bioproject_attribute_values.sql
```

Without it the sample filters' dropdowns are empty and searches using them return an error; everything else works. See [jattr-normalization.md](jattr-normalization.md#searching-by-sample-attributes).

### Text search needs the `bioproject_fulltext` view

The full-text half of the search box's text search reads from `bioproject_fulltext`, a materialized view with one row per BioProject holding its searchable text and a full-text index. Without it, text searches are semantic only.

It also holds each project's tag words, so create it after loading `bioprojects` and `bioproject_tags` (takes about a minute):

```bash
docker exec -i sra_explorer_dev psql -U postgres -d postgres < backend/sql/bioproject_fulltext.sql
```

After loading new data into `bioprojects`, or new tags into an existing `bioproject_tags` without recreating it, refresh it:

```bash
docker exec sra_explorer_dev psql -U postgres -d postgres -c "REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext"
```

Like `study_facets` below, the API detects it automatically within a minute.

For production, see [production.md](production.md): it lists every index and view the database needs, in order.

### Run filters need the `study_facets` view

Run filters (assay type, platform, sample country, and so on) read from `study_facets`, a materialized view with one row per SRA study that summarises its runs. Without it, every run filter scans the whole `sra_metadata` table, which takes one to two minutes per search on the full data.

Create it once after loading `sra_metadata` (takes a few minutes):

```bash
docker exec -i sra_explorer_dev psql -U postgres -d postgres < backend/sql/study_facets.sql
```

After loading new data into `sra_metadata`, refresh it:

```bash
docker exec sra_explorer_dev psql -U postgres -d postgres -c "REFRESH MATERIALIZED VIEW CONCURRENTLY study_facets"
```

The API detects the view automatically (it checks once a minute), so no restart is needed. Replace `-d postgres` with your database name if you use a different one.

A project matches the run filters when one of its runs has a selected value for every run filter.

The Released column, its sort and the release date filter all use `bioprojects.release_date`: the date the project's first run became public, or, failing that, the project's release date, or its submission date. NCBI's project release date alone is missing for about 90% of projects. The column is filled by `backend/sql/release_date.sql`.

## Production build of the frontend

```bash
cd frontend
npm run build     # outputs to frontend/dist
npm run preview   # serves the build locally
```

The `/api` proxy only exists in Vite's dev and preview servers. For a deployed build, set `VITE_API_BASE_URL` to the backend's full URL before building, and add the frontend's origin to `CORS_ORIGINS` on the backend.
