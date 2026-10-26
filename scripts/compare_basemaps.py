"""두 Protomaps 스키마 PMTiles의 레이어별 피처 수를 같은 줌·같은 타일 범위로 비교한다.
타일 경계에 걸친 피처는 양쪽 모두 중복으로 세지므로, 절대값보다 두 지도의 상대 비교용이다.

사용: python compare_basemaps.py <a.pmtiles> <b.pmtiles> <zoom> [layer ...]
"""
import gzip, sys
from collections import Counter
import mapbox_vector_tile
from pmtiles.reader import Reader, MmapSource, all_tiles

a, b, z, *layers = sys.argv[1:]
z = int(z)
layers = layers or ["buildings", "roads", "landuse", "pois", "water", "places"]


def count(path):
    feats, tiles, area = Counter(), 0, Counter()
    with open(path, "rb") as f:
        r = Reader(MmapSource(f))
        for (tz, x, y), data in all_tiles(r.get_bytes):
            if tz != z:
                continue
            tiles += 1
            t = mapbox_vector_tile.decode(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)
            for name in layers:
                if name in t:
                    feats[name] += len(t[name]["features"])
    return tiles, feats


ta, fa = count(a)
tb, fb = count(b)
print(f"z{z} tiles: {ta} vs {tb}")
print(f"{'layer':10s} {'A':>10s} {'B':>10s}  B/A")
for name in layers:
    ratio = f"{fb[name] / fa[name]:.2f}" if fa[name] else "-"
    print(f"{name:10s} {fa[name]:10,d} {fb[name]:10,d}  {ratio}")
