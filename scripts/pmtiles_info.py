"""원격 PMTiles의 헤더와 메타데이터를 HTTP range 요청으로 읽어 출력."""
import sys, json, urllib.request
from pmtiles.reader import Reader
url = sys.argv[1]
def get_bytes(offset, length):
    req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset+length-1}"})
    return urllib.request.urlopen(req).read()
r = Reader(get_bytes)
h = r.header()
print({k: v for k, v in h.items() if k in ("min_zoom","max_zoom","tile_type","tile_compression","addressed_tiles_count","tile_contents_count","min_lon_e7","max_lon_e7")})
m = r.metadata()
for k, v in m.items():
    if k != "vector_layers" and k != "tilestats":
        print(k, ":", str(v)[:300])
for l in m.get("vector_layers", []):
    print("layer", l["id"], l.get("minzoom"), l.get("maxzoom"), list(l.get("fields", {}).keys()))
