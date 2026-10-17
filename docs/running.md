# Running SRA Explorer locally

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

Open <http://localhost:5173>. The header shows **API connected** when the frontend can reach the backend.

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

## Pages

| Page   | URL       | What it shows                                                        |
| ------ | --------- | -------------------------------------------------------------------- |
| Home   | `/`       | What the app does, database counts, how to cite, data sources        |
| Search | `/search` | Filters for projects and runs, and a results table with links to NCBI |

The search page opens with the 100 most recently released BioProjects, which loads quickly. Choose filters and click **Search** to search all projects. Changes you haven't applied yet are flagged above the button. Removing a filter chip above the table applies straight away. Click a table row to see the project's description and details. Column headers sort the results.

The applied search is kept in the URL (e.g. `/search?supergroup=Bacteria&has_publications=true`), so it can be bookmarked or shared, and the back button returns to the previous search.

The text box at the top of the search page is for semantic search, which isn't built yet. What you type is kept in the URL as `q` but is not sent to the backend.

### Setting the DOI

When the paper is published, fill in `doi` and `citation` in `frontend/src/config.ts`. The home page then shows the DOI as a link and the citation with a copy button.

## Search API

The search page uses these endpoints, defined in `backend/app/search.py`:

| Endpoint                       | Purpose                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `GET /search/latest`           | The 100 most recently released projects, shown before any search    |
| `GET /search/bioprojects`      | Filtered, sorted, paged projects with a total count                  |
| `GET /search/facets/{field}`   | Dropdown options with counts for one filter                          |
| `GET /search/suggest`          | Type-ahead matches for organism, organization, journal, run organism and sequencing center |
| `GET /search/stats`            | Counts shown on the home page                                         |

All filter parameters are listed at <http://localhost:8000/docs>. Within one filter, several values match any of them. Different filters must all match.

Dropdown and type-ahead values are cached in the API process for an hour. Empty results aren't cached, so values appear as soon as data is loaded.

### Database setup for search

Create the search index once, so the search page's first view loads in milliseconds:

```bash
docker exec -i sra_explorer_dev psql -U postgres -d postgres < backend/sql/search_indexes.sql
```

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

A project matches a run filter when any of its runs has a selected value. With several run filters, each can be met by a different run of the same project. The run release date filter matches projects whose runs were released within the range.

## Production build of the frontend

```bash
cd frontend
npm run build     # outputs to frontend/dist
npm run preview   # serves the build locally
```

The `/api` proxy only exists in Vite's dev and preview servers. For a deployed build, set `VITE_API_BASE_URL` to the backend's full URL before building, and add the frontend's origin to `CORS_ORIGINS` on the backend.
