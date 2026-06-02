# 데이터 파이프라인 가이드

이 문서는 모델 학습/예측 전에 필요한 데이터셋을 만들기 위해, KOBIS 원본 파일에서 최종 `movie_snapshot_enriched` CSV를 생성하는 절차입니다.

## 1. 준비물

프로젝트 루트 기준으로 KOBIS 기간별 박스오피스 원본 파일을 `data/raw/`에 둡니다.

```text
data/raw/
  KOBIS_기간별박스오피스 (...).xls
```

현재 원본 `.xls` 파일은 확장자는 Excel이지만 실제 내용은 HTML 테이블입니다. 리더는 이 형식을 자동으로 처리합니다.

API 보강까지 재현하려면 다음 키가 필요합니다.

```bash
export KOBIS_API_KEY="your-kobis-api-key"
export KMDB_API_KEY="your-kmdb-api-key"
```

또는 프로젝트 루트의 `.env`에 아래처럼 둘 수 있습니다. `.env`는 Git에 올리지 않습니다.

```text
KOBIS_API_KEY=your-kobis-api-key
KMDB_API_KEY=your-kmdb-api-key
```

## 2. 환경 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. SQLite DB 생성

```bash
python3 src/scripts/build_kobis_sqlite.py
```

생성 파일:

```text
data/db/kobis_movies.db
```

생성 테이블:

```text
boxoffice_period_raw
movie_snapshot
movie_snapshot_selected
```

현재 데이터 기준 행 수:

```text
boxoffice_period_raw      26,375
movie_snapshot            20,621
movie_snapshot_selected   20,621
```

## 4. 기본 검증

```bash
python3 src/scripts/validate_db.py
```

정상이라면 다음과 비슷하게 출력됩니다.

```text
Validation passed
Raw 행 수: 26,375
Snapshot 행 수: 20,621
Selected snapshot 행 수: 20,621
```

## 5. KOBIS API 1차 보강

KOBIS 영화목록 API로 `movieCd`를 찾고, KOBIS 영화 상세정보 API를 캐시합니다.

```bash
python3 -u src/scripts/enrich_with_kobis_api.py --export-csv
```

생성/갱신 테이블:

```text
kobis_movie_match
kobis_movie_detail
movie_snapshot_enriched
```

현재 데이터 기준 캐시 행 수:

```text
kobis_movie_match    17,139
kobis_movie_detail   2,894
```

KOBIS 원본 파일과 KOBIS API는 같은 계열의 데이터라서, KOBIS API만으로는 결측치가 크게 줄지 않을 수 있습니다.

## 6. KMDb API 2차 보강

KOBIS로 채워지지 않은 값은 KMDb API로 보강합니다.

```bash
python3 -u src/scripts/enrich_with_kmdb_api.py --export-csv
```

생성/갱신 테이블:

```text
kmdb_movie_match
kmdb_movie_detail
movie_snapshot_enriched
```

현재 데이터 기준 캐시 행 수:

```text
kmdb_movie_match    17,139
kmdb_movie_detail   5,534
```

KMDb 매칭은 보수적으로 처리합니다.

- 제목 정확 일치 + 개봉일 정확 일치
- 제목 정확 일치 + 개봉연도 일치 + 후보 1개

그 외 `ambiguous`, `candidate`, `not_found`, `error`는 캐시에 저장하지만 자동 보강에는 사용하지 않습니다.

## 7. 포스터와 시놉시스 재생성

KMDb API 응답 원본 JSON은 DB에 저장됩니다.

```text
kmdb_movie_detail.raw_record_json
```

따라서 포스터 URL이나 시놉시스 같은 새 컬럼은 API 재호출 없이 기존 JSON에서 다시 뽑을 수 있습니다.

```bash
python3 src/scripts/enrich_with_kmdb_api.py --rebuild-only --export-csv
```

현재 `movie_snapshot_enriched`에는 다음 컬럼이 추가되어 있습니다.

```text
show_count
poster_url
synopsis
```

현재 데이터 기준:

```text
show_count 채워진 행    20,621
poster_url 채워진 행   4,737
synopsis 채워진 행     5,494
```

## 8. 최종 산출물

최종 DB:

```text
data/db/kobis_movies.db
```

최종 CSV:

```text
data/processed/movie_snapshot_enriched.csv
data/processed/movie_snapshot_enriched_utf8_sig.csv
```

Excel로 열거나 팀원에게 공유할 때는 한글 인코딩 문제를 줄이기 위해 다음 파일을 권장합니다.

```text
data/processed/movie_snapshot_enriched_utf8_sig.csv
```

최종 행 수:

```text
movie_snapshot_enriched   20,621
```

## 8-1. 인기 엔티티 Pool 생성

감독, 배우, 제작사, 배급사 기반 파생 feature를 만들 때는 전체 기간 기준 popular entity pool을 생성할 수 있습니다.

```bash
python3 src/scripts/build_popular_entity_pools.py
```

생성 위치:

```text
data/processed/entity_pools/
```

생성된 pool을 사용해 영화별 popular entity feature만 따로 만들 수 있습니다.

```bash
python3 src/scripts/add_popular_entity_features.py
```

생성 위치:

```text
data/processed/popular_entity_features_utf8_sig.csv
```

자세한 기준은 [docs/popular_entity_pools.md](popular_entity_pools.md)를 참고하세요.

## 9. 최종 결측치 현황

현재 `movie_snapshot_selected` 대비 `movie_snapshot_enriched`의 결측치 변화는 다음과 같습니다.

```text
column                selected_missing   enriched_missing   filled
country               1                  0                  1
production_company    12,950             8,989              3,961
distributor           830                830                0
rating                145                121                24
genre                 138                120                18
director              3,772              3,095              677
actor                 10,100             8,841              1,259
```

## 10. 재실행 시 주의점

- `build_kobis_sqlite.py`는 DB를 처음부터 다시 만듭니다. 기존 API 캐시도 사라집니다.
- API 보강 스크립트는 이미 저장된 match/detail 캐시를 재사용합니다.
- API 결과를 강제로 다시 받고 싶을 때만 `--refresh`를 사용합니다.
- `.env`와 API 키는 Git에 커밋하지 않습니다.
- `data/db/kobis_movies.db`에는 API 응답 JSON 캐시가 포함되어 있으므로 보관 가치가 큽니다.
