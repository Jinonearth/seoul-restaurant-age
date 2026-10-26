"""서울 타일 POI의 나이 후보 필드 분포 비교."""
import duckdb
B = (126.9140625, 37.509725842937506, 127.001953125, 37.57941251343839)
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
where = f"bbox.xmin >= {B[0]} AND bbox.xmax <= {B[2]} AND bbox.ymin >= {B[1]} AND bbox.ymax <= {B[3]}"
con.sql(f"""CREATE TABLE p AS SELECT id, sources FROM read_parquet('s3://overturemaps-us-west-2/release/2026-10-21.0/theme=places/type=place/*') WHERE {where}""")
con.sql(f"""CREATE TABLE r AS SELECT id, version, first_seen, last_changed FROM read_parquet('s3://overturemaps-us-west-2/registry/*.parquet')
            WHERE {where} AND path LIKE 'theme=places/%'""")
print("places", con.execute("SELECT count(*) FROM p").fetchall(), "registry", con.execute("SELECT count(*) FROM r").fetchall())
print(con.execute("SELECT s.dataset, s.property, left(s.update_time,7) ym, count(*) FROM (SELECT unnest(sources) s FROM p) GROUP BY ALL ORDER BY 1,3 DESC").fetchall())
print("first_seen", con.execute("SELECT first_seen, count(*) FROM r GROUP BY 1 ORDER BY 1").fetchall())
print("last_changed", con.execute("SELECT last_changed, count(*) FROM r GROUP BY 1 ORDER BY 1").fetchall())
print("joined", con.execute("SELECT count(*) FROM p JOIN r USING (id)").fetchall())
