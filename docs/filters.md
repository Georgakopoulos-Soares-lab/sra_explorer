# How filtering and searching work

This page describes the search page (`/search`) as it works now: the search box, the filter panel, how filters combine and narrow each other, the rows above the results, and the results table. It also lists where each filter's data comes from and where the code is.

Related pages:

| Page | Covers |
| --- | --- |
| [search.md](search.md) | How the text search (semantic + full-text) ranks projects |
| [bioproject-tags.md](bioproject-tags.md) | How tag words are made, and the tag features |
| [jattr-normalization.md](jattr-normalization.md) | How the sample attributes (cell line, tissue, sex, ...) are extracted and cleaned |
| [api.md](api.md) | The public API, which accepts the same filters |
| [production.md](production.md) | The tables, views and indexes the filters need |

## Overview

```
┌ Search box ─────────────────────────────────────────────┐
│ accessions → exact lookup   ·   any other text → text search
└─────────────────────────────────────────────────────────┘
┌ Filter panel ───────┐   Filters  [Organism: Mus musculus ×] ...      Clear all
│ Organism, samples   │   Tags     [liver ×]  │ + hepatocyte 199 ...   Clear all
│   and sequencing    │   ┌ Results table ─────────────────────────────────────┐
│ Tags                │   │ BioProject │ Title + tags │ Organism │ ... │ Released │
│ Submitter, size and │   │  (click a row for details)                       │
│   publications      │   └──────────────────────────────────────────────────┘
│ [Search] [Reset]    │
└─────────────────────┘
```

The page opens with the 100 most recently released projects. Choosing filters or typing in the search box and clicking **Search** searches all 670,000 projects. The applied search is kept in the URL (for example `/search?organism=Mus%20musculus&tissue=liver`), so it can be bookmarked and shared, and the back button returns to the previous search.

## The search box

| What is typed | What happens |
| --- | --- |
| Only BioProject (PRJNA, PRJEB, PRJDB) or SRA study (SRP, ERP, DRP) accessions, separated by spaces or commas | Sent as the `accession` filter: an exact lookup, combined with any other filters. The accessions appear as chips in the Filters row. |
| Anything else | A text search (`q`): semantic and full-text search merged into one ranking, sorted best match first. See [search.md](search.md). |

The text search and the filters combine: the filters are applied to the text search's matches. The text search considers at most about 2,000 matches before filters, so a broad text with narrow filters can miss some projects ([search.md](search.md#limits)).

## The filter panel

Filter changes are drafts until **Search** is clicked; unapplied changes are flagged above the button. **Reset** clears everything, including the search box.

### Organism, samples and sequencing

| Filter | Parameter | Control | Data | Kind |
| --- | --- | --- | --- | --- |
| Supergroup | `supergroup` | dropdown | `bioprojects.supergroup` | project |
| Organism | `organism` | type-ahead | `bioprojects.organism_name` | project |
| Assay type | `assay_type` | dropdown | runs (`study_facets`) | run |
| Cell line | `cell_line` | type-ahead | `bioproject_attribute_values` | sample |
| Cell type | `cell_type` | type-ahead | `bioproject_attribute_values` | sample |
| Tissue | `tissue` | type-ahead | `bioproject_attribute_values` | sample |
| Sex | `sex` | dropdown | `bioproject_attribute_values` | sample |
| Disease | `disease_state` | type-ahead | `bioproject_attribute_values` | sample |
| Genotype or strain | `genotype_or_strain` | type-ahead | `bioproject_attribute_values` | sample |
| Treatment or condition | `treatment_or_growth_condition` | type-ahead | `bioproject_attribute_values` | sample |
| ChIP target | `molecular_target` | type-ahead | `bioproject_attribute_values` | sample |
| Instrument | `instrument` | dropdown | runs (`study_facets`) | run |
| Library layout | `librarylayout` | dropdown | runs (`study_facets`) | run |
| Library selection | `libraryselection` | dropdown | runs (`study_facets`) | run |
| Sequencing center | `center_name` | type-ahead | runs (`study_facets`) | run |
| Released | `release_from`, `release_to` | date range | `bioprojects.release_date` | project |

### Tags

| Filter | Parameter | Control | Data |
| --- | --- | --- | --- |
| Tag | `tag` | type-ahead, with each tag's type when known | `bioproject_tags` |
| Match any of the tags | `tag_any=true` | on/off switch, off by default | |

### Submitter, size and publications

| Filter | Parameter | Control | Data |
| --- | --- | --- | --- |
| Organization | `organization` | type-ahead | `bioprojects.organization` |
| Country | `organization_country` | dropdown | `bioprojects.organization_country` |
| Number of experiments | `min_experiments`, `max_experiments` | min / max | `bioprojects.n_experiments` |
| Has publications | `has_publications` | Any / Yes / No | `bioprojects.publication_count` |
| Journal | `journals` | type-ahead | `bioprojects.journals` |

Dropdowns load their options when opened; type-ahead boxes search as you type. Both show the number of projects for each value.

### Filters only in the API

The backend still accepts filters that were taken out of the panel, so links and scripts using them keep working: `data_types`, `objectives`, `relevance`, `target_material`, `target_capture`, `sample_scope`, `method_type`, `access`, `platform`, `librarysource`, `run_organism`, `sample_country`, `run_release_from` / `run_release_to`, `submitted_from` / `submitted_to`, `updated_from` / `updated_to`, `first_publication_from` / `first_publication_to`, `min_publications`, `has_geo` and `has_grants`. `GET /v1/filters` lists them all. The sample attributes `age`, `developmental_stage`, `host` and `source_name` have no filter at all (see [jattr-normalization.md](jattr-normalization.md#searching-by-sample-attributes)).

## How filters combine

- **Different filters must all match.** Organism *Mus musculus* + Tissue *liver* finds mouse projects with liver samples.
- **Several values in one filter match any of them.** Tissue *liver* + *blood* finds projects with either.
- **Except tags: a project must have every chosen tag**, because tags usually describe one project from several sides (`liver` + `mouse`), so adding a tag narrows the search. Turn on **Match any of the tags** to find projects with at least one of them instead: `liver` + `hepatocyte` finds 319 projects with both, or 2,918 with either. The Tags row above the results says "all of" or "any of" when two or more tags are chosen. Only projects with tags (about a quarter so far) can match a tag filter.

Each kind of filter matches at its own level:

| Kind | A project matches when | Example |
| --- | --- | --- |
| Project | the project's own field has the value | Organism, Released, Organization |
| Run | **one run** of the project has a chosen value for every run filter at once | Assay type *RNA-Seq* + Instrument *PromethION* needs an RNA-Seq run sequenced on a PromethION, not an RNA-Seq run on another instrument and a different run on a PromethION |
| Sample | the project's samples include each chosen value, **not necessarily in the same sample** | Cell line *HeLa* + Sex *female* also matches a project with a male HeLa sample and a female sample of another cell line |
| Tag | the project has all chosen tags, or any of them with **Match any of the tags** | |

Run filters check one run because run metadata is stored per run (`sra_metadata`). Sample attributes are stored summarised per project (`bioproject_attributes`), so they can't be tied to one sample; matching within a sample would need the per-run attributes loaded as a table.

Other details:

- **Sample values ignore case.** `hela`, `HeLa` and `HELA` match the same projects. The same value is often spelled with different case across projects, so each dropdown lists a value once, in its most common spelling. Values are matched whole: `HeLa` doesn't include `HeLa S3`.
- **Tissue includes GEO source names** for projects that give no tissue, when the source name is a known tissue (used as a tissue by at least 20 projects).
- **Released** is `bioprojects.release_date`: the date the project's first run became public, or else NCBI's project release date, or else the submission date. NCBI's project release date alone is missing for about 90% of projects. Both ends of the range are included. The Released column in the results shows the same date.

## Filters narrow each other

Each filter only offers values found among the projects that match the other filters chosen in the panel, with counts of those projects. For example, after choosing Organism *Mus musculus* and Tissue *liver*, Sex offers male (1,202), female (505), mixed (16) and neuter (2), instead of the counts over all projects. Choosing Supergroup *Viruses* makes Organism suggest SARS-CoV-2, Influenza A virus and HIV-1 first.

- A filter ignores its own selection, so more of its values can still be added.
- The panel's current choices count, including ones not yet applied with **Search**, and a filter reloads its options when the others change.
- The counts match what a search with that value finds.
- The text in the search box doesn't narrow the filters; only the panel's choices do.

How it works: the frontend (`contextFor` in `frontend/src/search/FilterPanel.tsx`) sends the other choices as extra parameters, the same as `/search/bioprojects` takes, to `GET /search/facets/{field}` (dropdowns) and `GET /search/suggest` (type-ahead). The backend (`narrowed_values` in `backend/app/search.py`) counts the field's values over the matching projects:

| Field kind | Values read from |
| --- | --- |
| Project fields | `bioprojects` |
| Run fields | `study_facets` |
| Sample fields | `bioproject_attribute_values` |
| Tags | `bioproject_tags` |

A narrowed list takes 0.1–1 second the first time on the development data (broad choices such as RNA-Seq, 264,000 projects, take the longest), then comes from a cache for an hour (up to 500 combinations). Without other choices, a filter shows its full list, also cached for an hour. If narrowing isn't possible quickly, the filter shows its full list instead of failing: for run fields when `study_facets` is missing, or when the query takes over 15 seconds (`NARROWED_TIMEOUT_MS`).

## Above the results

### Filters row

The applied filters as chips (and accessions from the search box). Removing a chip searches again at once. **Clear all** removes every filter and accession but keeps the tags and any text search.

### Tags row

- **Chosen tags** as blue chips, each removable, after "all of" or "any of" when there are two or more. **Clear all** removes only the tags (and turns **Match any of the tags** off).
- **Suggested tags** (dashed, with a +): the tags most common among the search's top 2,000 results, each added with one click. Hovering shows the tag's type and how many of the top results have it. They leave out the organism, tags already chosen and tags found on only one project. They load after the results, so they never slow them down (`GET /search/tag-summary`).

Each row is hidden when it has nothing to show.

## The results table

| Column | Shows | Sort |
| --- | --- | --- |
| BioProject | BioProject (link to ENA) and SRA study (link to NCBI) | yes |
| Title | Title, then the project's tags | |
| Organism | | yes |
| Experiments | Number of experiments | yes |
| Publications | The number of publications in a green tag, darker for more: light for 1, medium for 2, dark for 3 or more; empty when there are none | yes, by number of publications |
| Released | `release_date`; hover the header for its meaning | yes, newest first by default |

Text searches are sorted best match first; clicking a column header sorts by that column instead. The match score isn't shown (`similarity` and `text_match` are in the API response; see [search.md](search.md#4-filters-sorting-and-paging)).

Under each title, the project's tags show as grey chips, without the tag that repeats the organism. Tags in the Tags filter come first, in blue, and always show; the rest fill up to five, and **+N more** shows the others. Clicking a tag adds it to the Tags filter and searches at once.

Clicking a row opens the project's details: description, organization with country, GEO accessions, a small table of publications (title, citation, PubMed / PMC / DOI links; it scrolls past four; missing titles and citations are fetched from PubMed by the browser, see [running.md](running.md#publication-titles-pubmed)), and a link to the project's sequencing files from ENA. An open project and its details share a light blue background and a blue bar on the left.

Results are paged (10, 25, 50 or 100 per page; 25 by default).

## Where the code is

| What | File |
| --- | --- |
| Filter definitions: sections, labels, controls, parameters | `frontend/src/search/filters.ts` |
| Filter panel, dropdowns and type-ahead, narrowing context | `frontend/src/search/FilterPanel.tsx` |
| URL state, draft vs applied search | `frontend/src/search/useSearchState.ts` |
| Filters row | `frontend/src/search/ActiveFilters.tsx` |
| Tags row with suggestions | `frontend/src/search/TagBar.tsx` |
| Tags under each title | `frontend/src/search/TagList.tsx` |
| Results table, project details, wiring | `frontend/src/pages/SearchPage.tsx` |
| Filter parameters (`SearchFilters`), conditions (`build_conditions`), filter values (`distinct_values`, `narrowed_values`), endpoints | `backend/app/search.py` |
| Public API, sharing the same filters | `backend/app/public_api.py` |

## Adding a filter

1. **Backend:** add the parameter to `SearchFilters` in `backend/app/search.py`, and make `build_conditions` handle it. A project column goes in `PROJECT_FIELDS`, a run column in `RUN_FIELDS` (and as an array in `backend/sql/study_facets.sql`), a sample attribute in `ATTRIBUTE_FIELDS` (and in the field list of `backend/sql/bioproject_attribute_values.sql`). Those three are handled by `build_conditions`, `distinct_values` and `narrowed_values` automatically.
2. **Values:** for a dropdown add the name to `FACET_FIELDS`, for a type-ahead to `SUGGEST_FIELDS`. Sample attributes are added to `SUGGEST_FIELDS` automatically (except `sex`, a dropdown).
3. **Public API:** add a description to `LIST_FILTER_HELP` in `backend/app/public_api.py` (sample attributes are included from `ATTRIBUTE_FIELDS`).
4. **Frontend:** add an entry to a section of `FILTER_SECTIONS` in `frontend/src/search/filters.ts`. The panel, chips, URL and narrowing pick it up from there.
5. **Docs:** add it to the tables on this page.
