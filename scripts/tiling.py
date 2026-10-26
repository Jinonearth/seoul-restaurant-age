"""POI를 건물 폴리곤에 붙여 PMTiles로 만드는 공용 단계 (상가 지도·음식점 지도가 함께 쓴다).

  match_buildings: POI 좌표를 건물 폴리곤에 매칭(포함 → SNAP_M 이내 최근접)하고 그룹 id(gid)를 부여한다.
  add_polygons / add_points: 그룹을 z14 타일 피처로 만든다(폴리곤은 타일 경계에서 자른다).
  write_grid: z0–13 격자 레이어를 쓴다.
"""
import gzip
import math
from collections import defaultdict

import numpy as np
import shapely
from pmtiles.tile import zxy_to_tileid

import mvt

POINT_Z = 14
CELL_BITS = 5
GRID_MAXZOOM = POINT_Z - 1
BASE = GRID_MAXZOOM + CELL_BITS
SNAP_M = 10  # 폴리곤 밖 좌표를 붙일 최대 거리
CLIP_BUFFER = 64  # 타일 경계 밖으로 남길 여유(타일 좌표 단위)
WORLD = (1 << POINT_Z) * mvt.EXTENT
MERC_Y_SQL = "(1 - ln(tan(radians(lat)) + 1 / cos(radians(lat))) / pi()) / 2"


def match_buildings(con, table, buildings):
    """table(lon, lat, ...)에 bld(건물 id 또는 NULL)와 gid(건물, 또는 건물 없는 좌표 하나당 하나)를 추가한다.
    건물 테이블 b(bld, g)를 만들어 두므로 add_polygons에서 쓴다."""
    con.sql(f"CREATE OR REPLACE TABLE b AS SELECT id AS bld, ST_GeomFromWKB(wkb) AS g FROM '{buildings}'")
    con.sql(f"""
    CREATE OR REPLACE TABLE pts AS
    SELECT row_number() OVER (ORDER BY lon, lat) - 1 AS bid, lon, lat, ST_Point(lon, lat) AS g
    FROM (SELECT DISTINCT lon, lat FROM {table})
    """)
    con.sql("CREATE OR REPLACE TABLE inside AS SELECT p.bid, any_value(b.bld) AS bld FROM pts p JOIN b ON ST_Contains(b.g, p.g) GROUP BY p.bid")
    snap_deg = SNAP_M / 111_000 * 1.15  # 위도 37.5도에서 경도 방향 여유
    con.sql(f"""
    CREATE OR REPLACE TABLE near AS
    SELECT p.bid, arg_min(b.bld, ST_Distance(b.g, p.g)) AS bld
    FROM pts p JOIN b ON ST_DWithin(b.g, p.g, {snap_deg})
    WHERE p.bid NOT IN (SELECT bid FROM inside)
    GROUP BY p.bid
    """)
    con.sql(f"""
    CREATE OR REPLACE TABLE {table} AS
    SELECT t.*, coalesce(i.bld, n.bld) AS bld,
           dense_rank() OVER (ORDER BY coalesce(i.bld, n.bld), CASE WHEN coalesce(i.bld, n.bld) IS NULL THEN p.bid END) - 1 AS gid
    FROM {table} t JOIN pts p USING (lon, lat)
    LEFT JOIN inside i USING (bid) LEFT JOIN near n USING (bid)
    """)


def merc(lon, lat):
    x = (np.asarray(lon) + 180) / 360 * WORLD
    lat_r = np.radians(np.asarray(lat))
    y = (1 - np.log(np.tan(lat_r) + 1 / np.cos(lat_r)) / math.pi) / 2 * WORLD
    return x, y


def new_tiles():
    return defaultdict(lambda: defaultdict(list))


def add_polygons(tiles, layer, rows):
    """rows: [(gid, wkb, *props)]. 전역 픽셀 좌표로 바꾼 뒤 걸치는 z14 타일마다 잘라 넣는다."""
    for gid, wkb, *props in rows:
        geom = shapely.transform(shapely.from_wkb(bytes(wkb)), lambda c: np.column_stack(merc(c[:, 0], c[:, 1])))
        x0, y0, x1, y1 = geom.bounds
        for tx in range(int(x0 // mvt.EXTENT), int(x1 // mvt.EXTENT) + 1):
            for ty in range(int(y0 // mvt.EXTENT), int(y1 // mvt.EXTENT) + 1):
                ox, oy = tx * mvt.EXTENT, ty * mvt.EXTENT
                part = shapely.clip_by_rect(geom, ox - CLIP_BUFFER, oy - CLIP_BUFFER,
                                            ox + mvt.EXTENT + CLIP_BUFFER, oy + mvt.EXTENT + CLIP_BUFFER)
                polys = [part] if part.geom_type == "Polygon" else [g for g in getattr(part, "geoms", []) if g.geom_type == "Polygon"]
                for poly in polys:
                    if poly.is_empty:
                        continue
                    poly = shapely.geometry.polygon.orient(poly, sign=1.0)  # 외곽 양의 면적(타일 좌표 y 아래 방향 기준)
                    rings = []
                    for ring in [poly.exterior, *poly.interiors]:
                        pts = []
                        for x, y in list(ring.coords)[:-1]:
                            q = (round(x - ox), round(y - oy))
                            if not pts or pts[-1] != q:
                                pts.append(q)
                        if len(pts) > 1 and pts[0] == pts[-1]:
                            pts.pop()
                        if len(set(pts)) >= 3:
                            rings.append(pts)
                    if rings:
                        tiles[(tx, ty)][layer].append((gid, mvt.polygon(rings), props))


def add_points(tiles, layer, rows):
    """rows: [(gid, lon, lat, *props)]"""
    for gid, lon, lat, *props in rows:
        x, y = merc(lon, lat)
        x, y = int(x), int(y)
        tiles[(x // mvt.EXTENT, y // mvt.EXTENT)][layer].append((gid, mvt.point(x % mvt.EXTENT, y % mvt.EXTENT), props))


def write_points_at_zoom(writer, z, layer, keys, rows):
    """rows: [(fid 또는 None, lon, lat, *props)]를 줌 z 한 단계의 점 타일로 쓴다(히트맵처럼 저줌에서 전체를 보여줄 때)."""
    world = (1 << z) * mvt.EXTENT
    by_tile = defaultdict(list)
    for fid, lon, lat, *props in rows:
        x = (lon + 180) / 360 * world
        lat_r = math.radians(lat)
        y = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * world
        x, y = int(x), int(y)
        by_tile[(x // mvt.EXTENT, y // mvt.EXTENT)].append((fid, mvt.point(x % mvt.EXTENT, y % mvt.EXTENT), props))
    for (tx, ty), feats in by_tile.items():
        writer.write_tile(zxy_to_tileid(z, tx, ty), gzip.compress(mvt.encode_layer(layer, keys, feats), 6))
    return len(by_tile)


def write_point_zoom(writer, tiles, keys):
    for (tx, ty), layers in tiles.items():
        data = b"".join(mvt.encode_layer(name, keys, feats) for name, feats in layers.items() if feats)
        writer.write_tile(zxy_to_tileid(POINT_Z, tx, ty), gzip.compress(data, 6))
    return len(tiles)


def write_grid(con, writer, table, sums):
    """table의 POI를 z0–13 격자(layer "grid")로 쓴다.
    sums: {key: SQL 집계식}. 'n'(개수)은 자동으로 들어가고, 나머지는 n 대비 비율(%)로 저장한다."""
    agg = ", ".join(f"{expr} AS {k}" for k, expr in sums.items())
    con.sql(f"""
    CREATE OR REPLACE TABLE grid_base AS
    SELECT cx, cy, count(*) AS n, {agg}
    FROM (SELECT *, floor((lon + 180) / 360 * {1 << BASE})::BIGINT AS cx, floor({MERC_Y_SQL} * {1 << BASE})::BIGINT AS cy FROM {table})
    GROUP BY ALL
    """)
    keys = ["n", *sums]
    cols = ", ".join(f"sum({k})::BIGINT" for k in keys)
    cell_px = mvt.EXTENT >> CELL_BITS
    for z in range(GRID_MAXZOOM + 1):
        sh = GRID_MAXZOOM - z
        rows = con.execute(f"""
          SELECT gx, gy, {cols}
          FROM (SELECT *, cx >> {sh} AS gx, cy >> {sh} AS gy FROM grid_base)
          GROUP BY gx, gy ORDER BY gx >> {CELL_BITS}, gy >> {CELL_BITS}
        """).fetchall()
        cur, feats = None, []
        for gx, gy, cnt, *vals in rows:
            tile = (gx >> CELL_BITS, gy >> CELL_BITS)
            if tile != cur:
                if feats:
                    writer.write_tile(zxy_to_tileid(z, *cur), gzip.compress(mvt.encode_layer("grid", keys, feats), 6))
                cur, feats = tile, []
            props = [cnt] + [round(100 * v / cnt) for v in vals]
            feats.append((None, mvt.square((gx & 31) * cell_px, (gy & 31) * cell_px, cell_px), props))
        if feats:
            writer.write_tile(zxy_to_tileid(z, *cur), gzip.compress(mvt.encode_layer("grid", keys, feats), 6))
    return keys
