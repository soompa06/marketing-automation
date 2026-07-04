#!/usr/bin/env bash
# 네이버 댓글용 '진짜 Chrome'을 디버그 모드로 실행 (macOS)
#
# 한 번 실행 → 뜨는 Chrome 창에서 네이버 로그인 → 그 상태로 둠.
# 이 창에 도구가 연결해 댓글을 답니다. (평소 크롬과 분리된 별도 프로필)
#
# 사용: bash src/naver_comment/start_chrome_mac.sh

set -e

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$HOME/chrome-naver-debug"

if [ ! -x "$CHROME" ]; then
  echo "❌ Google Chrome 을 찾을 수 없습니다: $CHROME"
  echo "   Chrome 이 설치돼 있는지 확인하세요."
  exit 1
fi

mkdir -p "$PROFILE"

echo "🟢 디버그 모드 Chrome 실행 (포트 9222, 프로필: $PROFILE)"
echo "   → 뜨는 창에서 네이버에 로그인하세요. 창은 닫지 말고 두세요."
echo "   → 그다음 도구에서 '실행'하면 이 창으로 댓글이 달립니다."

"$CHROME" \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-blink-features=AutomationControlled \
  "https://www.naver.com" \
  >/dev/null 2>&1 &

echo "✅ 실행됨 (백그라운드). 로그인 후 도구로 돌아가세요."
