"""현재 places + changelog 이력으로 POI '정보 나이' 테이블을 만든다.

정보 나이 = 기준 릴리스 날짜 - 마지막 갱신 근거일. 근거일은 다음 중 가장 최근 값:
  - first_seen: changelog에서 처음 added 된 릴리스 (2025-06-25 GERS 안정 ID 시작 이전부터 있던 POI는 그 날짜)
  - last_info_change: 실질 정보(이름·연락처·주소 등) 컬럼이 바뀐 마지막 릴리스 (columns_changed는 2026-03부터 제공)
  - source_record_update: meta·Overture를 뺀 출처(Foursquare 등)의 레코드 갱신일
    (meta update_time은 POI별 값이 아니라 스냅샷 날짜라 제외)

사용: python build_poi_table.py <places.parquet> <history.parquet> <out.parquet> <release>
"""
import sys
import duckdb

places, history, out, release = sys.argv[1:5]
GERS_START = "2025-06-25"
INFO_COLS = ["names", "phones", "websites", "addresses", "socials", "emails", "brand"]

con = duckdb.connect()
con.sql(f"""
CREATE TABLE h AS
SELECT id, change_type, columns_changed, strptime(left(release, 10), '%Y-%m-%d')::DATE AS rel_date
FROM '{history}'
WHERE release NOT LIKE '%.1'  -- .1은 같은 달의 재배포
""")
con.sql(f"""
COPY (
  WITH added AS (
    SELECT id, min(rel_date) AS first_seen FROM h
    WHERE change_type = 'added' AND rel_date >= DATE '{GERS_START}' GROUP BY id
  ), info AS (
    SELECT id, max(rel_date) AS last_info_change,
           arg_max(list_intersect(columns_changed, {INFO_COLS}), rel_date) AS last_info_cols
    FROM h
    WHERE change_type = 'data_changed' AND len(list_intersect(columns_changed, {INFO_COLS})) > 0
    GROUP BY id
  ), base AS (
    SELECT
      p.id,
      p.names.primary AS name,
      p.lon, p.lat,
      p.basic_category AS category,
      p.taxonomy.primary AS category_detail,
      p.taxonomy.hierarchy[1] AS category_group,
      p.confidence,
      p.operating_status,
      p.version AS gers_version,
      list_distinct(list_transform(list_filter(p.sources, lambda s: s.dataset <> 'Overture'), lambda s: s.dataset)) AS datasets,
      p.addresses[1].freeform AS address,
      p.phones, p.websites,
      coalesce(a.first_seen, DATE '{GERS_START}') AS first_seen,
      a.first_seen IS NULL AS seen_before_gers,
      i.last_info_change,
      i.last_info_cols,
      list_max(list_transform(
        list_filter(p.sources, lambda s: s.dataset NOT IN ('meta', 'Overture') AND s.update_time IS NOT NULL),
        lambda s: TRY_CAST(left(s.update_time, 10) AS DATE))) AS source_record_update
    FROM '{places}' p
    LEFT JOIN added a USING (id)
    LEFT JOIN info i USING (id)
  )
  SELECT row_number() OVER (ORDER BY id) - 1 AS fid,  -- 타일의 feature id. 상세는 이 값으로 조회한다
    *,
    greatest(first_seen, coalesce(last_info_change, first_seen), coalesce(source_record_update, first_seen)) AS last_evidence,
    date_diff('month',
      greatest(first_seen, coalesce(last_info_change, first_seen), coalesce(source_record_update, first_seen)),
      DATE '{release[:10]}') AS age_months
  FROM base
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print(con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0], "rows ->", out)
print(con.execute(f"""
  SELECT CASE WHEN age_months < 3 THEN 'a <3m' WHEN age_months < 6 THEN 'b 3-6m' WHEN age_months < 12 THEN 'c 6-12m'
              WHEN age_months < 24 THEN 'd 1-2y' ELSE 'e 2y+' END bucket,
         count(*) n, round(100.0 * count(*) / sum(count(*)) OVER (), 1) pct
  FROM '{out}' GROUP BY 1 ORDER BY 1""").fetchall())
print("evidence:", con.execute(f"""
  SELECT CASE WHEN last_evidence = source_record_update THEN 'source_record'
              WHEN last_evidence = last_info_change THEN 'info_change'
              WHEN seen_before_gers THEN 'gers_start' ELSE 'first_seen' END, count(*)
  FROM '{out}' GROUP BY 1 ORDER BY 2 DESC""").fetchall())
