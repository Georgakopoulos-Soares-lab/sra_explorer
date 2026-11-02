-- bioprojects.release_date: the one release date the search page shows, sorts
-- and filters on.
--
-- NCBI's ProjectReleaseDate (project_release_date) is missing for about 90% of
-- projects, so release_date is the first of these that exists:
--   1. the date the project's first run became public (study_facets),
--   2. project_release_date, unless it is in the future (placeholders such as 2037),
--   3. submitted_date.
-- On the development data this leaves 2 of 670,720 projects without a date.
--
-- Run after loading bioprojects and creating study_facets (backend/sql/study_facets.sql),
-- and again after every reload of either:
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/release_date.sql

ALTER TABLE bioprojects ADD COLUMN IF NOT EXISTS release_date date;

UPDATE bioprojects b
SET release_date = coalesce(
    (SELECT f.first_run_release FROM study_facets f WHERE f.sra_study = b.sra_study),
    CASE WHEN b.project_release_date <= current_date THEN b.project_release_date END,
    b.submitted_date
);

-- The search page's first view (the most recently released projects) and the
-- release sort and filter. Matches the ORDER BY in /search/latest, so that
-- view reads only the rows it returns.
DROP INDEX IF EXISTS bioprojects_release_date_idx;
CREATE INDEX bioprojects_release_date_idx
    ON bioprojects (release_date DESC NULLS LAST, bioproject, sra_study);

ANALYZE bioprojects;
