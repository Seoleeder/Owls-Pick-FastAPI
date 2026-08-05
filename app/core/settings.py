#app\core\settings.py

from functools import lru_cache
from typing import Tuple, Type
from pydantic_settings import (
    BaseSettings, 
    SettingsConfigDict, 
    PydanticBaseSettingsSource, 
    TomlConfigSettingsSource
)

# ==========================================
# 정적 인프라 설정 (TOML 파일 매핑)
# ==========================================
class LocalizationSettings(BaseSettings):
    game_semaphore_limit: int
    keyword_semaphore_limit: int
    
class ReviewSettings(BaseSettings):
    semaphore_limit: int

class HltbSettings(BaseSettings):
    semaphore_limit: int

class EmbeddingSettings(BaseSettings):
    output_dimension: int
    max_concurrent_tasks: int
    max_text_length: int
    micro_batch_size: int
    sleep_seconds: float

class Settings(BaseSettings):
    """
    서버 리소스 및 API 동작 관련 정적 임계치 정의
    - 외부 config.toml 파일의 값을 읽어와 객체로 구조화
    """
    
    app_env: str = "local"
    openai_api_key: str
    
    # TOML 섹션별 매핑
    localization: LocalizationSettings
    review: ReviewSettings
    hltb: HltbSettings
    embedding: EmbeddingSettings
    
    # TOML 파일 자동 매핑 지정 및 로컬 환경 변수 통합 매핑
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file="config.toml",
        extra="ignore"
    )
    
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """
        Pydantic 커스텀 설정 소스 주입
        config.toml 데이터 매핑을 위한 TomlConfigSettingsSource 등록
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls),
        )

@lru_cache
def get_settings() -> Settings:
    """
    설정 객체를 지연 생성(Lazy Evaluation)하고 캐싱하는 함수.
    """
    return Settings()