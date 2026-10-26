"""POI '나이'를 정의할 후보 필드 탐색: GERS registry 스키마와 sources.update_time 분포."""
import duckdb
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
print(con.execute("DESCRIBE SELECT * FROM read_parquet('s3://overturemaps-us-west-2/registry/*.parquet') LIMIT 1").fetchall())
print(con.execute("SELECT * FROM read_parquet('s3://overturemaps-us-west-2/registry/*.parquet') LIMIT 3").fetchall())
