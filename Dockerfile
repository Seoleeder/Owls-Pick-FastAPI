# ==========================================
# 1. 빌더 스테이지
# ==========================================

# Python 3.11 Slim 베이스 이미지 호출
FROM python:3.11-slim AS builder

# 작업 디렉토리 지정
WORKDIR /app

# 파이썬 가상환경(venv) 생성 및 환경 변수 등록
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 패키지 의존성 명세서 복사
COPY requirements.txt .

# BuildKit 캐시 마운트를 적용하여 파이썬 패키지 설치
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# ==========================================
# 2. 운영 런타임 스테이지
# ==========================================

FROM python:3.11-slim

# 작업 디렉토리 지정
WORKDIR /app

# 타임존 설정 적용 및 APT 패키지 인덱스 캐시 제거 (단일 레이어 최적화)
ENV TZ=Asia/Seoul
RUN apt-get update && apt-get install -y tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# Non-root 시스템 유저 그룹 및 사용자(fastapi) 생성, 폴더 소유권 부여
RUN addgroup --system fastapi && adduser --system --group fastapi && \
    chown -R fastapi:fastapi /app

# 실행 프로세스 권한 제한 
USER fastapi:fastapi

# 빌드 스테이지의 가상환경(패키지) 복사 및 소유권 지정
COPY --from=builder --chown=fastapi:fastapi /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# FastAPI 애플리케이션 소스 코드 복사 및 소유권 지정
COPY --chown=fastapi:fastapi . .

# 컨테이너의 8000 포트 개방 선언
EXPOSE 8000

# Uvicorn을 이용한 FastAPI 애플리케이션 구동 명령어 정의
ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]