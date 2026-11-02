# SRAscout

A web application for browsing metadata from the NCBI [Sequence Read Archive (SRA)](https://www.ncbi.nlm.nih.gov/sra). It brings SRA run metadata and NCBI BioProject records into one PostgreSQL database and lets you search them through a web interface.

- **Runs:** one record per SRA run (SRR/ERR/DRR), with its experiment, sample, organism, library and sequencing-platform details.
- **BioProjects:** one record per BioProject and SRA study pair, with the project's title, description, organism, publications, grants and dates.

## Project structure

```
sra_explorer/
├── Automations/   Scripts that download SRA/BioProject metadata and build the database tables
├── backend/       FastAPI + SQLAlchemy API serving data from PostgreSQL
├── frontend/      React + TypeScript + Vite app, styled with Ant Design and Tailwind CSS
└── docs/          Project documentation
```

## Tech stack

| Layer    | Technologies                                 |
| -------- | -------------------------------------------- |
| Frontend | React, TypeScript, Vite, Ant Design, Tailwind CSS |
| Backend  | Python, FastAPI, SQLAlchemy, Pydantic        |
| Database | PostgreSQL                                   |
| Data     | Bash and Python scripts, DuckDB, Apache Parquet |

## Getting started

Requires Docker, Python 3.9+ and Node.js 20+.

```bash
# Database
docker run --name sra_explorer_dev -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=mydb -p 5432:5432 -d postgres:latest

# Backend (http://localhost:8000)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload

# Frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

See [docs/running.md](docs/running.md) for the full setup, configuration options and production build, [docs/filters.md](docs/filters.md) for how the search page's filters and search work, [docs/production.md](docs/production.md) for the database indexes and views production needs, and [docs/search.md](docs/search.md) for how the text search works.

## Data sources

The scripts in `Automations/` build the database from public NCBI and ENA data:

- SRA metadata from the public SRA metadata S3 bucket, in Apache Parquet format
- SRA metadata files from the NCBI FTP server
- BioProject records from NCBI's `bioproject.xml`
- Study metadata from the European Nucleotide Archive (ENA)

The scripts in `Automations/metadata_dl/` are numbered in the order they run.
