#app\services\review_summary_service.py

import os
import json
import asyncio
import httplib2
from openai import AsyncOpenAI

from app.core.logger import setup_logger
from app.utils.file_util import load_prompt_text
from app.schema.enums.genai_fail_reason import GenaiFailReason
from app.services.factories.review_config_factory import ReviewConfigFactory
from app.schema.dto.review_summary_dto import ReviewSummaryRequest, ReviewSummaryResponse
from app.schema.genai.review_summary_genai_schema import ReviewSummaryResponseSchema

logger = setup_logger(__name__)

class ReviewSummaryService:
    def __init__(self, client: AsyncOpenAI):
        
        # 의존성 주입을 통해 전역 클라이언트 매핑
        self.client = client
        
        # 리뷰 요약 전용 환경 변수 로드
        self.model_name = os.getenv("REVIEW_MODEL_NAME", "gpt-5.4-mini")
        self.temperature = float(os.getenv("REVIEW_TEMPERATURE", "0.35")) 
        self.semaphore_limit = int(os.getenv("REVIEW_SEMAPHORE_LIMIT", "5"))

        # 시스템 프롬프트 로드
        self.system_instruction = load_prompt_text("review_summary_instruction.md")

       # 비동기 OpenAI 클라이언트 초기화
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )

        # API Rate Limit 방어 및 서버 과부하 방지를 위한 동시성 제어
        self.semaphore = asyncio.Semaphore(self.semaphore_limit)

        logger.info(f"[GenAI-Review Summary] Initialized with AsyncOpenAI SDK (Model: {self.model_name})")

    async def process_and_callback(self, req: ReviewSummaryRequest):
        """
        단일 게임 리뷰 요약 처리 후 웹훅으로 결과 전송
        """
        logger.info(f"[GenAI-Review Summary] Starting background processing for Request ID: {req.request_id}")
        
        try:
            # LLM 리뷰 요약 파이프라인 가동 (DTO 형태로 즉시 반환)
            response_payload = await self.summarize_reviews(req)
        except Exception as e:
            logger.error(f"[GenAI-Review Summary] Failed processing Request ID: {req.request_id} | Error: {str(e)}")
            response_payload = self._build_fallback_result(req.request_id, GenaiFailReason.NETWORK_ERROR)
            
        try:
            # 결과 전송용 HTTP 클라이언트 생성
            http = httplib2.Http()
            headers = {'Content-Type': 'application/json'}
            body = json.dumps(response_payload.model_dump(by_alias=True))
            
            logger.info(f"[GenAI-Review Summary] Sending webhook callback for Request ID: {req.request_id} to {req.callback_url}")
            
            response, content = http.request(req.callback_url, 'POST', headers=headers, body=body)
            
            # 4xx 이상 에러 발생 시 실패 로그 기록
            if response.status >= 400:
                logger.error(f"[GenAI-Review Summary] Webhook delivery failed for Request ID: {req.request_id} | Status: {response.status}")
                   
        except Exception as e:
            logger.error(f"[GenAI-Review Summary] Webhook connection error for Request ID: {req.request_id} | Error: {str(e)}")
            
    async def summarize_reviews(self, request: ReviewSummaryRequest, retries: int = 2) -> ReviewSummaryResponse:
        """
        단일 게임 리뷰 요약 파이프라인.
        유저 리뷰 데이터를 분석하여 핵심 요약 텍스트 및 긍/부정 키워드를 추출함.
        """
        # 불필요한 API 호출 방지를 위한 데이터 조기 검증
        if not request.review_texts:
            logger.debug(f"[GenAI-Review Summary] Insufficient data. Skipping - GameId: {request.game_id}")
            return self._build_fallback_result(GenaiFailReason.INSUFFICIENT_DATA)
        
        # 실제 데이터 분포(긍/부정 비율)에 따른 동적 설정 빌드
        # 팩토리를 통해 리뷰 점수가 반영된 동적 시스템 지시문 생성
        dynamic_instruction = ReviewConfigFactory.build_dynamic_instruction(
            review_score=request.review_score,
            system_instruction=self.system_instruction
        )

        # LLM 컨텍스트 주입을 위한 유저 리뷰 텍스트 병합 및 프롬프트 구성
        joined_reviews = "\n---\n".join(request.review_texts)
        prompt = f"다음은 게임 ID {request.game_id}의 스팀 리뷰입니다. 이를 바탕으로 요약과 키워드를 추출해주세요.\n\n<Reviews>\n{joined_reviews}\n</Reviews>"
    

        # 네트워크 지연 및 API 일시 오류 대응을 위한 재시도 루프
        for attempt in range(retries):
            try:
                async with self.semaphore:
                    # OpenAI API 호출 (Structured Outputs 파싱)
                    response = await self.client.responses.parse(
                        model=self.model_name,
                        instructions=dynamic_instruction,
                        input=prompt,
                        temperature=self.temperature,
                        text_format=ReviewSummaryResponseSchema,    # DTO 규격 강제
                        store=False                                 # 단건 처리용 상태 저장 비활성화
                    )

                parsed_data = None

                # 응답 배열 순회 및 파싱 결과 추출
                for output in response.output:
                    if output.type != "message":
                        continue
                    
                    for item in output.content:
                        # 모델 안전 정책 위반으로 인한 응답 거절 처리
                        if item.type == "refusal":
                            logger.warning(f"[GenAI-Review Summary] Refused by Safety Filter - GameId: {request.game_id}")
                            return self._build_fallback_result(GenaiFailReason.SAFETY_FILTER_REJECTED)
                        
                        # 파싱된 Pydantic 객체 추출
                        if getattr(item, "parsed", None):
                            parsed_data = item.parsed

                # 파싱 결과 누락 시 예외 로그 기록 후 실패 처리
                if not parsed_data:
                    logger.warning(f"[GenAI-Review Summary] No valid parsed content returned - GameId: {request.game_id}")
                    return self._build_fallback_result(GenaiFailReason.INVALID_RESPONSE)

                # 정상 파싱 성공 시 DTO 매핑 후 반환
                return ReviewSummaryResponse(
                    request_id=request.request_id,
                    summary_text=parsed_data.summary_text,
                    positive_keywords=parsed_data.positive_keywords,
                    negative_keywords=parsed_data.negative_keywords,
                    error_reason=None
                )

            except Exception as e:
                # 일시적 오류 발생 시 점진적 대기 후 재시도
                if attempt < retries - 1:
                    sleep_time = (attempt + 1) * 2
                    logger.warning(f"[GenAI-Review Summary] API Error, retrying {attempt + 1}/{retries}... GameId: {request.game_id} ({str(e)})")
                    await asyncio.sleep(sleep_time)
                    continue
                
                # 설정된 재시도 횟수 초과 시 최종 실패 로깅 및 에러 반환
                logger.error(f"[GenAI-Review Summary] Final Failure - GameId: {request.game_id} | Error: {str(e)}")
                return self._build_fallback_result(GenaiFailReason.NETWORK_ERROR)
    
    def _build_fallback_result(self, request_id: str, reason: GenaiFailReason) -> ReviewSummaryResponse:
        """
        실패 건에 대한 에러 응답 객체 생성
        """
        return ReviewSummaryResponse(
            request_id=request_id,
            summary_text=None,
            positive_keywords=[],
            negative_keywords=[],
            error_reason=reason
        )