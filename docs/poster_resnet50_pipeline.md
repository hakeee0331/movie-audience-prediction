# 포스터 ResNet50 Embedding 생성 과정

이 문서는 영화 포스터 이미지를 모델 입력 후보 feature로 만들기 위한 ResNet50 embedding 생성 과정을 정리합니다.

현재 구현은 다음 노트북에 있습니다.

```text
src/notebooks/Movie_Poster_ResNet50_Embedding.ipynb
```

## 목적

`movie_snapshot_enriched_utf8_sig.csv`의 `poster_url`을 이용해 영화 포스터 이미지를 다운로드하고, 사전학습 ResNet50 모델로 각 포스터를 2048차원 이미지 embedding 벡터로 변환합니다.

이 embedding은 이후 MLP 등 모델에서 이미지 feature로 사용할지 검토하기 위한 실험용 산출물입니다.

## 입력 데이터

기본 입력 CSV는 다음 파일입니다.

```text
data/processed/movie_snapshot_enriched_utf8_sig.csv
```

Colab에서는 현재 다음 경로를 우선 사용합니다.

```text
/content/gdrive/MyDrive/흥보위/sql_result/movie_snapshot_enriched_utf8_sig.csv
```

주요 사용 컬럼은 다음과 같습니다.

```text
movie_name_clean
release_date
kmdb_doc_id
poster_url
```

## 처리 대상

노트북에서는 먼저 `release_date >= 2016-01-01`인 영화만 남깁니다.

이 기준은 기존 모델링 노트북에서 2016년 이후 영화만 학습 대상으로 제한한 것과 맞추기 위한 것입니다.

그 다음 `poster_url`이 있는 행만 포스터 다운로드 대상으로 사용합니다.

## 실행 흐름

노트북은 다음 순서로 실행합니다.

```text
1. 라이브러리 로드
2. CSV 로드
2.5. 2016년 이후 데이터만 필터링
3. poster_url 있는 행만 필터링
4. 이미지 다운로드/cache
5. 다운로드 성공/실패 확인
6. 사전학습 CNN 모델 로드
7. 이미지 전처리
8. CNN embedding 추출
9. embedding 저장
10. 저장 결과 검증
```

처음 테스트할 때는 다음 설정을 유지합니다.

```python
MAX_IMAGES = 100
```

전체 포스터에 대해 실행할 때는 다음처럼 변경합니다.

```python
MAX_IMAGES = None
```

## 저장 위치

결과물은 CSV가 있는 폴더 아래 `poster_resnet50/` 디렉토리에 저장합니다.

로컬 실행 시:

```text
data/processed/poster_resnet50/
  posters/
  poster_embeddings_resnet50.npy
  poster_embeddings_resnet50_index.csv
  poster_download_log.csv
```

Colab 실행 시:

```text
/content/gdrive/MyDrive/흥보위/sql_result/poster_resnet50/
  posters/
  poster_embeddings_resnet50.npy
  poster_embeddings_resnet50_index.csv
  poster_download_log.csv
```

## 산출물 설명

### posters/

다운로드한 포스터 이미지 파일이 저장되는 폴더입니다.

파일명은 우선 `kmdb_doc_id`를 사용합니다. `kmdb_doc_id`가 없으면 영화명, 개봉일, 원본 행 번호를 조합한 값을 해시로 바꾸어 사용합니다.

### poster_embeddings_resnet50.npy

ResNet50으로 추출한 실제 이미지 embedding 배열입니다.

예를 들어 100개 포스터를 처리했다면 shape은 다음과 같습니다.

```text
(100, 2048)
```

여기서 `2048`은 ResNet50의 마지막 분류층을 제거했을 때 나오는 이미지 특징 벡터 차원입니다.

### poster_embeddings_resnet50_index.csv

`.npy` 파일의 각 벡터가 어떤 영화에 해당하는지 알려주는 연결표입니다.

현재 저장 컬럼은 다음과 같습니다.

```text
source_row_index
movie_name_clean
release_date
poster_path
```

연결 관계는 행 순서 기준입니다.

```text
poster_embeddings_resnet50.npy의 0번째 벡터
= poster_embeddings_resnet50_index.csv의 0번째 행 영화
```

`source_row_index`는 원본 `movie_snapshot_enriched_utf8_sig.csv`에서의 행 번호입니다.

### poster_download_log.csv

포스터 다운로드 시도 결과를 저장한 로그입니다.

다운로드 성공뿐 아니라 실패한 URL도 확인할 수 있습니다.

주요 상태값은 다음과 같습니다.

```text
downloaded
cached
failed: ...
```

## ResNet50 사용 방식

ResNet50은 원래 이미지를 1000개 ImageNet 클래스로 분류하는 CNN 모델입니다.

하지만 이 프로젝트에서는 포스터가 어떤 ImageNet 클래스인지 알고 싶은 것이 아니라, 포스터의 시각적 특징을 숫자 벡터로 얻고 싶습니다.

따라서 마지막 분류층을 제거하고, 그 직전의 2048차원 특징 벡터를 사용합니다.

코드상 핵심은 다음 부분입니다.

```python
cnn_model = models.resnet50(weights=weights)
cnn_model.fc = nn.Identity()
```

의미는 다음과 같습니다.

```text
포스터 이미지
→ ResNet50
→ 2048차원 이미지 특징 벡터
```

## 이미지 전처리

이미지 전처리는 ResNet50 사전학습 가중치에 맞는 기본 transform을 사용합니다.

```python
image_transform = weights.transforms()
```

일반적으로 이 과정에는 resize, center crop, tensor 변환, normalize가 포함됩니다.

현재 방식은 ResNet50 baseline 실험입니다. 포스터는 세로형 이미지가 많기 때문에 224x224 center crop 과정에서 포스터 상단 또는 하단 일부가 잘릴 수 있습니다.

이 방식은 최종 최적안이라기보다, 이미지 feature가 모델 성능에 도움이 되는지 확인하기 위한 기준 실험입니다.

## 포스터가 없는 영화 처리

현재 노트북은 포스터 URL이 있고 다운로드에 성공한 영화에 대해서만 embedding을 생성합니다.

포스터가 없는 영화의 처리 방식은 아직 확정하지 않았습니다.

후보는 다음과 같습니다.

```text
1. 포스터 embedding이 있는 영화만 사용
2. 포스터 없는 영화는 zero vector로 처리
3. has_poster_embedding flag를 추가
4. tabular-only 모델과 image+tabular 모델을 따로 비교
```

이 부분은 팀 논의 또는 모델 성능 비교 후 결정합니다.

## Git 관리 주의

포스터 이미지와 embedding 파일은 용량이 커질 수 있으므로 기본적으로 Git에 올리지 않습니다.

현재 `.gitignore`는 `data/processed/*`를 제외하도록 설정되어 있습니다.

공유가 필요한 경우에는 GitHub가 아니라 Google Drive, 별도 스토리지, 또는 재생성 가능한 노트북 실행 절차를 통해 공유하는 방식을 권장합니다.
