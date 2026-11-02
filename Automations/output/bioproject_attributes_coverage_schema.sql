-- How many sequencing runs (samples) and BioProjects have a value for each sample
-- attribute field; data from Automations/jattr_normalize.py
-- (bioproject_attributes_coverage.tsv, see docs/jattr-normalization.md).
-- One row per field. Counted per run while the pipeline reads sra_metadata_all.tsv,
-- which the database doesn't hold, so it can't be computed in SQL. The home page
-- shows runs_pct for tissue, cell_type and cell_line ("% of samples").
DROP TABLE IF EXISTS bioproject_attributes_coverage;

CREATE TABLE bioproject_attributes_coverage (
    field            TEXT PRIMARY KEY,   -- e.g. tissue
    runs             BIGINT NOT NULL,    -- runs with a value
    runs_pct         NUMERIC NOT NULL,   -- % of all runs read by the pipeline
    bioprojects      BIGINT NOT NULL,    -- BioProjects with a value in any run
    bioprojects_pct  NUMERIC NOT NULL    -- % of all BioProjects
);

\copy bioproject_attributes_coverage FROM '/work/11795/dgrigor/ls6/projects/sra_explorer/Automations/output/bioproject_attributes_coverage.tsv' WITH (FORMAT csv, DELIMITER E'\t', HEADER true)
