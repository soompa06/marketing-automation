"""
네이버 로그인 세션 관리 모듈 (댓글 작성용)

네이버는 자동화로 로그인 폼을 채우면 캡차/차단을 거니까,
블덱스와 같은 방식을 씁니다:

[첫 실행]
1. 브라우저 창을 띄움 (headless=False)
2. 사용자가 직접 네이버 로그인 (캡차/2단계 인증 직접 통과)
3. 로그인 완료를 자동 감지(NID_SES 쿠키) → 세션 파일 저장

[이후 모든 실행]
- 저장된 세션 자동 로드 → 즉시 로그인된 상태
- 만료되면 다시 첫 로그인처럼 진행

세션 파일 위치: config/naver_sessions/{user}.json  (.gitignore 등록 필요)
비밀번호는 코드/파일 어디에도 저장하지 않습니다 (쿠키 세션만 저장).
"""
from __future__ import annotations

import asyncio
import unicodedata
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SESSIONS_DIR = PROJECT_ROOT / "config" / "naver_sessions"
DEFAULT_USER = "default"

NAVER_HOME = "https://www.naver.com/"
NAVER_LOGIN = "https://nid.naver.com/nidlogin.login"

# 실제 사람 브라우저처럼 보이게 하는 공통 설정
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def get_session_path(user_name: str = DEFAULT_USER) -> Path:
    return SESSIONS_DIR / f"{user_name}.json"


def list_users() -> list[str]:
    if not SESSIONS_DIR.exists():
        return []
    return [f.stem for f in sorted(SESSIONS_DIR.glob("*.json"))]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").strip())


def has_user(user_name: str) -> bool:
    """세션 존재 여부 — 한글 파일명 NFC/NFD 차이를 무시하고 비교."""
    target = _nfc(user_name)
    return any(_nfc(u) == target for u in list_users())


def resolve_existing_session(user_name: str) -> Optional[Path]:
    """
    저장된 세션 중 user_name과 (정규화 무관) 일치하는 실제 파일 경로 반환.
    macOS에서 입력한 이름(NFC)과 디스크 파일명(NFD)이 달라도 찾아낸다.
    """
    target = _nfc(user_name)
    if not SESSIONS_DIR.exists():
        return None
    for f in SESSIONS_DIR.glob("*.json"):
        if _nfc(f.stem) == target:
            return f
    return None


async def is_logged_in(context: BrowserContext) -> bool:
    """
    네이버 로그인 여부를 쿠키로 판정.
    로그인 세션 쿠키(NID_SES, NID_AUT)가 있으면 로그인된 것으로 본다.
    """
    try:
        cookies = await context.cookies()
    except Exception:
        return False
    names = {c.get("name"): (c.get("value") or "") for c in cookies}
    return bool(names.get("NID_SES")) and bool(names.get("NID_AUT"))


async def initial_login(user_name: str = DEFAULT_USER, auto_confirm: bool = True) -> bool:
    """
    첫 로그인: 브라우저 창을 띄워 사용자가 직접 네이버 로그인.
    NID_SES 쿠키가 감지되면 세션을 저장한다.

    Returns: 로그인 성공 + 세션 저장 여부
    """
    print("\n" + "=" * 60)
    print(f"🔐 네이버 첫 로그인 (1회) — 사용자: {user_name}")
    print("=" * 60)
    print("브라우저 창에서 본인 네이버 계정으로 직접 로그인하세요.")
    print("(캡차/2단계 인증도 직접 통과 — 비밀번호는 저장하지 않습니다)")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=_USER_AGENT,
            locale="ko-KR",
        )
        page = await context.new_page()
        try:
            await page.goto(NAVER_LOGIN)
        except Exception:
            pass

        page_closed = {"value": False}
        page.on("close", lambda _: page_closed.update(value=True))
        context.on("close", lambda _: page_closed.update(value=True))

        save_path = get_session_path(user_name)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        POLL = 3
        MAX = 300  # 최대 5분
        elapsed = 0
        saved = False

        while elapsed < MAX:
            if page_closed["value"]:
                break
            try:
                if await is_logged_in(context):
                    await context.storage_state(path=str(save_path))
                    saved = True
                    print(f"  ✅ 로그인 감지 — 세션 저장 완료: {save_path.name}")
                    # 안정화를 위해 잠깐 더 저장 (쿠키 갱신 반영)
                    await asyncio.sleep(POLL)
                    try:
                        await context.storage_state(path=str(save_path))
                    except Exception:
                        pass
                    break
            except Exception as e:
                if "closed" in str(e).lower():
                    break
            if elapsed and elapsed % 30 == 0:
                print(f"  ⏳ 로그인 대기 중... ({elapsed}초)")
            await asyncio.sleep(POLL)
            elapsed += POLL

        if not saved and not page_closed["value"]:
            # 마지막으로 한 번 더 시도 (쿠키만이라도 저장)
            try:
                if await is_logged_in(context):
                    await context.storage_state(path=str(save_path))
                    saved = True
                    print(f"  ✅ 세션 저장 완료: {save_path.name}")
            except Exception:
                pass

        try:
            await browser.close()
        except Exception:
            pass

    if not saved:
        print("  ⚠️ 로그인을 감지하지 못했습니다. 다시 시도해주세요.")
    return saved


async def get_logged_in_context(
    headless: bool = True,
    user_name: str = DEFAULT_USER,
    auto_login_if_missing: bool = False,
) -> Optional[tuple]:
    """
    저장된 네이버 세션으로 로그인된 컨텍스트 반환.

    Returns: (playwright, browser, context) 또는 None
    """
    # 정규화 무관하게 기존 세션을 먼저 찾는다 (NFC/NFD 차이 방지)
    session_path = resolve_existing_session(user_name) or get_session_path(user_name)
    if not session_path.exists():
        if not auto_login_if_missing:
            print(f"⚠️ 네이버 세션이 없습니다: {get_session_path(user_name)}")
            return None
        if not await initial_login(user_name=user_name):
            return None
        session_path = resolve_existing_session(user_name) or get_session_path(user_name)

    p = await async_playwright().start()
    # 자동화 지문을 줄이는 실행 인자 (CDP/automation 배너·확장 비활성 등)
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-infobars",
        "--start-maximized",
        "--lang=ko-KR",
    ]
    # 네이버는 headless를 잘 감지하므로 항상 창을 띄우되, 백그라운드면 화면 밖에 배치
    if headless:
        launch_args += ["--window-position=-2000,-2000", "--window-size=1280,900"]

    browser = await p.chromium.launch(
        headless=False,
        args=launch_args,
        # Playwright 기본 --enable-automation 플래그 제거 (navigator.webdriver 등 노출 감소)
        ignore_default_args=["--enable-automation"],
    )
    context = await browser.new_context(
        storage_state=str(session_path),
        viewport={"width": 1280, "height": 900},
        user_agent=_USER_AGENT,
        locale="ko-KR",
        # 댓글 붙여넣기(clipboard API 폴백)용 권한
        permissions=["clipboard-read", "clipboard-write"],
    )

    # === 자동화 탐지 신호 숨기기 ===
    # 네이버(Xi 등)는 navigator.webdriver, navigator.plugins 비어있음 등으로 봇을 감지함.
    # 모든 새 페이지가 만들어지기 전에 주입되도록 add_init_script 사용.
    # ⚠️ 완전 우회는 아님. 보조 수단 + 사용자가 사람처럼 천천히 쓰는 게 더 중요.
    await context.add_init_script("""
        // 1) navigator.webdriver 제거
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 2) chrome 객체 흉내 (없으면 봇 의심)
        if (!window.chrome) {
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        }
        // 3) plugins 가짜 채움
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5].map(i => ({name: 'Plugin' + i})),
        });
        // 4) languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['ko-KR', 'ko', 'en-US', 'en'],
        });
        // 5) permissions.query Notification 우회
        const orig = window.navigator.permissions && window.navigator.permissions.query;
        if (orig) {
            window.navigator.permissions.query = (p) =>
                p && p.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : orig(p);
        }
    """)

    # 세션 유효성 확인 (참고용 — 실패해도 일단 진행)
    if not await is_logged_in(context):
        print("⚠️ 저장된 네이버 세션이 만료되었을 수 있습니다. 재로그인이 필요할 수 있어요.")

    return (p, browser, context)


async def _main():
    import argparse
    parser = argparse.ArgumentParser(description="네이버 로그인 세션 만들기 (댓글용)")
    parser.add_argument("--user", default=DEFAULT_USER, help="계정 별칭 (여러 계정 구분용)")
    args = parser.parse_args()
    ok = await initial_login(user_name=args.user)
    print("완료" if ok else "실패")


if __name__ == "__main__":
    asyncio.run(_main())
