"""
실제 사용자 Chrome 에 CDP(원격 디버깅)로 연결.

왜?
- Playwright가 띄우는 Chromium은 '자동화 브라우저' 지문이 남아, 네이버가
  비밀댓글을 사후에 삭제/차단한다.
- 사용자가 평소 쓰는 '진짜 Chrome'을 디버그 포트로 띄우고 거기에 붙으면,
  진짜 사람 브라우저 프로필·지문이라 자동화 탐지를 거의 받지 않는다.

사용 흐름:
1. (사용자) Chrome 을 디버그 모드로 1회 실행 + 네이버 로그인
     mac:  bash src/naver_comment/start_chrome_mac.sh
     win:  src\naver_comment\start_chrome_win.bat
   → 별도 프로필(~/chrome-naver-debug)로 9222 포트에 뜸
2. (도구) connect_over_cdp("http://localhost:9222") 로 그 Chrome 에 연결
3. 댓글 작성은 그 Chrome 의 로그인 세션을 그대로 사용

주의:
- 디버그 포트 Chrome 은 보안상 평소 브라우징과 분리된 별도 프로필을 쓴다.
- 이 방식은 'session.py(저장 세션)' 불필요 — 크롬에 이미 로그인돼 있어야 함.
"""
from __future__ import annotations

import urllib.request
from typing import Optional

from playwright.async_api import async_playwright

DEFAULT_CDP_URL = "http://localhost:9222"


def is_chrome_up(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    """디버그 포트 Chrome 이 떠 있는지 확인."""
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


async def connect(cdp_url: str = DEFAULT_CDP_URL) -> Optional[tuple]:
    """
    실행 중인 Chrome 에 연결.

    Returns: (playwright, browser, context) 또는 None
      - browser.close() 하지 말 것! (사용자 Chrome 을 닫아버림)
      - 호출 측은 context 만 쓰고, 종료 시 playwright.stop() 만.
    """
    if not is_chrome_up(cdp_url):
        print(f"❌ 디버그 모드 Chrome 을 찾을 수 없습니다 ({cdp_url}).")
        print("   먼저 Chrome 을 디버그 모드로 실행하세요:")
        print("     mac:  bash src/naver_comment/start_chrome_mac.sh")
        print("     win:  src\\naver_comment\\start_chrome_win.bat")
        return None

    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"❌ Chrome 연결 실패: {e}")
        await p.stop()
        return None

    # 이미 열려 있는 컨텍스트(사용자 프로필) 사용
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = await browser.new_context()

    return (p, browser, context)


async def is_logged_in(context) -> bool:
    """연결된 Chrome 이 네이버 로그인 상태인지 (쿠키로 판정)."""
    try:
        cookies = await context.cookies()
    except Exception:
        return False
    names = {c.get("name"): (c.get("value") or "") for c in cookies}
    return bool(names.get("NID_SES")) and bool(names.get("NID_AUT"))
