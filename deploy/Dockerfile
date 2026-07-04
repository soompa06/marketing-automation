# 마케팅 자동화 — Docker 이미지
#
# 두 프로세스를 함께 운영:
#   1) Streamlit 웹앱 (포트 8501)
#   2) 스케줄러 데몬 (background)
#
# 실행 위치 결정은 supervisor.sh가 담당.
# 시놀로지/QNAP Container Manager에 그대로 import 가능.

FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# 시스템 패키지 (한글 폰트 + tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        fonts-noto-cjk \
        fonts-nanum \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 (캐시 효율을 위해 먼저 복사)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Playwright 브라우저는 베이스 이미지에 이미 설치되어 있음

# 앱 코드 복사
COPY . /app

# 결과·설정 디렉토리 (volume mount 대상)
RUN mkdir -p /app/config /app/output /app/screenshots /app/output/.scheduler /app/output/.jobs

# 슈퍼바이저 스크립트
COPY deploy/supervisor.sh /app/deploy/supervisor.sh
RUN chmod +x /app/deploy/supervisor.sh

EXPOSE 8501

# 헬스체크: Streamlit이 응답하는지
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD wget -q -O- http://127.0.0.1:8501/_stcore/health || exit 1

CMD ["/app/deploy/supervisor.sh"]
