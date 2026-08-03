#app\api\embedding.py

import traceback
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

from app.schema.dto.embedding_dto import EmbeddingBatchRequest
from app.services.embedding_service import EmbeddingService
from app.core.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()

def get_embedding_service() -> EmbeddingService:
    """
    EmbeddingService 의존성 주입(DI)용 팩토리 함수
    """
    return EmbeddingService()

@router.post("/batch", status_code=202)
async def generate_batch_embeddings(
    req: EmbeddingBatchRequest,
    background_tasks: BackgroundTasks,
    service: EmbeddingService = Depends(get_embedding_service)
    ):
    """
    게임 메타데이터 배치 임베딩 생성 비동기 API
    요청 수신 즉시 커넥션을 해제하고 백그라운드 태스크로 임베딩 변환 위임
    """
    logger.info(f"Received Async Request: Batch Embedding for {len(req.games)} games. Request ID: {req.request_id}")
    
    try:
        # 백그라운드 태스크 큐에 임베딩 처리 및 Webhook 전송 로직 등록
        background_tasks.add_task(service.process_and_callback, req)
        return {"message": "Task accepted", "requestId": req.request_id}
        
    except Exception as e:
        # 내부 로직 실패 시 500 에러 반환
        logger.error(f"Python Internal Error (Embedding Initialization):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))