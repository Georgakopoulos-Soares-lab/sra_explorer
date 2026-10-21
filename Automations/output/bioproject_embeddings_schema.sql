-- Embeddings for semantic search over bioprojects; data from Automations/create_embeddings.py
-- One row per bioproject (join to bioprojects ON bioproject). Vectors are L2-normalised
-- BioBERT embeddings of title + name + organism_name + description.
CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS bioproject_embeddings;

CREATE TABLE bioproject_embeddings (
    bioproject  TEXT NOT NULL,       -- e.g. PRJNA559273
    embedding   vector(768) NOT NULL
);

\copy bioproject_embeddings FROM '/work/11795/dgrigor/ls6/projects/sra_explorer/Automations/output/bioproject_embeddings.tsv' WITH (FORMAT csv, DELIMITER E'\t', HEADER true)

-- Index on bioproject (unique: one embedding per project)
ALTER TABLE bioproject_embeddings ADD PRIMARY KEY (bioproject);

-- Approximate nearest-neighbour index for semantic search (cosine distance, operator <=>)
SET maintenance_work_mem = '4GB';
CREATE INDEX ON bioproject_embeddings USING hnsw (embedding vector_cosine_ops);
