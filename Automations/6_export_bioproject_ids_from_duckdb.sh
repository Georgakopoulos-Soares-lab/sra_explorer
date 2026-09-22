duckdb database/sra_metadata.duckdb -c  "
COPY (
    SELECT DISTINCT bioproject
    FROM sra_metadata
    WHERE bioproject IS NOT NULL
) TO 'all_sra_bioprojects.txt'
WITH (HEADER false);
"
