#!/bin/bash
# 마케팅 자동화 도구 - 자동 설치 스크립트 (macOS / Linux)
#
# 사용법:
# 1. 이 파일(install.command)을 더블클릭
#    또는 터미널에서 ./install.command 실행
# 2. 자동으로 가상환경 + 패키지 + Playwright 모두 설치
# 3. 완료되면 run.sh 더블클릭으로 웹앱 실행

set -e  # 에러 발생 시 즉시 중단

# 스크립트가 있는 폴더로 이동
cd "$(dirname "$0")"

# 색상 코드
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

clear
echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  📦 마케팅 자동화 도구 — 자동 설치${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# ========================================
# 1. Python 확인
# ========================================
echo -e "${YELLOW}[1/5] Python 확인 중...${NC}"

# Python 3 확인 (python3 우선, 없으면 python)
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    # python 명령이 Python 3인지 확인
    PY_VER=$(python --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    if [ "$PY_MAJOR" = "3" ]; then
        PYTHON_CMD="python"
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ Python 3이 설치되어 있지 않습니다.${NC}"
    echo ""
    echo "다음 단계를 따라 Python을 먼저 설치해주세요:"
    echo "  1. https://www.python.org/downloads/ 접속"
    echo "  2. 'Download Python 3.11' 또는 그 이상 다운로드"
    echo "  3. 다운받은 .pkg 파일 더블클릭해서 설치"
    echo "  4. 설치 완료 후 이 스크립트를 다시 실행"
    echo ""
    read -p "Enter를 누르면 종료합니다..."
    exit 1
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo -e "${GREEN}✓ ${PY_VERSION} 발견${NC}"
echo ""

# ========================================
# 2. 가상환경 생성
# ========================================
echo -e "${YELLOW}[2/5] 가상환경 생성 중...${NC}"
if [ -d "venv" ]; then
    echo -e "${GREEN}✓ 가상환경이 이미 있습니다 (재사용)${NC}"
else
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}✓ 가상환경 생성 완료${NC}"
fi
echo ""

# ========================================
# 3. 가상환경 활성화 + pip 업그레이드
# ========================================
echo -e "${YELLOW}[3/5] 가상환경 활성화 + pip 업데이트 중...${NC}"
source venv/bin/activate
pip install --upgrade pip --quiet
echo -e "${GREEN}✓ 활성화 완료${NC}"
echo ""

# ========================================
# 4. 패키지 설치
# ========================================
echo -e "${YELLOW}[4/5] 필요한 패키지 설치 중... (1~3분 소요)${NC}"
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ 패키지 설치 완료${NC}"
echo ""

# ========================================
# 5. Playwright 브라우저 설치
# ========================================
echo -e "${YELLOW}[5/5] 브라우저 설치 중... (인터넷 속도에 따라 1~5분 소요)${NC}"
playwright install chromium
echo -e "${GREEN}✓ 브라우저 설치 완료${NC}"
echo ""

# ========================================
# 완료
# ========================================
chmod +x run.sh

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  🎉 설치가 모두 완료되었습니다!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "다음 단계:"
echo ""
echo "  1. 'run.sh' 파일을 더블클릭하면 웹앱이 시작됩니다"
echo ""
echo "  2. 브라우저가 자동으로 열리고, ⚙️ 설정 메뉴에서:"
echo "     - 🔑 Google 인증 탭 → JSON 파일 업로드"
echo "     - 👤 블덱스 로그인 탭 → 사용자 추가 + 로그인"
echo "     - 🏪 캠페인 탭 → 본인 시트 ID 등록"
echo ""
echo "  3. 그 후 ① 검수, ② 월간보고서, ③ 블덱스 메뉴에서 작업"
echo ""
read -p "Enter를 누르면 이 창이 닫힙니다..."
