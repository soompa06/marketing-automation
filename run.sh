#!/bin/bash
# 마케팅 자동화 웹앱 실행 스크립트 (macOS / Linux)
# 사용법: ./run.sh 또는 더블클릭

# 이 스크립트가 있는 폴더로 이동
cd "$(dirname "$0")"

# 가상환경 활성화
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ 가상환경을 찾을 수 없습니다."
    echo "다음 명령으로 먼저 가상환경을 만들어주세요:"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    read -p "Enter를 누르면 종료합니다..."
    exit 1
fi

# Streamlit 설치 확인
if ! python -c "import streamlit" 2>/dev/null; then
    echo "📦 Streamlit이 설치되어 있지 않습니다. 설치 중..."
    pip install streamlit
fi

# 웹앱 실행
echo ""
echo "============================================================"
echo "🌐 마케팅 자동화 웹앱 시작 중..."
echo "============================================================"
echo ""
echo "✓ 브라우저에서 자동으로 열립니다."
echo "✓ 안 열리면 다음 주소로 접속: http://localhost:8501"
echo ""
echo "✓ 종료하려면 이 터미널 창에서 Ctrl+C를 누르세요."
echo ""

streamlit run streamlit_app/홈.py
