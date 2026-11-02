# Normalising filter values

Values in the database come from submitters and are spelled many ways: `Liver`, `liver` and `LIVER`; `WT`, `wildtype` and `wild type`. The normalisation page lets an administrator rename a value, which changes it at once in every row of the database, and keeps each rename as a rule so that it is applied again after every data load. Over time the values become consistent without ever redoing the work.

| What | Where |
| --- | --- |
| The page | `/admin/normalize` (not in the menu; open it by typing the address) |
| Page code | `frontend/src/pages/NormalizePage.tsx`, `frontend/src/api/admin.ts` |
| API | `backend/app/admin.py` (`/admin/...`, not in the OpenAPI docs) |
| Renaming, rules, re-applying | `backend/app/normalize.py` |
| Rules table | `value_normalizations`: one row per rule, with `action` `rename` (from → to) or `capitalize` (every value). Created by the API at startup (which also adds `action` to an older table), never dropped by the data loading scripts |

## Access

The page asks for a code, currently `srageek`, and remembers it for the browser tab. The code is hardcoded in two places, which must match:

| Where | Constant |
| --- | --- |
| The page | `ADMIN_CODE` in `frontend/src/pages/NormalizePage.tsx` |
| The API | `ADMIN_CODE` in `backend/app/admin.py` |

The page's copy is in its JavaScript, so it only keeps the page out of sight; it is not what protects the database. What protects the database is the API: every `/admin` request must carry the code in the `X-Admin-Code` header, and the API refuses it otherwise (401). The API never stores or logs the code. There is no login system: the page sends the code it was given with each request.

To change the code, change both constants. A deployment can also override the API's code with an `ADMIN_CODE` environment variable, without editing the code; then the page's constant must match it. Use HTTPS in production, since the header travels with every request.

## The page

1. **Choose a field.** The 12 fields with their storage:

   | Field | Stored in | Counts shown |
   | --- | --- | --- |
   | Organism | `bioprojects.organism_name` | projects |
   | Supergroup | `bioprojects.supergroup` | projects |
   | Country | `bioprojects.organization_country` | projects |
   | Assay type | `sra_metadata.assay_type`, summarised per study in `study_facets` | studies |
   | Cell line, Cell type, Tissue, Sex, Disease, Genotype or strain, Treatment or condition, ChIP target | lists in `bioproject_attributes.attributes`, summarised in `bioproject_attribute_values` | projects |

2. **Find values.** The table lists the field's distinct values, most common first, each exact spelling on its own (`Liver` and `liver` are two rows, since each is renamed on its own). The search box finds values containing some text, ignoring case: `liver` finds `Liver`, `LIVER`, `fetal liver` and `liver tissue`. Organism has about 125,000 values; the table is paged.

3. **Rename or merge.** **Rename** on a row changes that value. Ticking several rows and clicking **Merge into one value** changes all of them to one value. The new value can be typed, or picked from the field's existing values (suggested as you type, with their counts), which is how `Liver` and `LIVER` are merged into `liver`.

   The change runs as a background job, one at a time, and the page shows its progress and result ("4,391 projects changed; refreshed bioproject_attribute_values"). Most renames take seconds; an assay type takes minutes (below). While a job runs, the page can't start another.

4. **Rules.** Under the table, the rules recorded for the field: from, to, rows changed, when. A rule can be forgotten with its delete button, which only stops it being applied after the next data load; rows already changed stay as they are (rename them back if needed).

5. **Capitalise first letters** makes the first letter of every value of the field upper case: `liver` becomes `Liver`, `epididymal white adipose tissue (eWAT)` becomes `Epididymal white adipose tissue (eWAT)`. The rest of each value is kept, and values starting with a digit or symbol don't change. If two values in one project's list become equal (`liver` and `Liver`), one is kept. It is recorded as a single rule ("every value → first letter capitalised"), not one per value, so values arriving in future data loads are capitalised too. Like a rename, it is replayed in order: a rename made after it works on the capitalised values.

6. **Re-apply all rules** applies every recorded rule for every field again, for use after loading new data. The same thing from the command line:

   ```bash
   cd backend
   .venv/bin/python -m app.normalize apply
   ```

## What a rename changes

Each rename updates the field's storage in one transaction (all rows or none), records the rule, refreshes the materialized views built from that storage, and forgets the API's cached filter values, so the filters show the new value at once.

| Field kind | Updated | Views refreshed afterwards | Time on the full data |
| --- | --- | --- | --- |
| Organism | `bioprojects.organism_name` | `bioproject_fulltext` (its text includes the organism) | seconds, plus about a minute for the view |
| Supergroup, Country | the `bioprojects` column | none | seconds |
| Assay type | `sra_metadata.assay_type` | `study_facets` | minutes: the whole 42-million-row (15 GB) table is scanned, about a minute (renaming the 88,775 Hi-C runs took 62 seconds), then the view takes a few minutes. An index on `sra_metadata (assay_type)` would make the update itself seconds, at the cost of a few minutes to build and about 300 MB |
| Sample attributes | the field's list in `bioproject_attributes.attributes`; the list keeps its order, and a duplicate is dropped if the new value was already in it | `bioproject_attribute_values` | seconds, plus about 20 seconds for the view |

Only the storage the filter reads is changed. An organism rename doesn't touch the tags (`bioproject_tags`), the runs' own organism (`sra_metadata.organism`), the `organism` list in `bioproject_attributes` or `tax_id`; an assay type rename doesn't touch the `assay_type` list in `bioproject_attributes` (no filter reads it). A tissue rename also renames the value in the `source_name` lists, because a project without a tissue gets its GEO source name as its tissue in the filter ([jattr-normalization.md](jattr-normalization.md#the-bioproject_attribute_values-view)); the counts shown for Tissue come from the `tissue` lists only.

## Rules and the weekly data load

The loading scripts drop and recreate the data tables, so the renamed values would come back in their original spelling. The rules table is separate and survives, and applying the rules again restores the normalisation. Rules are applied in the order they were made, so chains resolve: with `Liver → liver` recorded and later `liver → hepatic tissue`, a newly loaded `Liver` ends up as `hepatic tissue`. Applying the rules twice changes nothing the second time.

After loading, run the rules before or after creating the views; both work:

```bash
# tables loaded (bioprojects, sra_metadata, bioproject_attributes, ...)
cd backend && .venv/bin/python -m app.normalize apply     # applies the rules; refreshes the views that already exist
# then create any views that don't exist yet (study_facets, bioproject_attribute_values, ...)
```

If a view is created after the apply, it is built from the already normalised data. If it existed before, the apply refreshes it. The full reload order is in [production.md](production.md#reloading-data).

`jattr_normalize.py --reclean` and the pipeline's own cleaning ([jattr-normalization.md](jattr-normalization.md)) still run first and fix what they fix; the rules then apply on top. A rule for a value the pipeline no longer produces simply changes nothing.

## Notes

- **Jobs are kept in the API's memory** (the last 50), not in the database, so a restart forgets their history; the rules themselves are in the database. A job interrupted by a restart leaves either all of its rows changed and its rules recorded, or none: the updates and the rule records are one transaction. Only the view refresh, which runs afterwards, can be missing; re-applying the rules refreshes it.
- **Several API workers** would each have their own job queue and job list; the page polls the worker that answers. Run one worker, or accept that a job's status may not be visible from another worker.
- **A rename can create a value the filters merge anyway.** The sample filters ignore case, so `Liver` and `liver` already match the same projects there; merging them still helps, because the dropdown then shows one spelling and the counts add up.
- **Scripts and links using the old value** (`?organism=...`) stop matching once it is renamed.
