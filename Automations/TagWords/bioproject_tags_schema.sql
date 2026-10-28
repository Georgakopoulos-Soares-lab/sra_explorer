-- Tag words per bioproject; data from Automations/TagWords/extract_tags.py
-- One row per bioproject (join to bioprojects ON bioproject). tags is a "; "-separated
-- list of organisms, diseases, tissues, organs, cell types, cell lines, chemicals and
-- environments extracted from title + name + description, most relevant first.
DROP TABLE IF EXISTS bioproject_tags;

CREATE TABLE bioproject_tags (
    bioproject  TEXT NOT NULL,       -- e.g. PRJNA559273
    tags        TEXT NOT NULL        -- e.g. Mus musculus; osteoarthritis; skin; synovial fibroblast
);

\copy bioproject_tags FROM '/work/11795/dgrigor/ls6/projects/sra_explorer/Automations/TagWords/output/bioproject_tags.tsv' WITH (FORMAT csv, DELIMITER E'\t', HEADER true)

-- Index on bioproject (unique: one tag list per project)
ALTER TABLE bioproject_tags ADD PRIMARY KEY (bioproject);

-- Exact tag lookup: WHERE string_to_array(tags, '; ') @> ARRAY['osteoarthritis']
CREATE INDEX ON bioproject_tags USING gin (string_to_array(tags, '; '));
