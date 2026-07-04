@echo off
REM 마케팅 자동화 웹앱 실행 스크립트 (Windows)
REM 사용법: 더블클릭 또는 터미널에서 run.bat

cd /d "%~dp0"

REM 가상환경 활성화
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo X 가상환경을 찾을 수 없습니다.
    echo 다음 명령으로 먼저 가상환경을 만들어주세요:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Streamlit 설치 확인
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo Streamlit이 설치되어 있지 않습니다. 설치 중...
    pip install streamlit
)

REM 웹앱 실행
echo.
echo ============================================================
echo 마케팅 자동화 웹앱 시작 중...
echo ============================================================
echo.
echo 브라우저에서 자동으로 열립니다.
echo 안 열리면 다음 주소로 접속: http://localhost:8501
echo.
echo 종료하려면 이 터미널 창에서 Ctrl+C를 누르세요.
echo.

streamlit run streamlit_app/홈.py
