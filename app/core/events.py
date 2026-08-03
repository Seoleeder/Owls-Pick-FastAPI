#app\core\events.py

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from openai import AsyncOpenAI
from app.core.config import init_config
from app.core.settings import get_settings
from app.core.logger import setup_logger

logger = setup_logger(__name__)

# 전역 싱글톤 OpenAI 클라이언트 객체 선언
openai_client: AsyncOpenAI | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 생명주기(시작/종료) 관리 및 전역 리소스 초기화
    """
    global openai_client
    
    logger.info("Starting up Owl's Pick AI Microservice...")
    
    # 환경변수 로드 및 초기화 수행
    init_config()
    
    # Pydantic Settings 객체 생성 및 메모리 캐싱 적용
    get_settings()
    
    # 싱글톤 AsyncOpenAI 클라이언트 인스턴스화
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    yield
    
    logger.info("Shutting down AI Microservice. Cleaning up resources...")
    
    # 애플리케이션 종료 시 유지 중인 HTTP 커넥션 풀 반환
    if openai_client:
        await openai_client.close()