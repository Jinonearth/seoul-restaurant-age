"""PMTiles용 HTTP Range 요청을 지원하는 정적 파일 서버 + 업소 상세 API. 사용: python serve.py [port]

GET /api/store/<fid>         ->  data/seoul_stores.parquet 의 한 행
GET /api/building/<gid>      ->  상가 지도: 한 건물의 업소 목록
GET /api/restaurants/<gid>   ->  음식점 지도: 한 건물의 음식점 목록 (오래된 순)
"""
import json, os, re, sys
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import duckdb

STORES = "data/seoul_stores.parquet"
RESTAURANTS = "data/seoul_restaurants.parquet"
_db = None


def db():
    global _db
    if _db is None:
        _db = duckdb.connect()
        _db.sql(f"CREATE TABLE stores AS SELECT * FROM '{STORES}'")  # 55만 행이라 메모리에 올려둔다
        _db.sql(f"CREATE TABLE restaurants AS SELECT * FROM '{RESTAURANTS}'")
    return _db.cursor()


class RangeHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        m = re.fullmatch(r"/api/store/(\d+)", self.path)
        if m:
            return self.send_json(self.store(int(m.group(1))))
        m = re.fullmatch(r"/api/building/(\d+)", self.path)
        if m:
            return self.send_json(self.building(int(m.group(1))))
        m = re.fullmatch(r"/api/restaurants/(\d+)", self.path)
        if m:
            return self.send_json(self.restaurants(int(m.group(1))))
        return super().do_GET()

    def building(self, gid, limit=300):
        """한 건물(gid)의 업소 목록. 층 순(지하 → 지상), 같은 층은 상호명 순."""
        cur = db()
        rows = cur.execute("""
            SELECT name, branch, cat_l, cat_m_name, cat_s_name, floor, reg_ym, building, road_address, sigungu, dong
            FROM stores WHERE gid = ?
            ORDER BY CASE WHEN floor LIKE 'B%' THEN -TRY_CAST(substr(floor, 2) AS INTEGER) ELSE TRY_CAST(floor AS INTEGER) END NULLS LAST, name
        """, [gid]).fetchall()
        if not rows:
            return None
        cols = [d[0] for d in cur.description]
        stores = [dict(zip(cols, r)) for r in rows]
        first = stores[0]
        return {
            "gid": gid, "count": len(stores),
            "building": Counter(s["building"] for s in stores if s["building"]).most_common(1)[0][0] if any(s["building"] for s in stores) else None,  # 타일 라벨과 같은 최빈값
            "road_address": first["road_address"], "sigungu": first["sigungu"], "dong": first["dong"],
            "stores": [{k: s[k] for k in ("name", "branch", "cat_l", "cat_m_name", "cat_s_name", "floor", "reg_ym")} for s in stores[:limit]],
        }

    def restaurants(self, gid, limit=300):
        """한 건물(gid)의 영업 중인 일반음식점 목록. 인허가일자가 이른 순."""
        cur = db()
        rows = cur.execute("""
            SELECT name, kind, open_date, open_year, permit_year, year_source, years, address, phone, area_m2, traditional, baeknyeon, chain, permit_count,
                   building_name, station, station_m
            FROM restaurants WHERE gid = ? ORDER BY open_year NULLS LAST, open_date, name
        """, [gid]).fetchall()
        if not rows:
            return None
        cols = [d[0] for d in cur.description]
        items = [dict(zip(cols, r)) for r in rows]
        top = lambda key: (Counter(i[key] for i in items if i[key]).most_common(1) or [(None,)])[0][0]
        near = min((i for i in items if i["station_m"] is not None), key=lambda i: i["station_m"], default=None)
        return {"gid": gid, "count": len(items), "building": top("building_name"), "address": top("address"),
                "station": near and near["station"], "station_m": near and near["station_m"],
                "restaurants": [{k: v for k, v in i.items() if k not in ("building_name", "station", "station_m")}
                                for i in items[:limit]]}

    def store(self, fid):
        cur = db()
        rows = cur.execute("SELECT * FROM stores WHERE fid = ?", [fid]).fetchall()
        if not rows:
            return None
        return dict(zip([d[0] for d in cur.description], rows[0]))

    def send_json(self, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(200 if obj is not None else 404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        size = os.path.getsize(path)
        start = int(m.group(1))
        end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        if start >= size:
            self.send_error(416)
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 프로젝트 루트를 서빙
db()  # 첫 요청이 기다리지 않도록 시작할 때 적재
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
print(f"http://localhost:{port}/viewer/")
ThreadingHTTPServer(("127.0.0.1", port), RangeHandler).serve_forever()
