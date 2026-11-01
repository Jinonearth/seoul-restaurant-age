"""정적 호스팅(GitHub Pages)에 올릴 사이트 폴더를 만든다.

viewer/restaurants.html → site/index.html. 데이터 경로를 data/로 바꾼다.
기본은 PMTiles 파일을 그대로 복사한다(호스트가 Range 요청을 지원해야 한다. GitHub Pages는 지원).
--split: Range를 지원하지 않는 호스트(Cloudflare Pages 등)용으로 PMTiles를 z/x/y.pbf 폴더로 풀고(압축 해제),
         뷰어의 tileSource()를 그 폴더를 가리키는 소스로 바꾼다.
파일당 MAX_FILE(GitHub 100 MB 제한보다 여유 있게 50 MiB)을 넘으면 실패시킨다.
뷰어의 BASE_YEAR(슬라이더 끝 연도)는 seoul_restaurants_hist.json의 기준일 연도로 바꾼다.
--manifest: fetch_sources.py가 남긴 manifest.json의 기준일로 안내 문구의 자료 시점(상가정보·백년가게)을 바꾼다.

사용: python build_site.py [--split] [--manifest manifest.json] [site 폴더]
"""
import gzip
import json
import os
import re
import shutil
import sys

from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[1:]
split = "--split" in args
args = [a for a in args if a != "--split"]
manifest = None
if "--manifest" in args:
    i = args.index("--manifest")
    manifest = json.load(open(args[i + 1], encoding="utf-8"))
    del args[i:i + 2]
site = args[0] if args else os.path.join(ROOT, "site")
data = os.path.join(site, "data")
MAX_FILE, MAX_FILES = 50 * 1024 * 1024, 20_000

TILESETS = {  # 뷰어 경로 → site/data 안 폴더
    "../out/seoul_restaurants_bldg.pmtiles": "bldg",
    "../out/seoul_restaurants_pts.pmtiles": "pts",
    "../out/basemap_seoul_overture.pmtiles": "basemap",
}
FILES = {  # 뷰어 경로 → site/data 안 이름
    "../out/seoul_restaurants_hist.json": "seoul_restaurants_hist.json",
    "../out/seoul_restaurants_stations.geojson": "seoul_restaurants_stations.geojson",
}
DETAIL = "../out/seoul_restaurants_detail/"
TILE_SOURCE = 'const tileSource = path => ({ url: "pmtiles://" + new URL(path, location.href).href });'


def unpack(src, dst):
    """PMTiles를 dst/{z}/{x}/{y}.pbf로 풀고 MapLibre 소스 속성(minzoom, maxzoom, bounds)을 돌려준다."""
    with open(src, "rb") as f:
        r = Reader(MmapSource(f))
        h = r.header()
        for (z, x, y), tile in all_tiles(r.get_bytes):
            if h["tile_compression"] == Compression.GZIP:
                tile = gzip.decompress(tile)
            os.makedirs(os.path.join(dst, str(z), str(x)), exist_ok=True)
            with open(os.path.join(dst, str(z), str(x), f"{y}.pbf"), "wb") as out:
                out.write(tile)
    return {"minzoom": h["min_zoom"], "maxzoom": h["max_zoom"],
            "bounds": [h["min_lon_e7"] / 1e7, h["min_lat_e7"] / 1e7, h["max_lon_e7"] / 1e7, h["max_lat_e7"] / 1e7]}


shutil.rmtree(site, ignore_errors=True)
os.makedirs(data)
html = open(os.path.join(ROOT, "viewer", "restaurants.html"), encoding="utf-8").read()


def sub1(pattern, repl):
    global html
    html, n = re.subn(pattern, repl, html)
    assert n == 1, pattern


base_date = json.load(open(os.path.join(ROOT, "out", "seoul_restaurants_hist.json"), encoding="utf-8"))["base_date"]
sub1(r"BASE_YEAR = \d{4};", f"BASE_YEAR = {base_date[:4]};")
if manifest:
    first, last, cur = manifest["sbiz_snapshots"][0], manifest["sbiz_snapshots"][-1], manifest["sbiz_current"]
    sub1(r"상가\(상권\)정보의 \d{4}~\d{4}년 연말 시점 자료 및 \d{4}년 \d{1,2}월 자료",
         f"상가(상권)정보의 {first[:4]}~{last[:4]}년 연말 시점 자료 및 {cur[:4]}년 {int(cur[4:6])}월 자료")
    sub1(r"백년가게 지정 목록\(\d{4}년(, \d{4}년)*\)", "백년가게 지정 목록(" + ", ".join(f"{d[:4]}년" for d in manifest["baeknyeon"]) + ")")
    sub1(r"상가\(상권\)정보\(\d{4}~\d{4}\)", f"상가(상권)정보({first[:4]}~{cur[:4]})")

if split:
    dirs = {}
    for ref, name in TILESETS.items():
        assert f'tileSource("{ref}")' in html, ref
        dirs[ref] = {"dir": "data/" + name, **unpack(os.path.join(ROOT, "out", os.path.basename(ref)), os.path.join(data, name))}
    assert TILE_SOURCE in html
    html = html.replace(TILE_SOURCE, f"""const TILE_DIRS = {json.dumps(dirs)};
const tileSource = path => {{
  const {{ dir, ...rest }} = TILE_DIRS[path];
  return {{ ...rest, tiles: [location.href.replace(/[^/]*([?#].*)?$/, "") + dir + "/{{z}}/{{x}}/{{y}}.pbf"] }};
}};""")
else:
    for ref, name in TILESETS.items():
        assert f'tileSource("{ref}")' in html, ref
        html = html.replace(ref, f"data/{name}.pmtiles")
        shutil.copy(os.path.join(ROOT, "out", os.path.basename(ref)), os.path.join(data, f"{name}.pmtiles"))

for ref, name in FILES.items():
    assert ref in html, ref
    html = html.replace(ref, "data/" + name)
    shutil.copy(os.path.join(ROOT, "out", os.path.basename(ref)), os.path.join(data, name))
assert DETAIL in html
html = html.replace(DETAIL, "data/detail/")
shutil.copytree(os.path.join(ROOT, "out", "seoul_restaurants_detail"), os.path.join(data, "detail"))
assert "/api/" not in html and (split and "pmtiles://" not in html or not split and "../" not in html)  # split이면 ../out/ 경로가 TILE_DIRS 키로만 남는다
with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)

sizes = [(os.path.getsize(os.path.join(d, n)), os.path.join(d, n)) for d, _, ns in os.walk(site) for n in ns]
big = max(sizes)
print(f"{len(sizes)} files, {sum(s for s, _ in sizes) / 2**20:.1f} MiB, largest {big[0] / 2**20:.1f} MiB {os.path.relpath(big[1], site)}")
assert len(sizes) <= MAX_FILES, "파일 수 한도 초과"
assert big[0] <= MAX_FILE, "파일 크기 한도 초과"
