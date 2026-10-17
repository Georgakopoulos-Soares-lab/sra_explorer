-- Indexes for the search API on bioprojects.
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/search_indexes.sql

-- The search page's first view: the most recently released projects.
-- Matches the ORDER BY in /search/latest, so it reads only the rows it returns.
CREATE INDEX IF NOT EXISTS bioprojects_release_date_idx
    ON bioprojects (project_release_date DESC NULLS LAST, bioproject, sra_study);
