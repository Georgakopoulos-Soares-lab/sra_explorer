duckdb database/sra_metadata.duckdb -c  "
COPY (
    SELECT
        experiment,
        any_value(sra_study) AS sra_study,
        any_value(bioproject) AS bioproject,
        any_value(sample_acc) AS sample_acc,
        any_value(biosample) AS biosample,
        any_value(sample_name) AS sample_name,
        any_value(organism) AS organism,
        any_value(assay_type) AS assay_type,
        any_value(library_name) AS library_name,
        any_value(librarylayout) AS librarylayout,
        any_value(libraryselection) AS libraryselection,
        any_value(librarysource) AS librarysource,
        any_value(platform) AS platform,
        any_value(instrument) AS instrument,
        any_value(center_name) AS center_name,
        any_value(consent) AS consent,
        MIN(releasedate) AS first_releasedate,
        MAX(loaddate) AS last_loaddate,
        SUM(CAST(mbytes AS DOUBLE)) AS total_mbytes,
        SUM(CAST(mbases AS DOUBLE)) AS total_mbases,
        COUNT(*) AS number_of_runs,
        string_agg(acc, ';') AS run_accessions
    FROM sra_metadata
    WHERE experiment IS NOT NULL
    GROUP BY experiment
) TO 'all_sra_experiments_metadata.tsv.gz'
WITH (HEADER true, DELIMITER E'\t', COMPRESSION gzip);
"