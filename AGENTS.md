# 에이전트 작업 지침

이 프로젝트에서 LLM 에이전트가 작업할 때 참고할 맥락과 규칙입니다.

## 프로젝트 목적

이 프로젝트는 KOBIS 기간별 박스오피스 원본 파일을 기반으로 영화별 관객 수 예측에 사용할 데이터셋을 만드는 프로젝트입니다.

현재 핵심 산출물은 다음 두 가지입니다.

```text
data/db/kobis_movies.db
data/processed/movie_snapshot_enriched_utf8_sig.csv
```

모델링 코드를 실행하기 전에는 `movie_snapshot_enriched` 테이블 또는 해당 CSV가 준비되어 있어야 합니다.

## 먼저 읽을 문서

작업을 시작하기 전에 아래 문서를 우선 확인하세요.

```text
README.md
docs/data_pipeline.md
docs/merge_rules.md
docs/enrichment_rules.md
```

역할은 다음과 같습니다.

- `README.md`: 프로젝트 개요와 기본 실행 방법
- `docs/data_pipeline.md`: 원본 파일에서 최종 enriched 데이터까지 만드는 절차
- `docs/merge_rules.md`: KOBIS 파일 병합과 snapshot 생성 규칙
- `docs/enrichment_rules.md`: KOBIS/KMDb API 보강 규칙

## 주요 테이블

```text
boxoffice_period_raw
movie_snapshot
movie_snapshot_selected
kobis_movie_match
kobis_movie_detail
kmdb_movie_match
kmdb_movie_detail
movie_snapshot_enriched
```

분석과 모델링의 기본 입력은 `movie_snapshot_enriched`입니다.

`movie_snapshot_selected`는 보강 전 selected 데이터이고, `movie_snapshot_enriched`는 KOBIS/KMDb 보강 결과가 반영된 최종 데이터입니다.

## 중요한 데이터 규칙

- 원본 파일은 `data/raw/`에 두고 수정하지 않습니다.
- DB를 직접 손으로 수정하지 않습니다. 변경은 스크립트로 재현 가능하게 만듭니다.
- 영화 식별 기준은 `movie_name_clean + release_date`입니다.
- 같은 영화가 여러 기간 파일에 있으면 `period_end`가 가장 최신인 행을 대표 snapshot으로 사용합니다.
- `target_final_audience`는 같은 영화 그룹의 `cumulative_audience` 최댓값입니다.
- 메타데이터 보강값 우선순위는 `selected > KOBIS API > KMDb API`입니다.
- 자동 매칭은 보수적으로 유지합니다. 애매한 후보는 `ambiguous` 또는 `candidate`로 저장하고 자동 보강에 사용하지 않습니다.

## 주요 명령

DB를 처음부터 다시 만들 때:

```bash
python3 src/scripts/build_kobis_sqlite.py
```

기본 검증:

```bash
python3 src/scripts/validate_db.py
```

KOBIS API 보강:

```bash
python3 -u src/scripts/enrich_with_kobis_api.py --export-csv
```

KMDb API 보강:

```bash
python3 -u src/scripts/enrich_with_kmdb_api.py --export-csv
```

API 재호출 없이 기존 KMDb JSON 캐시에서 파생 컬럼을 다시 만들 때:

```bash
python3 src/scripts/enrich_with_kmdb_api.py --rebuild-only --export-csv
```

## API 키와 보안

KOBIS/KMDb API 키는 환경변수 또는 `.env`로 관리합니다.

```text
KOBIS_API_KEY
KMDB_API_KEY
```

`.env`는 커밋하지 않습니다. API 키를 코드, 문서, 커밋 메시지에 넣지 마세요.

## 캐시와 재실행 주의점

`data/db/kobis_movies.db`에는 KOBIS/KMDb API 응답 캐시가 들어 있습니다.

특히 다음 컬럼은 원본 JSON 캐시입니다.

```text
kobis_movie_match.raw_response_json
kobis_movie_detail.raw_response_json
kmdb_movie_match.raw_response_json
kmdb_movie_match.matched_record_json
kmdb_movie_detail.raw_record_json
```

`poster_url`, `synopsis` 같은 컬럼은 KMDb API를 다시 호출하지 않고 `kmdb_movie_detail.raw_record_json`에서 재생성할 수 있습니다.

주의:

- `build_kobis_sqlite.py`는 DB를 삭제하고 처음부터 다시 만듭니다.
- 이 경우 API 캐시 테이블도 사라질 수 있습니다.
- API 결과를 강제로 새로 받고 싶을 때만 `--refresh`를 사용합니다.
- 전체 API 보강은 시간이 오래 걸릴 수 있으므로 먼저 `--limit 100`으로 테스트하는 것이 좋습니다.

## 코드 작성 기준

- 문서 본문은 한국어로 유지합니다.
- 파일명, 테이블명, 컬럼명, 명령어는 기존 영어 식별자를 유지합니다.
- 원본 데이터 처리 로직은 `src/utils/kobis_reader.py`와 `src/utils/cleaner.py`에 둡니다.
- KOBIS API 로직은 `src/utils/kobis_api.py`와 `src/scripts/enrich_with_kobis_api.py`에 둡니다.
- KMDb API 로직은 `src/utils/kmdb_api.py`와 `src/scripts/enrich_with_kmdb_api.py`에 둡니다.
- 모델링 코드를 추가할 때도 데이터 생성 절차와 모델 학습 절차를 분리합니다.

## 현재 데이터 상태

현재 기준 주요 행 수는 다음과 같습니다.

```text
boxoffice_period_raw      26,375
movie_snapshot            20,621
movie_snapshot_selected   20,621
movie_snapshot_enriched   20,621
kobis_movie_match         17,139
kobis_movie_detail        2,894
kmdb_movie_match          17,139
kmdb_movie_detail         5,534
```

현재 `movie_snapshot_enriched`에는 다음 파생 컬럼도 포함되어 있습니다.

```text
poster_url
synopsis
```
