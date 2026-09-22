import duckdb

con = duckdb.connect()

n = con.execute("""
SELECT COUNT(*)
FROM read_parquet('sra_metadata_local/*')
""").fetchone()[0]

print("Total SRA metadata records:", n)
