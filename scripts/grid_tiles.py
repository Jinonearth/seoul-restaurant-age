"""전세계 POI 밀도 격자를 PMTiles(MVT)로 생성.

각 줌 z의 타일을 32x32 칸으로 나누고(칸 = z+5 레벨 타일), 칸마다 POI 수·평균 신뢰도·출처 비율을 담는다.
집계는 DuckDB, 인코딩은 정사각형 전용의 최소 MVT 인코더로 처리한다.

사용: python grid_tiles.py data/places_slim.parquet out/poi_grid.pmtiles [maxzoom]
"""
import gzip
import json
import sys
import time

import duckdb
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

SRC, OUT = sys.argv[1], sys.argv[2]
MAXZOOM = int(sys.argv[3]) if len(sys.argv) > 3 else 12
CELL_BITS = 5  # 타일당 2^5 = 32칸
BASE = MAXZOOM + CELL_BITS  # 가장 세밀한 칸의 레벨
EXTENT = 4096
CELL_PX = EXTENT >> CELL_BITS
LAYER = "grid"


# ---- 최소 protobuf / MVT 인코더 ----

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(num, wire, payload):
    if wire == 0:
        return varint(num << 3) + varint(payload)
    return varint(num << 3 | 2) + varint(len(payload)) + payload


def zz(n):
    return (n << 1) ^ (n >> 31)


def packed(nums):
    return b"".join(varint(n) for n in nums)


def encode_tile(cells, keys):
    """cells: [(cx, cy, [prop values...])] (cx, cy는 타일 안의 0..31 칸 좌표)."""
    values, value_idx, feats = [], {}, []
    for cx, cy, props in cells:
        tags = []
        for ki, v in enumerate(props):
            if v not in value_idx:
                value_idx[v] = len(values)
                values.append(v)
            tags += (ki, value_idx[v])
        x0, y0 = cx * CELL_PX, cy * CELL_PX
        geom = [9, zz(x0), zz(y0), 26, zz(CELL_PX), 0, 0, zz(CELL_PX), zz(-CELL_PX), 0, 15]
        feats.append(field(2, 2, field(2, 2, packed(tags)) + field(3, 0, 3) + field(4, 2, packed(geom))))
    layer = field(15, 0, 2) + field(1, 2, LAYER.encode())
    layer += b"".join(feats)
    layer += b"".join(field(3, 2, k.encode()) for k in keys)
    layer += b"".join(field(4, 2, field(5, 0, v)) for v in values)  # uint_value
    layer += field(5, 0, EXTENT)
    return field(3, 2, layer)


# ---- 집계 ----

con = duckdb.connect()
con.sql("SET threads=8; SET preserve_insertion_order=false;")
t0 = time.time()

datasets = [r[0] for r in con.execute(f"""
    SELECT d, count(*) c FROM (SELECT unnest(datasets) d FROM '{SRC}') WHERE d <> 'Overture'  -- 모든 POI에 붙는 출처라 제외
    GROUP BY d ORDER BY c DESC LIMIT 4
""").fetchall()]
print("datasets:", datasets)
ds_cols = ", ".join(f"count_if(list_contains(datasets, '{d}')) AS ds{i}" for i, d in enumerate(datasets))
ds_sums = ", ".join(f"sum(ds{i}) AS ds{i}" for i in range(len(datasets)))

con.sql(f"""
CREATE TABLE base AS
SELECT x, y, count(*) AS n, sum(confidence) AS conf_sum,
       count_if(has_hangul) AS ko, {ds_cols}
FROM (
  SELECT datasets, confidence, has_hangul,
    least(floor((lon + 180) / 360 * (1 << {BASE})), (1 << {BASE}) - 1)::BIGINT AS x,
    least(greatest(floor((1 - ln(tan(radians(lat)) + 1 / cos(radians(lat))) / pi()) / 2 * (1 << {BASE})), 0),
          (1 << {BASE}) - 1)::BIGINT AS y
  FROM '{SRC}'
  WHERE lat BETWEEN -85.05 AND 85.05
)
GROUP BY ALL
""")
print("base cells:", con.execute("SELECT count(*) FROM base").fetchone()[0], f"{time.time()-t0:.0f}s")

keys = ["n", "conf", "ko"] + [f"ds{i}" for i in range(len(datasets))]

writer_f = open(OUT, "wb")
writer = Writer(writer_f)
stats = {}
for z in range(MAXZOOM + 1):
    sh = MAXZOOM - z
    rel = con.execute(f"""
        SELECT cx, cy, sum(n)::BIGINT AS n, sum(conf_sum) AS conf_sum, sum(ko)::BIGINT AS ko, {ds_sums}
        FROM (SELECT *, x >> {sh} AS cx, y >> {sh} AS cy FROM base)
        GROUP BY cx, cy ORDER BY cx >> {CELL_BITS}, cy >> {CELL_BITS}
    """)
    ntiles = nfeat = 0
    cur, cells = None, []

    def flush():
        global ntiles
        tx, ty = cur
        writer.write_tile(zxy_to_tileid(z, tx, ty), gzip.compress(encode_tile(cells, keys), 6))
        ntiles += 1

    while batch := rel.fetchmany(200_000):
        for row in batch:
            cx, cy, n, conf_sum, ko, *ds = row
            tile = (cx >> CELL_BITS, cy >> CELL_BITS)
            if tile != cur:
                if cells:
                    flush()
                cur, cells = tile, []
            # n은 개수, conf는 평균 신뢰도 x100, ko·ds*는 비율(%)
            props = [n, round(100 * conf_sum / n), round(100 * ko / n)] + [round(100 * int(d) / n) for d in ds]
            cells.append((cx & 31, cy & 31, props))
            nfeat += 1
    if cells:
        flush()
    stats[z] = (ntiles, nfeat)
    print(f"z{z}: {ntiles} tiles, {nfeat} cells, {time.time()-t0:.0f}s", flush=True)

writer.finalize(
    {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.GZIP,
        "min_zoom": 0,
        "max_zoom": MAXZOOM,
        "min_lon_e7": -1800000000, "min_lat_e7": -850000000,
        "max_lon_e7": 1800000000, "max_lat_e7": 850000000,
        "center_zoom": 2, "center_lon_e7": 1270000000, "center_lat_e7": 375000000,
    },
    {
        "name": "Overture POI density grid",
        "attribution": '<a href="https://docs.overturemaps.org/attribution">&copy; Overture Maps Foundation</a>',
        "datasets": json.dumps({f"ds{i}": d for i, d in enumerate(datasets)}),
        "vector_layers": [{
            "id": LAYER, "minzoom": 0, "maxzoom": MAXZOOM,
            "fields": {k: "Number" for k in keys},
        }],
    },
)
writer_f.close()
print("done", OUT, f"{time.time()-t0:.0f}s")
