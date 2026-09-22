import duckdb
import os

INPUT = "sra_metadata_local/*"

os.makedirs("database", exist_ok=True)

DB = "database/sra_metadata.duckdb"

con = duckdb.connect(DB)

con.execute("""
CREATE OR REPLACE TABLE sra_metadata AS
SELECT *
FROM read_parquet(?)
""", [INPUT])

n = con.execute("SELECT COUNT(*) FROM sra_metadata").fetchone()[0]

print("Created database:", DB)
print("Rows:", n)

con.close()