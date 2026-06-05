# KOBIS Audience Prediction

KOBIS 기간별 박스오피스 파일을 읽어 영화별 관객 수 예측에 쓸 SQLite DB를 만드는 프로젝트입니다.

원본 파일은 `data/raw/`에 그대로 두고, 스크립트를 실행해서 `data/db/kobis_movies.db`를 재생성합니다.

## Project Structure

```text
kobis-audience-prediction/
  AGENTS.md
  README.md
  .gitignore
  requirements.txt
  data/
    raw/
    processed/
      movie_snapshot_selected.csv
      movie_snapshot_selected_utf8_sig.csv
      movie_snapshot_enriched.csv
      movie_snapshot_enriched_utf8_sig.csv
      poster_resnet50/
    db/
      kobis_movies.db
  src/
    scripts/
      build_kobis_sqlite.py
      enrich_with_kobis_api.py
      enrich_with_kmdb_api.py
      validate_db.py
    notebooks/
      embeddings/
        Movie_Poster_ResNet50_Embedding.ipynb
        Movie_Poster_ResNet50_PosterPadding_Embedding.ipynb
        Movie_Synopsis_RoBERTa_Embedding.ipynb
      mlps/
        NEW_MLP_only_공통_데이터_전처리.ipynb
      preprocessing/
        Common_preprocessing.ipynb
    utils/
      cleaner.py
      kobis_api.py
      kobis_reader.py
      kmdb_api.py
  docs/
    data_pipeline.md
    enrichment_rules.md
    merge_rules.md
    poster_resnet50_pipeline.md
```

모델 학습/예측 코드를 실행하기 전에는 먼저 데이터 파이프라인을 실행해 `movie_snapshot_enriched` 테이블과 CSV를 생성해야 합니다.
자세한 절차는 [docs/data_pipeline.md](docs/data_pipeline.md)를 참고하세요.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

현재 저장된 KOBIS `.xls` 파일처럼 HTML 테이블 형식인 파일은 표준 라이브러리만으로도 읽을 수 있습니다.
실제 `.xlsx` 파일을 읽으려면 `requirements.txt`의 의존성이 필요합니다.
포스터 embedding 실험 노트북을 실행하려면 `torch`, `torchvision`, `Pillow`, `tqdm`도 필요합니다.

## Build DB

```bash
python3 src/scripts/build_kobis_sqlite.py
```

생성 위치:

```text
data/db/kobis_movies.db
```

기존 DB가 있으면 삭제하고 처음부터 다시 만듭니다. DB를 직접 수정하지 않고, 항상 스크립트로 재생성합니다.

## DB 검증

```bash
python3 src/scripts/validate_db.py
```

검증 내용:

- 필수 테이블 존재 여부
- raw/snapshot 행 수
- snapshot 중복 여부
- `target_final_audience` 결측/음수 여부
- `show_count` 결측/음수 여부
- 기간 날짜 순서

## 테이블

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

같은 영화가 여러 파일에 있으면 `period_end`가 가장 최신인 행을 대표 행으로 사용합니다.
`target_final_audience`는 같은 영화 그룹의 `누적관객수` 최댓값입니다.
`show_count`는 대표 행의 최신값이 아니라, 같은 영화 그룹의 `상영횟수`를 합산한 누적 상영횟수입니다.

그룹 기준:

```text
movie_name_clean + release_date
```

예를 들어 같은 영화가 여러 기간 파일에 나뉘어 있으면 `show_count`는 아래처럼 계산합니다.

```text
show_count = SUM(boxoffice_period_raw.show_count)
```

### `movie_snapshot_selected`

`movie_snapshot`에서 모델링/분석에 우선 필요한 컬럼만 남긴 테이블입니다.

포함 컬럼:

- `movie_name_clean`
- `release_date`
- `cumulative_sales_amount`
- `cumulative_audience`
- `show_count`: 같은 영화 그룹의 기간별 `상영횟수` 합계
- `country`
- `production_company`
- `distributor`
- `rating`
- `genre`
- `director`
- `actor`

자세한 병합 규칙은 [docs/merge_rules.md](docs/merge_rules.md)를 참고하세요.

## Enrich Metadata With KOBIS API

KOBIS Open API 키와 KMDb API 키를 환경변수로 설정합니다.

```bash
export KOBIS_API_KEY="your-api-key"
export KMDB_API_KEY="your-kmdb-api-key"
```

먼저 샘플로 실행합니다.

```bash
python3 src/scripts/enrich_with_kobis_api.py --limit 100 --export-csv
```

전체 보강은 limit 없이 실행합니다.

```bash
python3 src/scripts/enrich_with_kobis_api.py --export-csv
```

KOBIS로 채워지지 않은 값은 KMDb API로 추가 보강할 수 있습니다.

```bash
python3 src/scripts/enrich_with_kmdb_api.py --limit 100 --export-csv
```

생성/갱신 테이블:

- `kobis_movie_match`
- `kobis_movie_detail`
- `kmdb_movie_match`
- `kmdb_movie_detail`
- `movie_snapshot_enriched`

공유용 CSV:

- `data/processed/movie_snapshot_enriched.csv`
- `data/processed/movie_snapshot_enriched_utf8_sig.csv`

보강 규칙은 [docs/enrichment_rules.md](docs/enrichment_rules.md)를 참고하세요.

## Poster ResNet50 Embedding 실험

`movie_snapshot_enriched_utf8_sig.csv`의 `poster_url`을 이용해 포스터 이미지를 다운로드하고, 사전학습 ResNet50으로 2048차원 이미지 embedding을 만드는 실험 노트북입니다.

```text
src/notebooks/embeddings/Movie_Poster_ResNet50_Embedding.ipynb
```

실행 전에는 `movie_snapshot_enriched_utf8_sig.csv`에 `poster_url` 컬럼이 준비되어 있어야 합니다. `poster_url`은 KMDb 보강 결과에서 생성됩니다.

노트북은 기본적으로 2016년 이후 영화 중 `poster_url`이 있는 행만 사용합니다. 처음 테스트할 때는 노트북의 아래 설정을 유지합니다.

```python
MAX_IMAGES = 100
```

전체 포스터에 대해 실행하려면 다음처럼 변경합니다.

```python
MAX_IMAGES = None
```

실행 결과는 입력 CSV가 있는 폴더 아래 `poster_resnet50/`에 저장됩니다.

```text
data/processed/poster_resnet50/
  posters/
  poster_embeddings_resnet50.npy
  poster_embeddings_resnet50_index.csv
  poster_download_log.csv
```

포스터 이미지와 embedding 파일은 실험용 산출물이며 용량이 커질 수 있으므로 Git에 올리지 않습니다. 자세한 실행 절차와 산출물 설명은 [docs/poster_resnet50_pipeline.md](docs/poster_resnet50_pipeline.md)를 참고하세요.

모델 실행 전 필요한 데이터 생성 과정은 [docs/data_pipeline.md](docs/data_pipeline.md)에 정리되어 있습니다.
