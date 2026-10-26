"""Protomaps basemaps의 --overture 입력용으로, bbox에 걸치는 Overture 피처를 parquet 하나로 받는다.
protomaps/basemaps tiles/download-overture.sh 와 같은 조건(테마·bbox 교차, hive 파티션 컬럼 포함).
Planetiler가 읽을 수 있게 geometry는 GeoParquet V1(WKB + geo 메타데이터)로 쓴다.

사용: python download_overture_area.py <release> <xmin,ymin,xmax,ymax> <out.parquet>
"""
import sys, time
import duckdb

rel, bbox, out = sys.argv[1:4]
x0, y0, x1, y1 = map(float, bbox.split(","))
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
t = time.time()
con.sql(f"""
COPY (
  SELECT * FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/**/*.parquet', hive_partitioning=1, union_by_name=1)
  WHERE theme IN ('transportation', 'places', 'base', 'buildings', 'divisions')
    AND bbox.xmin <= {x1} AND bbox.xmax >= {x0} AND bbox.ymin <= {y1} AND bbox.ymax >= {y0}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd, GEOPARQUET_VERSION 'V1')
""")
print("done", f"{time.time() - t:.0f}s")
print(con.execute(f"SELECT theme, type, count(*) FROM '{out}' GROUP BY ALL ORDER BY 1, 2").fetchall())
