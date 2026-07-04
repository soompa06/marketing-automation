#!/bin/bash
# 컨테이너 안에서 Streamlit + 스케줄러를 동시 운영
#
# 둘 중 하나가 죽으면 컨테이너를 종료해서 NAS/Docker가 재시작하도록 함.
# (Container Manager / docker-compose의 restart 정책에 의존)

set -e

cd /app

echo "[supervisor] Streamlit + Scheduler 시작..."

# 백그라운드: 스케줄러 데몬
python /app/src/scheduler/runner.py &
SCHEDULER_PID=$!
echo "[supervisor] scheduler PID=$SCHEDULER_PID"

# 포그라운드: Streamlit (이게 죽으면 컨테이너도 종료)
python -m streamlit run /app/streamlit_app/홈.py \
    --server.port=${STREAMLIT_SERVER_PORT:-8501} \
    --server.address=${STREAMLIT_SERVER_ADDRESS:-0.0.0.0} \
    --server.headless=true \
    --browser.gatherUsageStats=false &
STREAMLIT_PID=$!
echo "[supervisor] streamlit PID=$STREAMLIT_PID"

# 종료 처리: 신호 받으면 둘 다 깨끗이 정리
cleanup() {
    echo "[supervisor] 종료 신호 수신 — 자식 프로세스 정리"
    kill -TERM "$SCHEDULER_PID" 2>/dev/null || true
    kill -TERM "$STREAMLIT_PID" 2>/dev/null || true
    wait
    exit 0
}
trap cleanup SIGTERM SIGINT

# 둘 중 하나라도 죽으면 컨테이너 종료
wait -n $SCHEDULER_PID $STREAMLIT_PID
EXIT_CODE=$?
echo "[supervisor] 자식 프로세스 종료 (exit=$EXIT_CODE) — 컨테이너 종료"
cleanup
exit $EXIT_CODE
