"""서울 타일 POI의 출처별 update_time·version 분포."""
import duckdb
B = (126.9140625, 37.509725842937506, 127.001953125, 37.57941251343839)
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
con.sql(f"""CREATE TABLE p AS SELECT id, version, sources FROM read_parquet('s3://overturemaps-us-west-2/release/2026-10-21.0/theme=places/type=place/*')
  WHERE bbox.xmin >= {B[0]} AND bbox.xmax <= {B[2]} AND bbox.ymin >= {B[1]} AND bbox.ymax <= {B[3]}""")
print(con.execute("SELECT s.dataset, s.property, s.resource, count(*) FROM (SELECT unnest(sources) s FROM p) GROUP BY ALL ORDER BY 4 DESC").fetchall())
print(con.execute("""SELECT s.dataset, left(s.update_time, 4) y, count(*) FROM (SELECT unnest(sources) s FROM p)
  WHERE s.dataset <> 'Overture' GROUP BY ALL ORDER BY 1, 2""").fetchall())
print(con.execute("""SELECT s.dataset, s.version, count(*) FROM (SELECT unnest(sources) s FROM p) WHERE s.dataset <> 'Overture' GROUP BY ALL ORDER BY 3 DESC LIMIT 15""").fetchall())
print("gers version", con.execute("SELECT version, count(*) FROM p GROUP BY 1 ORDER BY 1").fetchall())
