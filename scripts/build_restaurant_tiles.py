"""지방행정 인허가 '식품_일반음식점' 데이터로 서울 음식점 나이 테이블과 PMTiles 두 개를 만든다.

영업 중(영업/정상)이고 좌표가 있는 업소만 쓴다. 좌표는 EPSG:5174(중부원점 TM)를 WGS84로 변환한다.
인허가일자는 영업자 지위승계 시 그대로 이어지는 것으로 보여서, '현재 가게'보다 '그 자리에서 음식점 영업이 시작된 시점'에 가깝다.

뷰어에서 개업 연도 구간으로 거를 수 있도록 미리 집계하지 않고 음식점 한 곳당 피처 하나로 둔다.
  - <out>_bldg.pmtiles (z14 한 단계): 음식점마다 붙은 건물 폴리곤(layer "bldg") 또는 폴리곤 못 찾은 좌표(layer "store").
    같은 건물의 음식점은 같은 폴리곤을 겹쳐 쓴다. 타일 안에서 새로운 가게부터 오래된 가게 순으로 써서(연도 미상은 맨 앞),
    나중에 그려지는 오래된 가게가 맨 위에 오게 한다. 기간 필터로 숨겨도 남은 것 중 가장 오래된 곳이 위에 남는다.
    속성: y(개업 연도, 미상이면 없음), g(건물 gid, 상세 API용), name, n(건물의 음식점 수). feature id = fid.
  - <out>_pts.pmtiles (z9 한 단계): 음식점 점(layer "pt", 속성 y). 축소 시 개별 점 표시용.

  - <out>_stations.geojson: 지하철역 점(--stations가 있을 때).

사용: python build_restaurant_tiles.py <utf8.csv> <buildings.parquet> <out_table.parquet> <out_prefix> <기준일 YYYY-MM-DD>
                                      [--stores stores.parquet] [--stations overture_area.parquet]
                                      [--snapshots "sbiz_*1231/seoul.csv"] [--baeknyeon 백년가게.csv ...]

건물명(building_name): 같은 Overture 건물에 붙은 상가정보 업소들의 건물명 최빈값(--stores), 없으면 Overture 건물 이름.
개업 연도(open_year): 기본은 인허가 연도(permit_year). 상가정보 연말 스냅샷(--snapshots)과 현재 파일에서 같은 상호가
  100m 안에 처음 나타난 연도(first_seen_year)가 첫 스냅샷 이후이고, 인허가 연도가 그보다 5년 이상 이르면 영업자 지위승계로
  예전 인허가를 이어받은 것으로 보고 first_seen_year를 쓴다(year_source = 'sbiz'). 단, 그 직전 연도 스냅샷에 같은 자리의
  다른 음식점(전 주인)이 있다가 사라진 흔적이 있을 때만이다. 흔적이 없거나, 그 자리에 음식점이 여러 곳 입주해 있어
  전 주인을 특정할 수 없으면 상가정보 누락일 수 있어 인허가를 그대로 쓴다. 다만 차이가 30년 이상이면 흔적이 없어도 보정한다.
  예전 스냅샷에 이미 있던 가게(업소번호 재발급 같은 재등록)는 first_seen_year가 앞당겨져 빠지고, 현재 등록이 대량 등록 달인
  가게도 제외한다.
백년가게(baeknyeon, --baeknyeon): 소상공인시장진흥공단 백년가게 지정 목록과 상호 + 도로명·건물번호로 맞춘다. 업력 30년 이상이
  확인된 가게라 인허가 연도가 기준연도-30보다 늦으면 그 연도로 올리고(year_source = 'baeknyeon'), 상가정보 보정은 적용하지 않는다.
  옛 자리·새 자리(1km 안 같은 상호, 폐업 기록 포함)를 같은 가게로 이어 가장 이른 인허가 연도를 쓴다.
체인(chain): 지점명을 뗀 브랜드가 서울에 3곳 이상인 가게. 연도는 바꾸지 않고 표시만 한다.
가까운 역(station, station_m): Overture base 테마 infrastructure/subway_station을 이름별로 합친 역 중 가장 가까운 곳.
"""
import argparse
import glob
import json
import shutil
from collections import Counter, defaultdict
import os
import re
import sys
import time

import duckdb
from pmtiles.tile import Compression, TileType
from pmtiles.writer import Writer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 같은 폴더의 모듈 (-I 실행 시에도)
import tiling  # noqa: E402

ap = argparse.ArgumentParser()
for a in ("src", "buildings", "out_table", "out_prefix", "base_date"):
    ap.add_argument(a)
ap.add_argument("--stores")
ap.add_argument("--stations")
ap.add_argument("--snapshots", help="연말 상가정보 서울 CSV glob, 예: data/raw/sbiz_*1231/seoul.csv")
ap.add_argument("--baeknyeon", nargs="*", default=[], help="백년가게 지정 CSV(UTF-8). 업체명과 주소 컬럼을 자동으로 찾는다")
args = ap.parse_args()
src, buildings, out_table, out_prefix, base_date, stores = (args.src, args.buildings, args.out_table, args.out_prefix,
                                                            args.base_date, args.stores)
SBIZ_BULK_MONTHS = (202406, 202409, 202410, 202411)  # 실제 개업이 아니라 데이터 보강으로 보이는 대량 등록 달
INHERIT_GAP_YEARS = 5
DETAIL_Z = 16  # 정적 상세 JSON을 나눌 타일 줌(칸 하나 약 600m)
BAEKNYEON_MIN_YEARS = 30  # 백년가게 지정 요건(업력 30년 이상)
CHAIN_MIN_STORES = 3  # 같은 브랜드가 이만큼 있으면 체인으로 표시
BAEKNYEON_LINK_M = 1000  # 이전한 백년가게의 옛 자리·새 자리를 같은 가게로 볼 거리
SAME_STORE_M = 100  # 스냅샷끼리 같은 가게로 볼 거리(상호명이 같을 때)
PREDECESSOR_M = 15  # 전 주인(같은 자리의 다른 음식점)으로 볼 거리. 상가정보 좌표는 건물 단위
INHERIT_SURE_YEARS = 30  # 이만큼 차이 나면 전 주인 흔적이 없어도 승계로 본다(상가정보에 수십 년 누락될 가능성은 낮다)
PREDECESSOR_MAX_FOOD = 2  # 그 자리의 음식점이 이보다 많으면(다중 입주 건물) 전 주인을 특정할 수 없어 보정하지 않는다
sys.stdout.reconfigure(encoding="utf-8")
PTS_Z = 9
base_year = int(base_date[:4])

con = duckdb.connect()
con.sql("INSTALL spatial; LOAD spatial; SET geometry_always_xy = true; SET threads=8; SET preserve_insertion_order=false;")
t0 = time.time()


def log(*a):
    print(*a, f"{time.time() - t0:.0f}s", flush=True)


con.sql(f"""
CREATE TABLE r AS
WITH src AS (
  SELECT *, ST_Transform(ST_Point(trim("좌표정보(X)")::DOUBLE, trim("좌표정보(Y)")::DOUBLE), 'EPSG:5174', 'EPSG:4326') AS g
  FROM read_csv('{src}', all_varchar=true, header=true)
  WHERE 영업상태명 = '영업/정상' AND nullif(trim("좌표정보(X)"), '') IS NOT NULL
)
SELECT
  row_number() OVER (ORDER BY 관리번호) - 1 AS fid,
  관리번호 AS id, trim(사업장명) AS name, 업태구분명 AS kind,
  TRY_CAST(인허가일자 AS DATE) AS open_date,
  year(TRY_CAST(인허가일자 AS DATE)) AS open_year,
  coalesce(nullif(trim(도로명주소), ''), trim(지번주소)) AS address,
  nullif(trim(전화번호), '') AS phone,
  TRY_CAST(시설총규모 AS DOUBLE) AS area_m2,
  전통업소지정번호 IS NOT NULL AS traditional,
  round(ST_X(g), 7) AS lon, round(ST_Y(g), 7) AS lat
FROM src  -- 인허가일자가 없거나 읽을 수 없어도 남긴다(연도 미상으로 표시)
""")
con.sql(f"ALTER TABLE r ADD COLUMN years INTEGER; UPDATE r SET years = {base_year} - open_year;")
tiling.match_buildings(con, "r", buildings)
# 건물명 칸(상가정보·Overture)에는 '일부', '우측', '1~2층', '나호', '102동' 같은 위치·층·호수 표기가 섞여 있어 걸러낸다.
con.sql(r"""
CREATE MACRO real_building_name(b) AS CASE WHEN
  length(b) >= 3
  AND NOT regexp_matches(b, '^(우측|좌측|일부|전체|왼쪽|오른쪽|가운데|명칭|지하|지상|비[0-9])')
  AND NOT regexp_matches(b, '[0-9~]+층$|^.{1,2}호$|^[0-9]+(-[0-9]+)?동?$')  -- 층·호수·아파트 동 번호·지번
  AND upper(b) NOT IN ('빌딩', '타워', 'TOWER', '건물', '주택')
  THEN b END
""")
store_names = (f"SELECT bld, mode(real_building_name(building)) AS nm FROM '{stores}' WHERE bld IS NOT NULL GROUP BY bld"
               if stores else "SELECT NULL::VARCHAR AS bld, NULL::VARCHAR AS nm WHERE false")
con.sql(f"""
CREATE OR REPLACE TABLE r AS
SELECT r.*, coalesce(s.nm, real_building_name(o.name)) AS building_name
FROM r LEFT JOIN ({store_names}) s USING (bld)
LEFT JOIN (SELECT id AS bld, name FROM '{buildings}' WHERE name IS NOT NULL) o USING (bld)
""")

# ---- 개업 연도 보정: 인허가 승계 의심이면 상가정보에 처음 등장한 연도 ----
# 상가정보 등록 연월만 보면 업소번호 재발급(재등록)도 신규로 보인다. 그래서 연말 스냅샷(--snapshots)에서
# 같은 상호가 100m 안에 처음 나타난 연도(first_seen_year)를 구하고, 그 연도와 인허가를 비교한다.
con.sql(r"""CREATE MACRO norm_name(s) AS lower(regexp_replace(coalesce(s, ''), '[\s\(\)\[\]\-_.,·&/]+', '', 'g'))""")
snap_sources = [(int(re.search(r"sbiz_(\d{4})", p).group(1)), p) for p in sorted(glob.glob(args.snapshots))] if args.snapshots else []
parts = [f"""SELECT {y} AS snap_year, norm_name(상호명) AS k, norm_name(상호명 || coalesce(지점명, '')) AS kb,
                    TRY_CAST(경도 AS DOUBLE) AS lon, TRY_CAST(위도 AS DOUBLE) AS lat, 상권업종대분류명 = '음식' AS food
             FROM read_csv('{p.replace(os.sep, "/")}', all_varchar=true, header=true, quote='"', escape='"',
                           strict_mode=false, ignore_errors=true)""" for y, p in snap_sources]  # 자동 판별이 실패하는 해가 있어 형식을 명시
if stores:  # 현재 파일(--stores)도 마지막 시점으로 넣는다
    parts.append(f"SELECT {base_year} AS snap_year, norm_name(name), norm_name(name || coalesce(branch, '')), lon, lat, cat_l = 'I2' FROM '{stores}'")
if parts:
    con.sql("CREATE TABLE snap AS " + " UNION ALL ".join(parts))
    con.sql("CREATE TABLE snap_k AS SELECT snap_year, k AS key, lon, lat FROM snap UNION ALL SELECT snap_year, kb, lon, lat FROM snap WHERE kb <> k")
    con.sql(f"""
    CREATE TABLE seen AS
    SELECT r.fid, min(s.snap_year) AS first_seen_year
    FROM r JOIN snap_k s ON s.key = norm_name(r.name)
    WHERE ST_Distance_Sphere(ST_Point(r.lon, r.lat), ST_Point(s.lon, s.lat)) < {SAME_STORE_M}
    GROUP BY r.fid
    """)
    # 전 주인 흔적: 처음 등장하기 직전 연도에 같은 자리(PREDECESSOR_M 안)에 이름이 다른 음식점이 있었고,
    # 그 음식점이 등장 연도에는 그 자리에서 사라졌다. 이게 없으면 가게가 없었던 게 아니라 상가정보에서 빠져 있었던 것일 수 있다.
    con.sql(f"""
    CREATE TABLE pred AS
    WITH spot AS (  -- 직전 연도에 그 자리의 음식점 수. 여러 곳이 입주한 건물은 누가 누구 자리를 이었는지 알 수 없다
      SELECT seen.fid, count(*) AS n_food
      FROM seen JOIN r USING (fid)
      JOIN snap p ON p.snap_year = seen.first_seen_year - 1 AND p.food
        AND ST_Distance_Sphere(ST_Point(r.lon, r.lat), ST_Point(p.lon, p.lat)) < {PREDECESSOR_M}
      GROUP BY seen.fid
    )
    SELECT DISTINCT seen.fid
    FROM seen JOIN r USING (fid) JOIN spot USING (fid)
    JOIN snap p ON p.snap_year = seen.first_seen_year - 1 AND p.food AND p.k <> norm_name(r.name)
      AND ST_Distance_Sphere(ST_Point(r.lon, r.lat), ST_Point(p.lon, p.lat)) < {PREDECESSOR_M}
    WHERE spot.n_food <= {PREDECESSOR_MAX_FOOD} AND NOT EXISTS (
      SELECT 1 FROM snap q WHERE q.snap_year = seen.first_seen_year AND q.k = p.k
        AND ST_Distance_Sphere(ST_Point(p.lon, p.lat), ST_Point(q.lon, q.lat)) < {PREDECESSOR_M})
    """)
else:
    con.sql("CREATE TABLE seen AS SELECT NULL::BIGINT AS fid, NULL::INTEGER AS first_seen_year WHERE false")
    con.sql("CREATE TABLE pred AS SELECT NULL::BIGINT AS fid WHERE false")
first_snap = min((y for y, _ in snap_sources), default=None)
sbiz_reg = (f"""
  SELECT r.fid, min(s.reg_ym) AS sbiz_reg_ym
  FROM r JOIN '{stores}' s ON r.bld = s.bld
    AND norm_name(r.name) IN (norm_name(s.name), norm_name(s.name || coalesce(s.branch, '')))
  GROUP BY r.fid""" if stores else "SELECT NULL::BIGINT AS fid, NULL::INTEGER AS sbiz_reg_ym WHERE false")
con.sql(f"""
CREATE OR REPLACE TABLE r AS
WITH m AS ({sbiz_reg}), x AS (
  SELECT r.* EXCLUDE (years), m.sbiz_reg_ym, seen.first_seen_year, r.open_year AS permit_year,
    -- 첫 스냅샷에 이미 있으면 그 전을 알 수 없고, 대량 등록 달에 들어온 가게는 데이터 범위 확장일 수 있어 제외
    seen.first_seen_year > {first_snap if first_snap else 9999}
      AND (pred.fid IS NOT NULL OR r.open_year <= seen.first_seen_year - {INHERIT_SURE_YEARS})
      AND coalesce(m.sbiz_reg_ym, 0) NOT IN {SBIZ_BULK_MONTHS}
      AND r.open_year <= seen.first_seen_year - {INHERIT_GAP_YEARS} AS inherited
  FROM r LEFT JOIN m USING (fid) LEFT JOIN seen USING (fid) LEFT JOIN pred USING (fid)
)
SELECT * EXCLUDE (open_year, inherited),
  CASE WHEN inherited THEN first_seen_year ELSE permit_year END AS open_year,
  CASE WHEN inherited THEN 'sbiz' ELSE 'permit' END AS year_source,
  {base_year} - CASE WHEN inherited THEN first_seen_year ELSE permit_year END AS years
FROM x
""")

# ---- 백년가게: 업력 30년 이상이 공식 확인된 가게 ----
# 지정 데이터에는 창업 연도가 없다. 대신 30년 이상은 확실하니, 인허가(이전·재허가로 늦게 찍힌 경우)가
# 그보다 늦으면 상한 연도로 올리고, 상가정보 보정으로 젊어지지 않게 한다.
# 매칭: 상호 + 도로명·건물번호, 안 되면 같은 구에 같은 상호가 한 곳뿐일 때만.
con.sql(r"""CREATE MACRO road_key(a) AS replace(regexp_extract(coalesce(a, ''), '([가-힣0-9]+(로|길))\s*[0-9]+(-[0-9]+)?', 0), ' ', '')""")  # 예: '경희궁2길14-4'
con.sql(r"""CREATE MACRO gu_of(a) AS regexp_extract(coalesce(a, ''), '([가-힣]+구)\s', 1)""")
bk_parts = []
for path in args.baeknyeon:
    cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_csv('{path}', all_varchar=true, header=true, quote='\"', escape='\"', strict_mode=false)").fetchall()]
    addr_col = next(c for c in ("업체주소", "기본주소") if c in cols)
    bk_parts.append(f"""SELECT 업체명 AS name, {addr_col} AS addr
      FROM read_csv('{path}', all_varchar=true, header=true, quote='"', escape='"', strict_mode=false)""")
if bk_parts:
    con.sql("CREATE TABLE bk AS SELECT DISTINCT norm_name(name) AS k, road_key(addr) AS rk, gu_of(addr) AS gu FROM (" + " UNION ALL ".join(bk_parts) + ") WHERE addr LIKE '서울%'")
    con.sql("""
    CREATE TABLE bk_hit AS
    SELECT DISTINCT r.fid FROM r JOIN bk ON bk.k = norm_name(r.name) AND bk.rk <> '' AND bk.rk = road_key(r.address)
    UNION
    SELECT r.fid FROM r JOIN bk ON bk.k = norm_name(r.name) AND bk.gu = gu_of(r.address)
    WHERE (SELECT count(*) FROM r r2 WHERE norm_name(r2.name) = bk.k AND gu_of(r2.address) = bk.gu) = 1
    """)
else:
    con.sql("CREATE TABLE bk_hit AS SELECT NULL::BIGINT AS fid WHERE false")
bk_cap = base_year - BAEKNYEON_MIN_YEARS
# 이전한 백년가게: 매칭된 가게를 기준으로 BAEKNYEON_LINK_M 안의 같은 상호 인허가 기록(영업 중·폐업 모두)을 같은 가게로 보고,
# 그중 가장 이른 인허가 연도를 쓴다. 새 자리의 영업 중 기록에도 백년가게 표시를 붙인다.
# 예: 이문설농탕 견지동(1977) + 공평동 폐업 기록(1969) → 1969, 신안촌 내수동 새 자리(2025) + 내자동(1986) → 1986
# 이력을 이을 때만 쓰는 상호 키: 같은 음식의 다른 표기를 하나로(예: 이문설농탕 ↔ 공평동 시절 이문설렁탕)
con.sql("CREATE MACRO link_key(s) AS replace(norm_name(s), '설농탕', '설렁탕')")
con.sql(f"""
CREATE TABLE allp AS
SELECT link_key(사업장명) AS k, year(TRY_CAST(인허가일자 AS DATE)) AS py,
       gu_of(coalesce(nullif(trim(도로명주소), ''), 지번주소)) AS gu,
       CASE WHEN nullif(trim("좌표정보(X)"), '') IS NOT NULL THEN
         ST_Transform(ST_Point(trim("좌표정보(X)")::DOUBLE, trim("좌표정보(Y)")::DOUBLE), 'EPSG:5174', 'EPSG:4326') END AS g
FROM read_csv('{src}', all_varchar=true, header=true)  -- 오래된 폐업 기록은 좌표가 없는 경우가 있어 구로도 잇는다
""")
con.sql(f"""
CREATE TABLE bk_year AS
WITH anchor AS (SELECT r.fid, link_key(r.name) AS k, ST_Point(r.lon, r.lat) AS g, gu_of(r.address) AS gu, r.permit_year
                FROM r JOIN bk_hit USING (fid)),
related AS (  -- 기준 가게 주변의 같은 상호 기록 → 기준 가게별 가장 이른 연도
  SELECT a.fid, least(min(p.py), min(a.permit_year)) AS y FROM anchor a
  JOIN allp p ON p.k = a.k AND (ST_Distance_Sphere(a.g, p.g) < {BAEKNYEON_LINK_M} OR (p.g IS NULL AND p.gu = a.gu))
  GROUP BY a.fid
),
moved AS (  -- 기준 가게 주변에서 영업 중인 같은 상호(옮긴 새 자리)도 같은 연도로
  SELECT r.fid, min(rel.y) AS y FROM anchor a JOIN related rel USING (fid)
  JOIN r ON link_key(r.name) = a.k AND ST_Distance_Sphere(a.g, ST_Point(r.lon, r.lat)) < {BAEKNYEON_LINK_M}
  GROUP BY r.fid
)
SELECT fid, min(y) AS bk_y FROM (SELECT * FROM related UNION ALL SELECT * FROM moved) GROUP BY fid
""")
con.sql(f"""
CREATE OR REPLACE TABLE r AS
WITH y AS (SELECT r.*, b.bk_y, least(coalesce(b.bk_y, {bk_cap}), {bk_cap}) AS bk_open FROM r LEFT JOIN bk_year b USING (fid))
SELECT * EXCLUDE (open_year, year_source, years, bk_y, bk_open), bk_y IS NOT NULL AS baeknyeon,
  CASE WHEN bk_y IS NULL THEN open_year ELSE bk_open END AS open_year,
  CASE WHEN bk_y IS NULL THEN year_source WHEN bk_open IS DISTINCT FROM permit_year THEN 'baeknyeon' ELSE 'permit' END AS year_source,
  {base_year} - CASE WHEN bk_y IS NULL THEN open_year ELSE bk_open END AS years
FROM y
""")
log("baeknyeon (stores, year changed):", con.execute("SELECT count_if(baeknyeon), count_if(year_source = 'baeknyeon') FROM r").fetchall()[0])
log("first seen in snapshots:", con.execute("SELECT count(first_seen_year), count(*) FROM r").fetchall()[0],
    "| opening year from snapshots (inherited permit):", con.execute("SELECT count_if(year_source = 'sbiz') FROM r").fetchall()[0][0])

# ---- 체인점 표시 ----
# 상호 끝의 지점명('○○점', '(○○점)')을 뗀 브랜드가 서울에 CHAIN_MIN_STORES곳 이상이면 체인으로 본다.
# 지점명 앞에 띄어쓰기나 괄호가 있어야 나눈다(영신반점·소숯점처럼 한 단어 상호는 나누지 않음). 연도는 바꾸지 않고 표시만 한다.
con.sql(r"""CREATE MACRO brand_of(n) AS nullif(lower(regexp_replace(
  regexp_extract(regexp_replace(trim(n), '\(주\)|주식회사', '', 'g'), '^(.+?)(\s+|\()[^\s()]+점\)?$', 1), '\s+', '', 'g')), '')""")
con.sql(f"""
CREATE OR REPLACE TABLE r AS
WITH c AS (SELECT brand_of(name) AS br FROM r WHERE brand_of(name) IS NOT NULL GROUP BY 1 HAVING count(*) >= {CHAIN_MIN_STORES})
SELECT r.*, c.br IS NOT NULL AS chain FROM r LEFT JOIN c ON c.br = brand_of(r.name)
""")
log("chain stores:", con.execute("SELECT count_if(chain) FROM r").fetchall()[0][0])

# ---- 가까운 지하철역 ----
if args.stations:
    con.sql(f"""
    CREATE TABLE st AS
    SELECT regexp_replace(coalesce(names.common['ko'], names.primary), '역$', '') || '역' AS name,
           avg(ST_X(ST_Centroid(geometry))) AS lon, avg(ST_Y(ST_Centroid(geometry))) AS lat
    FROM '{args.stations}'
    WHERE type = 'infrastructure' AND class = 'subway_station' AND names.primary IS NOT NULL
    GROUP BY 1  -- 노선마다 따로 있는 같은 이름의 역을 하나로
    """)
    con.sql("""
    CREATE OR REPLACE TABLE r AS
    SELECT r.*, n.station, n.station_m FROM r LEFT JOIN (
      SELECT r.fid, arg_min(st.name, d) AS station, round(min(d))::INTEGER AS station_m
      FROM r, st, LATERAL (SELECT ST_Distance_Sphere(ST_Point(r.lon, r.lat), ST_Point(st.lon, st.lat)) AS d)
      GROUP BY r.fid) n USING (fid)
    """)
    path = f"{out_prefix}_stations.geojson"
    rows = con.execute("SELECT name, lon, lat FROM st ORDER BY name").fetchall()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": n}, "geometry": {"type": "Point", "coordinates": [round(x, 6), round(y, 6)]}}
            for n, x, y in rows]}, f, ensure_ascii=False)
    log(len(rows), "stations ->", path)

# ---- 같은 건물·같은 상호의 인허가 여러 건을 한 가게로 ----
# 옆 칸으로 넓히며 허가를 따로 받은 경우 등(예: 설이동 종로3길 28-6 1977년 + 24-17 2008년).
# 가장 이른 연도의 기록을 대표로 남기고, 허가 수(permit_count)와 면적 합을 둔다.
con.sql("""
CREATE OR REPLACE TABLE r AS
WITH g AS (
  SELECT *, norm_name(name) AS nk,
    row_number() OVER (PARTITION BY gid, norm_name(name) ORDER BY open_year NULLS LAST, open_date NULLS LAST, fid) AS rk,
    count(*) OVER (PARTITION BY gid, norm_name(name)) AS permit_count,
    sum(area_m2) OVER (PARTITION BY gid, norm_name(name)) AS area_sum,
    bool_or(baeknyeon) OVER (PARTITION BY gid, norm_name(name)) AS bk_any,
    bool_or(chain) OVER (PARTITION BY gid, norm_name(name)) AS chain_any,
    bool_or(traditional) OVER (PARTITION BY gid, norm_name(name)) AS trad_any
  FROM r
)
SELECT * EXCLUDE (nk, rk, area_sum, bk_any, chain_any, trad_any, area_m2, baeknyeon, chain, traditional),
  area_sum AS area_m2, bk_any AS baeknyeon, chain_any AS chain, trad_any AS traditional
FROM g WHERE rk = 1
""")
log("merged same-name permits in a building ->", con.execute("SELECT count(*), count_if(permit_count > 1) FROM r").fetchall()[0])

con.sql(f"COPY r TO '{out_table}' (FORMAT parquet, COMPRESSION zstd)")
log(*con.execute("""SELECT count(*) || ' restaurants, ' || count_if(bld IS NOT NULL) || ' in buildings, '
                    || count(DISTINCT gid) || ' groups' FROM r""").fetchall()[0], "->", out_table)
con.sql("CREATE TABLE gn AS SELECT gid, count(*) AS n FROM r GROUP BY gid")
# 상세 목록을 정적 JSON으로 나눠 담을 칸: 건물(gid)의 대표 좌표가 속한 z{DETAIL_Z} 타일. 타일 속성 k로 뷰어에 알려 준다
con.sql(f"""
CREATE TABLE shard AS
SELECT gid, floor((lon + 180) / 360 * {1 << DETAIL_Z})::INT || '-' ||
            floor((1 - ln(tan(radians(lat)) + 1 / cos(radians(lat))) / pi()) / 2 * {1 << DETAIL_Z})::INT AS k
FROM (SELECT gid, arg_min(lon, fid) AS lon, arg_min(lat, fid) AS lat FROM r GROUP BY gid)
""")

x0, x1, y0, y1 = con.execute("SELECT min(lon), max(lon), min(lat), max(lat) FROM r").fetchall()[0]
attribution = "행정안전부 지방행정 인허가(식품_일반음식점) · Overture Maps buildings"


def finalize(writer, z, name, layers):
    writer.finalize(
        {
            "tile_type": TileType.MVT, "tile_compression": Compression.GZIP, "min_zoom": z, "max_zoom": z,
            "min_lon_e7": int(x0 * 1e7), "min_lat_e7": int(y0 * 1e7), "max_lon_e7": int(x1 * 1e7), "max_lat_e7": int(y1 * 1e7),
            "center_zoom": max(z, 11), "center_lon_e7": int((x0 + x1) / 2 * 1e7), "center_lat_e7": int((y0 + y1) / 2 * 1e7),
        },
        {"name": name, "attribution": attribution,
         "vector_layers": [{"id": lid, "minzoom": z, "maxzoom": z, "fields": fields} for lid, fields in layers]},
    )


# ---- z14: 음식점별 건물 폴리곤 / 점 ----
# 그리는 순서 = 타일에 쓴 순서. 새로운 가게를 먼저, 오래된 가게를 나중에(위에) 쓴다.
DRAW_ORDER = "ORDER BY r.open_year DESC NULLS FIRST, r.fid"
keys = ["y", "g", "name", "n", "b", "k"]
# b: 백년가게 표시(1 = 인허가 연도 그대로, 2 = 30년 이상으로 올림)
props_sql = "r.open_year, r.gid, r.name, gn.n, CASE WHEN r.year_source = 'baeknyeon' THEN 2 WHEN r.baeknyeon THEN 1 END, sh.k"
tiles = tiling.new_tiles()
tiling.add_polygons(tiles, "bldg", con.execute(
    f"SELECT r.fid, ST_AsWKB(b.g), {props_sql} FROM r JOIN b USING (bld) JOIN gn USING (gid) JOIN shard sh USING (gid) {DRAW_ORDER}").fetchall())
tiling.add_points(tiles, "store", con.execute(
    f"SELECT r.fid, r.lon, r.lat, {props_sql} FROM r JOIN gn USING (gid) JOIN shard sh USING (gid) WHERE r.bld IS NULL {DRAW_ORDER}").fetchall())
path = f"{out_prefix}_bldg.pmtiles"
with open(path, "wb") as f:
    w = Writer(f)
    log(f"z{tiling.POINT_Z}:", tiling.write_point_zoom(w, tiles, keys), "tiles")
    fields = {"y": "Number", "g": "Number", "name": "String", "n": "Number", "b": "Number", "k": "String"}
    finalize(w, tiling.POINT_Z, "서울 일반음식점 (건물)", [("bldg", fields), ("store", fields)])
log("done", path)

# ---- z9: 축소 시 개별 점 ----
path = f"{out_prefix}_pts.pmtiles"
with open(path, "wb") as f:
    w = Writer(f)
    n = tiling.write_points_at_zoom(w, PTS_Z, "pt", ["y"], con.execute(f"SELECT NULL, lon, lat, open_year FROM r {DRAW_ORDER}").fetchall())  # 점은 id가 필요 없어 생략
    log(f"z{PTS_Z}:", n, "tiles")
    finalize(w, PTS_Z, "서울 일반음식점 (점)", [("pt", {"y": "Number"})])
log("done", path)

# ---- 건물별 상세 목록(정적 JSON): <out>_detail/<k>.json = {gid: {...}} ----
# 서버 없이(정적 호스팅) hover·상세 목록을 보여주기 위한 것. 형식은 serve.py의 /api/restaurants/<gid>와 같다.
detail_dir = f"{out_prefix}_detail"
shutil.rmtree(detail_dir, ignore_errors=True)
os.makedirs(detail_dir)
rows = con.execute("""
  SELECT sh.k, r.gid, r.name, r.kind, strftime(r.open_date, '%Y-%m-%d'), r.open_year, r.permit_year, r.year_source, r.years,
         r.address, r.traditional, r.baeknyeon, r.chain, r.permit_count, r.building_name, r.station, r.station_m
  FROM r JOIN shard sh USING (gid)
  ORDER BY sh.k, r.gid, r.open_year NULLS LAST, r.open_date NULLS LAST, r.name
""").fetchall()
ROAD_ADDR = re.compile(r"^(.+?(?:로|길)\s+\d+(?:-\d+)?)(?=[\s,(]|$)")


def building_address(a):
    """가게 주소에서 층·호수를 떼고 건물 주소만 남긴다.
    '서울특별시 용산구 보광로 118, 2층 (이태원동, ○○빌딩)' → '서울특별시 용산구 보광로 118 (이태원동)'"""
    m = ROAD_ADDR.match(a)
    if not m:
        return a
    dong = re.search(r"\(([^,)]+)", a[m.end():])
    return m.group(1) + (f" ({dong.group(1).strip()})" if dong else "")


shards = defaultdict(lambda: defaultdict(list))
for k, gid, *rest in rows:
    shards[k][gid].append(rest)
for k, buildings_ in shards.items():
    out = {}
    for gid, items in buildings_.items():
        names = Counter(i[12] for i in items if i[12])
        addrs = Counter(building_address(i[7]) for i in items if i[7])
        near = min((i for i in items if i[14] is not None), key=lambda i: i[14], default=None)
        out[gid] = {
            "count": len(items),
            "building": names.most_common(1)[0][0] if names else None,
            "address": addrs.most_common(1)[0][0] if addrs else None,
            "station": near and near[13], "station_m": near and near[14],
            "restaurants": [dict(zip(("name", "kind", "open_date", "open_year", "permit_year", "year_source", "years",
                                      "address", "traditional", "baeknyeon", "chain", "permit_count"), i[:12])) for i in items],
        }
    with open(f"{detail_dir}/{k}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
log(len(shards), "detail shards ->", detail_dir)

# ---- 연도별 개수 (뷰어 슬라이더 위 히스토그램·구간 합계용) ----
path = f"{out_prefix}_hist.json"
hist = dict(con.execute("SELECT open_year, count(*) FROM r WHERE open_year IS NOT NULL GROUP BY 1 ORDER BY 1").fetchall())
unknown = con.execute("SELECT count(*) FROM r WHERE open_year IS NULL").fetchall()[0][0]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"base_date": base_date, "total": sum(hist.values()) + unknown, "unknown": unknown,
               "years": {str(k): v for k, v in hist.items()}}, f)
log("done", path)
