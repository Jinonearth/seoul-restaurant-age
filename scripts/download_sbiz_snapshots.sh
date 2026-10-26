#!/usr/bin/env bash
# 공공데이터포털 상가(상권)정보 과거 분기 파일을 받는다. 사이트와 같은 순서: 파일 ID 조회 → 사용량 확인 → 다운로드
# 사용: download_sbiz_snapshots.sh <out_dir> <기준일:publicDataDetailPk> ...
set -euo pipefail
OUT="$1"; shift
UA="Mozilla/5.0 (overture-poi-age-map)"
J=$(mktemp)
curl -s -c "$J" -b "$J" -A "$UA" https://www.data.go.kr/data/15083033/fileData.do -o /dev/null
for spec in "$@"; do
  date="${spec%%:*}"; pk="${spec#*:}"
  dir="$OUT/sbiz_$date"; mkdir -p "$dir"
  if [ -s "$dir/sbiz_$date.zip" ]; then echo "$date already"; continue; fi
  meta=$(curl -s -c "$J" -b "$J" -A "$UA" "https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?recommendDataYn=Y&publicDataPk=15083033&publicDataDetailPk=$pk")
  fid=$(echo "$meta" | grep -o '"atchFileId":"[^"]*"' | head -1 | cut -d'"' -f4)
  sn=$(echo "$meta" | grep -o '"fileDetailSn":"[^"]*"' | head -1 | cut -d'"' -f4)
  lim=$(curl -s -c "$J" -b "$J" -A "$UA" -X POST -d "atchFileId=$fid&fileDetailSn=$sn" https://www.data.go.kr/cmm/cmm/check-limit.json)
  if echo "$lim" | grep -q '"needCaptcha":true'; then echo "$date: CAPTCHA required, stopping"; exit 2; fi
  curl -s -c "$J" -b "$J" -A "$UA" -o "$dir/sbiz_$date.zip" "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=$fid&fileDetailSn=$sn"
  echo "$date $fid $(du -h "$dir/sbiz_$date.zip" | cut -f1)"
done
