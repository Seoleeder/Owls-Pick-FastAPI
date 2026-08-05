#app\services\embedding_service.py

import os
import json
import asyncio
import httpx
import gc
from typing import List

from app.core import events
from app.core.logger import setup_logger
from app.core.settings import get_settings
from app.schema.enums.genai_fail_reason import GenaiFailReason
from app.services.factories.embedding_source_factory import EmbeddingSourceFactory

from app.schema.dto.embedding_dto import EmbeddingBatchRequest, EmbeddingBatchResponse, EmbeddingData, EmbeddingResult, EmbeddingStatus

logger = setup_logger(__name__)

class EmbeddingService:
    """
    Owls 챗봇 검색용 게임 메타데이터 임베딩 서비스
    """
    
    def __init__(self):
        settings = get_settings()
        
        # 전역 생명주기(Lifespan)에서 초기화된 싱글톤 OpenAI 클라이언트 매핑
        self.client = events.openai_client
        
        # 임베딩 전용 환경 변수 로드
        self.model_name = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
        self.output_dimension = int(os.getenv("EMBEDDING_OUTPUT_DIMENSION", "768"))
        self.semaphore_limit = int(os.getenv("EMBEDDING_MAX_CONCURRENT_TASKS", "10"))
        self.max_text_length = int(os.getenv("EMBEDDING_MAX_TEXT_LENGTH", "4000"))
        
        # API Rate Limit 방어를 위한 배치 크기 및 지연 시간 설정
        self.micro_batch_size = int(os.getenv("EMBEDDING_MICRO_BATCH_SIZE", "10"))
        self.sleep_seconds = float(os.getenv("EMBEDDING_SLEEP_SECONDS", "1.0"))

        # API Rate Limit 방어 및 서버 과부하 방지를 위한 동시성 제어
        self.semaphore = asyncio.Semaphore(settings.embedding.max_concurrent_tasks)

        logger.info(f"[GenAI-Embedding] Initialized with AsyncOpenAI SDK (Model: {self.model_name}, Dimension: {self.output_dimension})")

    async def process_and_callback(self, req: EmbeddingBatchRequest, retries: int = 2):
        """
        배치 데이터 임베딩 변환 처리 후 Spring Boot 웹훅으로 결과 전송
        """
        logger.info(f"[GenAI-Embedding] Starting background processing for Request ID: {req.request_id}")
        
        try:
            # 병렬 임베딩 파이프라인 가동
            results = await self.generate_embeddings(req.games)
            response_payload = EmbeddingBatchResponse(
                request_id=req.request_id,
                results=results
            )
        except Exception as e:
            # 예기치 못한 메인 로직 에러 시 해당 배치의 모든 데이터를 네트워크 에러로 매핑
            logger.error(f"[GenAI-Embedding] Failed processing Request ID: {req.request_id} | Error: {str(e)}")
            fallback_results = [
                self._build_fallback_result(game.game_id, GenaiFailReason.NETWORK_ERROR) 
                for game in req.games
            ]
            response_payload = EmbeddingBatchResponse(
                request_id=req.request_id,
                results=fallback_results
            )
            
        try:
            # Webhook 전송용 헤더 및 바디 구성
            headers = {'Content-Type': 'application/json'}
            body = json.dumps(response_payload.model_dump(by_alias=True))
            
            logger.info(f"[GenAI-Embedding] Sending webhook callback for Request ID: {req.request_id} to {req.callback_url}")
            
            # 지수 백오프 재시도 루프
            for attempt in range(retries + 1):
                try:
                    
                    # httpx를 활용한 비동기 네트워크 통신 수행
                    async with httpx.AsyncClient(timeout=10.0) as http_client:
                        response = await http_client.post(req.callback_url, headers=headers, content=body)
                        response.raise_for_status()
                        
                        logger.info(f"[GenAI-Embedding] Webhook delivered successfully - Request ID: {req.request_id}")
                        break
                except Exception as e:
                    # 일시적 오류 발생 시 점진적 대기(2초, 4초) 후 재시도
                    if attempt < retries:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"[GenAI-Embedding] Webhook delivery failed, retrying {attempt + 1}/{retries}... Request ID: {req.request_id} ({str(e)})")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # 설정된 재시도 횟수 초과 시 최종 실패 처리
                    logger.error(f"[GenAI-Embedding] Final Webhook delivery failure - Request ID: {req.request_id} | Error: {str(e)}")
                
        except Exception as e:
            logger.error(f"[GenAI-Embedding] Webhook connection error for Request ID: {req.request_id} | Error: {str(e)}")
        finally:
            # 사용 완료 객체 물리 메모리 즉시 반환
            gc.collect()

    async def generate_embeddings(self, batch: List[EmbeddingData], retries: int = 2) -> List[EmbeddingResult]:
        """
        대량의 게임 데이터 비동기 병렬 임베딩 파이프라인.
        """
        results: List[EmbeddingResult] = []
        total_games = len(batch)
        
        logger.debug(f"[GenAI-Embedding] Processing {total_games} games in micro-batches of {self.micro_batch_size}.")

        # 마이크로 배치 단위 분할 및 순차 처리
        for i in range(0, total_games, self.micro_batch_size):
            micro_batch = batch[i : i + self.micro_batch_size]
            
            valid_games = []
            source_texts = []
            
            # 팩토리를 활용한 메타데이터 텍스트 병합 및 길이 검증
            for game in micro_batch:
                text = EmbeddingSourceFactory.create_source_text(game, self.max_text_length)
                
                # 기준 길이 미만 데이터는 API 호출에서 제외 및 에러 반환
                if not text or len(text) < 5:
                    logger.debug(f"[GenAI-Embedding] Skip: Insufficient text - GameId: {game.game_id}")
                    results.append(self._build_fallback_result(game.game_id, GenaiFailReason.INSUFFICIENT_DATA))
                else:
                    valid_games.append(game)
                    source_texts.append(text)
                    
            
            # 유효 데이터 부재 시 요청 생략
            if not valid_games:
                continue

            # 네트워크 일시 장애 대응 재시도 루프
            for attempt in range(retries + 1):
                try:
                    async with self.semaphore:
                        # OpenAI 임베딩 변환 API 호출 (텍스트 배열 일괄 전송)
                        response = await self.client.embeddings.create(
                            model=self.model_name,
                            input=source_texts,
                            dimensions=self.output_dimension
                        )

                    # API 응답 인덱스와 원본 객체 리스트의 1:1 매핑
                    for idx, game in enumerate(valid_games):
                        results.append(EmbeddingResult(
                            game_id=game.game_id,
                            vector=response.data[idx].embedding,
                            status=EmbeddingStatus.SUCCESS,
                            error_reason=None
                        ))
                    
                    # 성공 시 재시도 루프 즉시 탈출
                    break

                except Exception as e:
                    if attempt < retries:
                        sleep_time = (attempt + 1) * 2
                        logger.warning(f"[GenAI-Embedding] Batch API Error, retrying {attempt+1}/{retries}... ({str(e)})")
                        await asyncio.sleep(sleep_time)
                        continue
                    
                    # 재시도 초과 시 마이크로 배치 전체 실패(Network Error) 할당
                    logger.error(f"[GenAI-Embedding] Batch Final Failure | Error: {str(e)}")
                    for game in valid_games:
                        results.append(self._build_fallback_result(game.game_id, GenaiFailReason.NETWORK_ERROR))
            
            # Rate Limit 방어를 위한 마이크로 배치 간 의도적 지연 시간 부여
            if i + self.micro_batch_size < total_games:
                logger.debug(f"[GenAI-Embedding] Processed {i + len(micro_batch)}/{total_games}. Sleeping for {self.sleep_seconds}s...")
                await asyncio.sleep(self.sleep_seconds)
                
        logger.debug("[GenAI-Embedding] All micro-batches processed successfully.")
        return results
    
    def _build_fallback_result(self, game_id: int, reason: GenaiFailReason) -> EmbeddingResult:
        """
        실패 건에 대한 에러 응답 객체 생성
        """
        return EmbeddingResult(
            game_id=game_id, 
            vector=None, 
            status=EmbeddingStatus.FAILED,
            error_reason=reason
        )