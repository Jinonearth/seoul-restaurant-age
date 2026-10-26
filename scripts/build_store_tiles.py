"""소상공인 상가정보 + 건물 외곽선으로 서울 업소 테이블과 PMTiles를 만든다.

서울건물나이지도처럼 타일을 최소화한다.
  - z14 한 단계에만 건물 레이어. 더 확대하면 z14를 늘려 쓴다.
    상가정보 좌표는 건물 단위라, 같은 좌표의 업소를 묶어 건물 폴리곤에 붙인다(tiling.match_buildings).
    폴리곤은 layer "bldg", 폴리곤을 못 찾은 좌표는 layer "store" 점으로 남긴다.
    속성: name(건물명 또는 상호명), n(업소 수), cat(최다 업종), share(최다 업종 비중 %), reg(가장 최근 등록 연월),
          newp(2022-08 이후 등록 비율 %), recentp(최근 1년 등록 비율 %). feature id = gid.
  - z0–13은 격자(layer "grid": 업소 수, 신규 등록 비율, 음식점 비율). 타일당 32x32칸.
  - 건물의 업소 목록은 타일에 넣지 않고 gid로 API에서 조회한다.

등록 연월은 상가업소번호 7–12번째 자리(YYYYMM). 2022-08은 시스템 전환 때 기존 업소에 일괄 부여된 값이다.

사용: python build_store_tiles.py <sbiz.parquet> <시도명> <buildings.parquet> <out_table.parquet> <out.pmtiles> <기준연월 YYYYMM>
"""
import json
import os
import sys
import time

import duckdb
from pmtiles.tile import Compression, TileType
from pmtiles.writer import Writer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 같은 폴더의 모듈 (-I 실행 시에도)
import tiling  # noqa: E402

src, sido, buildings, out_table, out_tiles, base_ym = sys.argv[1:7]
sys.stdout.reconfigure(encoding="utf-8")
MIGRATION_YM = 202208
CATEGORIES = ["I2", "G2", "M1", "S2", "P1", "N1", "L1", "R1", "Q1", "I1"]  # 서울 업소 수 순

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial; SET threads=8; SET preserve_insertion_order=false;")
t0 = time.time()


def log(*a):
    print(*a, f"{time.time() - t0:.0f}s", flush=True)


con.sql(f"""
CREATE TABLE s AS
SELECT
  row_number() OVER (ORDER BY 상가업소번호) - 1 AS fid,
  상가업소번호 AS id,
  상호명 AS name, 지점명 AS branch,
  상권업종대분류코드 AS cat_l, 상권업종대분류명 AS cat_l_name,
  상권업종중분류명 AS cat_m_name, 상권업종소분류명 AS cat_s_name,
  표준산업분류명 AS ksic_name,
  시군구명 AS sigungu, 행정동명 AS dong, 법정동명 AS bdong,
  도로명주소 AS road_address, 지번주소 AS jibun_address, 건물명 AS building, 층정보 AS floor,
  TRY_CAST(substr(상가업소번호, 7, 6) AS INTEGER) AS reg_ym,
  경도::DOUBLE AS lon, 위도::DOUBLE AS lat
FROM '{src}'
WHERE 시도명 = '{sido}'
""")
con.sql(f"""
ALTER TABLE s ADD COLUMN reg_months INTEGER;
UPDATE s SET reg_months = (({base_ym} // 100) * 12 + {base_ym} % 100) - ((reg_ym // 100) * 12 + reg_ym % 100);
""")
tiling.match_buildings(con, "s", buildings)
con.sql(f"COPY s TO '{out_table}' (FORMAT parquet, COMPRESSION zstd)")
log(*con.execute("""SELECT count(*) || ' stores, ' || count_if(bld IS NOT NULL) || ' in buildings, '
                    || count(DISTINCT gid) || ' groups' FROM s""").fetchall()[0], "->", out_table)

con.sql(f"""
CREATE TABLE grp AS
WITH cats AS (
  SELECT gid, cat_l, count(*) AS c, row_number() OVER (PARTITION BY gid ORDER BY count(*) DESC, cat_l) AS rk
  FROM s GROUP BY gid, cat_l
)
SELECT s.gid, any_value(s.bld) AS bld, any_value(s.lon) AS lon, any_value(s.lat) AS lat,
  count(*) AS n,
  any_value(c.cat_l) AS cat,
  round(100 * any_value(c.c) / count(*))::INTEGER AS share,
  max(reg_ym) AS reg,
  round(100 * count_if(reg_ym > {MIGRATION_YM}) / count(*))::INTEGER AS newp,
  round(100 * count_if(reg_ym >= {int(base_ym) - 100}) / count(*))::INTEGER AS recentp,
  CASE WHEN count(*) = 1 THEN any_value(s.name)
       WHEN mode(s.building) IS NOT NULL THEN mode(s.building)
       ELSE arg_min(s.name, s.fid) || ' 외 ' || (count(*) - 1) END AS label
FROM s JOIN cats c ON c.gid = s.gid AND c.rk = 1
GROUP BY s.gid
""")

keys = ["name", "n", "cat", "share", "reg", "newp", "recentp"]
props_sql = "g.label, g.n, g.cat, g.share, g.reg, g.newp, g.recentp"
tiles = tiling.new_tiles()
tiling.add_polygons(tiles, "bldg", con.execute(f"SELECT g.gid, ST_AsWKB(b.g), {props_sql} FROM grp g JOIN b USING (bld)").fetchall())
tiling.add_points(tiles, "store", con.execute(f"SELECT g.gid, g.lon, g.lat, {props_sql} FROM grp g WHERE bld IS NULL").fetchall())

f = open(out_tiles, "wb")
writer = Writer(f)
log(f"z{tiling.POINT_Z}:", tiling.write_point_zoom(writer, tiles, keys), "tiles")
gkeys = tiling.write_grid(con, writer, "s", {
    "new": f"count_if(reg_ym > {MIGRATION_YM})",
    "recent": f"count_if(reg_ym >= {int(base_ym) - 100})",
    "food": "count_if(cat_l = 'I2')",
})
log(f"grid z0-{tiling.GRID_MAXZOOM}")

x0, x1, y0, y1 = con.execute("SELECT min(lon), max(lon), min(lat), max(lat) FROM s").fetchall()[0]
fields = {"name": "String", "n": "Number", "cat": "String", "share": "Number", "reg": "Number", "newp": "Number", "recentp": "Number"}
writer.finalize(
    {
        "tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
        "min_zoom": 0, "max_zoom": tiling.POINT_Z,
        "min_lon_e7": int(x0 * 1e7), "min_lat_e7": int(y0 * 1e7), "max_lon_e7": int(x1 * 1e7), "max_lat_e7": int(y1 * 1e7),
        "center_zoom": 11, "center_lon_e7": int((x0 + x1) / 2 * 1e7), "center_lat_e7": int((y0 + y1) / 2 * 1e7),
    },
    {
        "name": f"소상공인 상가정보 {sido} {base_ym}",
        "attribution": "소상공인시장진흥공단 상가(상권)정보 · Overture Maps buildings",
        "categories": json.dumps(CATEGORIES),
        "vector_layers": [
            {"id": "grid", "minzoom": 0, "maxzoom": tiling.GRID_MAXZOOM, "fields": {k: "Number" for k in gkeys}},
            {"id": "bldg", "minzoom": tiling.POINT_Z, "maxzoom": tiling.POINT_Z, "fields": fields},
            {"id": "store", "minzoom": tiling.POINT_Z, "maxzoom": tiling.POINT_Z, "fields": fields},
        ],
    },
)
f.close()
log("done", out_tiles)
