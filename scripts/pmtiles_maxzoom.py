"""PMTiles에서 maxzoom 이하 타일만 남겨 새 파일로 쓴다(더 확대하면 뷰어가 maxzoom 타일을 늘려 쓴다).
Cloudflare Pages 파일당 25MiB 제한에 맞추려고 만들었다.

사용: python pmtiles_maxzoom.py <in.pmtiles> <out.pmtiles> <maxzoom>
"""
import sys
from pmtiles.reader import Reader, MmapSource, all_tiles
from pmtiles.tile import zxy_to_tileid
from pmtiles.writer import Writer

src, out, maxzoom = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(src, "rb") as f:
    r = Reader(MmapSource(f))
    header, metadata = r.header(), r.metadata()
    tiles = sorted((zxy_to_tileid(z, x, y), d) for (z, x, y), d in all_tiles(r.get_bytes) if z <= maxzoom)
with open(out, "wb") as f:
    w = Writer(f)
    for tid, d in tiles:
        w.write_tile(tid, d)
    header["max_zoom"] = maxzoom
    for layer in metadata.get("vector_layers", []):
        layer["maxzoom"] = min(layer.get("maxzoom", maxzoom), maxzoom)
    w.finalize(header, metadata)
print(len(tiles), "tiles ->", out)
