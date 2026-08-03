# app\api\owls_chat.py

import traceback
from fastapi import APIRouter, HTTPException, Depends

from app.schema.dto.owls_chat_dto import (
    QueryEmbeddingRequest, QueryEmbeddingResponse,
    RagGenerationRequest, RagGenerationResponse,
    TitleGenerationRequest, TitleGenerationResponse
)
from app.services.chat_service import ChatService
from app.core.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()

def get_chat_service() -> ChatService:
    """
    ChatService 의존성 주입(DI)용 팩토리 함수
    """
    return ChatService()

@router.post("/embeddings/query", response_model=QueryEmbeddingResponse)
async def generate_query_embedding(
    req: QueryEmbeddingRequest,
    service: ChatService = Depends(get_chat_service)
):
    """
    RAG 검색을 위한 사용자 메시지 벡터 임베딩 API
    """
    logger.info(f"Received Request: Query Embedding (History Length: {len(req.history)})")
    
    try:
        # 서비스 계층 호출 및 검색용 벡터 추출
        vector = await service.extract_query_embedding(req)
        logger.info("Query Embedding Completed Successfully.")
        
        return QueryEmbeddingResponse(vector=vector)
        
    except Exception as e:
        # 내부 로직 실패 시 HTTP 500 에러 및 로깅 처리
        logger.error(f"Python Internal Error (Query Embedding):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate query embedding")


@router.post("/generate", response_model=RagGenerationResponse)
async def generate_rag_chat(
    req: RagGenerationRequest,
    service: ChatService = Depends(get_chat_service)
):
    """
    검색된 연관 게임 데이터 기반 챗봇 최종 응답 생성 API
    """
    logger.info(f"Received Request: Chat Generation (Contexts Length: {len(req.contexts)})")
    
    try:
        # 서비스 계층 호출 및 최종 텍스트 응답 생성
        reply = await service.generate_chat_reply(req)
        logger.info("Chat Generation Completed Successfully.")
        
        return RagGenerationResponse(reply=reply)
        
    except Exception as e:
        # 내부 로직 실패 시 HTTP 500 에러 및 로깅 처리
        logger.error(f"Python Internal Error (Chat Generation):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate chat reply")
    
    
@router.post("/title/generate", response_model=TitleGenerationResponse)
async def generate_session_title(
    req: TitleGenerationRequest,
    service: ChatService = Depends(get_chat_service)
):
    """
    사용자 발화 기반 채팅 세션 타이틀 요약 생성 API
    """
    logger.info(f"Received Request: Title Generation (Message Length: {len(req.user_message)})")
    
    try:
        # 서비스 계층 호출 및 최종 세션 타이틀 추출
        title_text = await service.generate_session_title(req)
        logger.info(f"Title Generation Completed Successfully. Generated Title: '{title_text}'")
        
        return TitleGenerationResponse(title=title_text)
        
    except Exception as e:
        # 내부 로직 실패 시 HTTP 500 에러 및 로깅 처리
        logger.error(f"Python Internal Error (Title Generation):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to generate session title")