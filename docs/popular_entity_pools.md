# 인기 엔티티 Pool 생성 가이드

이 문서는 감독, 배우, 제작사, 배급사 기반 파생 feature를 만들기 위한 popular entity pool 생성 규칙을 정리합니다.

## 목적

`movie_snapshot_enriched`의 인물/회사 메타데이터를 사용해 인기 감독, 인기 배우, 인기 제작사, 인기 배급사 목록을 만듭니다.

생성된 pool은 모델링 단계에서 아래와 같은 파생 feature를 만들 때 사용합니다.

```text
has_popular_director
popular_director_count
has_popular_actor
popular_actor_count
has_popular_production_company
popular_production_company_count
has_popular_distributor
popular_distributor_count
```

## 입력 데이터

기본 입력은 SQLite DB의 최종 보강 테이블입니다.

```text
data/db/kobis_movies.db
movie_snapshot_enriched
```

인기 기준 관객 수는 `movie_snapshot.target_final_audience`를 사용합니다.

현재 `movie_snapshot_enriched_utf8_sig.csv`에는 `target_final_audience` 컬럼이 없기 때문에, 스크립트는 DB에서 `movie_snapshot_enriched`와 `movie_snapshot`을 아래 키로 조인합니다.

```text
movie_name_clean + release_date
```

조인 후 `target_final_audience`가 없으면 `movie_snapshot_enriched.cumulative_audience`를 fallback으로 사용합니다.

## 생성 스크립트

```bash
python3 src/scripts/build_popular_entity_pools.py
```

기본 출력 위치:

```text
data/processed/entity_pools/
```

DB 경로, 출력 경로, alias map 경로를 바꾸고 싶으면 아래 옵션을 사용할 수 있습니다.

```bash
python3 src/scripts/build_popular_entity_pools.py \
  --db-path data/db/kobis_movies.db \
  --output-dir data/processed/entity_pools \
  --alias-map-path docs/company_alias_map_utf8_sig.csv
```

## Pool 선정 기준

인기 기준은 전체 기간의 누적 관객 수 통계로 만듭니다.

각 엔티티별로 참여 영화의 `target_final_audience`를 집계하고, 최소 참여 영화 수 조건을 통과한 엔티티 중 `total_audience` 상위 N개를 pool에 포함합니다.

```text
entity_type           min_movie_count   top_n
director              2                 100
actor                 3                 300
production_company    2                 100
distributor           2                 50
```

정렬 우선순위는 다음과 같습니다.

1. `total_audience` 내림차순
2. `hit_5m_count` 내림차순
3. `hit_3m_count` 내림차순
4. `movie_count` 내림차순
5. `mean_audience` 내림차순

## 엔티티 분리 규칙

감독, 배우, 제작사, 배급사는 한 컬럼 안에 여러 값이 들어올 수 있습니다.

스크립트는 아래 구분자를 엔티티 구분자로 처리합니다.

```text
,
|
;
```

각 엔티티 이름은 앞뒤 공백과 중복 공백을 정리합니다.

아래 값은 빈 값으로 보고 제외합니다.

```text
""
-
--
nan
none
null
정보없음
N/A
n/a
```

같은 영화 안에서 같은 엔티티가 중복으로 들어오면 한 번만 집계합니다.

## 제작사/배급사 Alias Map

제작사와 배급사는 표기 흔들림이 많기 때문에 alias map을 먼저 적용합니다.

기본 alias map:

```text
docs/company_alias_map_utf8_sig.csv
```

alias map 컬럼:

```text
entity_type
canonical_entity
aliases
```

`aliases`는 `|` 문자로 여러 표기를 구분합니다.

예:

```text
production_company,Disney,disney|walt disney|월트디즈니|디즈니|pixar|픽사
distributor,Sony Pictures,sony|sony pictures|소니픽쳐스|한국소니픽쳐스
```

스크립트는 원문 엔티티와 alias를 모두 정규화한 뒤, 원문 엔티티 안에 alias가 포함되면 해당 `canonical_entity`로 집계합니다.

정규화 규칙:

- 영문 대소문자 구분 제거
- `㈜`를 `주`로 변환
- 공백과 특수문자 제거

예:

```text
Sony Pictures Entertainment -> sonypicturesentertainment
sony pictures               -> sonypictures
```

따라서 `sony pictures` alias는 `Sony Pictures Entertainment`에 포함되는 것으로 판단합니다.

여러 alias가 동시에 매칭될 수 있을 때는 가장 긴 alias를 우선합니다. 예를 들어 `소니픽쳐스릴리징월트디즈니스튜디오스코리아`처럼 Sony와 Disney 관련 문자열이 함께 있는 경우, 더 구체적인 Sony alias가 먼저 적용됩니다.

alias map에 매칭되지 않는 제작사/배급사는 공백과 특수문자를 제거한 `entity_key`로 집계합니다.

예를 들어 아래 값들은 같은 `entity_key`로 집계될 수 있습니다.

```text
Studio Canal
StudioCanal
```

`㈜`는 `(주)`와 같은 의미로 맞추기 위해 `주`로 변환한 뒤 특수문자를 제거합니다.

```text
(주)동아수출공사 -> 주동아수출공사
㈜동아수출공사   -> 주동아수출공사
```

단, alias map에 없는 일반 단어는 제거하지 않습니다. 따라서 아래처럼 `(주)` 유무가 다른 경우는 alias map에 명시하지 않는 한 같은 회사로 자동 병합하지 않습니다.

```text
(주)시네마달 -> 주시네마달
시네마달     -> 시네마달
```

이 방식은 과도한 자동 병합을 피하면서, 영향이 큰 회사는 사람이 관리하는 alias map으로 확실히 묶기 위한 절충안입니다.

## 산출물

생성되는 CSV는 UTF-8 BOM 인코딩으로 저장합니다.

```text
data/processed/entity_pools/popular_director_pool_utf8_sig.csv
data/processed/entity_pools/popular_actor_pool_utf8_sig.csv
data/processed/entity_pools/popular_production_company_pool_utf8_sig.csv
data/processed/entity_pools/popular_distributor_pool_utf8_sig.csv
```

각 파일의 컬럼은 다음과 같습니다.

```text
rank
entity
entity_key
raw_entity_variants
movie_count
total_audience
mean_audience
median_audience
max_audience
hit_1m_count
hit_3m_count
hit_5m_count
```

컬럼 의미:

- `rank`: pool 안에서의 순위
- `entity`: 대표 표시 이름. alias map에 매칭되면 `canonical_entity`, 아니면 같은 `entity_key` 안에서 가장 자주 나온 원문명을 사용
- `entity_key`: 집계에 사용한 엔티티 key. alias map에 매칭되면 `canonical:*`, 아니면 공백과 특수문자를 제거한 key를 사용
- `raw_entity_variants`: 같은 `entity_key`로 묶인 원문 표기 목록
- `movie_count`: 해당 엔티티가 참여한 영화 수
- `total_audience`: 참여 영화의 최종 관객 수 합계
- `mean_audience`: 참여 영화의 평균 최종 관객 수
- `median_audience`: 참여 영화의 중앙값 최종 관객 수
- `max_audience`: 참여 영화 중 최대 최종 관객 수
- `hit_1m_count`: 100만 이상 영화 수
- `hit_3m_count`: 300만 이상 영화 수
- `hit_5m_count`: 500만 이상 영화 수

## 전처리에서 사용하는 방법

모델 전처리에서는 원본 엔티티 이름을 pool의 `entity`와 직접 비교하지 않습니다.

pool 생성 때와 같은 규칙으로 영화 row의 엔티티를 `entity_key`로 변환한 뒤, pool 파일의 `entity_key` 집합과 비교합니다.

기본 흐름:

1. `docs/company_alias_map_utf8_sig.csv`를 로드합니다.
2. popular pool CSV에서 `entity_key` 집합을 만듭니다.
3. 영화 row의 `director`, `actor`, `production_company`, `distributor` 값을 엔티티 단위로 분리합니다.
4. 감독/배우는 원문 정리 후 이름 자체를 `entity_key`로 사용합니다.
5. 제작사/배급사는 alias map을 먼저 적용합니다.
6. alias map에 매칭되면 `canonical:*` 형태의 `entity_key`를 사용합니다.
7. alias map에 매칭되지 않으면 공백과 특수문자를 제거한 `entity_key`를 사용합니다.
8. 변환된 `entity_key` 중 popular pool에 포함된 값이 있는지 확인합니다.

파생 feature 예:

```text
has_popular_director
popular_director_count
has_popular_actor
popular_actor_count
has_popular_production_company
popular_production_company_count
has_popular_distributor
popular_distributor_count
```

feature 생성 규칙 예:

```text
popular_actor_count = 영화의 actor entity_key 중 popular_actor_pool의 entity_key에 포함된 개수
has_popular_actor = popular_actor_count > 0

popular_distributor_count = 영화의 distributor entity_key 중 popular_distributor_pool의 entity_key에 포함된 개수
has_popular_distributor = popular_distributor_count > 0
```

제작사/배급사 예:

```text
원문 distributor:
  소니픽쳐스엔터테인먼트코리아주식회사극장배급지점

alias match:
  소니픽쳐스

변환 결과:
  entity = Sony Pictures
  entity_key = canonical:sonypictures

pool 비교:
  canonical:sonypictures가 popular_distributor_pool의 entity_key에 있으면 popular distributor hit
```

감독/배우 예:

```text
원문 actor:
  오달수,황정민,마동석

변환 결과:
  오달수
  황정민
  마동석

pool 비교:
  각 이름이 popular_actor_pool의 entity_key에 있으면 popular actor hit
```

주의할 점:

- 제작사/배급사는 `entity` 표시명이 아니라 `entity_key`로 비교합니다.
- pool 생성 스크립트와 전처리 코드의 엔티티 분리 규칙이 같아야 합니다.
- alias map을 수정하면 popular pool을 다시 생성한 뒤 feature도 다시 만들어야 합니다.

## 현재 생성 결과 예시

현재 데이터 기준 상위권 예시는 다음과 같습니다.

```text
popular_director_pool:
  류승완, 김한민, 안소니 루소, 조 루소, 봉준호

popular_actor_pool:
  오달수, 황정민, 마동석, 정인기, 유해진

popular_production_company_pool:
  CJ ENM, Warner Bros, Disney, Marvel Studios, (주)비에이엔터테인먼트

popular_distributor_pool:
  CJ ENM, Disney, Lotte Entertainment, Showbox, NEW
```

## 모델링 시 주의점

이 pool은 전체 기간 기준으로 생성합니다.

따라서 순수한 시계열 예측 평가 관점에서는 미래 정보가 일부 포함될 수 있습니다. 이 프로젝트에서는 감독, 배우, 제작사, 배급사의 인기도를 쉽게 바뀌지 않는 정적 정보에 가깝게 보고, 전체 기간 기준 popular pool을 파생 feature로 사용합니다.

보고서나 실험 설명에는 아래 내용을 명시하는 것이 좋습니다.

```text
인기 감독/배우/제작사/배급사 pool은 전체 데이터 기간의 target_final_audience 기준으로 사전에 정의했다.
```
