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

The backend connects to `postgresql+psycopg://postgres:postgres@localhost:5432/mydb` by default. To use a different database, set `DATABASE_URL` before starting. For example, to load it from `backend/.env`:

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
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/mydb` | Database connection string                  |
| `CORS_ORIGINS` | `http://localhost:5173`                                     | Comma-separated origins allowed to call the API directly |

## Production build of the frontend

```bash
cd frontend
npm run build     # outputs to frontend/dist
npm run preview   # serves the build locally
```

The `/api` proxy only exists in Vite's dev and preview servers. For a deployed build, set `VITE_API_BASE_URL` to the backend's full URL before building, and add the frontend's origin to `CORS_ORIGINS` on the backend.
