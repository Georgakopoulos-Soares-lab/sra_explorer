-- One row per bioproject, sample attribute field and value, from the JSON in
-- bioproject_attributes (Automations/output/bioproject_attributes_schema.sql).
--
-- The search API's sample filters (cell line, tissue, sex, ...) read this view
-- instead of the JSON: value_key is the lowercased value, so "liver", "Liver"
-- and "LIVER" match each other (the same value is spelled with different case
-- across projects), and the index finds a field's value without reading every
-- project's JSON. Only the fields with a filter are included: the field list
-- in the query below must match ATTRIBUTE_FIELDS in backend/app/search.py
-- (plus source_name, read for the tissue fallback and then left out).
--
-- Tissue fallback: a project with no tissue but a GEO source_name that is a
-- known tissue gets that source name as its tissue. GEO submitters often put
-- the tissue only in source_name ("Liver"). "Known" means used as a tissue by
-- at least 20 projects, so free-text labels ("WT_rep1") never become tissues.

-- Create after loading bioproject_attributes (takes under a minute):
--   docker exec -i sra_explorer_dev psql -U postgres -d <db> < backend/sql/bioproject_attribute_values.sql
-- Rebuild after loading new data into bioproject_attributes:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY bioproject_attribute_values;
-- bioproject_attributes_schema.sql drops this view when it reloads the table.

DROP MATERIALIZED VIEW IF EXISTS bioproject_attribute_values;

CREATE MATERIALIZED VIEW bioproject_attribute_values AS
WITH raw AS (
    SELECT a.bioproject, f.field, v.value
    FROM bioproject_attributes a,
         jsonb_each(a.attributes) AS f(field, vals),
         jsonb_array_elements_text(f.vals) AS v(value)
    WHERE jsonb_typeof(f.vals) = 'array'
      AND v.value <> ''
      AND f.field IN ('cell_line', 'cell_type', 'tissue', 'sex', 'disease_state',
                      'genotype_or_strain', 'treatment_or_growth_condition',
                      'molecular_target', 'source_name')
),
known_tissues AS (
    SELECT lower(value) AS value_key
    FROM raw WHERE field = 'tissue'
    GROUP BY 1 HAVING count(DISTINCT bioproject) >= 20
),
tissue_from_source AS (
    SELECT r.bioproject, 'tissue' AS field, r.value
    FROM raw r JOIN known_tissues k ON k.value_key = lower(r.value)
    WHERE r.field = 'source_name'
      AND NOT EXISTS (SELECT 1 FROM raw t WHERE t.bioproject = r.bioproject AND t.field = 'tissue')
),
merged AS (
    SELECT * FROM raw WHERE field <> 'source_name'
    UNION ALL
    SELECT * FROM tissue_from_source
)
-- Within a project, values differing only in case are already merged by
-- jattr_normalize.py; DISTINCT ON keeps one row per key regardless.
SELECT DISTINCT ON (bioproject, field, lower(value))
    bioproject,
    field,
    value,
    lower(value) AS value_key
FROM merged
ORDER BY bioproject, field, lower(value), value;

-- Unique, so the view can be refreshed CONCURRENTLY.
CREATE UNIQUE INDEX bioproject_attribute_values_key_idx
    ON bioproject_attribute_values (bioproject, field, value_key);
-- Filters: the projects with a field's value.
CREATE INDEX bioproject_attribute_values_lookup_idx
    ON bioproject_attribute_values (field, value_key, bioproject);

ANALYZE bioproject_attribute_values;
