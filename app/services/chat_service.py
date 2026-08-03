#app\services\chat_service.py

import os
import logging
from app.core import events
from app.schema.dto.owls_chat_dto import (
    QueryEmbeddingRequest, 
    RagGenerationRequest, 
    TitleGenerationRequest,
    RagGenerationResponse,
    TitleGenerationResponse
)
from app.utils.file_util import load_prompt_text

logger = logging.getLogger(__name__)

class ChatService:
    """
    Owls 챗봇의 RAG 파이프라인(임베딩 및 답변 생성) 관리 서비스
    독립 검색어 추출, 벡터 임베딩, 최종 답변 및 세션 제목 생성 담당
    """
    
    def __init__(self):
        # 전역 생명주기(Lifespan)에서 초기화된 싱글톤 OpenAI 클라이언트 매핑
        self.client = events.openai_client
        
       # 모델 사양 환경 변수 로드
        self.chat_model = os.getenv("CHAT_MODEL_NAME", "gpt-5.4-mini") 
        self.embedding_model = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
        
        # 임베딩 출력 차원 및 답변 생성 온도 설정
        self.output_dimension = int(os.getenv("EMBEDDING_OUTPUT_DIMENSION", "768"))
        self.chat_temperature = float(os.getenv("CHAT_TEMPERATURE", "0.3"))
        self.title_temperature = float(os.getenv("TITLE_GENERATION_TEMPERATURE", "0.1"))
        
        # 시스템 프롬프트 메모리 로드
        self._load_resources()
        
        logger.info(f"[GenAI-Chat] Initialized (Chat: {self.chat_model}, Embedding: {self.embedding_model}, Dimension: {self.output_dimension})")

    def _load_resources(self):
        """
        외부 파일로 분리된 마크다운 시스템 지시문 로드.
        """
        
        self.system_instruction = load_prompt_text("chat/chat_system.md")
        self.rewrite_instruction = load_prompt_text("chat/chat_rewrite.md")
        self.title_system_instruction = load_prompt_text("chat/title_generation_instruction.md")

    async def extract_query_embedding(self, request: QueryEmbeddingRequest) -> list[float]:
        """
        대화 맥락이 반영된 독립 검색어(Standalone Query) 추출 및 벡터 임베딩 수행
        """
        
        # 임베딩 대상 텍스트 초기화
        processed_message = request.user_message

        # 대화 내역 존재 여부 검증
        if request.history:
            # 대화 내역을 단순 텍스트로 병합
            formatted_history = "\n".join([f"{h.role}: {h.content}" for h in request.history])
            
            # OpenAI Role 규격에 맞추어 유저 프롬프트 동적 조립
            user_prompt = f"[대화 내역]\n{formatted_history}\n\n[사용자의 마지막 메시지]\n{request.user_message}"
            
            try:
                # Responses API 호출 (구조화되지 않은 단순 텍스트 생성)
                rewrite_response = await self.client.responses.create(
                    model=self.chat_model,
                    instructions=self.rewrite_instruction,
                    input=user_prompt,
                    temperature=0.1,
                    store=False
                )
                
                # 파싱 및 공백 제거 후 임베딩 대상 문자열 갱신
                processed_message = rewrite_response.choices[0].message.content.strip()
                
            except Exception as e:
                # 재작성 API 호출 실패 시 원본 사용자 메시지로 폴백(Fallback) 처리
                logger.warning(f"[GenAI-Chat] Rewriting Failed. Using original message. Error: {str(e)}")
                processed_message = request.user_message

        try:
            # 최종 확정 텍스트 기반 차원 축소 임베딩 API 호출
            embedding_response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=processed_message,
                dimensions=self.output_dimension
            )
            
            # 추출된 벡터 리스트 반환
            return embedding_response.data[0].embedding
            
        except Exception as e:
            logger.error(f"[GenAI-Chat] Query Embedding Failed | Error: {str(e)}")
            raise e

    async def generate_chat_reply(self, request: RagGenerationRequest) -> str:
        """
        벡터 DB에서 검색된 연관 게임 데이터와 대화 문맥 기반 RAG 기반 최종 응답을 생성함
        """
        
        # 메타데이터 누락 여부 검증 및 LLM 주입 컨텍스트 상태 추적
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[GenAI-Chat] Starting Chat Generation with {len(request.contexts)} contexts.")
            for idx, context in enumerate(request.contexts):
                text_preview = context[:100] + "..." if len(context) > 100 else context
                logger.debug(f"[GenAI-Chat] Context [{idx + 1}] Preview: {text_preview}")
                
        # 배열 형태의 대화 내역과 메타데이터를 단일 텍스트 포맷으로 병합
        formatted_history = "\n".join([f"{h.role}: {h.content}" for h in request.history])
        formatted_context = "\n---\n".join(request.contexts)
        
        # 내부에서 프롬프트 동적 결합
        user_prompt = f"[Context]\n{formatted_context}\n\n[History]\n{formatted_history}\n\n[User Message]\n{request.user_message}"

        try:
            # OpenAI API 호출 (Structured Outputs 파싱)
            response = await self.client.responses.parse(
                model=self.chat_model,
                instructions=self.system_instruction,
                input=user_prompt,
                temperature=self.chat_temperature,
                text_format=RagGenerationResponse,    # DTO 규격 강제
                store=False                                 # 단건 처리용 상태 저장 비활성화
            )
            
            parsed_data = None
            
            # 방어적 이중 루프 파싱
            for output in response.output:
                if output.type != "message":
                    continue
                for item in output.content:
                    if item.type == "refusal":
                        raise ValueError(f"Refused by Safety Filter: {item.refusal}")
                    if getattr(item, "parsed", None):
                        parsed_data = item.parsed
            
            if not parsed_data:
                raise ValueError("Parsed data is missing from the RAG response.")
            
            # 앞뒤 공백 제거 후 최종 답변 텍스트 반환
            return parsed_data.reply.strip()
            
        except Exception as e:
            logger.error(f"[GenAI-Chat] Generation Failed | Error: {str(e)}")
            raise e
        
    async def generate_session_title(self, request: TitleGenerationRequest) -> str:
        """
        사용자의 첫 발화를 분석하여 채팅 세션 타이틀 생성 (30자 이내)
        """
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[GenAI-Chat] Starting Title Generation for message: {request.user_message}")

        try:
            # OpenAI API 호출 (Structured Outputs 파싱)
            response = await self.client.responses.parse(
                model=self.chat_model,
                instructions=self.title_system_instruction,
                input=request.user_message,
                temperature=self.title_temperature,
                text_format=TitleGenerationResponse,    # DTO 규격 강제
                store=False                             # 단건 처리용 상태 저장 비활성화
            )
            
            parsed_data = None
            
            # 방어적 이중 루프 파싱
            for output in response.output:
                if output.type != "message":
                    continue
                for item in output.content:
                    if item.type == "refusal":
                        raise ValueError(f"Refused by Safety Filter: {item.refusal}")
                    if getattr(item, "parsed", None):
                        parsed_data = item.parsed
            
            if not parsed_data:
                raise ValueError("Parsed title data is missing from the response.")
            
            # 앞뒤 공백 제거 후 생성된 세션 타이틀 반환 
            return parsed_data.title.strip()
            
        except Exception as e:
            logger.error(f"[GenAI-Chat] Title Generation Failed | Error: {str(e)}")
            raise e