# KOBIS 병합 규칙

## 원본 파일

- KOBIS 기간별 박스오피스 파일은 `data/raw/`에 둡니다.
- 원본 파일은 수정하지 않습니다.
- DB는 `src/scripts/build_kobis_sqlite.py`로 재생성합니다.

```bash
python3 src/scripts/build_kobis_sqlite.py
```

생성 위치:

```text
data/db/kobis_movies.db
```

## 원본 테이블

`boxoffice_period_raw`는 각 KOBIS 파일에서 읽은 영화 행을 그대로 저장하는 원본성 테이블입니다.

원본 컬럼 외에 추적을 위한 메타데이터 컬럼을 추가합니다.

- `source_file`: 원본 파일명
- `period_start`: KOBIS 조회 시작일
- `period_end`: KOBIS 조회 종료일
- `loaded_at`: DB 생성 시각
- `row_number_in_file`: 감지된 데이터 테이블 안에서의 행 번호

## 영화 식별 기준

영화는 다음 두 값을 기준으로 묶습니다.

- `movie_name_clean`
- `release_date`

즉 같은 영화명이라도 개봉일이 다르면 다른 영화로 봅니다.

## 스냅샷 생성 규칙

`movie_snapshot`은 영화 그룹마다 대표 행 하나만 남긴 테이블입니다.

대표 행은 다음 순서로 선택합니다.

1. `period_end`가 가장 최신인 행
2. `cumulative_audience`가 가장 큰 행
3. `source_file`이 사전순으로 앞서는 행
4. `row_number_in_file`이 가장 작은 행

## 타깃 생성 규칙

`target_final_audience`는 같은 영화 그룹 안에서 `cumulative_audience`의 최댓값으로 만듭니다.

그룹 기준:

```text
movie_name_clean + release_date
```

## 파생 테이블

### `movie_snapshot_selected`

`movie_snapshot`에서 모델링/분석에 우선 필요한 컬럼만 남긴 테이블입니다.
`show_count`는 KOBIS 원본의 `상영횟수` 값이며, 같은 영화 그룹 안의 값을 합산해 누적 상영횟수로 사용합니다.

### `movie_snapshot_enriched`

`movie_snapshot_selected`에 KOBIS/KMDb API 보강값을 더한 최종 분석용 테이블입니다.
