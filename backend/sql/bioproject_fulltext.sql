-- One row per bioproject with its searchable text, for the full-text half of
-- the search box's hybrid search (backend/app/search.py).
--
-- The text is the same fields as the embeddings (Automations/create_embeddings.py),
-- with title and name weighted above organism and description. Storing it
-- here means ranking a match reads the stored tsvector instead of rebuilding
-- it from bioprojects. Without this view, text searches are semantic only.
--
-- Create (takes about a minute on the full table):
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/bioproject_fulltext.sql
-- Rebuild after loading new data into bioprojects:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext;

DROP MATERIALIZED VIEW IF EXISTS bioproject_fulltext;

-- bioprojects has one row per SRA study, all with the same text.
CREATE MATERIALIZED VIEW bioproject_fulltext AS
SELECT DISTINCT ON (bioproject)
    bioproject,
    setweight(to_tsvector('english', coalesce(title, '')), 'A')
    || setweight(to_tsvector('english', coalesce(name, '')), 'A')
    || setweight(to_tsvector('english', coalesce(organism_name, '')), 'B')
    || setweight(to_tsvector('english', coalesce(description, '')), 'C') AS document
FROM bioprojects
ORDER BY bioproject, sra_study;

-- Unique, so the view can be refreshed CONCURRENTLY.
CREATE UNIQUE INDEX bioproject_fulltext_bioproject_idx ON bioproject_fulltext (bioproject);
CREATE INDEX bioproject_fulltext_document_idx ON bioproject_fulltext USING gin (document);

ANALYZE bioproject_fulltext;
