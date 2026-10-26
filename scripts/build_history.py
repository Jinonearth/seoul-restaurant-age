"""Overture changelog(릴리스별 added/data_changed/removed)에서 bbox 영역 places의 변경 이력을 모은다.

사용: python build_history.py <out.parquet> <xmin,ymin,xmax,ymax>
결과: release, id, change_type, columns_changed 한 행씩 (모든 릴리스).
"""
import re, sys, time, urllib.request
import duckdb

out, (x0, y0, x1, y1) = sys.argv[1], map(float, sys.argv[2].split(","))
B = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
listing = urllib.request.urlopen(f"{B}/?list-type=2&prefix=changelog/&delimiter=/").read().decode()
releases = sorted(re.findall(r"<Prefix>changelog/([^<]+)/</Prefix>", listing))
print(len(releases), "releases:", releases[0], "..", releases[-1], flush=True)

con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET enable_progress_bar=false;")
con.sql("CREATE TABLE h (release VARCHAR, id VARCHAR, change_type VARCHAR, columns_changed VARCHAR[])")
for rel in releases:
    t = time.time()
    for ct in ("added", "data_changed", "removed"):
        src = f"s3://overturemaps-us-west-2/changelog/{rel}/theme=places/type=place/change_type={ct}/*.parquet"
        # columns_changed는 2026-03 릴리스부터 있다. 없으면 NULL로 채운다.
        for cols in ("columns_changed", "NULL::VARCHAR[]"):
            try:
                con.sql(f"""
                  INSERT INTO h SELECT '{rel}', id, '{ct}', {cols} FROM read_parquet('{src}')
                  WHERE bbox.xmin >= {x0} AND bbox.xmax <= {x1} AND bbox.ymin >= {y0} AND bbox.ymax <= {y1}""")
                break
            except duckdb.BinderException:
                continue
            except duckdb.IOException:
                break  # 이 릴리스에는 해당 변경 유형이 없음 (변경 없는 달은 unchanged만 있다)
    counts = con.execute(f"SELECT change_type, count(*) FROM h WHERE release = '{rel}' GROUP BY 1 ORDER BY 1").fetchall()
    print(rel, dict(counts), f"{time.time() - t:.0f}s", flush=True)
con.sql(f"COPY h TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
print("done", out)
