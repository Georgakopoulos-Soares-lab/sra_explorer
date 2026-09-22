duckdb database/sra_metadata.duckdb -c  "
COPY (
    SELECT
        *
    FROM sra_metadata
    WHERE experiment IS NOT NULL
    Limit 1
) TO 'all_sra_fields_names.tsv'
WITH (HEADER true, DELIMITER E'\t');
"