#app\api\review_summary.py

import traceback
from openai import AsyncOpenAI
from app.core.dependencies import get_openai_client
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.schema.dto.review_summary_dto import ReviewSummaryRequest
from app.services.review_summary_service import ReviewSummaryService
from app.core.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()

def get_review_summary_service(
    client: AsyncOpenAI = Depends(get_openai_client)
) -> ReviewSummaryService:
    """
    ReviewSummaryService 의존성 주입(DI)용 팩토리 함수
    """
    return ReviewSummaryService(client=client)

@router.post("/reviews", status_code=202)
async def summarize_game_reviews(
    req: ReviewSummaryRequest,
    background_tasks: BackgroundTasks,
    service: ReviewSummaryService = Depends(get_review_summary_service)
    ):
    """
    게임 리뷰 요약 및 긍정/부정 키워드 추출 비동기 요청 API
    요청 수신 즉시 커넥션을 해제하고 백그라운드 태스크로 요약 위임
    """
    logger.info(f"Received Async Request: Review Summary for Game ID {req.game_id} ({len(req.review_texts)} reviews). Request ID: {req.request_id}")
    
    try:
        # 백그라운드 태스크 큐에 리뷰 요약 추론 및 Webhook 전송 로직 등록
        background_tasks.add_task(service.process_and_callback, req)
        return {"message": "Task accepted", "requestId": req.request_id}
    
    except Exception as e:
        # 내부 로직 실패 시 HTTP 500 에러 반환
        logger.error(f"Python Internal Error:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))