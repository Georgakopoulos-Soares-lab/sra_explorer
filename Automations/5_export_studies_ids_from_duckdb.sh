duckdb database/sra_metadata.duckdb -c  "
COPY (
    SELECT DISTINCT sra_study
    FROM sra_metadata
    WHERE sra_study IS NOT NULL
) TO 'all_sra_study_ids.tsv'
WITH (HEADER false);
"
