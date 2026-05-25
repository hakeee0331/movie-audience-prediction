# 메타데이터 보강 규칙

## 목적

`movie_snapshot_selected`에서 비어 있는 영화 메타데이터를 보강합니다.

보강은 다음 순서로 진행합니다.

1. KOBIS Open API
2. KMDb API

## 값 선택 우선순위

최종 테이블인 `movie_snapshot_enriched`를 만들 때는 아래 우선순위를 따릅니다.

1. `movie_snapshot_selected`에 이미 값이 있으면 그 값을 유지합니다.
2. selected 값이 비어 있고 KOBIS 상세정보에 값이 있으면 KOBIS 값을 사용합니다.
3. selected와 KOBIS 값이 모두 비어 있고 KMDb 상세정보에 값이 있으면 KMDb 값을 사용합니다.

즉 최종 우선순위는 다음과 같습니다.

```text
selected > KOBIS API > KMDb API
```

## KOBIS 보강 흐름

1. `movie_name_clean`과 개봉연도를 사용해 KOBIS 영화목록 API를 검색합니다.
2. 안전하게 매칭되는 경우에만 KOBIS `movieCd`를 확정합니다.
3. 확정된 `movieCd`로 KOBIS 영화 상세정보 API를 호출합니다.
4. 검색 결과와 상세정보 응답을 DB에 캐시합니다.
5. selected 데이터와 API 상세정보를 합쳐 `movie_snapshot_enriched`를 만듭니다.

## KMDb 보강 흐름

1. `movie_name_clean`으로 KMDb API를 검색합니다.
2. 안전하게 매칭되는 경우에만 KMDb 데이터를 확정합니다.
3. KMDb 매칭 결과와 상세정보를 DB에 저장합니다.
4. `selected > KOBIS API > KMDb API` 우선순위로 `movie_snapshot_enriched`를 다시 만듭니다.

## 자동 매칭 규칙

KOBIS와 KMDb 모두 보수적인 자동 매칭 규칙을 사용합니다.

자동으로 `matched` 처리하는 경우는 아래 두 가지뿐입니다.

1. 제목이 정확히 일치하고 개봉일도 정확히 일치하는 경우
2. 제목이 정확히 일치하고 개봉연도가 같으며, 해당 조건의 후보가 하나뿐인 경우

그 외 경우는 자동 보강에 사용하지 않습니다.

```text
candidate
ambiguous
not_found
error
```

위 상태들은 캐시 테이블에 저장하지만, `movie_snapshot_enriched` 값 보강에는 사용하지 않습니다.

## 테이블

### `kobis_movie_match`

KOBIS 영화목록 API 검색 결과와 매칭 판단을 저장합니다.

### `kobis_movie_detail`

안전하게 매칭된 KOBIS `movieCd`의 영화 상세정보 API 응답을 저장합니다.

### `kmdb_movie_match`

KMDb 검색 결과와 매칭 판단을 저장합니다.

### `kmdb_movie_detail`

안전하게 매칭된 KMDb 영화 레코드에서 추출한 상세정보를 저장합니다.

KMDb 원본 레코드는 `raw_record_json`에 저장합니다. 따라서 이후 `poster_url`, `synopsis` 같은 새 컬럼은 API 재호출 없이 기존 JSON에서 다시 추출할 수 있습니다.

### `movie_snapshot_enriched`

최종 보강 테이블입니다.

기존 selected 값을 우선 유지하고, 비어 있는 값만 KOBIS 또는 KMDb 값으로 채웁니다.

현재 추가된 주요 보강 컬럼은 다음과 같습니다.

```text
poster_url
synopsis
```
