"""Overture places 전세계에서 커버리지 분석용 컬럼만 뽑아 로컬 parquet로 저장."""
import duckdb, sys, time
rel, out = sys.argv[1], sys.argv[2]
# 선택: xmin,ymin,xmax,ymax 로 영역 제한
where = ""
if len(sys.argv) > 3:
    x0, y0, x1, y1 = map(float, sys.argv[3].split(","))
    where = f"WHERE bbox.xmin >= {x0} AND bbox.xmax <= {x1} AND bbox.ymin >= {y0} AND bbox.ymax <= {y1}"
con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET threads=8; SET preserve_insertion_order=false;")
t = time.time()
con.sql(f"""
COPY (
  SELECT
    id,
    (bbox.xmin + bbox.xmax) / 2 AS lon,
    (bbox.ymin + bbox.ymax) / 2 AS lat,
    addresses[1].country AS country,
    basic_category,
    taxonomy.hierarchy[1] AS top_category,
    confidence,
    operating_status,
    list_distinct(list_transform(sources, lambda s: s.dataset)) AS datasets,
    len(sources) AS n_sources,
    list_max(list_transform(sources, lambda s: s.update_time)) AS update_time,
    names.primary AS name,
    coalesce(regexp_matches(names.primary, '[가-힣]'), false) AS has_hangul,
    coalesce(len(websites), 0) > 0 AS has_website,
    coalesce(len(phones), 0) > 0 AS has_phone,
    brand.wikidata IS NOT NULL AS has_brand
  FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*')
  {where}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print("done", round(time.time() - t), "s")
print(con.sql(f"SELECT count(*), count(DISTINCT country) FROM '{out}'"))
