"""
블덱스 세션 관리 모듈

블덱스는 구글 OAuth로 로그인합니다.
Playwright/Selenium 같은 자동화 도구로 구글 로그인을 직접 처리하면
Google이 차단하므로, 다음 흐름을 사용합니다:

[첫 실행]
1. 브라우저 창을 띄움 (headless=False)
2. 사용자가 직접 구글 로그인 (한 번만)
3. 로그인 완료 후 사용자가 Enter 키 누름
4. 로그인 세션을 파일로 저장

[이후 모든 실행]
- 저장된 세션 자동 로드 → 즉시 로그인된 상태
- 세션이 만료되면 → 다시 첫 실행처럼 진행

세션 파일 위치: config/blogdex_session.json
- .gitignore에 등록되어 GitHub 업로드 안 됨
- 사용자 PC에만 저장
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SESSIONS_DIR = PROJECT_ROOT / "config" / "blogdex_sessions"  # 다중 사용자용
LEGACY_SESSION_PATH = PROJECT_ROOT / "config" / "blogdex_session.json"  # 기존(단일) 호환
DEFAULT_USER = "default"  # 사용자 이름 미지정 시
BLOGDEX_HOME = "https://blogdex.space/"


def get_session_path(user_name: str = DEFAULT_USER) -> Path:
    """
    특정 사용자의 세션 파일 경로 반환 (읽기용).

    하위 호환:
    - 사용자가 'default'이고 신형 파일이 없으면 → 기존 blogdex_session.json 사용
    - 그 외에는 → blogdex_sessions/{user_name}.json
    """
    user_session = SESSIONS_DIR / f"{user_name}.json"

    # 기존 단일 세션 파일 자동 마이그레이션
    if user_name == DEFAULT_USER and not user_session.exists() and LEGACY_SESSION_PATH.exists():
        return LEGACY_SESSION_PATH

    return user_session


def _resolve_save_path(user_name: str = DEFAULT_USER) -> Path:
    """
    저장용 경로: 항상 신형 위치(blogdex_sessions/{user}.json)에 저장.
    레거시 단일 파일에 덮어쓰지 않도록 보장.
    """
    return SESSIONS_DIR / f"{user_name}.json"


def list_users() -> list[str]:
    """저장된 사용자 세션 목록."""
    users = []
    
    # 신형 디렉토리의 사용자들
    if SESSIONS_DIR.exists():
        for f in sorted(SESSIONS_DIR.glob("*.json")):
            users.append(f.stem)
    
    # 기존 단일 세션 파일이 있고 'default'가 아직 없으면 추가
    if LEGACY_SESSION_PATH.exists() and DEFAULT_USER not in users:
        users.insert(0, DEFAULT_USER)
    
    return users


# 하위 호환을 위한 변수 (다른 모듈에서 import할 수 있음)
SESSION_PATH = LEGACY_SESSION_PATH


async def is_logged_in(page: Page) -> bool:
    """
    현재 페이지에서 로그인 상태인지 정확히 판정.
    
    엄격한 판정: 다음 모든 조건을 만족해야 로그인된 것으로 간주.
    1. Cloudflare 차단 페이지가 아님
    2. 로그인 버튼이 안 보임
    3. 페이지에 의미 있는 콘텐츠가 충분히 있음 (10줄 이상)
    """
    await page.wait_for_timeout(2000)
    
    result = await page.evaluate("""
        () => {
            const text = document.body.innerText || '';
            const title = document.title || '';
            const url = window.location.href || '';
            
            // === 1. Cloudflare 봇 차단 페이지 감지 (최우선) ===
            const cloudflareIndicators = [
                '보안 확인 수행 중',
                'Checking your browser',
                '사람인지 확인',
                'Verifying you are human',
                'Just a moment',
                'cloudflare',
            ];
            for (const ind of cloudflareIndicators) {
                if (text.toLowerCase().includes(ind.toLowerCase()) ||
                    title.toLowerCase().includes(ind.toLowerCase())) {
                    return { state: 'cloudflare', reason: ind };
                }
            }
            // Cloudflare 위젯 iframe도 체크
            if (document.querySelector('iframe[src*="challenges.cloudflare"]')) {
                return { state: 'cloudflare', reason: 'iframe' };
            }
            
            // === 2. 명확한 로그인 버튼 후보들 ===
            const loginIndicators = [
                'Google로 로그인', 'Google 로그인', 'Sign in with Google',
                '구글로 로그인', '구글 로그인',
            ];
            for (const indicator of loginIndicators) {
                if (text.includes(indicator)) {
                    return { state: 'logged_out', reason: 'login_text: ' + indicator };
                }
            }
            
            // === 3. 로딩 상태 ===
            if (text.includes('로그인 확인중') || text.includes('Loading...')) {
                return { state: 'loading' };
            }
            
            // === 4. 페이지 콘텐츠가 너무 적음 (Cloudflare 통과 직후 등) ===
            const lineCount = text.split('\\n').filter(l => l.trim()).length;
            if (lineCount < 5) {
                return { state: 'too_thin', lineCount: lineCount };
            }
            
            // === 5. 블덱스 특유의 로그인 후 콘텐츠 지표 ===
            // 로그인되면 보이는 키워드들 (블로그, 검색, 지수 등)
            const loggedInIndicators = [
                '블로그', '검색', '지수', '조회', '랭킹',
                'blog', 'search', 'rank',
            ];
            const foundLoggedIn = loggedInIndicators.filter(
                ind => text.toLowerCase().includes(ind.toLowerCase())
            );
            
            if (foundLoggedIn.length >= 2) {
                return { state: 'logged_in', confidence: 'high', found: foundLoggedIn };
            }
            
            // 콘텐츠는 있지만 블덱스 특유의 키워드가 없음 = 의심스러움
            return { state: 'uncertain', lineCount: lineCount };
        }
    """)
    
    state = result.get("state")
    
    # Cloudflare 차단 = 미로그인 (사용자가 통과해야 함)
    if state == "cloudflare":
        return False
    
    # 명확한 미로그인
    if state == "logged_out":
        return False
    
    # 콘텐츠 부족 = 미로그인 (아직 로딩 중이거나 빈 페이지)
    if state == "too_thin":
        return False
    
    # 확실히 로그인됨
    if state == "logged_in":
        return True
    
    # 로딩 중 → 한 번 더 확인
    if state == "loading":
        await page.wait_for_timeout(2500)
        return await is_logged_in(page)
    
    # 불확실한 경우 → 미로그인으로 간주 (안전)
    return False


async def initial_login(
    headless: bool = False,
    user_name: str = DEFAULT_USER,
    auto_confirm: bool = False,
) -> bool:
    """
    첫 로그인: 사용자가 직접 구글 계정으로 로그인하고 세션 저장.
    
    Args:
        headless: 브라우저 창 숨김 (로그인 시엔 항상 보이게 권장)
        user_name: 사용자 이름 (다중 사용자용)
        auto_confirm: True면 로그인 완료를 자동 감지 (Enter 입력 불필요)
                      UI에서 호출할 때 사용
    
    Returns:
        True: 로그인 성공 + 세션 저장 완료
        False: 사용자가 취소하거나 실패
    """
    print("\n" + "=" * 60)
    print("🔐 블덱스 첫 로그인 (1회만 수행)")
    print("=" * 60)
    print()
    print("브라우저 창이 열리면 다음 단계를 따라주세요:")
    print()
    print("  1. 블덱스 페이지에서 '구글로 로그인' 버튼 클릭")
    print("  2. 본인의 구글 계정으로 직접 로그인")
    print("  3. 블덱스로 돌아와서 로그인이 완료된 것을 확인")
    if auto_confirm:
        print("  4. 자동으로 감지해서 세션을 저장합니다 (최대 5분 대기)")
    else:
        print("  4. 이 터미널 창으로 돌아와서 Enter 키를 누르세요")
    print()
    print("⚠️  자동화 보안 우회를 위해 브라우저 창이 보이는 모드로 실행됩니다")
    print()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # 첫 로그인은 무조건 보이는 모드
            args=[
                "--disable-blink-features=AutomationControlled",  # 봇 감지 우회
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        
        page = await context.new_page()
        await page.goto(BLOGDEX_HOME)
        
        if auto_confirm:
            # UI 모드: 로그인 완료를 즉시 자동 감지
            # 정책:
            # - 강제 대기 없이 처음부터 3초마다 폴링
            # - 1회 감지되면 즉시 세션 저장 (사용자가 그 직후 브라우저를 닫아도 OK)
            # - 감지 실패 + 페이지 닫힘 → 마지막으로 저장 시도 (쿠키만 있어도 다음 자동 검증에서 활용)
            print("👉 브라우저에서 로그인하시면 자동으로 감지됩니다 (즉시 폴링).")

            # 페이지 닫힘 감지용 플래그
            page_closed = {"value": False}
            page.on("close", lambda _: page_closed.update(value=True))
            context.on("close", lambda _: page_closed.update(value=True))

            # OAuth 리디렉트 후 다시 blogdex.space로 돌아왔는지 빠르게 알기 위한 신호
            returned_to_blogdex = {"value": False}

            def _on_navigated(frame):
                try:
                    if frame == page.main_frame:
                        url = (frame.url or "").lower()
                        if "blogdex.space" in url:
                            returned_to_blogdex["value"] = True
                except Exception:
                    pass

            page.on("framenavigated", _on_navigated)

            session_path_for_save = _resolve_save_path(user_name)
            session_path_for_save.parent.mkdir(parents=True, exist_ok=True)

            saved_once = False

            async def _save_now() -> bool:
                """현재 컨텍스트 상태를 세션 파일로 저장."""
                try:
                    await context.storage_state(path=str(session_path_for_save))
                    return True
                except Exception as e:
                    # 페이지가 닫힌 직후엔 이 호출이 실패할 수 있음
                    print(f"  ⚠️ 세션 저장 실패: {e}")
                    return False

            # 폴링 루프: 최대 5분, 3초 간격
            POLL_INTERVAL = 3
            MAX_TOTAL_SECONDS = 300
            elapsed = 0
            last_log_at = 0
            login_detected = False

            while elapsed < MAX_TOTAL_SECONDS:
                if page_closed["value"]:
                    break

                try:
                    is_in = await is_logged_in(page)
                except Exception as e:
                    err_text = str(e)
                    if "closed" in err_text.lower() or "Target page" in err_text:
                        page_closed["value"] = True
                        print("  ℹ️ 사용자가 브라우저 창을 닫았습니다.")
                        break
                    is_in = False

                if is_in:
                    if not saved_once:
                        print(f"  ✓ 로그인 감지! 즉시 세션 저장 (경과 {elapsed}초)")
                        if await _save_now():
                            saved_once = True
                            login_detected = True
                            print("  ✅ 세션 저장 완료 — 이제 브라우저를 닫으셔도 됩니다.")
                            # 안정화를 위해 잠깐 더 (사용자가 브라우저를 안 닫는다면)
                            stabilize_loops = 2  # 2 × 3초 = 6초
                            for _ in range(stabilize_loops):
                                if page_closed["value"]:
                                    break
                                await asyncio.sleep(POLL_INTERVAL)
                                elapsed += POLL_INTERVAL
                            if not page_closed["value"]:
                                await _save_now()
                                print("  🔄 세션 재저장 (안정화)")
                            break
                    else:
                        # 추가 감지 시 갱신 (도달 잘 안 함 — 위에서 break)
                        await _save_now()

                # 진행 안내 (30초마다)
                if elapsed - last_log_at >= 30:
                    print(f"  ... 로그인 대기 중 ({elapsed}초 경과)")
                    last_log_at = elapsed

                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL

            # 페이지가 닫혔는데 아직 저장 못 했으면, 마지막으로 한 번 더 시도
            # (드물게 storage_state 호출이 페이지 닫힘과 경쟁 상황이면 이 시점에 성공할 수도)
            if not saved_once and not page_closed["value"]:
                # 타임아웃이지만 페이지는 살아있는 경우 — 마지막 저장 시도
                try:
                    if await _save_now():
                        saved_once = True
                        login_detected = True
                        print("  ✓ 타임아웃 직전 마지막 저장 성공")
                except Exception:
                    pass

            # 결과 판정
            if saved_once:
                login_detected = True
                print(f"\n✅ 로그인 세션이 저장되었습니다.")
            else:
                print("\n⚠️ 로그인이 감지되지 않았습니다.")
                if page_closed["value"]:
                    print("   브라우저가 너무 일찍 닫혔거나, 로그인이 완료되지 않았습니다.")
                else:
                    print("   5분 동안 로그인이 확인되지 않았습니다.")
                print("   다시 시도해주세요.")
                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass
                return False

            # 저장 성공 후 정리
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
            return True
        else:
            # 터미널 모드: 사용자 Enter 입력 대기
            print("👉 로그인이 끝나면 이 터미널로 돌아와서 Enter를 누르세요...", end="", flush=True)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input)

            # 로그인 상태 자동 감지 (참고용 — 실패해도 세션은 저장)
            print("\n로그인 상태 확인 중...")
            try:
                logged_in = await is_logged_in(page)
            except Exception:
                logged_in = False

            if not logged_in:
                print()
                print("⚠️  자동 감지로는 로그인 상태를 확인하지 못했습니다.")
                print("    하지만 사용자가 로그인했다고 알려주셨으니 세션을 저장합니다.")
                print("    조회가 정상 작동하지 않으면 다시 로그인해주세요.")

            session_path = _resolve_save_path(user_name)
            session_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(session_path))
            print(f"✅ 세션 저장 완료: [{user_name}] {session_path.name}")
            print("이제 브라우저를 닫아도 됩니다.")

            try:
                await browser.close()
            except Exception:
                pass
            return True


async def get_logged_in_context(
    headless: bool = True,
    auto_login_if_missing: bool = True,
    user_name: str = DEFAULT_USER,
) -> Optional[tuple]:
    """
    로그인된 브라우저 컨텍스트를 반환.
    
    저장된 세션이 있으면 그것을 사용하고, 없거나 만료되면 자동 로그인 진행.
    
    Args:
        user_name: 사용자 이름 (여러 계정을 쓸 때 구분용). 기본값 'default'.
    
    Returns:
        (playwright, browser, context) 튜플 또는 None (실패 시)
    """
    session_path = get_session_path(user_name)
    
    # 세션 파일 없으면 첫 로그인 진행
    if not session_path.exists():
        if not auto_login_if_missing:
            print(f"⚠️  세션 파일이 없습니다: {session_path}")
            return None
        
        print(f"저장된 로그인 세션이 없습니다. 첫 로그인을 진행합니다... (사용자: {user_name})")
        success = await initial_login(user_name=user_name)
        if not success:
            return None
        session_path = get_session_path(user_name)
    
    # 저장된 세션으로 컨텍스트 생성
    # 핵심 정책: Cloudflare 우회를 위해 항상 headless=False 사용
    # - True 모드는 Cloudflare가 거의 100% 차단
    # - False 모드여도 창을 화면 밖에 위치시키면 사용자 눈에는 안 보임
    p = await async_playwright().start()
    
    launch_args = ["--disable-blink-features=AutomationControlled"]
    
    # headless=True일 때 (백그라운드 모드): 창은 띄우되 화면 밖에 배치
    # 사용자 눈에는 안 보이지만 Cloudflare에는 정상 브라우저로 인식됨
    if headless:
        # 화면 좌측 멀리 (보통 모니터 음수 좌표 = 화면 밖)
        launch_args.append("--window-position=-2000,-2000")
        launch_args.append("--window-size=1280,800")
    
    browser = await p.chromium.launch(
        headless=False,  # 항상 False — Cloudflare 우회의 핵심
        args=launch_args,
    )
    context = await browser.new_context(
        storage_state=str(session_path),
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="ko-KR",
    )
    
    if headless:
        print("  💡 백그라운드 모드 (창은 화면 밖에 위치 — Dock에서 보일 수 있음)")
    
    # 세션 유효성 검증 (참고용)
    page = await context.new_page()
    try:
        await page.goto(BLOGDEX_HOME, timeout=15000)
        logged_in = await is_logged_in(page)
    except Exception as e:
        print(f"  ⚠️  블덱스 접속 확인 중 오류: {e}")
        logged_in = True  # 에러여도 일단 진행
    finally:
        await page.close()
    
    if not logged_in:
        print()
        print("⚠️  저장된 세션이 만료되었거나 자동 감지가 실패했습니다.")
        print("   조회가 안 되면 'python src/blogdex/session.py'로 재로그인해주세요.")
        print("   (일단 저장된 세션으로 계속 진행합니다)")
        print()
    
    return (p, browser, context)


# =============================================================================
# CLI 진입점 (세션만 새로 만들 때)
# =============================================================================

async def main():
    """첫 로그인 또는 세션 갱신만 수행."""
    import argparse
    parser = argparse.ArgumentParser(description="블덱스 로그인 세션 만들기")
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help="사용자 이름 (여러 계정 구분용, 기본: default)"
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="기존 세션이 있어도 묻지 않고 덮어쓰기 (UI에서 호출 시)"
    )
    args = parser.parse_args()
    
    user_name = args.user
    session_path = get_session_path(user_name)
    
    if session_path.exists() and not args.auto_confirm:
        print(f"[{user_name}] 기존 세션 파일이 있습니다: {session_path}")
        ans = input("덮어쓰기 하시겠습니까? (y/N): ").strip().lower()
        if ans != "y":
            print("취소되었습니다.")
            return
    elif session_path.exists():
        print(f"[{user_name}] 기존 세션 덮어쓰기 (--auto-confirm)")
    
    success = await initial_login(user_name=user_name, auto_confirm=args.auto_confirm)
    if success:
        print(f"\n✅ [{user_name}] 세션 설정 완료. 이제 지수 조회할 수 있습니다.")
    else:
        print("\n❌ 세션 설정 실패")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
