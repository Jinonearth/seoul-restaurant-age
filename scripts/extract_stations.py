"""Overture base 테마의 지하철역(infrastructure/subway_station) 중 bbox 영역을 parquet로 저장한다.
build_restaurant_tiles.py --stations 입력용. download_overture_area.py 결과와 같은 컬럼(type, class, names, geometry)을 쓴다.

사용: python extract_stations.py <release> <out.parquet> <xmin,ymin,xmax,ymax>
"""
import sys, time
import duckdb

rel, out, (x0, y0, x1, y1) = sys.argv[1], sys.argv[2], map(float, sys.argv[3].split(","))
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
t = time.time()
con.sql(f"""
COPY (
  SELECT *
  FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=base/type=infrastructure/*', hive_partitioning=1)
  WHERE class = 'subway_station'
    AND bbox.xmin <= {x1} AND bbox.xmax >= {x0} AND bbox.ymin <= {y1} AND bbox.ymax >= {y0}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd, GEOPARQUET_VERSION 'V1')
""")
print("done", con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0], "stations", f"{time.time() - t:.0f}s")
