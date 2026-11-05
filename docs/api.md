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
| `GET /v1/tags/related` | Projects with given tags: how many, the tags most often found with them, their organisms and release years |
| `GET /v1/tags/overview` | Tag statistics: coverage, the most common tags, tags per project, and the pairs of tags found together |
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
- Except `tag`: repeated, a project must have **all** the tags: `?tag=liver&tag=mouse`. Add `tag_any=true` for projects with at least one of them. Only projects with tags (about a quarter so far) can match.
- Different parameters must all match.
- Run filters (`assay_type`, `platform`, `librarylayout`, `sample_country`, ...) match projects that have at least one run with all the given values.

Common parameters (`GET /v1/filters` lists all of them):

| Parameter | Example |
| --- | --- |
| `accession` | `PRJNA169753`, `SRP079428` (repeatable, any case) |
| `organism`, `supergroup`, `data_types` | `organism=Homo sapiens` |
| `cell_line`, `cell_type`, `tissue`, `sex`, `disease_state`, `genotype_or_strain`, `treatment_or_growth_condition`, `molecular_target` | `cell_line=HeLa&sex=female` (sample attributes, case-insensitive; values from `/v1/filters/{name}`; see [jattr-normalization.md](jattr-normalization.md#searching-by-sample-attributes)) |
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

### Tags

```
GET /v1/tags/related?tag=liver&tag=mouse
GET /v1/tags/related?tag=mouse&tag=Mus%20musculus&tag_any=true
```

What the projects with the given tags look like, the same numbers the website's tag explorer page (`/tags`) shows for them. `tag` is repeatable; a project must have all the tags, or at least one with `tag_any=true` (as in `/v1/projects`). At most 10 tags.

```json
{
  "tags": ["liver", "mouse"], "tag_any": false,
  "projects": 721,
  "related": [
    {"value": "Mus musculus", "count": 501, "total": 16823, "group": "organism", "organism": true},
    {"value": "hepatocyte", "count": 133, "total": 519, "group": null, "organism": false}
  ],
  "organisms": [{"value": "Mus musculus", "count": 502}],
  "organism_known": 538,
  "years": [{"year": 2010, "count": 1}, {"year": 2025, "count": 277}]
}
```

- `related`: the 30 tags most often on the matching projects, the given tags left out. `count` is how many of the matching projects have the tag and `total` how many tagged projects have it at all, so `(count / projects) / (total / tagged projects)` is the tag's lift among these projects. `group` is the tag's type when known; `organism` says whether the tag names an organism (a project's organism name or a common name such as `mouse`).
- `organisms`: the projects' organism from BioProject (10 most common), and `organism_known` how many of the projects have one.
- `years`: matching projects per release year.

`projects` counts BioProjects. `/v1/projects` with the same tags returns one result per BioProject and SRA study pair, so its `total` can be slightly higher for tags whose projects have several studies.

```
GET /v1/tags/overview
```

Everything on the tag explorer page in one JSON, computed once a week (`generated_at`): `totals` (projects, tagged projects, distinct tags, occurrences, tags per project), `frequency` (tags on at least 1, 2, 10, 100 and 1,000 projects), `top` (the 300 most common tags with counts, types and the organism flag), `types` (occurrences per tag type; empty until tag types are stored), `tags_per_project`, `coverage_by_year` (all and tagged projects per release year), `by_year` (the 20 most common tags per year) and `network` (the 80 most common tags as `nodes`, and as `edges` every pair of them found on at least 20 projects, with that count). See [bioproject-tags.md](bioproject-tags.md#the-tag-explorer-page).

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
