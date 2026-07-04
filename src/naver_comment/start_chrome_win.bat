@echo off
REM 네이버 댓글용 '진짜 Chrome'을 디버그 모드로 실행 (Windows)
REM
REM 한 번 실행 -> 뜨는 Chrome 창에서 네이버 로그인 -> 그 상태로 둠.
REM 이 창에 도구가 연결해 댓글을 답니다. (평소 크롬과 분리된 별도 프로필)
REM
REM 사용: src\naver_comment\start_chrome_win.bat

setlocal
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set "PROFILE=%USERPROFILE%\chrome-naver-debug"

if not exist "%CHROME%" (
  echo [오류] Google Chrome 을 찾을 수 없습니다.
  echo        Chrome 설치 경로를 확인하세요.
  exit /b 1
)

if not exist "%PROFILE%" mkdir "%PROFILE%"

echo [실행] 디버그 모드 Chrome (포트 9222, 프로필: %PROFILE%)
echo   - 뜨는 창에서 네이버에 로그인하세요. 창은 닫지 말고 두세요.
echo   - 그다음 도구에서 '실행'하면 이 창으로 댓글이 달립니다.

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check --disable-blink-features=AutomationControlled "https://www.naver.com"

echo [완료] 실행됨. 로그인 후 도구로 돌아가세요.
endlocal
