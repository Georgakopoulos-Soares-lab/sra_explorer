-- Table for Automations/output/sra_metadata_filtered.tsv (produced by Automations/filter_columns.py)
-- One row per SRA run (acc = SRR/ERR/DRR accession).
DROP TABLE IF EXISTS sra_metadata;

CREATE TABLE sra_metadata (
    acc                        TEXT NOT NULL,
    assay_type                 TEXT,
    center_name                TEXT,
    experiment                 TEXT,
    sample_name                TEXT,
    instrument                 TEXT,
    librarylayout              TEXT,
    libraryselection           TEXT,
    librarysource              TEXT,
    platform                   TEXT,
    sample_acc                 TEXT,
    biosample                  TEXT,
    organism                   TEXT,
    sra_study                  TEXT,
    releasedate                DATE,
    bioproject                 TEXT,
    library_name               TEXT,
    geo_loc_name_country_calc  TEXT
);

-- CSV mode with a tab delimiter and a quote character that never occurs in the data,
-- so quotes and backslashes in values are loaded literally and empty fields become NULL.
\copy sra_metadata FROM '/work/11795/dgrigor/ls6/projects/sra_explorer/Automations/output/sra_metadata_filtered.tsv' WITH (FORMAT csv, HEADER true, DELIMITER E'\t', QUOTE E'\x01')

-- Added after the load so the bulk insert is faster.
ALTER TABLE sra_metadata ADD PRIMARY KEY (acc);
CREATE INDEX ON sra_metadata (experiment);
CREATE INDEX ON sra_metadata (sra_study);
CREATE INDEX ON sra_metadata (bioproject);
CREATE INDEX ON sra_metadata (biosample);
CREATE INDEX ON sra_metadata (organism);

ANALYZE sra_metadata;
