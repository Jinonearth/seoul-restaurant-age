"""Overture buildings에서 bbox 영역 건물 외곽선을 로컬 parquet(WKB)로 저장.

사용: python extract_buildings.py <release> <out.parquet> <xmin,ymin,xmax,ymax>
"""
import sys, time
import duckdb

rel, out, (x0, y0, x1, y1) = sys.argv[1], sys.argv[2], map(float, sys.argv[3].split(","))
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
t = time.time()
con.sql(f"""
COPY (
  SELECT id, names.primary AS name, height, num_floors, ST_AsWKB(geometry) AS wkb,
         bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
  FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=buildings/type=building/*')
  WHERE bbox.xmin >= {x0} AND bbox.xmax <= {x1} AND bbox.ymin >= {y0} AND bbox.ymax <= {y1}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print("done", con.execute(f"SELECT count(*) FROM '{out}'").fetchall()[0][0], "buildings", f"{time.time() - t:.0f}s")
