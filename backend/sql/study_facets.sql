-- One row per SRA study, summarising its runs in sra_metadata.
--
-- The search API filters on this instead of sra_metadata itself: scanning the
-- full runs table takes over a minute per search, while this view is small and
-- indexed. Without it the API still works, but run filters are slow.
--
-- Create (takes a few minutes on the full table):
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/study_facets.sql
-- Rebuild after loading new data into sra_metadata:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY study_facets;

DROP MATERIALIZED VIEW IF EXISTS study_facets;

-- Empty strings and NULLs are left out of the arrays.
CREATE MATERIALIZED VIEW study_facets AS
SELECT
    sra_study,
    array_remove(array_agg(DISTINCT NULLIF(assay_type, '')), NULL)                AS assay_types,
    array_remove(array_agg(DISTINCT NULLIF(platform, '')), NULL)                  AS platforms,
    array_remove(array_agg(DISTINCT NULLIF(instrument, '')), NULL)                AS instruments,
    array_remove(array_agg(DISTINCT NULLIF(librarylayout, '')), NULL)             AS library_layouts,
    array_remove(array_agg(DISTINCT NULLIF(librarysource, '')), NULL)             AS library_sources,
    array_remove(array_agg(DISTINCT NULLIF(libraryselection, '')), NULL)          AS library_selections,
    array_remove(array_agg(DISTINCT NULLIF(organism, '')), NULL)                  AS run_organisms,
    array_remove(array_agg(DISTINCT NULLIF(geo_loc_name_country_calc, '')), NULL) AS sample_countries,
    array_remove(array_agg(DISTINCT NULLIF(center_name, '')), NULL)               AS center_names,
    min(releasedate)                                                              AS first_run_release,
    max(releasedate)                                                              AS last_run_release,
    count(*)                                                                      AS n_runs
FROM sra_metadata
WHERE sra_study IS NOT NULL
GROUP BY sra_study;

-- The unique index is required for REFRESH ... CONCURRENTLY.
CREATE UNIQUE INDEX study_facets_sra_study_idx ON study_facets (sra_study);
CREATE INDEX study_facets_assay_types_idx        ON study_facets USING gin (assay_types);
CREATE INDEX study_facets_platforms_idx          ON study_facets USING gin (platforms);
CREATE INDEX study_facets_instruments_idx        ON study_facets USING gin (instruments);
CREATE INDEX study_facets_library_layouts_idx    ON study_facets USING gin (library_layouts);
CREATE INDEX study_facets_library_sources_idx    ON study_facets USING gin (library_sources);
CREATE INDEX study_facets_library_selections_idx ON study_facets USING gin (library_selections);
CREATE INDEX study_facets_run_organisms_idx      ON study_facets USING gin (run_organisms);
CREATE INDEX study_facets_sample_countries_idx   ON study_facets USING gin (sample_countries);
CREATE INDEX study_facets_center_names_idx       ON study_facets USING gin (center_names);
CREATE INDEX study_facets_release_idx            ON study_facets (first_run_release, last_run_release);

ANALYZE study_facets;
