# How text search works

The search page's main text box accepts two kinds of input:

- **Accessions:** text made only of BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accessions is sent as the `accession` filter and matched exactly.
- **Anything else** is sent as `q` and runs a **hybrid search**: a semantic search and a full-text search, merged into one ranking.

The split happens in the frontend (`parseAccessions` in `frontend/src/search/filters.ts`). The hybrid search is `hybrid_search` in `backend/app/search.py`, behind `GET /search/bioprojects?q=...`. The public API (`/v1`) doesn't offer text search yet.

## Why hybrid

Each method misses what the other finds:

| | Semantic search | Full-text search |
| --- | --- | --- |
| Finds | Projects about the same thing in other words. For "single cell RNA-seq of mouse brain" it finds "Gene expression profile at single cell level of mice brain tissues", which full-text search misses because "mice" and "mouse" are different words to it | Projects containing the exact words, including terms the model doesn't know well: gene names, strain IDs, acronyms (BRCA1, H1N1, GenomeTrakr) |
| Misses | Exact identifiers; and it overrates very short texts, so a project titled "RNA-seq of RD1" can rank first for "single cell RNA-seq of mouse brain" | Projects that describe the topic in other words |

Merging the two puts projects found by both at the top, and keeps each method's own finds below them.

## The pipeline

```
search text ──┬─► embed with BioBERT ─► 1,000 nearest projects (HNSW index)
              │                          keep similarity ≥ 0.5 ──────────────► semantic ranks ─┐
              │                                                                                ├─► fuse (RRF) ─► filters ─► page
              └─► websearch_to_tsquery ─► 1,000 best projects containing all words (GIN index)│
                                         keep similarity ≥ 0.3 ──────────────► text ranks ─────┘
```

All of it is one SQL query (plus one for the total count), run against three database objects:

| Object | Holds | Index |
| --- | --- | --- |
| `bioproject_embeddings` | One 768-dimension vector per BioProject | HNSW, cosine distance |
| `bioproject_fulltext` (materialized view) | One `tsvector` per BioProject | GIN |
| `bioprojects` | The project records, one row per BioProject and SRA study pair | Primary key |

See [production.md](production.md) for creating them.

### 1. Semantic list

The text is embedded by `backend/app/embeddings.py` with the model that built the stored embeddings in `Automations/create_embeddings.py`: `pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb`, 512-token limit, L2-normalised output. The stored and query vectors must come from the same model with the same settings, or their similarities mean nothing; change both together.

The 1,000 nearest projects come from the HNSW index (`ORDER BY embedding <=> query LIMIT 1000`, with `hnsw.ef_search` raised to 1000 so the index returns that many). The stored embeddings embed title, name, organism and description, in that order.

Projects with a cosine similarity below `SEMANTIC_MIN_SIMILARITY` (0.5) are dropped. The rest are ranked 1, 2, 3… by similarity.

### 2. Full-text list

`bioproject_fulltext` stores each project's text as a weighted `tsvector`, built from the same fields as the embeddings:

| Field | Weight |
| --- | --- |
| `title`, `name` | A (highest) |
| `organism_name` | B |
| `description` | C |
| tag words from `bioproject_tags`, except the organism | D (lowest) |

Tags are cleaned-up forms of words already in the title and description (`mice` → `mouse`, `L. japonicus` → `Lotus japonicus`), so they mainly add matches for those forms. They get the lowest weight because only about a quarter of projects have tags so far: at a higher weight, a tagged project would outrank an untagged one with the same title just for having tags. Projects without tags keep exactly the text they had before. On six test queries every untagged project in the old top 100 was still found, and untagged projects moved a median of 0–1 places ([details](bioproject-tags.md#checks-on-the-development-data)). Once every project is tagged, the weight can be raised to B in `backend/sql/bioproject_fulltext.sql`; re-check the rankings when doing so.

The search text goes through `websearch_to_tsquery('english', ...)`. A project must contain every word, after stemming ("mutations" matches "mutation") and dropping stop words ("of", "the"). Users can also write `"quoted phrases"`, `OR`, and `-word` to exclude a word.

Matches are scored with `ts_rank_cd(document, query, 1)`. The `1` divides the score by the log of the document's length. Without it, long texts that repeat a word win (for "mouse": titles listing several mouse samples, such as "…mouse liver…, mouse embryonic stem cells, … single mouse oocytes and embryos"). With full length normalisation (`2`), bare titles like "Mouse metagenome" win. Option 1 sits between the two.

The 1,000 best-scored matches are kept. Of those, projects with a similarity below `TEXT_MIN_SIMILARITY` (0.3) are dropped: they contain the words but are mostly about something else, like a zebrafish study that also uses mouse samples (similarity 0.16 for "mouse"). The floor is checked after taking the top 1,000, on purpose: in the same step as the text match, Postgres computes the similarity for every embedding in the table first, which took 2 seconds instead of milliseconds. The remaining matches are ranked 1, 2, 3… by text score.

### 3. Fusion

The two lists are merged with **reciprocal rank fusion (RRF)**. Each project scores

```
score = 1 / (60 + semantic rank) + 1 / (60 + text rank)
```

with a list's term left out when the project isn't in that list. Ranks are used instead of the raw scores because similarity (0–1) and `ts_rank_cd` (unbounded) aren't on comparable scales. The constant 60 is the usual RRF value; it keeps one list's first place from outweighing a project that ranks well in both.

Examples:

| Project | Semantic rank | Text rank | Score |
| --- | --- | --- | --- |
| Found by both, near the top | 3 | 5 | 1/63 + 1/65 = 0.0313 |
| Top semantic match only | 1 | — | 1/61 = 0.0164 |
| Top text match only | — | 1 | 1/61 = 0.0164 |

So any project ranked reasonably in both lists outranks the first place of either one alone.

### 4. Filters, sorting and paging

The sidebar filters, including the **Tags** filter, are applied to the fused list, then results are sorted by score (`sort=relevance`, the default for text searches) or by a column the user clicks. The total count is the number of fused projects that pass the filters.

Each result carries:

| Field | Meaning | Shown as |
| --- | --- | --- |
| `similarity` | Cosine similarity between the search text and the project's embedding, 0–1 | The number in the **Match** column |
| `text_match` | Whether the project was in the full-text list | A green **Words** tag in the **Match** column |

A project with a **Words** tag and a low similarity got there through the text list; one with no tag got there through the semantic list.

### 5. Suggested tags

After the results arrive, the page asks `GET /search/tag-summary` (same parameters) for the most frequent tags among the top 2,000 results, and shows them as **Suggested** in the Tags row above the table. For a text search this reuses the same fused list (`fused_matches` in `search.py`); the search text's embedding is cached, so it isn't computed twice. See [bioproject-tags.md](bioproject-tags.md#how-search-uses-the-tags).

## Limits

- **At most about 2,000 results.** Each list holds at most 1,000 projects before filters are applied. A broad search ("mouse") with narrow filters can therefore miss matching projects that ranked below 1,000 in both lists. pgvector 0.8's iterative index scans (`hnsw.iterative_scan`) could lift this for the semantic list if it becomes a problem.
- **Short texts still score high semantically.** Projects with only a short title (and no description) get high similarities to many queries. The fusion limits the damage when the text list has good matches, but not for queries with no full-text matches.
- **All words must match** for the text list. A long, descriptive query rarely matches word for word, so its results come mostly from the semantic list, which handles that kind of query well.
- **Nonsense text** can still match short titles. "asdf qwerty" matches a project titled "ads" at 0.54 similarity. A higher threshold would also drop real results.
- **Projects without an embedding** (added after the embeddings were built) can't be found by text search at all: they aren't in the semantic list, and the text list's similarity floor needs an embedding. Rebuild the embeddings after loading new projects.

## Tuning

| Setting | Default | Raise it to | Lower it to |
| --- | --- | --- | --- |
| `SEMANTIC_MIN_SIMILARITY` (env) | 0.5 | Return fewer, more closely related semantic matches | Return more, looser matches |
| `TEXT_MIN_SIMILARITY` (env) | 0.3 | Drop more passing mentions | Keep more exact-word matches |
| `RRF_K` (`search.py`) | 60 | Weigh lower ranks almost as much as top ranks | Favour each list's top results |
| `SEMANTIC_CANDIDATES`, `TEXT_CANDIDATES` (`search.py`) | 1000 | Larger lists (semantic is capped at 1000 by `hnsw.ef_search`) | Faster queries |

The thresholds come from searches on the full development data (669,736 embeddings):

- Relevant projects scored 0.55–0.85 similarity. For "soil microbiome", the 900th result still scored 0.70 and was on topic. For "breast cancer tamoxifen resistance", results were still on topic at rank 100 (0.54) and fell to 0.46 by rank 900.
- Nonsense scored at most about 0.55 ("asdf qwerty": 0.54 against a project titled "ads"), and "hello" matched nothing.
- Exact-word matches mostly about something else scored as low as 0.16, while relevant ones mostly scored 0.4 and up ("BRCA1 mutations": 0.41–0.56). The 0.3 floor isn't perfect: for "mouse" it also drops a mouse cornea study at 0.29.

Scores depend on the query: broad, common topics score higher than specific ones. That rules out a cutoff relative to the best score, which would cut good results for "soil microbiome" (top score 1.00). Re-check the thresholds after changing the model or the embedded text.

## Performance

On the development machine (Apple M-series, 16 GB, everything warm), text searches take 0.1–0.9 seconds. Embedding the text takes about 30 ms; the rest is the database. After a restart, the first search waits for the model to load (a few seconds, plus a 440 MB download the very first time).

Most of the speed comes from the stored `tsvector`s in `bioproject_fulltext`. Before it existed, ranking matches meant rebuilding the text vector for every matching row: "mouse" matches hundreds of thousands of rows and took 10 seconds, against 0.7 seconds now.
