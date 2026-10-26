"""소상공인 상가(상권)정보 시도별 CSV를 하나의 parquet로 변환.

사용: python load_sbiz.py <csv_dir> <out.parquet>
"""
import sys, time
import duckdb

src, out = sys.argv[1], sys.argv[2]
sys.stdout.reconfigure(encoding="utf-8")
con = duckdb.connect()
t = time.time()
con.sql(f"""
COPY (
  SELECT * FROM read_csv('{src}/*.csv', header=true, all_varchar=true, filename=false)
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print("rows", con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0], f"{time.time() - t:.0f}s")
for name, typ, *_ in con.execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall():
    sample = con.execute(f'SELECT "{name}" FROM \'{out}\' WHERE "{name}" IS NOT NULL LIMIT 1').fetchone()
    nulls = con.execute(f'SELECT round(100.0 * count_if("{name}" IS NULL) / count(*), 1) FROM \'{out}\'').fetchone()[0]
    print(f"{name:12s} null {nulls:5}%  e.g. {sample[0] if sample else None}")
