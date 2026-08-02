#app\schema\localization_dto.py

from typing import List
from pydantic import Field
from app.schema.dto.base_dto import CamelModel
from app.schema.enums.genai_fail_reason import GenaiFailReason

# ==========================================
# [Localization Request/Response] 설명/스토리라인 한글화 DTO
# ==========================================

class GameItem(CamelModel):
    """
    단일 게임 데이터 요청 DTO
    """
    game_id: int = Field(
        ..., 
        description="게임 ID",
        json_schema_extra={"example": 10423}
    )
    description: str | None = Field(
        default=None, 
        description="원본 영문 게임 설명",
        json_schema_extra={"example": "An open-world action RPG."}
    )
    storyline: str | None = Field(
        default=None, 
        description="원본 영문 게임 스토리라인",
        json_schema_extra={"example": "Save the kidnapped princess from the dark lord."}
    )

class BulkLocalizationRequest(CamelModel):
    """
    대량 게임 데이터 한글화 요청 DTO
    """
    request_id: str = Field(
        ...,
        description="비동기 콜백 매핑용 요청 식별자"
    )
    callback_url: str = Field(
        ...,
        description="완료 후 결과를 전송할 Spring Boot Webhook URL"
    )
    games: List[GameItem] = Field(
        ..., 
        description="한글화 대상 게임 데이터 목록",
        min_length=1,
        json_schema_extra={"example": [{"gameId": 10423, "description": "An open-world action RPG.", "storyline": "Save the princess."}]}
    )

class LocalizationResult(CamelModel):
    """
    단일 게임 한글화 응답 DTO
    """
    game_id: int = Field(
        ..., 
        description="게임 ID"
    )
    description_ko: str | None = Field(
        default=None, 
        description="한글화된 설명"
    )
    storyline_ko: str | None = Field(
        default=None, 
        description="한글화된 스토리라인"
    )
    error_reason: GenaiFailReason | None = Field(
        default=None,
        description="한글화 작업 실패 사유"
    )

class BulkLocalizationResponse(CamelModel):
    """
    대량 게임 한글화 응답 DTO
    """
    request_id: str = Field(
        ...,
        description="비동기 콜백 매핑용 요청 식별자"
    )
    success: bool = Field(
        ..., 
        description="대량 한글화 성공 여부"
    )
    results: List[LocalizationResult] = Field(
        ..., 
        description="한글화 완료 게임 목록"
    )

