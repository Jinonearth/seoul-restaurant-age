"""bbox 영역 places의 현재 릴리스 전체 속성(geometry 대신 lon/lat)을 로컬 parquet로 저장.

사용: python extract_detail.py <release> <out.parquet> <xmin,ymin,xmax,ymax>
"""
import sys, time
import duckdb

rel, out, (x0, y0, x1, y1) = sys.argv[1], sys.argv[2], map(float, sys.argv[3].split(","))
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
t = time.time()
con.sql(f"""
COPY (
  SELECT * EXCLUDE (geometry, bbox, theme, type),
    (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat
  FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*')
  WHERE bbox.xmin >= {x0} AND bbox.xmax <= {x1} AND bbox.ymin >= {y0} AND bbox.ymax <= {y1}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print("done", con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0], "rows", f"{time.time() - t:.0f}s")
