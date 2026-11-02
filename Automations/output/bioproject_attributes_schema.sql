-- Sample attributes per bioproject, normalised from sra_metadata's jattr column;
-- data from Automations/jattr_normalize.py (see docs/jattr-normalization.md).
-- One row per bioproject (join to bioprojects ON bioproject). attributes is a JSON
-- object: each field (tissue, sex, cell_type, ...) holds a list of distinct values,
-- most frequent first, plus n_runs, e.g.
--   {"n_runs": 2, "organism": ["Mus musculus"], "tissue": ["thymus"], "sex": ["male"]}
DROP TABLE IF EXISTS bioproject_attributes;

CREATE TABLE bioproject_attributes (
    bioproject  TEXT NOT NULL,       -- e.g. PRJDB10518
    attributes  JSONB NOT NULL
);

-- The JSON is full of double quotes and may contain backslash escapes (\", \\).
-- FORMAT text would unescape those and FORMAT csv would treat " as quoting, so
-- load as CSV with a quote character that never occurs in the file (\x01):
-- each line is then split on the tab only and the JSON is kept byte for byte.
\copy bioproject_attributes FROM '/work/11795/dgrigor/ls6/projects/sra_explorer/Automations/output/bioproject_attributes.tsv' WITH (FORMAT csv, DELIMITER E'\t', HEADER true, QUOTE E'\x01')

-- Index on bioproject (unique: one attribute record per project)
ALTER TABLE bioproject_attributes ADD PRIMARY KEY (bioproject);

-- Containment lookups, e.g. projects with female samples from the liver:
--   WHERE attributes @> '{"sex": ["female"], "tissue": ["liver"]}'
CREATE INDEX ON bioproject_attributes USING gin (attributes jsonb_path_ops);

ANALYZE bioproject_attributes;
