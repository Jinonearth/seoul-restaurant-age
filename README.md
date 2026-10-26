# 서울 음식점 나이 지도

**[지도 보기 → jinonearth.github.io/seoul-restaurant-age](https://jinonearth.github.io/seoul-restaurant-age/#15/37.57/126.985)**

서울에서 영업 중인 일반음식점 약 11만 8천 곳을 개업 연도에 따라 건물 단위로 칠한 지도입니다.
갈색일수록 오래된 가게, 초록색일수록 최근에 문을 연 가게입니다. 기간 슬라이더로 특정 시기에 문을 연 가게만 골라 볼 수 있습니다.

## 만든 이유

**Overture Maps로 서울의 배경지도를 만들 수 있는지 궁금했습니다.**
Overture 데이터를 Protomaps basemaps(`--overture`)로 빌드해 서울 배경지도를 만들었습니다.
도로, 하천, 녹지, 건물, 한글 지명까지 PMTiles 파일 하나(약 40 MB, z0–15)에 들어갔고, 이 지도의 배경으로 쓰기에 부족함이 없었습니다.
건물 외곽선과 지하철역도 Overture에서 가져왔습니다.

**시간에 따라 그려 볼 만한 데이터는 무엇일까요?**
[서울건물나이지도](https://hanbyul-here.github.io/seoul-building-explorer-2024/)를 보면서, 건물 말고 다른 데이터로도 이런 지도를 그릴 수 있을지 궁금했습니다.
음식점은 건물보다 훨씬 자주 바뀌고, 인허가 데이터에 개업 연도가 남아 있습니다.
그래서 개업 연도로 색을 칠하면 오래된 가게가 남아 있는 곳과 최근에 가게가 많이 바뀐 곳을 구분해 볼 수 있다고 생각했습니다.

**공공데이터는 완벽하지 않습니다.**
인허가 데이터에는 이미 폐업한 가게가 영업 중으로 남아 있기도 하고, 영업자가 바뀌어도 인허가일자가 그대로 이어져 개업 연도가 실제와 다른 경우가 많습니다.
상가정보와 백년가게 목록으로 일부를 보정했지만, 모두 바로잡지는 못했습니다.
그래도 이런 오류는 지도에 올려야 눈에 띄고, 눈에 띄어야 고칠 수 있다고 생각해 그대로 공개합니다.

## 자료

| 자료 | 용도 |
| --- | --- |
| [행정안전부 지방행정 인허가 – 식품_일반음식점](https://www.data.go.kr/data/15045016/fileData.do) | 영업 중인 음식점, 인허가일자, 위치 |
| [소상공인시장진흥공단 상가(상권)정보](https://www.data.go.kr/data/15083033/fileData.do) (2019~2025 연말, 2026년 6월) | 가게가 실제로 존재한 시점 확인 |
| [소상공인시장진흥공단 백년가게 지정 목록](https://www.data.go.kr/data/15132695/fileData.do) (2022, 2026) | 업력 30년 이상 검증 |
| [Overture Maps](https://overturemaps.org) (2026-10-21.0) | 건물 외곽선, 지하철역, 배경지도 |

## 개업 연도 추정 방법

인허가일자를 그대로 쓰면 틀리는 경우가 많습니다. 영업자 지위승계를 하면 새 가게도 이전 가게의 인허가일자를 물려받기 때문입니다.
그래서 다음 순서로 개업 연도를 정했습니다.

### 1. 백년가게

백년가게는 업력 30년 이상이 공식 확인된 가게이므로 가장 먼저 적용했습니다.

- 백년가게 목록과 인허가 데이터는 도로명주소(○○로/길 + 건물번호)로 연결했습니다. 주소로 연결되지 않으면 같은 구 안에서 상호가 하나뿐인 경우에 한해 상호로 연결했습니다.
- 가게가 이전한 경우를 고려해, 반경 1km 안에서 같은 상호를 쓰는 인허가 기록을 같은 가게로 보았습니다. 이미 폐업한 기록도 포함하며, 그중 가장 이른 인허가 연도를 개업 연도로 썼습니다. 설렁탕·설농탕처럼 표기만 다른 상호는 같은 상호로 취급했습니다.
- 연결할 수 있는 이전 기록이 없으면 지정 요건에 따라 「30년+」로 표기했습니다.

### 2. 영업자 변경 흔적이 있는 가게

상가(상권)정보의 2019~2025년 연말 자료를 이어 붙여, 각 가게가 처음 등장한 연도를 구했습니다. 다음 조건을 모두 만족하면 처음 등장한 연도를 개업 연도로 썼습니다.

- 처음 등장한 연도가 인허가 연도보다 5년 이상 늦습니다.
- 처음 등장한 연도가 첫 자료(2019년)보다 뒤입니다. 2019년에 이미 있던 가게는 언제 생겼는지 알 수 없기 때문입니다.
- 직전 연도 자료에서 같은 자리(15m 이내)에 있던 다른 음식점이 사라졌습니다. 같은 자리의 음식점이 3곳 이상이면 어느 가게가 바뀐 것인지 판단하기 어려워 제외했습니다.
- 상가정보가 대량으로 새로 등록된 달(2024년 6월, 9~11월)에 처음 등장한 가게는 제외했습니다. 이때 등장한 가게는 실제로 새로 생긴 것이 아니라 등록이 늦게 반영된 경우가 많기 때문입니다.

인허가 연도와 처음 등장한 연도가 30년 이상 차이 나면 직전 음식점 조건 없이 적용했습니다. 이 정도 차이는 같은 가게라고 보기 어렵기 때문입니다.

### 3. 그 외

인허가 연도를 그대로 썼습니다. 이 값은 지금 가게의 개업 연도라기보다, 그 자리에서 음식점 영업이 시작된 연도에 가깝습니다.

### 표기 방식

- 같은 건물에서 같은 상호로 인허가가 여러 건 있으면 한 가게로 합치고 「인허가 N건」으로 표시했습니다.
- 지점명을 뺀 상호가 서울에 3곳 이상 있으면 「체인」으로 표시했습니다. 체인 지점은 기존 가게의 인허가를 승계하는 경우가 많아, 표시된 연도가 실제 입점 시점보다 이를 수 있습니다.
- 한 건물에 여러 가게가 있으면 선택한 기간 안에서 가장 오래된 가게를 기준으로 건물 색과 이름을 표시했습니다.

## 한계

- 상가정보가 2019년부터 있어서, 그 이전에 영업자가 바뀐 경우는 보정하지 못했습니다.
- 새로 인허가를 받은 가게 중 약 30%는 상가정보에 1년 이상 늦게 반영됩니다. 그래서 추정한 개업 연도가 실제보다 늦을 수 있습니다.
- 잘못 보정하는 것을 줄이기 위해 판단이 애매하면 인허가 연도를 유지했습니다. 그래서 일부 승계 가게는 실제보다 오래된 가게로 표시됩니다.
- 인허가 데이터에서 영업 중으로 되어 있어도 실제로는 폐업한 가게가 적지 않습니다.
- 건물은 Overture Maps의 외곽선에 매칭했습니다. 10m 안에 건물이 없으면 점으로 표시했습니다.

## 구조

- **배경지도**: Overture GeoParquet → [Protomaps basemaps](https://github.com/protomaps/basemaps)(`--overture`, Planetiler) → PMTiles
- **음식점 타일**: DuckDB(spatial)로 인허가·상가정보·백년가게를 결합하고 건물에 매칭한 뒤, 직접 작성한 MVT 인코더로 PMTiles 생성
- **건물별 상세 목록**: z16 타일 단위로 나눈 정적 JSON(타일 속성 `k`로 조회)
- **뷰어**: MapLibre GL JS + pmtiles.js, 단일 HTML
- **호스팅**: GitHub Pages. PMTiles는 HTTP Range 요청으로 필요한 부분만 읽습니다. (아래 「호스팅」 참고)

```
scripts/build_restaurant_tiles.py   음식점 테이블·타일·상세 JSON 생성
scripts/tiling.py, mvt.py           건물 매칭, MVT 인코딩
scripts/build_site.py               배포용 site/ 폴더 생성
viewer/restaurants.html             로컬 개발용 뷰어 (scripts/serve.py로 실행)
site/                               배포본 (GitHub Actions가 Pages에 올림)
```

원본 데이터(`data/`)와 중간 산출물(`out/`)은 용량 문제로 저장소에 포함하지 않았습니다.

## 호스팅

비용이 들지 않는 것, 결제수단을 등록하지 않는 것을 조건으로 호스팅을 골랐습니다.

처음에는 Cloudflare Pages(무료 플랜)에 올렸는데, 두 가지가 걸렸습니다.

- **파일 크기 제한.** 파일 하나가 25 MiB를 넘을 수 없습니다. 배경지도 PMTiles가 약 40 MB여서, z15를 빼고 z14까지만 남겨야 했습니다.
- **Range 요청 미지원.** PMTiles는 파일 전체가 아니라 필요한 타일 부분만 Range 요청으로 받아 옵니다.
  그런데 Cloudflare Pages는 Range 요청에도 206(부분 응답) 대신 200으로 파일 전체를 돌려줍니다. [공식 문서](https://developers.cloudflare.com/pages/configuration/serving-pages/)에도 아직 지원하지 않는다고 적혀 있습니다.
  Workers의 정적 자산 호스팅으로 배포해 봐도 결과는 같았고, 결국 지도가 뜨지 않았습니다.

Cloudflare에서 PMTiles를 쓰려면 보통 R2를 권하지만, R2는 무료 범위 안에서 쓰더라도 결제수단을 등록해야 합니다.
PMTiles를 `{z}/{x}/{y}.pbf` 파일 수천 개로 풀어 올리면 Cloudflare Pages에서도 동작합니다(`scripts/build_site.py --split`).
다만 파일 하나로 관리하는 PMTiles의 장점이 사라집니다.

GitHub Pages는 Range 요청에 206으로 정상 응답하고, 파일 하나당 100 MB까지 올릴 수 있어 PMTiles를 그대로 쓸 수 있습니다.
사이트 용량(1 GB)과 월 대역폭(100 GB, 권장 한도) 제한은 있지만 이 지도에는 충분해서 GitHub Pages를 골랐습니다.

결제수단 없이 Cloudflare Pages에서 PMTiles를 잘 서빙하는 방법을 알고 계신다면 이슈로 알려 주세요.

## 오류 제보

- 영업 상태·인허가일자: 공공데이터포털 [「행정안전부_식품_일반음식점」](https://www.data.go.kr/data/15045016/fileData.do) 데이터 개선요청
- 상가(상권)정보: 공공데이터포털 [「소상공인시장진흥공단_상가(상권)정보」](https://www.data.go.kr/data/15083033/fileData.do) 데이터 개선요청
- 백년가게: 공공데이터포털 [「소상공인시장진흥공단_전국 백년가게 지정리스트 현황 정보」](https://www.data.go.kr/data/15132695/fileData.do) 데이터 개선요청
- 건물·지하철역·배경지도: [Overture Maps](https://github.com/OvertureMaps/data/issues) 또는 [OpenStreetMap](https://www.openstreetmap.org)에서 직접 수정

## 출처

- 음식점: [행정안전부 지방행정 인허가 – 식품_일반음식점](https://www.data.go.kr/data/15045016/fileData.do) (공공데이터포털)
- 상가 존재 시점: [소상공인시장진흥공단 상가(상권)정보](https://www.data.go.kr/data/15083033/fileData.do) (공공데이터포털)
- 백년가게: [소상공인시장진흥공단 전국 백년가게 지정리스트 현황 정보](https://www.data.go.kr/data/15132695/fileData.do) (공공데이터포털)
- 건물·지하철역·배경지도: © [Overture Maps Foundation](https://overturemaps.org) · © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
- 배경지도 스타일·빌드: [Protomaps basemaps](https://github.com/protomaps/basemaps)
- 지도 라이브러리: [MapLibre GL JS](https://maplibre.org) · [PMTiles](https://github.com/protomaps/PMTiles)

## 라이선스

- **코드** (`scripts/`, `viewer/`, `site/index.html`): [MIT](LICENSE)
- **데이터**: 각 원천 데이터의 라이선스를 따릅니다.
  - 행정안전부 인허가, 소상공인시장진흥공단 상가(상권)정보·백년가게 목록: 공공데이터포털 이용허락범위 「제한 없음」
  - Overture Maps: 테마별 라이선스를 따릅니다. 건물·교통·기반(base) 테마는 [ODbL](https://opendatacommons.org/licenses/odbl/), 장소(places) 테마는 [CDLA-Permissive-2.0](https://cdla.dev/permissive-2-0/)입니다. 자세한 내용은 [Overture 라이선스 안내](https://docs.overturemaps.org/attribution/)를 참고해 주세요.
  - 이 저장소의 배경지도·건물 타일(`site/data/*.pmtiles`)은 Overture(OpenStreetMap 포함) 데이터를 가공한 것이므로 ODbL을 따릅니다.

## 영감을 받은 프로젝트

- [서울건물나이지도](https://hanbyul-here.github.io/seoul-building-explorer-2024/) — [hanbyul-here/seoul-building-explorer-2024](https://github.com/hanbyul-here/seoul-building-explorer-2024)
