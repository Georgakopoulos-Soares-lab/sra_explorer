import duckdb

con = duckdb.connect()

df = con.execute("""
SELECT *
FROM read_parquet('sra_metadata_local/*')
LIMIT 1
""").fetchdf()

print(df.to_string())
