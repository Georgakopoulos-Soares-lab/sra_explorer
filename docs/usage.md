# App usage

Every search made on the website or through the public API is recorded, and the admin usage page shows what people search for and how much the app is used.

| What | Where |
| --- | --- |
| The page | `/admin/usage` (linked at the far right of the menu, next to Normalization) |
| Page code | `frontend/src/pages/UsagePage.tsx`, `frontend/src/api/admin.ts` |
| API | `backend/app/admin.py` (`/admin/usage/...`, not in the OpenAPI docs) |
| Recording and reports | `backend/app/usage.py` |
| Events table | `search_events` (`backend/app/models.py`): one row per request. Created by the API at startup, never dropped by the data loading scripts |

## Access

The page asks for the same code as the normalisation page ([normalization.md](normalization.md#access)), `ADMIN_CODE` in `frontend/src/components/AdminGate.tsx` and `backend/app/admin.py`, and remembers it for the browser tab, so opening one admin page opens the other.

## What is recorded

| Request | `source` | `kind` | `query` |
| --- | --- | --- | --- |
| Website search, `/search/bioprojects` | `site` | `search` | the search text, if any |
| Public API search, `/v1/projects` | `api` | `search` | empty (the API has no text search yet) |
| Public API lookup, `/v1/projects/{accession}` | `api` | `lookup` | the accession |

Each row also has the time (`created_at`), the filters that were set (`filters`, JSON without defaults, paging or sorting), `sort`, `offset`, the number of matching projects (`total`), the time the search took (`duration_ms`), and who searched: `client_ip` (read from `X-Forwarded-For` when `TRUST_FORWARDED_FOR` is set, see `rate_limit.py`), `visitor` and `user_agent`.

A visitor is a random id the browser keeps in local storage and sends in an `X-Visitor-Id` header with every request (`frontend/src/api/client.ts`). It tells browsers apart better than IP addresses, which are shared behind institutional networks. The public API sends no id, so API visitors are counted by IP.

The row is written from a FastAPI background task after the response is sent, so recording never slows a search down, and a failure to record (logged) never fails a search.

Paging through results repeats the request with a larger `offset`. Those rows are kept but the page counts a search once: everywhere it says "searches" it counts rows with `offset = 0`; "requests" includes paging.

## The page

A time range (7, 30, 90 days, a year, or all time) and a source (all, website, public API) apply to everything on the page.

- **Headline numbers** for today, the last 7 days, the last 30 days and the chosen range: searches, visitors, the website/API split, and the share of searches with no results.
- **Searches over time** and **visitors over time** per day, week or month, with the table and CSV every chart has.
- **Searches by hour of day** (UTC).
- **Filters used**: how many searches set each filter, and the most used filter values.
- **Most searched texts**, case-insensitively, with how many visitors searched them, the results the search found, and when it was last searched.
- **Most active visitors**, with their active days.
- **Latest searches**, newest first: time, source, text, filters, results, time taken and visitor (the IP and browser on hover).

The table grows by one row per request, a few hundred bytes each; a year of heavy use is a few hundred megabytes at most. Old rows can be deleted with `DELETE FROM search_events WHERE created_at < ...`.
