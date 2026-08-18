# Owl's Pick - AI & Data Scraper Engine

> OpenAI API 기반 비동기 GenAI 파이프라인 및 HowLongToBeat 메타데이터 수집을 전담하는 FastAPI 서브 모듈

<br/>

## 1. 모듈 개요

* **역할:** Spring Boot 메인 서버와 통신하며 OpenAI API 연동 및 HowLongToBeat 스크래핑을 전담하는 무상태 비동기 처리 엔진
* **메인 저장소:** [Owl's Pick](https://github.com/Seoleeder/owls-pick)
* **개발 인원 및 기간:** 1인 개발 / 2026.03 ~ 2026.08

<br/>
<br/>

## 2. 기술 스택

| 분류 | 기술 스택 | 적용 목적 및 세부 내용 |
| :--- | :--- | :--- |
| **Framework** | FastAPI, Uvicorn, Starlette | 비동기 I/O 기반 고성능 API 서빙 |
| **AI & Model** | OpenAI API (`gpt-5.4-mini`, `text-embedding-3-small`) | 메타데이터 한글화, 리뷰 요약, 768차원 임베딩 벡터 생성 |
| **Data Scraping** | howlongtobeatpy, Requests | HowLongToBeat 게임 플레이타임 데이터 수집 및 가공 |
| **Config & Validation** | Pydantic v2, Pydantic-Settings (TOML), Python-Dotenv | 파이프라인 동시성 파라미터 관리 및 입출력 DTO 유효성 검증 |
| **Monitoring & Cloud** | Prometheus Fastapi Instrumentator, Python-Logging-Loki, Boto3 | 메트릭 계측, 구조화 로그 전송 및 AWS Parameter Store 연동 |

<br/>
<br/>

## 3. 핵심 기능 및 파이프라인

### 1) 게임 메타데이터 한글화 파이프라인
* Steam 및 IGDB에서 수집된 영문 메타데이터(설명, 스토리라인, 키워드)를 `gpt-5.4-mini`를 통해 한국어로 정제 및 번역
* `Pydantic` 기반 구조화 출력(Structured Outputs)을 적용하여 정형화된 JSON 응답 보장

### 2) 스팀 유저 리뷰 요약 및 키워드 추출
* `gpt-5.4-mini`를 활용하여 다수의 유저 리뷰 텍스트를 분석하고 핵심 내용 요약 및 장단점 키워드 추출
* LLM 컨텍스트 한도 관리를 위한 입력 텍스트 전처리 및 토큰 압축 로직 적용

### 3) 텍스트 임베딩 벡터 생성
* 게임 메타데이터 및 리뷰 요약 텍스트를 `text-embedding-3-small` 모델을 통해 768차원 실수 벡터로 변환
* Spring Boot 백엔드의 `pgvector` 저장을 지원하기 위해 마이크로 배치 및 동시성 제어가 적용된 임베딩 결과 반환

### 4) 대화형 게임 추천 RAG 및 세션 요약 (Owl's 챗봇)
* 사용자 대화 맥락을 반영한 검색용 쿼리 벡터 임베딩 추출 (`/query`)
* `pgvector` 코사인 유사도로 검색된 게임 메타데이터 컨텍스트 기반 RAG 최종 추천 답변 생성 (`/generate`)
* 사용자 첫 발화 메시지 요약 기반 채팅 세션 타이틀 비동기 자동 생성 (`/title/generate`)

### 5) HowLongToBeat 플레이타임 데이터 스크래핑
* `howlongtobeatpy` 라이브러리를 연동하여 게임별 메인 스토리, 서브 퀘스트, 전체 플레이타임 데이터 수집 및 정규화

### 6) 비동기 콜백(Webhook) 및 동시성 제어
* Spring Boot 연동 타임아웃 방지를 위한 `202 Accepted` 즉시 응답 반환 및 `BackgroundTasks` 기반 백그라운드 AI 가공
* 가공 완료 시 Spring Boot 내부 Webhook Push 전송 및 `requestId` 기반 비동기 트랜잭션 추적
* `asyncio.Semaphore`를 활용한 파이프라인별(한글화, 리뷰, HLTB, 임베딩) 동시 요청 수 제어 및 OpenAI Rate Limit 방어

<br/>
<br/>

## 4. 내부 API 인터페이스 명세

| Method | Endpoint | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/genai/localization/games/bulk` | 게임 설명 및 스토리라인 한글화 및 정제 |
| `POST` | `/api/genai/localization/keywords/bulk` | 게임 키워드 태 한글화 및 정제 |
| `POST` | `/api/genai/summarize/reviews` | 스팀 유저 리뷰 요약 및 장단점 키워드 추출 |
| `POST` | `/api/genai/embeddings/batch` | 768차원 텍스트 임베딩 벡터 생성 |
| `POST` | `/api/genai/chat/embeddings/query` | 대화 맥락 기반 RAG 검색용 쿼리 벡터 임베딩 생성 |
| `POST` | `/api/genai/chat/generate` | 검색된 게임 컨텍스트 기반 RAG 최종 답변 생성 |
| `POST` | `/api/genai/chat/title/generate` | 사용자 첫 메시지 기반 채팅 세션 타이틀 생성 |
| `POST` | `/api/init/hltb/scrape` | HowLongToBeat 게임 플레이타임 데이터 스크래핑 |
| `GET` | `/health` | 서버 상태 및 모듈 헬스체크 |
| `GET` | `/metrics` | Prometheus 모니터링 메트릭 수집 엔드포인트 |

<br/>
<br/>

## 5. 실행 방법 (Getting Started)

### 1) 사전 요구사항 (Prerequisites)
* **Python 3.11+**

<br/>

### 2) 설정 파일 구성

* 루트 디렉터리의 `.env.example` 복사 후 `.env` 생성 및 필수 키 정의.

```bash
cp .env.example .env
```

```properties
APP_ENV="local"
OPENAI_API_KEY=your_openai_api_key
```

* `config.toml` 파일을 통한 파이프라인별 세마포어 및 임베딩 파라미터 정의.

```Ini, TOML
[localization]
game_semaphore_limit = 5
keyword_semaphore_limit = 50

[review]
semaphore_limit = 5

[hltb]
semaphore_limit = 10

[embedding]
output_dimension = 768
max_concurrent_tasks = 10
max_text_length = 4000
micro_batch_size = 20
sleep_seconds = 0.5
```

<br/>

### 3) 의존성 설치 및 로컬 실행

```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# Uvicorn 서버 구동
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4) 구동 확인 및 API 명세
* FastAPI Swagger UI: `http://localhost:8000/docs`

* Health Check Endpoint: `http://localhost:8000/health`


