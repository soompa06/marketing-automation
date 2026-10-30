#!/bin/bash
# 블덱스 지수 일일 조회 (launchd에서 10:00 / 15:00 두 번 호출)
# 설치: cp deploy/launchd/run_blogdex_daily.sh ~/.local/bin/ (~/Downloads 안의 스크립트는 launchd가 못 열어서 밖에 둔다)
# - 오늘 이미 성공했으면 건너뜀 (15:00은 10:00이 실패/미실행일 때만 실제로 돎)
# - 성공 = 프로세스 정상 종료 + 로그인 실패/중단 흔적 없음 → 마커 파일에 오늘 날짜 기록
cd /Users/under0tree/Downloads/marketing_automation || exit 1   # ~/.local/bin 사본으로도 실행되므로 절대경로
STATE_DIR="output/.scheduler"
MARKER="$STATE_DIR/blogdex_daily_ok"
LOG="$STATE_DIR/blogdex_daily_$(date +%Y%m%d).log"
TODAY=$(date +%Y-%m-%d)
mkdir -p "$STATE_DIR"

if [ "$(cat "$MARKER" 2>/dev/null)" = "$TODAY" ]; then
    echo "[$(date +%T)] 오늘 이미 완료 — 건너뜀" >> "$LOG"
    exit 0
fi

echo "[$(date +%T)] 시작" >> "$LOG"
# caffeinate: 실행 중 잠자기 방지
caffeinate -i ./venv/bin/python -W ignore -u src/blogdex/sheet_pipeline.py --all >> "$LOG" 2>&1
RC=$?

# 이번 실행분 로그만 검사 (시작 줄 이후)
if [ $RC -eq 0 ] && \
   ! awk '/\] 시작$/{buf=""} {buf=buf"\n"$0} END{print buf}' "$LOG" | grep -q "🛑\|블덱스 로그인 실패\|로그인이 풀렸\|세션 만료\|처리 실패"; then
    echo "$TODAY" > "$MARKER"
    echo "[$(date +%T)] 성공 — 마커 기록" >> "$LOG"
else
    echo "[$(date +%T)] 실패/중단 (rc=$RC) — 다음 시각에 재시도" >> "$LOG"
    osascript -e 'display notification "블덱스 일일 조회가 중단됐습니다. 재로그인이 필요할 수 있어요." with title "마케팅 자동화"' 2>/dev/null
fi
exit 0
# launchd(plist)는 `open -g -a Terminal ~/.local/bin/run_blogdex_daily.command` 로 이 스크립트를 띄운다.
# ~/Downloads 접근 권한이 있는 Terminal.app 안에서 실행해야 macOS 폴더 보호(Operation not permitted)를 피한다.
