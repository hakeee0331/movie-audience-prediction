# KOBIS Audience Prediction

KOBIS 기간별 박스오피스 파일을 읽어 영화별 관객 수 예측에 쓸 SQLite DB를 만드는 프로젝트입니다.

원본 파일은 `data/raw/`에 그대로 두고, 스크립트를 실행해서 `data/db/kobis_movies.db`를 재생성합니다.

## Project Structure

```text
kobis-audience-prediction/
  README.md
  .gitignore
  requirements.txt
  data/
    raw/
    processed/
    db/
  src/
    scripts/
      build_kobis_sqlite.py
      validate_db.py
    notebooks/
    utils/
      kobis_reader.py
      cleaner.py
  docs/
    merge_rules.md
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

현재 저장된 KOBIS `.xls` 파일처럼 HTML 테이블 형식인 파일은 표준 라이브러리만으로도 읽을 수 있습니다.
실제 `.xlsx` 파일을 읽으려면 `requirements.txt`의 의존성이 필요합니다.

## Build DB

```bash
python3 src/scripts/build_kobis_sqlite.py
```

생성 위치:

```text
data/db/kobis_movies.db
```

기존 DB가 있으면 삭제하고 처음부터 다시 만듭니다. DB를 직접 수정하지 않고, 항상 스크립트로 재생성합니다.

## Validate DB

```bash
python3 src/scripts/validate_db.py
```

검증 내용:

- 필수 테이블 존재 여부
- raw/snapshot row 수
- snapshot 중복 여부
- `target_final_audience` 결측/음수 여부
- 기간 날짜 순서

## Tables

### `boxoffice_period_raw`

KOBIS 파일의 실제 데이터 테이블을 읽어 저장한 원본성 테이블입니다.

추가 메타데이터:

- `source_file`
- `period_start`
- `period_end`
- `loaded_at`
- `row_number_in_file`

### `movie_snapshot`

`영화명 + 개봉일` 기준으로 영화별 한 행만 남긴 테이블입니다.

같은 영화가 여러 파일에 있으면 `period_end`가 가장 최신인 행을 대표 row로 사용합니다.
`target_final_audience`는 같은 영화 그룹의 `누적관객수` 최댓값입니다.

### `movie_snapshot_selected`

`movie_snapshot`에서 모델링/분석에 우선 필요한 컬럼만 남긴 테이블입니다.

포함 컬럼:

- `movie_name_clean`
- `release_date`
- `cumulative_sales_amount`
- `cumulative_audience`
- `country`
- `production_company`
- `distributor`
- `rating`
- `genre`
- `director`
- `actor`

자세한 병합 규칙은 [docs/merge_rules.md](docs/merge_rules.md)를 참고하세요.
