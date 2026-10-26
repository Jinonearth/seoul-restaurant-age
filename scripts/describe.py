import duckdb, sys
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
rel = sys.argv[1]
print(con.sql(f"DESCRIBE SELECT * FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*', hive_partitioning=1) LIMIT 1"))
