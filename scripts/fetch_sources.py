"""음식점 지도 빌드에 쓰는 공공데이터를 받아 UTF-8 CSV로 풀어 둔다. CI(.github/workflows/build.yml)와 로컬에서 같이 쓴다.

  <data>/raw/localdata/seoul.csv          지방행정 인허가 식품_일반음식점 서울 전체(폐업 포함). 매번 새로 받는다
  <data>/raw/sbiz_current/seoul.csv       상가(상권)정보 최신 파일의 서울 부분. 기준일이 바뀔 때만 받는다
  <data>/raw/sbiz_<YYYY>1231/seoul.csv    상가정보 연말 스냅샷(FIRST_SNAPSHOT년 ~ 최신 파일 전년). 이미 있으면 건너뛴다
  <data>/raw/baeknyeon/<YYYYMMDD>.csv     백년가게 지정 목록(두 데이터셋의 최신 + 과거 파일 전부). 이미 있으면 건너뛴다
  <data>/raw/manifest.json                받은 자료의 기준일 (build_site.py가 안내 문구에 쓴다)

공공데이터포털 파일 목록은 사이트가 쓰는 것과 같은 요청(파일 상세 페이지 → 과거 데이터 목록)으로 얻는다.
다운로드는 download_sbiz_snapshots.sh와 같은 순서(파일 ID 조회 → 사용량 확인 → 다운로드)로 한다.

사용: python fetch_sources.py <data_dir>
"""
import datetime
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

FIRST_SNAPSHOT = 2019  # 상가정보 연말 스냅샷을 쓰는 첫해 (build_restaurant_tiles.py는 첫 스냅샷 이전 개업을 알 수 없다고 본다)
SBIZ_PK = "15083033"
BAEKNYEON_PKS = ("15132695", "15102255")  # 전국 백년가게 지정리스트 현황 정보(2024~), 전국 백년가게 현황(2022)
LOCALDATA_PK = "15045016"
LOCALDATA_URL = "https://file.localdata.go.kr/file/download/general_restaurants/info?orgCode=6110000_ALL"
UA = "Mozilla/5.0 (seoul-restaurant-age)"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8")

data = sys.argv[1]
raw = os.path.join(data, "raw")
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url, data=None, referer=None, timeout=120):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                 headers={"User-Agent": UA, **({"Referer": referer} if referer else {})})
    return opener.open(req, timeout=timeout)


def save(resp, path):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f, 1 << 20)
    os.replace(tmp, path)


def to_utf8(src, dst):
    """CP949·UTF-8 어느 쪽이든 UTF-8로 저장한다."""
    raw_bytes = open(src, "rb").read()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text, enc = raw_bytes.decode("cp949", errors="replace"), "cp949(replace)"
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    return enc


def datago_files(pk):
    """공공데이터포털 파일데이터의 [(기준일 YYYYMMDD, publicDataDetailPk)], 최신 파일이 맨 앞."""
    page = f"https://www.data.go.kr/data/{pk}/fileData.do"
    html = get(page).read().decode("utf-8")
    current = re.search(r'detailPk = "([^"]+)"', html).group(1)
    current_date = re.search(r"_(\d{8})\s*\|\s*공공데이터포털", html) or re.search(r"<title>[^<]*?(\d{8})", html)
    hist = get("https://www.data.go.kr/tcs/dss/selectHistAndCsvData.do", {"publicDataPk": pk, "publicDataDetailPk": current},
               referer=page).read().decode("utf-8")
    files = [(current_date.group(1), current)]
    for detail, title in re.findall(r'data-public-pk="(uddi:[^"]+)"[^>]*>\s*([^<]+?)\s*<', hist):
        m = re.search(r"_(\d{8})$", title)
        if m and detail != current:
            files.append((m.group(1), detail))
    return files


def datago_download(pk, detail, path):
    page = f"https://www.data.go.kr/data/{pk}/fileData.do"
    get(page).read()
    meta = json.load(get(f"https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?recommendDataYn=Y&publicDataPk={pk}"
                         f"&publicDataDetailPk={urllib.parse.quote(detail)}", referer=page))
    text = json.dumps(meta)
    fid = re.search(r'"atchFileId": "([^"]+)"', text).group(1)
    sn = re.search(r'"fileDetailSn": "([^"]+)"', text).group(1)
    limit = json.load(get("https://www.data.go.kr/cmm/cmm/check-limit.json", {"atchFileId": fid, "fileDetailSn": sn}, referer=page))
    if limit.get("needCaptcha"):
        sys.exit(f"{pk} {detail}: 다운로드 한도에 걸려 CAPTCHA가 필요합니다. 나중에 다시 실행하세요.")
    save(get(f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={fid}&fileDetailSn={sn}", referer=page, timeout=1800), path)
    print(pk, detail, f"{os.path.getsize(path) / 1e6:.0f}MB", flush=True)


def sbiz_seoul(detail, out_dir, date):
    """상가정보 zip을 받아 서울 CSV만 남긴다. 이미 같은 기준일 파일이 있으면 건너뛴다."""
    csv, stamp = os.path.join(out_dir, "seoul.csv"), os.path.join(out_dir, "date.txt")
    if os.path.exists(csv) and os.path.exists(stamp) and open(stamp).read().strip() == date:
        print(f"sbiz {date} already ({out_dir})")
        return
    os.makedirs(out_dir, exist_ok=True)
    zp = os.path.join(out_dir, "sbiz.zip")
    datago_download(SBIZ_PK, detail, zp)
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "extract_sbiz_seoul.py"), zp, csv], check=True)
    os.remove(zp)
    with open(stamp, "w") as f:
        f.write(date)


os.makedirs(raw, exist_ok=True)

# ---- 인허가: 서울 전체(폐업 포함) ----
d = os.path.join(raw, "localdata")
os.makedirs(d, exist_ok=True)
page = f"https://www.data.go.kr/data/{LOCALDATA_PK}/fileData.do"
get(page).read()
get("https://file.localdata.go.kr/file/validate/download-count", referer=page).read()
save(get(LOCALDATA_URL, referer=page, timeout=1800), os.path.join(d, "seoul.download"))
enc = to_utf8(os.path.join(d, "seoul.download"), os.path.join(d, "seoul.csv"))
os.remove(os.path.join(d, "seoul.download"))
localdata_date = datetime.date.today().isoformat()
print("localdata", enc, f"{os.path.getsize(os.path.join(d, 'seoul.csv')) / 1e6:.0f}MB", flush=True)

# ---- 상가정보: 최신 파일 + 연말 스냅샷 ----
sbiz = datago_files(SBIZ_PK)
current_date, current_pk = sbiz[0]
sbiz_seoul(current_pk, os.path.join(raw, "sbiz_current"), current_date)
year_end = sorted((date, pk) for date, pk in sbiz[1:]
                  if date.endswith("1231") and FIRST_SNAPSHOT <= int(date[:4]) < int(current_date[:4]))
for date, pk in year_end:
    sbiz_seoul(pk, os.path.join(raw, f"sbiz_{date}"), date)

# ---- 백년가게 ----
bk_dir = os.path.join(raw, "baeknyeon")
os.makedirs(bk_dir, exist_ok=True)
baeknyeon = sorted((date, dataset, pk) for dataset in BAEKNYEON_PKS for date, pk in datago_files(dataset))
for date, dataset, pk in baeknyeon:
    path = os.path.join(bk_dir, f"{date}.csv")
    if os.path.exists(path):
        print(f"baeknyeon {date} already")
        continue
    datago_download(dataset, pk, path + ".download")
    to_utf8(path + ".download", path)
    os.remove(path + ".download")

with open(os.path.join(raw, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump({"localdata": localdata_date, "sbiz_current": current_date, "sbiz_snapshots": [d for d, _ in year_end],
               "baeknyeon": [d for d, _, _ in baeknyeon]}, f, ensure_ascii=False, indent=1)
print("manifest:", open(os.path.join(raw, "manifest.json"), encoding="utf-8").read())
