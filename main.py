#main.py

from fastapi import FastAPI

# 메트릭 수집 라이브러리
from prometheus_fastapi_instrumentator import Instrumentator

# 설정 및 로거
from app.core.logger import setup_logger

from app.core.events import lifespan
from app.core.cors import setup_cors

# 커스텀 미들웨어
from app.core.middleware import TraceIdMiddleware

# API 라우터 
from app.api import (
    localization,
    keyword_localization,
    review_summary,
    embedding,
    owls_chat,
    hltb)


logger = setup_logger("main")

# FastAPI 애플리케이션 객체 생성
app = FastAPI(
    title="Owl's Pick AI Microservice",
    description="게임 데이터 번역, OWLS 챗봇 등 AI 기반 마이크로서비스 API",
    version="1.0.0",
    lifespan=lifespan
)

# 미들웨어(Trace ID 분산 추적) 등록 - 가장 먼저 요청을 가로채서 식별자 부여
app.add_middleware(TraceIdMiddleware)

# 미들웨어(CORS) 적용
setup_cors(app)

# Prometheus 메트릭 수집기 세팅
instrumentator = Instrumentator(
    should_group_status_codes=False,            # 상태 코드 개별 수집 (200, 404, 500 등 그룹화 방지)
    should_ignore_untemplated=True,             # 잘못된 경로의 요청은 수집 제외
    should_instrument_requests_inprogress=True, # 현재 처리 중인 요청 개수 추적 활성화
).instrument(app)

# /metrics 엔드포인트 개방 
instrumentator.expose(app, endpoint="/metrics", tags=["System"])

# API 라우터 등록 
app.include_router(
    localization.router, 
    prefix="/api/genai/localization", 
    tags=["Game Localization"]
)

app.include_router(
    keyword_localization.router, 
    prefix="/api/genai/localization", 
    tags=["Keyword Localization"]
)

app.include_router(
    review_summary.router,
    prefix="/api/genai/summarize",
    tags=["Review Summary"]
)

app.include_router(
    hltb.router,
    prefix="/api/init/hltb",
    tags=["HowLongToBeat"]
    
)

app.include_router(
    embedding.router,
    prefix="/api/genai/embeddings",
    tags=["Embedding"]
)

app.include_router(
    owls_chat.router,
    prefix="/api/genai/chat",
    tags=["RAG Chatbot"]
)

# Health Check 엔드포인트
@app.get("/health", tags=["System"])
async def health_check():
    """MSA 환경(Docker, k8s 등)에서 서버가 살아있는지 확인하는 용도"""
    return {"status": "ok", "service": "owls-pick-ai"}
