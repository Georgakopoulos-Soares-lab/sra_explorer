-- One row per bioproject with its searchable text, for the full-text half of
-- the search box's hybrid search (backend/app/search.py).
--
-- The text is the same fields as the embeddings (Automations/create_embeddings.py),
-- with title and name weighted above organism and description. Storing it
-- here means ranking a match reads the stored tsvector instead of rebuilding
-- it from bioprojects. Without this view, text searches are semantic only.
--
-- Tag words (bioproject_tags) are added at the lowest weight, D, apart from
-- the organism tag, which repeats organism_name. Projects without tags keep
-- exactly the text they had, so they are found as before. While only some
-- projects have tags, D keeps tagged projects from outranking untagged ones
-- with the same words; tags mainly add matches for their cleaned-up forms.
-- Once every project is tagged, D can be raised (see docs/search.md).
--
-- Needs bioproject_tags to exist (the API creates it, empty, at startup).
--
-- Create (takes about a minute on the full table):
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/bioproject_fulltext.sql
-- Rebuild after loading new data into bioprojects or bioproject_tags:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_fulltext;

DROP MATERIALIZED VIEW IF EXISTS bioproject_fulltext;

-- bioprojects has one row per SRA study, all with the same text.
CREATE MATERIALIZED VIEW bioproject_fulltext AS
SELECT DISTINCT ON (b.bioproject)
    b.bioproject,
    setweight(to_tsvector('english', coalesce(b.title, '')), 'A')
    || setweight(to_tsvector('english', coalesce(b.name, '')), 'A')
    || setweight(to_tsvector('english', coalesce(b.organism_name, '')), 'B')
    || setweight(to_tsvector('english', coalesce(b.description, '')), 'C')
    || setweight(to_tsvector('english', coalesce(array_to_string(
           array_remove(string_to_array(t.tags, '; '), b.organism_name), ' '), '')), 'D') AS document
FROM bioprojects b
LEFT JOIN bioproject_tags t ON t.bioproject = b.bioproject
ORDER BY b.bioproject, b.sra_study;

-- Unique, so the view can be refreshed CONCURRENTLY.
CREATE UNIQUE INDEX bioproject_fulltext_bioproject_idx ON bioproject_fulltext (bioproject);
CREATE INDEX bioproject_fulltext_document_idx ON bioproject_fulltext USING gin (document);

ANALYZE bioproject_fulltext;
