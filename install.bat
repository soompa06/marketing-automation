@echo off
REM 마케팅 자동화 도구 - 자동 설치 스크립트 (Windows)
REM
REM 사용법: 이 파일(install.bat)을 더블클릭

cd /d "%~dp0"

cls
echo.
echo ============================================================
echo   마케팅 자동화 도구 - 자동 설치
echo ============================================================
echo.

REM ========================================
REM 1. Python 확인
REM ========================================
echo [1/5] Python 확인 중...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python이 설치되어 있지 않습니다.
    echo.
    echo 다음 단계를 따라 Python을 먼저 설치해주세요:
    echo   1. https://www.python.org/downloads/ 접속
    echo   2. 'Download Python 3.11' 또는 그 이상 다운로드
    echo   3. 설치 시 "Add Python to PATH" 체크 필수
    echo   4. 설치 완료 후 이 스크립트를 다시 실행
    echo.
    pause
    exit /b 1
)
python --version
echo OK
echo.

REM ========================================
REM 2. 가상환경 생성
REM ========================================
echo [2/5] 가상환경 생성 중...
if exist "venv\Scripts\activate.bat" (
    echo OK - 가상환경이 이미 있습니다 (재사용)
) else (
    python -m venv venv
    if errorlevel 1 (
        echo 가상환경 생성 실패
        pause
        exit /b 1
    )
    echo OK - 가상환경 생성 완료
)
echo.

REM ========================================
REM 3. 가상환경 활성화 + pip 업그레이드
REM ========================================
echo [3/5] 가상환경 활성화 + pip 업데이트 중...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo OK
echo.

REM ========================================
REM 4. 패키지 설치
REM ========================================
echo [4/5] 필요한 패키지 설치 중... (1-3분 소요)
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo 패키지 설치 실패
    pause
    exit /b 1
)
echo OK
echo.

REM ========================================
REM 5. Playwright 브라우저 설치
REM ========================================
echo [5/5] 브라우저 설치 중... (1-5분 소요)
playwright install chromium
if errorlevel 1 (
    echo 브라우저 설치 실패
    pause
    exit /b 1
)
echo OK
echo.

REM ========================================
REM 완료
REM ========================================
echo ============================================================
echo   설치가 모두 완료되었습니다!
echo ============================================================
echo.
echo 다음 단계:
echo.
echo   1. 'run.bat' 파일을 더블클릭하면 웹앱이 시작됩니다
echo.
echo   2. 브라우저가 자동으로 열리고, [설정] 메뉴에서:
echo      - Google 인증 탭에서 JSON 파일 업로드
echo      - 블덱스 로그인 탭에서 사용자 추가 + 로그인
echo      - 캠페인 탭에서 본인 시트 ID 등록
echo.
echo   3. 그 후 [검수], [월간보고서], [블덱스] 메뉴에서 작업
echo.
pause
