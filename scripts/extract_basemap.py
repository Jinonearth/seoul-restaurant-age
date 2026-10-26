"""원격 PMTiles(예: Protomaps 일일 빌드)에서 bbox 영역의 타일만 잘라 로컬 PMTiles로 저장.

사용: python extract_basemap.py <url> <out.pmtiles> <xmin,ymin,xmax,ymax> [maxzoom]
"""
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import mercantile
from pmtiles.reader import Reader
from pmtiles.tile import zxy_to_tileid
from pmtiles.writer import Writer

url, out, bbox = sys.argv[1], sys.argv[2], [float(v) for v in sys.argv[3].split(",")]
maxzoom = int(sys.argv[4]) if len(sys.argv) > 4 else 15
local = threading.local()


@lru_cache(maxsize=4096)  # 헤더·디렉터리는 같은 범위를 반복해서 읽으니 캐시한다
def get_bytes(offset, length):
    req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": "overture-poi-age-map/0.1"})
    return urllib.request.urlopen(req, timeout=60).read()


reader = Reader(get_bytes)
header, metadata = reader.header(), reader.metadata()
maxzoom = min(maxzoom, header["max_zoom"])
tiles = [t for z in range(maxzoom + 1) for t in mercantile.tiles(*bbox, zooms=z)]
print(f"{len(tiles)} tiles z0-{maxzoom}", flush=True)

def fetch(t):
    return t, reader.get(t.z, t.x, t.y)

with ThreadPoolExecutor(16) as pool:
    results = list(pool.map(fetch, tiles))

results.sort(key=lambda r: zxy_to_tileid(r[0].z, r[0].x, r[0].y))
with open(out, "wb") as f:
    w = Writer(f)
    for t, data in results:
        if data:
            w.write_tile(zxy_to_tileid(t.z, t.x, t.y), data)
    header.update({
        "max_zoom": maxzoom,
        "min_lon_e7": int(bbox[0] * 1e7), "min_lat_e7": int(bbox[1] * 1e7),
        "max_lon_e7": int(bbox[2] * 1e7), "max_lat_e7": int(bbox[3] * 1e7),
        "center_zoom": 11,
        "center_lon_e7": int((bbox[0] + bbox[2]) / 2 * 1e7), "center_lat_e7": int((bbox[1] + bbox[3]) / 2 * 1e7),
    })
    w.finalize(header, metadata)
print("done", out, sum(1 for _, d in results if d), "tiles written")
