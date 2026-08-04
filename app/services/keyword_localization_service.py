#app\services\keyword_localization_service.py

import os
import json
import asyncio
import httpx
import gc

from app.core import events
from app.core.logger import setup_logger
from app.utils.file_util import load_prompt_text

from app.schema.enums.genai_fail_reason import GenaiFailReason
from app.schema.dto.keyword_localization_dto import (
    KeywordResult,
    KeywordLocalizationRequest,
    BulkKeywordLocalizationResponse
)
from app.schema.genai.keyword_genai_schema import BulkKeywordResponseSchema


logger = setup_logger(__name__)

class KeywordLocalizationService:
    def __init__(self):
        
        # 전역 생명주기(Lifespan)에서 초기화된 싱글톤 OpenAI 클라이언트 매핑
        self.client = events.openai_client
        
        # 키워드 한글화 전용 환경 변수 로드
        self.model_name = os.getenv("KEYWORD_MODEL_NAME", "gpt-5.4-mini")
        self.temperature = float(os.getenv("KEYWORD_TEMPERATURE", "0.1"))

        # 시스템 프롬프트 로드
        self.system_instruction = load_prompt_text("keyword_instruction.md")

        # API Rate Limit 방어 및 서버 과부하 방지를 위한 동시성 제어
        self.semaphore = asyncio.Semaphore(50)

        logger.info(f"[KeywordLocalization] Initialized (Model: {self.model_name})")

    async def process_and_callback(self, req: KeywordLocalizationRequest, retries: int = 2):
        """
        비동기 병렬 한글화 처리 후 Spring Boot Webhook으로 결과 전송
        """
        logger.info(f"[KeywordLocalization] Starting background processing for Request ID: {req.request_id}")
        
        try:
            # 키워드 병렬 한글화 파이프라인 가동
            results = await self.process_keyword_localization(req.keywords)
            response_payload = BulkKeywordLocalizationResponse(
                request_id=req.request_id, 
                success=True, 
                localization_results=results
            )
        except Exception as e:
            logger.error(f"[KeywordLocalization] Failed processing Request ID: {req.request_id} | Error: {str(e)}")
            response_payload = BulkKeywordLocalizationResponse(
                request_id=req.request_id, 
                success=False, 
                localization_results=[]
            )
            
        try:
            # Webhook 전송용 헤더 및 바디 구성
            headers = {'Content-Type': 'application/json'}
            body = json.dumps(response_payload.model_dump(by_alias=True))
            
            logger.info(f"[KeywordLocalization] Sending webhook callback for Request ID: {req.request_id} to {req.callback_url}")
            
            # 지수 백오프 재시도 루프
            for attempt in range(retries):
                try:
                    # httpx를 활용한 비동기 네트워크 통신 수행
                    async with httpx.AsyncClient(timeout=10.0) as http_client:
                        response = await http_client.post(req.callback_url, headers=headers, content=body)
                        response.raise_for_status()
                        
                        logger.info(f"[KeywordLocalization] Webhook delivered successfully - Request ID: {req.request_id}")
                        break
                    
                except Exception as e:
                    # 일시적 오류 발생 시 점진적 대기(2초, 4초) 후 재시도
                    if attempt < retries:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"[KeywordLocalization] Webhook delivery failed, retrying {attempt + 1}/{retries}... Request ID: {req.request_id} ({str(e)})")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # 설정된 재시도 횟수 초과 시 최종 실패 처리
                    logger.error(f"[KeywordLocalization] Final Webhook delivery failure - Request ID: {req.request_id} | Error: {str(e)}")
                
        except Exception as e:
            logger.error(f"[KeywordLocalization] Webhook connection error for Request ID: {req.request_id} | Error: {str(e)}")
        finally:
            # 사용 완료 객체 물리 메모리 즉시 반환
            gc.collect()

    async def process_keyword_localization(self, keywords: list[str], retries: int = 2) -> list[KeywordResult]:
            """
            대량의 키워드 데이터 비동기 한글화 파이프라인.
            벌크 처리 실패 시 개별 비동기 처리로 전환하여 가용성을 확보함.
            """
            
            # 불필요한 API 호출 방지를 위한 데이터 조기 검증
            if not keywords:
                return []

            # API 요청을 위한 사용자 프롬프트 구성
            prompt = f"다음 키워드들을 번역해 주세요:\n{json.dumps(keywords, ensure_ascii=False)}"

            # 네트워크 지연 및 API 일시 오류 대응을 위한 지수 백오프 재시도 루프
            for attempt in range(retries):
                try:
                    # OpenAI API 호출 및 파싱 결과 추출
                    is_refused, parsed_data = await self._call_openai_api(prompt)

                    # 파싱 결과 누락 및 거절 시 예외를 발생시켜 개별 단건 처리로 전환
                    if is_refused or not parsed_data:
                        raise ValueError("Refused by policy or Invalid Response")

                    # 정상 파싱 완료 시 DTO 매핑 후 반환
                    return [
                        KeywordResult(
                            eng_name=item.eng_name, 
                            kor_name=item.kor_name, 
                            error_reason=None
                        ) 
                        for item in parsed_data.localization_results
                    ]

                except Exception as e:
                    # 일시적 오류 발생 시 점진적 대기 후 재시도
                    if attempt < retries - 1:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"[KeywordLocalization] Bulk API Error, retrying {attempt + 1}/{retries}... ({str(e)})")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # 설정된 재시도 횟수 초과 시 예외 로그 기록
                    logger.error(f"[KeywordLocalization] Bulk Translation Failed. Triggering Individual Processing. Error: {str(e)}")

            # 벌크 처리 실패에 따른 개별 키워드 독립 비동기 태스크 생성
            logger.debug(f"[KeywordLocalization] Starting individual processing for {len(keywords)} keywords.")
            tasks = [self._localize_single_keyword(kw) for kw in keywords]
            
            # 태스크 병렬 실행 및 결과 취합
            results = await asyncio.gather(*tasks)
            
            return list(results)

    async def _localize_single_keyword(self, keyword: str) -> KeywordResult:
        """
        단일 키워드 한글화 프로세스. 
        """
        prompt = f"다음 키워드를 번역해 주세요:\n[\"{keyword}\"]"
        
        try:
            # 동시성 한도 내에서만 API 요청 실행
            async with self.semaphore:
                # OpenAI API 호출 및 파싱 결과 추출
                is_refused, parsed_data = await self._call_openai_api(prompt)

                # 모델 안전 정책 위반으로 인한 응답 거절 처리
                if is_refused:
                    logger.warning(f"[KeywordLocalization] Refused by Safety Filter: Keyword '{keyword}'")
                    return self._build_fallback_result(keyword, GenaiFailReason.SAFETY_FILTER_REJECTED)

                # 파싱 결과 누락 시 예외 로그 기록 후 실패 처리
                if not parsed_data or not parsed_data.localization_results:
                    logger.warning(f"[KeywordLocalization] No valid parsed content returned - Keyword: '{keyword}'")
                    return self._build_fallback_result(keyword, GenaiFailReason.INVALID_RESPONSE)

                # 정상 파싱 성공 시 번역된 키워드 반환
                return KeywordResult(
                    eng_name=parsed_data.localization_results[0].eng_name,
                    kor_name=parsed_data.localization_results[0].kor_name,
                    error_reason=None
                )

        except Exception as e:
            # 통신 장애 등 예외 발생 시 영문 원본과 에러 상태 코드 반환
            logger.warning(f"[KeywordLocalization] Individual API Error for '{keyword}'. Reason: {str(e)}")
            return self._build_fallback_result(keyword, GenaiFailReason.NETWORK_ERROR)

    async def _call_openai_api(self, prompt: str) -> tuple[bool, BulkKeywordResponseSchema | None]:
        """
        OpenAI API 요청 및 Structured Outputs 파싱 전담 헬퍼 메서드
        """
        
        # OpenAI API 호출 (Structured Outputs 파싱)
        response = await self.client.responses.parse(
            model=self.model_name,
            instructions=self.system_instruction,
            input=prompt,
            temperature=self.temperature,
            text_format=BulkKeywordResponseSchema,  # DTO 규격 강제
            store=False                             # 단건 처리용 상태 저장 비활성화    
        )

        parsed_data = None
        is_refused = False

        # 응답 배열 순회 및 파싱 결과 검증
        for output in response.output:
            if output.type != "message":
                continue
            
            for item in output.content:
                # 안전 정책 위반으로 인한 응답 거절 여부 검증
                if item.type == "refusal":
                    is_refused = True
                    break
                
                # 파싱된 Pydantic 객체 추출
                if getattr(item, "parsed", None):
                    parsed_data = item.parsed

        return is_refused, parsed_data
                
    def _build_fallback_result(self, keyword: str, reason: GenaiFailReason) -> KeywordResult:
        """
        실패 건에 대한 에러 응답 객체 생성
        """
        return KeywordResult(
            eng_name=keyword, 
            kor_name=keyword, 
            error_reason=reason
        )