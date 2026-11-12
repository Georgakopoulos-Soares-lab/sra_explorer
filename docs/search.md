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

The sidebar filters, including the **Tags** filter, are applied to the fused list ([filters.md](filters.md) describes them), then results are sorted by score (`sort=relevance`, the default for text searches) or by a column the user clicks. The total count is the number of fused projects that pass the filters.

Each result carries:

| Field | Meaning | Shown as |
| --- | --- | --- |
| `similarity` | Cosine similarity between the search text and the project's embedding, 0–1 | Not shown on the website |
| `text_match` | Whether the project was in the full-text list | Not shown on the website |

The search page used to show both in a **Match** column; it was removed to keep the table simple, and the results stay sorted best match first. The API still returns both: a project with `text_match` true and a low similarity got there through the text list; one with `text_match` false got there through the semantic list.

### 5. Suggested tags

After the results arrive, the page asks `GET /search/tag-summary` (same parameters) for the most frequent tags among the top 2,000 results, and shows them as **Suggested** in the Tags row above the table. For a text search this reuses the same fused list (`fused_matches` in `search.py`); the search text's embedding is cached, so it isn't computed twice. See [bioproject-tags.md](bioproject-tags.md#how-search-uses-the-tags). The [deep search](#deep-search) goes one step further and adds the tags the text itself names, before the search runs.

## Deep search

The **Deep search** switch under the search box (on by default; `guided=0` in the page URL turns it off) makes a text search more precise by adding tags to it: the tag words found in the text, matched with the tags of the search's own top results. It is the same hybrid search, with the Tags filter filled in from the text ("guided" in the code and the URL). The code is `backend/app/query_tags.py`; the page's part is in `frontend/src/pages/SearchPage.tsx`.

A deep search is two requests, which reproduce it from the command line:

```bash
# 1. Which tags does the text give, with the current filters?
curl 'http://localhost:8000/search/query-tags?q=single-cell+RNA-seq+of+human+lung+tumours'
# → "selected": ["Homo sapiens", "lung cancer"], with every tag considered and why

# 2. The ordinary search with those tags (what the page then runs).
curl 'http://localhost:8000/search/bioprojects?q=single-cell+RNA-seq+of+human+lung+tumours&tag=Homo+sapiens&tag=lung+cancer'
```

`GET /search/query-tags` takes the same parameters as `/search/bioprojects` (`q` is required; the filters are honoured, and `tag_any=true` is refused with 422, since every added tag must match). Like every search, `q` is at most `MAX_QUERY_CHARS` (4,000) characters (`search.py`; the search box stops there), enough for a long abstract: the embedding reads about the first 400 words and the tags the first 300, so a longer text adds nothing. A longer `q` is a 422 whose `detail` is a sentence (`main.py` words every validation error for people, with the usual list under `errors`). The pool query (step 2) has its own `POOL_TIMEOUT_MS` (45 s) and answers 503 past it; the page then runs the search without tags and says so. It answers in four steps:

1. **Phrases.** The text (for a DOI or PubMed ID, the paper's title and abstract) is cut into every run of 1–5 words among its first 300 words, except runs that start or end with a stop word ("of", "the", "sequencing", "data"). Phrases and tags are compared after the same normalisation: lowercase, hyphens split, possessives dropped, British spellings made American, the last word made singular with the tagging pipeline's rules. "lung tumours" becomes "lung tumor", "T-cells" "t cell", "CD4+ T cells" "cd4 t cell".
2. **Pool.** The search's top rows with the current filters, at most 2,000 (the same list the suggested tags are counted over; for a text search it is the fused candidate list, usually about 1,000 projects, see [Limits](#limits)), are read with their tags. A tag's **count** is the number of pool projects that have it; tags on fewer than 3 are ignored, since a tag the results don't share is no use as a filter however well it matches the text.
3. **Matches.** A phrase matches a pool tag when they are the same after normalisation (**exact**), when the phrase is a common organism name and the tag its species (**alias**: "human" → `Homo sapiens`, "mouse" → `Mus musculus`; 53 common names for 38 species in `ORGANISM_ALIASES`), or when they are **similar**: a BioBERT cosine similarity of at least 0.75 together with a word or head word in common ("lung tumor" → `lung cancer` at 0.83; `HEAD_WORDS` maps tumor and carcinoma to cancer, renal to kidney, hepatic to liver…), or of at least 0.85 without one; only phrases of up to 3 words are compared this way (`MAX_SIMILAR_WORDS`), longer ones match only as they are. Pairs that differ only in a qualifier never match ("type 1 diabetes" and "type 2 diabetes", "T cell" and "B cell"). A phrase that is itself a tag only matches that way; its synonyms aren't looked up ("hepatocellular carcinoma" is also 0.82 from "cholangiocarcinoma").
4. **Choice.** Each match is scored by its tag's count times the log of its **lift**, the tag's share of the pool's tagged projects divided by its share of all tagged projects, so tags the results share far more than usual come first, while a common tag the text names (`Homo sapiens`, on 10% of all tagged projects) still scores by its count. An exact match inside a longer exact match of comparable count gives way to it ("soil" to "soil microbiome"). Matches are taken best first. One is skipped when its words were already used by a taken tag ("lung" after "lung tumours" took `lung cancer`), when its tag is a spelling of a taken one or names the same organism ("silkworm" after `Bombyx mori`, `S. pombe` after `Schizosaccharomyces pombe`), and, because a project must have every chosen tag, when fewer than the **floor** (5 or 2% of the pool's tagged projects, whichever is larger) would keep all the tags taken so far. At most 4 tags are taken.

The answer lists every tag considered with the words it matched, how (and the cosine for similar matches), its count, how many pool projects keep every tag up to it, and why it was or wasn't selected; The page then applies the selected tags like tags chosen by hand: they are in the URL as `tag=`, marked with ✦ in the Tags row and listed in `auto=`, so they can be removed one by one or together, and the next text search drops them before choosing again. Filter, sort and page changes keep them.

Only projects with tags can match a tag filter (about a quarter so far, see [bioproject-tags.md](bioproject-tags.md#how-search-uses-the-tags)), so a deep search returns fewer results (the API answer says how many of the top results had no tags). When no tag word in the text is shared by the results, the search runs without tags. If `/search/query-tags` fails (the model unavailable, a 20-second statement timeout on the pool), the search still runs, as a standard one, with a warning.

### Checks on the development data

Self-retrieval over 300 random tagged projects (development data, 2026-11-11): each project's own title and description was the search text, and a chosen tag counts as right only when it is among that project's own tags, so a synonym or another spelling of a right tag counts as wrong:

| | |
| --- | --- |
| Projects for which tags were chosen | 263 of 300 (88%) |
| Tags chosen per project (mean) | 1.3 |
| Chosen tags among the project's own tags | 60% (57% before spellings are evened out) |
| Projects still found by their own description with all chosen tags | 48% of the 263 |
| Time to choose the tags (median / 90th percentile, model warm, Apple M-series) | 0.75 s / 1.5 s |

The fourth row is the recall cost of the mode: a chosen tag that a project lacks (a synonym the pipeline spelled differently, or a mention the pipeline's relevance filter dropped) hides that project, and the mode is meant for precision, not recall. `backend/tests/evaluate_query_tags.py` reruns the check (`cd backend && .venv/bin/python -m tests.evaluate_query_tags 300`); the numbers will change as more projects are tagged. The pure parts (phrases, matching, choice) are unit-tested in `backend/tests/test_query_tags.py`. Eight hand-checked queries ("single-cell RNA-seq of human lung tumours" → `Homo sapiens`, `lung cancer`; "ATAC-seq of mouse hematopoietic stem cells" → `hematopoietic stem cell`, `Mus musculus`; "soil microbiome" → `soil microbiome`; "tamoxifen resistance in breast cancer" → `breast cancer`, `tamoxifen`; "gut microbiota of patients with inflammatory bowel disease" → `gut microbiota`, `inflammatory bowel disease`; "type 2 diabetes pancreatic islets" → `type 2 diabetes`, `pancreatic islet`; "Alzheimer's disease microglia in aged mice" → `microglia`, `alzheimer's disease`, `Mus musculus`; a PubMed ID → `Homo sapiens`, `lung cancer`) chose only tags named in the text. The vectors of the 5,000 most common tags are embedded at startup and those of phrases and other tags are cached, so a new text costs the pool query plus one embedding batch: 0.1–0.5 s for a sentence, about a second for an abstract, before the search itself.

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
