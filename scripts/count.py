import duckdb, sys
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
rel = sys.argv[1]
print(con.sql(f"SELECT sum(num_rows) rows, count(*) files FROM parquet_file_metadata('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*')"))
print(con.sql(f"SELECT sources[1] FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*') LIMIT 1"))
print(con.sql(f"DESCRIBE SELECT addresses, names, sources, taxonomy FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*') LIMIT 1").fetchall())
