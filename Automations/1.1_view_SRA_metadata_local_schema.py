import duckdb

con = duckdb.connect()

schema = con.execute("""
DESCRIBE SELECT *
FROM read_parquet('sra_metadata_local/*')
""").fetchdf()

print(schema.to_string())
