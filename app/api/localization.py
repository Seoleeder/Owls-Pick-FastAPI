#app\api\localization.py

import traceback
from openai import AsyncOpenAI
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from app.schema.dto.localization_dto import BulkLocalizationRequest, BulkLocalizationResponse
from app.services.localization_service import LocalizationService
from app.core.dependencies import get_openai_client
from app.core.logger import setup_logger
from fastapi import HTTPException

logger = setup_logger(__name__)
router = APIRouter()

def get_localization_service(
    client: AsyncOpenAI = Depends(get_openai_client)
) -> LocalizationService:
    """
    LocalizationService 의존성 주입(DI)용 팩토리 함수
    """
    return LocalizationService(client=client)

@router.post("/games/bulk", status_code=202)
async def localize_bulk_games(
    req: BulkLocalizationRequest,
    background_tasks: BackgroundTasks,
    service: LocalizationService = Depends(get_localization_service)
    ):
    """
    대량 게임 데이터 비동기 한글화 요청 수신 API
    요청 수신 즉시 커넥션을 해제하고 백그라운드 태스크로 한글화 위임
    """
    game_count = len(req.games)
    logger.info(f"Received Async Request: Bulk Localization for {game_count} games. Request ID: {req.request_id}")
    
    try:
        # 백그라운드 태스크에 한글화 수행 및 Webhook 전송 로직 등록
        background_tasks.add_task(service.process_and_callback, req)
        
        return {"message": "Task accepted", "requestId": req.request_id}
    
    except Exception as e:
        logger.error(f"Python Internal Error (Game Localization Initialization):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))    




