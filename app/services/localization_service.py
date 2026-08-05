#app\services\localization_service.py

import os
import asyncio
import json
import httpx
import gc

from app.core import events
from app.core.logger import setup_logger
from app.core.settings import get_settings
from app.utils.file_util import load_prompt_text

from app.schema.enums.genai_fail_reason import GenaiFailReason
from app.schema.dto.localization_dto import GameItem, LocalizationResult, BulkLocalizationRequest, BulkLocalizationResponse
from app.schema.genai.localization_genai_schema import LocalizationResponseSchema

logger = setup_logger(__name__)

class LocalizationService:
    def __init__(self):
        
        settings = get_settings()
        
        # 싱글톤 OpenAI 클라이언트 매핑
        self.client = events.openai_client
        
        # 한글화 전용 환경 변수 로드
        self.model_name = os.getenv("LOCALIZATION_MODEL_NAME", "gpt-5.4-mini")
        self.temperature = float(os.getenv("LOCALIZATION_TEMPERATURE", "0.2"))

        self.system_instruction = load_prompt_text("localization_instruction.md")
        
        # API Rate Limit 방어 및 프로세스 과부하 방지를 위한 동시성 제어
        self.semaphore = asyncio.Semaphore(settings.localization.game_semaphore_limit)
        
        logger.info(f"[Localization] Initialized with AsyncOpenAI SDK (Model: {self.model_name})")
        
    async def process_and_callback(self, req: BulkLocalizationRequest, retries: int = 2):
        """
        비동기 병렬 한글화 처리 후 Spring Boot 웹훅으로 최종 결과 전송
        """
        logger.info(f"[Localization] Starting background processing for Request ID: {req.request_id}")
        
        try:
            # 데이터 병렬 한글화 수행 및 결과 객체 취합
            results = await self.process_bulk_localizations(req.games)
            response_payload = BulkLocalizationResponse(
                request_id=req.request_id, 
                success=True, 
                results=results
            )
        except Exception as e:
            logger.error(f"[Localization] Failed processing Request ID: {req.request_id} | Error: {str(e)}")
            response_payload = BulkLocalizationResponse(
                request_id=req.request_id, 
                success=False, 
                results=[]
            )
            
        
        try:
            # Webhook 전송용 헤더 및 바디 구성
            headers = {'Content-Type': 'application/json'}
            body = json.dumps(response_payload.model_dump(by_alias=True))
            
            logger.info(f"[Localization] Sending webhook callback for Request ID: {req.request_id} to {req.callback_url}")
            
            # 지수 백오프 재시도 루프
            for attempt in range(retries):
                try:
                    # httpx를 활용한 비동기 네트워크 통신 수행
                    async with httpx.AsyncClient(timeout=10.0) as http_client:
                        response = await http_client.post(req.callback_url, headers=headers, content=body)
                        response.raise_for_status()
                        
                        logger.info(f"[Localization] Webhook delivered successfully - Request ID: {req.request_id}")
                        break
                except Exception as e:
                    # 일시적 오류 발생 시 점진적 대기(2초, 4초) 후 재시도
                    if attempt < retries:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"[Localization] Webhook delivery failed, retrying {attempt + 1}/{retries}... Request ID: {req.request_id} ({str(e)})")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # 설정된 재시도 횟수 초과 시 최종 실패 처리
                    logger.error(f"[Localization] Final Webhook delivery failure - Request ID: {req.request_id} | Error: {str(e)}")
                
        except Exception as e:
            logger.error(f"[Localization] Webhook connection error for Request ID: {req.request_id} | Error: {str(e)}")
        finally:
            # 사용 완료 객체 물리 메모리 즉시 반환
            gc.collect()
            
    
    async def localize_task (self, game: GameItem, retries: int = 2) -> LocalizationResult:
        """
        단일 게임 데이터 한글화 프로세스
        """
        # 불필요한 API 호출 방지를 위한 데이터 조기 검증
        if not game.description and not game.storyline:
            logger.debug(f"[Localization] Insufficient data. Skipping - GameId: {game.game_id}")
            return LocalizationResult(game.game_id, GenaiFailReason.INSUFFICIENT_DATA)
        
        # 필드별 유효 데이터 존재 여부 검증
        has_desc = bool(game.description and game.description.strip())
        has_story = bool(game.storyline and game.storyline.strip())
            
        # 유효한 데이터만 추출하여 API 요청 컨텍스트 구성
        prompt_parts = []
        if has_desc:
            prompt_parts.append(f"<Description>\n{game.description}\n</Description>")
        if has_story:
            prompt_parts.append(f"<Storyline>\n{game.storyline}\n</Storyline>")
        
        user_prompt = "\n\n".join(prompt_parts) 
        
        # 네트워크 지연 및 API 일시 오류 대응을 위한 지수 백오프 재시도 루프
        for attempt in range(retries):
            try:
                # 할당된 세마포어 한도 내에서만 API 요청 실행
                async with self.semaphore:  
                    # OpenAI API 호출 (Structured Outputs 적용)
                    response = await self.client.responses.parse(
                        model=self.model_name,
                        instructions=self.system_instruction,  
                        input=user_prompt,                     
                        temperature=self.temperature,
                        text_format=LocalizationResponseSchema,     # DTO 규격 강제
                        store=False                                 # 단건 처리용 상태 저장 비활성화
                    )
                
                parsed_data = None
                
                # 응답 배열 순회 및 파싱 결과 추출
                for output in response.output:
                    if output.type != "message":
                        continue
                    
                    for item in output.content:
                        # 모델 안전 정책 위반으로 인한 응답 거절
                        if item.type == "refusal":
                            logger.warning(f"[Localization] Refused by Safety Filter: {item.refusal} - GameId: {game.game_id}")
                            return self._build_fallback_result(game.game_id, GenaiFailReason.SAFETY_FILTER_REJECTED)
                        
                        # 파싱된 Pydantic 객체 추출
                        if getattr(item, "parsed", None):
                            parsed_data = item.parsed

                # 파싱 결과 누락 시 예외 로그 기록 후 우회 처리
                if not parsed_data:
                     logger.warning(f"[Localization] No valid parsed content returned - GameId: {game.game_id}")
                     return self._build_fallback_result(game.game_id, GenaiFailReason.INVALID_RESPONSE)   

                return LocalizationResult(
                    game_id=game.game_id,
                    description_ko=parsed_data.description_ko if has_desc else None,
                    storyline_ko=parsed_data.storyline_ko if has_story else None
                )
                
            except Exception as e:
                # 일시적 오류 발생 시 점진적 대기 후 재시도
                if attempt < retries - 1:
                    sleep_time = (attempt + 1) * 2
                    logger.warning(f"[Localization] API Error, retrying {attempt + 1}/{retries}... GameId: {game.game_id} ({str(e)})")
                    await asyncio.sleep(sleep_time)
                    continue
                
                # 설정된 재시도 횟수 초과 시 최종 실패 처리
                logger.error(f"[Localization] Final Failure - GameId: {game.game_id} | Error: {str(e)}")
                return self._build_fallback_result(game.game_id, GenaiFailReason.NETWORK_ERROR)

    async def process_bulk_localizations(self, games: list[GameItem]) -> list[LocalizationResult]:
        """
        대량의 게임 데이터 비동기 병렬 한글화 파이프라인
        """
        total_count = len(games)
        logger.debug(f"[Localization] Starting async concurrent localization for {total_count} items.")
        
        # 각 게임 데이터를 독립적인 비동기 태스크로 변환
        tasks = [self.localize_task(game) for game in games]
        
        # 태스크 병렬 실행 및 결과 취합
        results = await asyncio.gather(*tasks)
        
        logger.debug(f"[Localization] Localization completed for {total_count} items.")
        
        return list(results)
    
    
    def _build_fallback_result(self, game_id: int, reason: GenaiFailReason) -> LocalizationResult:
        """
        실패 건에 대한 에러 응답 객체 생성
        """
        return LocalizationResult(
            game_id=game_id, 
            description_ko=None, 
            storyline_ko=None,
            error_reason=reason
        )