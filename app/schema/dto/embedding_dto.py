#app\schema\embedding_dto.py

from enum import Enum
from pydantic import Field
from app.schema.dto.base_dto import CamelModel
from app.schema.enums.genai_fail_reason import GenaiFailReason

# ==========================================
# [Embedding Status Enum] 벡터 임베딩 상태값
# ==========================================

class EmbeddingStatus(str, Enum):
    UNEMBEDDED = "UNEMBEDDED" # 파이프라인 진입 전 
    SUCCESS = "SUCCESS"       # 임베딩 성공 
    FAILED = "FAILED"         # 임베딩 실패 (타임아웃, 모델 에러 등 일시적 오류)

# ==========================================
# [Embedding Request] 게임 메타데이터 청크 요청 DTO
# ==========================================

class EmbeddingData(CamelModel):
    """
    Spring Boot -> FastAPI 임베딩 원본 데이터 DTO
    """
    game_id: int = Field(
        ...,
        description="게임 ID"
    )
    title: str = Field(
        ...,
        description="게임 제목"
    )
    description: str | None = Field(
        default=None,
        description="게임 설명"
    )
    genres: list[str] = Field(
        default_factory=list,
        description="장르 태그 배열"
    )
    themes: list[str] = Field(
        default_factory=list,
        description="테마 태그 배열"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="키워드 태그 배열"
    )
    main_story: int | None = Field(
        default=None,
        description="메인 스토리 플레이 타임(분)"
    )

class EmbeddingBatchRequest(CamelModel):
    """
    배치 단위 임베딩 비동기 요청 DTO
    """
    request_id: str = Field(
        ...,
        description="비동기 콜백 매핑용 요청 식별자"
    )
    callback_url: str = Field(
        ...,
        description="작업 완료 후 결과를 수신할 Webhook URL"
    )
    games: list[EmbeddingData] = Field(
        ...,
        description="임베딩 대상 게임 데이터 배열"
    )

# ==========================================
# [Embedding Response] 벡터 임베딩 결과 응답 DTO
# ==========================================

class EmbeddingResult(CamelModel):
    """
    단일 게임 벡터 임베딩 결과 DTO
    """
    game_id: int = Field(
        ...,
        description="게임 ID"
    )
    vector: list[float] | None = Field(
        default=None,
        description="텍스트 임베딩 벡터 배열"
    )
    status: EmbeddingStatus = Field(
        ...,
        description="임베딩 결과 상태"
    )
    error_reason: GenaiFailReason | None = Field(
        default=None,
        description="임베딩 실패 사유"
    )

class EmbeddingBatchResponse(CamelModel):
    """
    FastAPI -> Spring Boot 임베딩 배치 비동기 응답 DTO
    """
    request_id: str = Field(
        ...,
        description="비동기 콜백 매핑용 요청 식별자"
    )
    results: list[EmbeddingResult] = Field(
        ...,
        description="배치 단위 임베딩 결과 배열"
    )