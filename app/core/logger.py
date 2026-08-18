#app\core\logger.py

import logging
import sys
import os
from dotenv import load_dotenv
from logging_loki import LokiHandler
from app.core.middleware import trace_id_var

# .env 파일에서 환경변수 로드
load_dotenv()

# ==========================================
#  분산 추적 및 Loki 메타데이터 주입 필터
# ==========================================
class TraceIdFilter(logging.Filter):
    """
    LogRecord에 분산 추적용 Trace ID 및 Loki 인덱싱 태그를 주입하는 로깅 필터
    """
    def filter(self, record):
        
        # 비동기 컨텍스트에서 현재 요청의 Trace ID 추출 및 할당
        record.trace_id = trace_id_var.get()
        
        # LokiHandler 전송 시 인덱스 라벨로 활용될 태그 딕셔너리 검증 및 초기화
        if not hasattr(record, "tags") or not isinstance(record.tags, dict):
            record.tags = {}
            
        # Grafana 알림 쿼리 및 대시보드 필터링용 메타데이터 라벨 병합
        record.tags["application"] = "owls-pick-fastapi"
        record.tags["level"] = record.levelname
        
        return True
    
    
# ==========================================
#  Uvicorn 및 프레임워크 전역 로거 바인딩
# ==========================================
def attach_global_loki_handler(loki_handler: LokiHandler, trace_filter: logging.Filter):
    """
    Uvicorn 웹 서버 및 FastAPI 프레임워크 전역 시스템 로거에 Loki 핸들러와 필터 바인딩
    """
    
    # 프레임워크 및 웹 서버 런타임 예외 수집 대상 로거 목록
    target_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]

    for logger_name in target_loggers:
        sys_logger = logging.getLogger(logger_name)
        
        # 전역 로거 내 TraceIdFilter 중복 등록 방지 및 등록
        if not any(isinstance(f, TraceIdFilter) for f in sys_logger.filters):
            sys_logger.addFilter(trace_filter)
            
        # 전역 로거 내 LokiHandler 중복 등록 방지 및 등록
        if not any(isinstance(h, LokiHandler) for h in sys_logger.handlers):
            sys_logger.addHandler(loki_handler)
           
           
# ==========================================
#  모듈별 로거 생성 및 설정 팩토리
# ==========================================
def setup_logger(name: str) -> logging.Logger:
    """
    모듈별 커스텀 로거 생성 및 콘솔/Loki 핸들러 설정 팩토리 함수
    logger = setup_logger(__name__)
    """
    logger = logging.getLogger(name)
    
    # 환경변수 기반 로그 레벨 설정 (기본값: INFO)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # logging 라이브러리 상수 타입으로 변환
    log_level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(log_level)
    
    # Trace ID 및 동적 태그 주입용 커스텀 필터 인스턴스 생성
    trace_filter = TraceIdFilter()
    
    # 핸들러 실행 전 태그 및 Trace ID가 주입되도록 로거 레벨에 필터 등록
    if not any(isinstance(f, TraceIdFilter) for f in logger.filters):
        logger.addFilter(trace_filter)
    
    # 로거 호출 시 핸들러 중복 추가 방지
    if not logger.handlers:
        # 로그 출력 포맷 지정
        formatter = logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)-5s [%(trace_id)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # 로컬 디버깅용 콘솔 출력 핸들러 설정
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.addFilter(trace_filter)  # 콘솔 출력 전 Trace ID 필터 등록
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 통합 모니터링용 Loki 전송 핸들러 설정
        loki_url = os.getenv("LOKI_URL", "http://loki:3100/loki/api/v1/push")
        
        # 기본 정적 라벨 설정 및 LokiHandler 인스턴스 생성
        loki_handler = LokiHandler(
            url=loki_url,
            tags={"application": "owls-pick-fastapi"},
            version="1",
        )
        loki_handler.setLevel(log_level)
        loki_handler.addFilter(trace_filter)    # Loki 서버 전송 전 Trace ID 필터 등록
        loki_handler.setFormatter(formatter)    # Trace ID가 포함된 포맷으로 전송 데이터 구성
        logger.addHandler(loki_handler)
        
        # 모듈 로거 생성 시 Uvicorn 및 FastAPI 전역 로거에도 핸들러 및 필터 바인딩
        attach_global_loki_handler(loki_handler, trace_filter)
        
    return logger