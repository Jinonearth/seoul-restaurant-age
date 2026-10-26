"""원격 PMTiles에서 특정 지점의 줌별 타일을 받아 레이어별 피처 수와 샘플 속성을 출력."""
import sys, gzip, urllib.request, mercantile, mapbox_vector_tile
from pmtiles.reader import Reader
url, lon, lat = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
zooms = [int(z) for z in sys.argv[4].split(",")]
def get_bytes(offset, length):
    req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset+length-1}"})
    return urllib.request.urlopen(req).read()
r = Reader(get_bytes)
for z in zooms:
    t = mercantile.tile(lon, lat, z)
    data = r.get(z, t.x, t.y)
    if not data:
        print(z, "no tile"); continue
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    tile = mapbox_vector_tile.decode(data)
    print(z, f"{len(data)/1024:.0f}KB", {k: len(v["features"]) for k, v in tile.items()})
    if z == zooms[-1]:
        for k, v in tile.items():
            print(" sample", {kk: str(vv)[:80] for kk, vv in v["features"][0]["properties"].items()})
