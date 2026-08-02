#app\api\keyword_localization.py

import traceback
from openai import AsyncOpenAI
from app.core.dependencies import get_openai_client
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.schema.dto.keyword_localization_dto import KeywordLocalizationRequest
from app.services.keyword_localization_service import KeywordLocalizationService
from app.core.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()

def get_keyword_localization_service(
    client: AsyncOpenAI = Depends(get_openai_client)
) -> KeywordLocalizationService:
    """
    LocalizationService 의존성 주입(DI)용 팩토리 함수
    """
    return KeywordLocalizationService(client=client)

@router.post("/keywords/bulk", status_code=202)
async def localize_bulk_keywords(
    req: KeywordLocalizationRequest,
    background_tasks: BackgroundTasks,
    service: KeywordLocalizationService = Depends(get_keyword_localization_service)
    ):
    """
    대량 게임 키워드 비동기 한글화 요청 수신 API
    요청 수신 즉시 커넥션을 해제하고 백그라운드 태스크로 한글화 위임
    """
    kw_count = len(req.keywords)
    logger.info(f"Received Async Request: Keyword Localization for {kw_count} keywords. Request ID: {req.request_id}")
    
    try:
        # 백그라운드 태스크에 키워드 한글화 수행 및 Webhook 전송 로직 등록
        background_tasks.add_task(service.process_and_callback, req)
        return {"message": "Task accepted", "requestId": req.request_id}
        
    except Exception as e:
        # 실패 시 500 에러를 반환하여 Spring Boot에서 캐치하도록 유도
        logger.error(f"Python Internal Error (Keyword Localization Initialization):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))