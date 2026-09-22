duckdb database/sra_metadata.duckdb -c  "
COPY (
    SELECT *
    FROM sra_metadata
) TO 'sra_metadata_all.tsv'
WITH (HEADER true, DELIMITER E'\t');
"