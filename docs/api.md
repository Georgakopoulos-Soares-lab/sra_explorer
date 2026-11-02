# SRAscout public API (v1)

Search SRAscout's BioProject and SRA study records from your own scripts and tools. The API is read-only, needs no key, and returns JSON.

Base URL: `<server>/v1`. For example, on a local setup: `http://localhost:8000/v1`.

Interactive documentation, where you can try every endpoint, is at `<server>/docs` under **Public API v1**.

## Rate limit

**1 request every 5 seconds per IP address.** A request sent sooner gets HTTP `429 Too Many Requests`, with a `Retry-After` header giving the seconds to wait:

```json
{"detail": "Rate limit exceeded: 1 request per 5 seconds. Try again in 4 s."}
```

To page through many results, use `limit=100` and wait at least 5 seconds between requests.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /v1` | API version, rate limit and endpoint list |
| `GET /v1/projects` | Search projects with filters |
| `GET /v1/projects/{accession}` | Look up a project by BioProject or SRA study accession |
| `GET /v1/filters` | Every search parameter, with a description |
| `GET /v1/filters/{name}` | The values of a list filter, with counts |
| `GET /v1/projects/semantic?q=...` | Natural-language search. **Not available yet**: returns `501` |

### Search projects

```
GET /v1/projects?supergroup=Bacteria&platform=OXFORD_NANOPORE&limit=2
```

```json
{
  "total": 3216,
  "limit": 2,
  "offset": 0,
  "results": [
    {"bioproject": "PRJDB13601", "sra_study": "DRP018874", "title": "...", "organism_name": "...", "...": "..."}
  ]
}
```

Each result is one BioProject and SRA study pair, with all its fields (title, description, organism, dates, publications, and so on).

How filters combine:

- Repeat a parameter to match any of several values: `?platform=ILLUMINA&platform=PACBIO_SMRT`.
- Except `tag`: repeated, a project must have **all** the tags: `?tag=liver&tag=mouse`. Only projects with tags (about a quarter so far) can match.
- Different parameters must all match.
- Run filters (`assay_type`, `platform`, `librarylayout`, `sample_country`, ...) match projects that have at least one run with all the given values.

Common parameters (`GET /v1/filters` lists all of them):

| Parameter | Example |
| --- | --- |
| `accession` | `PRJNA169753`, `SRP079428` (repeatable, any case) |
| `organism`, `supergroup`, `data_types` | `organism=Homo sapiens` |
| `tag` | `tag=osteoarthritis` (values from `/v1/filters/tag?q=...`; see [bioproject-tags.md](bioproject-tags.md)) |
| `assay_type`, `platform`, `librarylayout`, `sample_country` | `assay_type=RNA-Seq` |
| `release_from`, `release_to` | `release_from=2020-01-01` (the `release_date` field: first public run, else project release, else submission) |
| `min_experiments`, `max_experiments` | `min_experiments=10` |
| `has_publications`, `has_geo`, `has_grants` | `has_geo=true` |
| `sort` | `release_desc` (default), `release_asc`, `experiments_desc`, `publications_desc`, ... |
| `limit`, `offset` | `limit=100&offset=200` (limit 1–100, default 25) |

### Look up a project

```
GET /v1/projects/PRJDB16527
GET /v1/projects/SRP079428
```

Returns `{"results": [...]}`. A BioProject with several SRA studies returns one result per study. An unknown accession returns `404`.

### Filter values

```
GET /v1/filters/platform
GET /v1/filters/organism?q=homo&limit=10
```

```json
[{"value": "ILLUMINA", "count": 618963}, {"value": "PACBIO_SMRT", "count": 26339}]
```

Values come most common first. Counts are projects for project filters and studies for run filters. Use `q` to keep only values containing some text.

## Examples

curl:

```bash
curl "http://localhost:8000/v1/projects?accession=PRJNA169753"
```

Python, paging through all results while respecting the rate limit:

```python
import time
import requests

BASE = "http://localhost:8000/v1"
params = {"assay_type": "RNA-Seq", "sample_country": "Greece", "limit": 100, "offset": 0}

results = []
while True:
    r = requests.get(f"{BASE}/projects", params=params)
    if r.status_code == 429:
        time.sleep(int(r.headers.get("Retry-After", 5)))
        continue
    r.raise_for_status()
    page = r.json()
    results += page["results"]
    params["offset"] += params["limit"]
    if params["offset"] >= page["total"]:
        break
    time.sleep(5)

print(len(results), "projects")
```

## Errors

| Status | Meaning |
| --- | --- |
| `404` | No project with that accession |
| `422` | Invalid parameter (the response says which) |
| `429` | Rate limit exceeded; wait `Retry-After` seconds |
| `501` | Semantic search isn't available yet |

## Versioning

All URLs start with `/v1`. Changes that could break existing clients will go into a new version (`/v2`), and `/v1` keeps working.
