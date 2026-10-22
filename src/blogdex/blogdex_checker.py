"""
블덱스 블로그 지수 자동 조회 모듈

기능:
1. 한 명 또는 여러 명의 블로그 지수 한 번에 조회
2. 지수가 자격 등급(준최6, 준최7, 최적1~4+ 등)에 해당하는지 자동 분류
3. 결과를 CSV로 저장

사용 예시:
    # 한 명
    python blogdex_checker.py --url "https://blog.naver.com/blogger_id"
    
    # 여러 명 (세미콜론으로 구분)
    python blogdex_checker.py \\
        --urls "https://blog.naver.com/aaa;https://blog.naver.com/bbb"
    
    # CSV 파일로 일괄 (URL만 한 줄에 하나씩)
    python blogdex_checker.py --input bloggers_to_check.txt
"""
from __future__ import annotations

import argparse
import asyncio
import time
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Page

# 같은 폴더의 session 모듈
sys.path.insert(0, str(Path(__file__).resolve().parent))
from session import get_logged_in_context, BLOGDEX_HOME

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"

# 진단 정보를 한 번만 저장하기 위한 전역 플래그 (디버그 파일 폭증 방지)
_debug_saved = False

# 페이지별 팝업 자동 닫기 핸들러 등록 여부 (중복 등록 방지)
_popup_autoclose_pages: set[int] = set()

# 지수 미확인/조회 실패 시 기록할 라벨
LOOKUP_FAILED_LABEL = "조회 불가"

# 지수 파싱 JS (최초 + 재시도에서 재사용)
#
# 중요: 검색한 blogId가 결과 페이지에 실제로 보일 때만 등급을 인정한다.
# 블덱스는 검색이 실패하면(미등록/오타) 이전 검색 결과나 샘플을 그대로 보여줄 수 있어,
# 그 화면의 등급을 그대로 긁으면 '다른 블로그의 등급'을 잘못 가져온다 (예: vicphos→준최6).
_GRADE_PARSE_JS = """
    (blogId) => {
        const bodyText = document.body.innerText || '';
        const lower = bodyText.toLowerCase();
        const bid = (blogId || '').toLowerCase();
        const sample = bodyText.substring(0, 1000);

        // 0) 아직 비동기 로딩 중이면 '대기' 신호 (스테일/조기판정 방지)
        if (bodyText.includes('불러오는 중') || bodyText.includes('로딩 중')
            || bodyText.includes('로딩중')) {
            return { grade: '', reason: 'loading', bodyTextSample: sample };
        }

        // 이 페이지가 '해당 blogId의 페이지'인지 — blogId/@handle 노출로 확인.
        // 직접 URL(/blog/{id})로 이동해도 직전 블로그 내용이 잠깐 남는 스테일을 막는다.
        const bidPresent = bid ? lower.includes(bid) : true;

        // 0-a) 로그인 화면으로 튕김 (페이지 로딩 후 비동기 리다이렉트라 사전 로그인 확인으로는 못 잡음)
        if (bodyText.includes('구글로 계속하기') || bodyText.includes('카카오로 계속하기')) {
            return { grade: '', reason: 'session_expired', bodyTextSample: sample };
        }

        // 0-b) 블덱스 로그인 세션 만료 — 미등록으로 오판하면 시트가 잘못 이동되므로 별도 신호로 분리.
        if (bodyText.includes('세션 만료')) {
            return { grade: '', reason: 'session_expired', bodyTextSample: sample };
        }

        // 1) 조회 제한(일시 차단) 신호 — 미등록 안내문('1분에 N회 조회 가능')은 제외.
        //    예: "1분에 2번 이상 요청할 수 없습니다. 잠시 후 다시 시도해주세요(56 초 후 가능)"
        const rateLimitSignals = [
            '이상 요청할 수 없', '번 이상 요청',   // ('분에 2회'는 미등록 화면 하단 안내문이라 제외)
            '조회 횟수', '횟수를 초과', '횟수 초과', '이용량', '요청이 많',
            '잠시 후 다시', '잠시후 다시', '제한되었습니다',
            '초과하셨', 'too many', 'rate limit',
        ];
        for (const s of rateLimitSignals) {
            if (bodyText.includes(s)) {
                // '(56 초 후 가능)' 처럼 남은 대기초를 추출
                let waitSec = 0;
                const m = bodyText.match(/(\\d+)\\s*초\\s*후/);
                if (m) waitSec = parseInt(m[1], 10) || 0;
                return { grade: '', reason: 'rate_limited', waitSec: waitSec,
                         bodyTextSample: sample };
            }
        }

        // 2) 미등록(확정 조회 불가) — 이 블로그의 페이지일 때만 (스테일 방지).
        //    (예: omosiroigirl 페이지 → '이전 블로그 지수가 없는 블로그입니다.')
        const notFoundSignals = [
            '이전 블로그 지수가 없는', '지수가 없는 블로그',
            '등록되지 않은', '조회된 블로그가 없', '블로그를 찾을 수 없',
        ];
        if (bidPresent) {
            for (const s of notFoundSignals) {
                if (bodyText.includes(s)) {
                    return { grade: '', reason: 'notfound', bodyTextSample: sample };
                }
            }
        }

        // 3) 아직 이 블로그 페이지가 아니면(스테일/로딩 잔여) → 더 기다림
        if (!bidPresent) {
            return { grade: '', reason: 'blogid_absent', bodyTextSample: sample };
        }

        // 4) 등급 추출 — blogId 근처에서 가장 가까운 것
        const bidIdx = bid ? lower.indexOf(bid) : -1;
        const gradeRe = /(최적[1-4]\\+?|준최[1-7]|일반)/g;
        let m, best = '', bestDist = Infinity;
        while ((m = gradeRe.exec(bodyText)) !== null) {
            const dist = bidIdx >= 0 ? Math.abs(m.index - bidIdx) : 0;
            if (dist < bestDist) { bestDist = dist; best = m[1]; }
        }
        if (bid && best && bidIdx >= 0 && bestDist > 1500) {
            return { grade: '', reason: 'grade_too_far', bodyTextSample: sample };
        }
        return { grade: best, bodyTextSample: sample };
    }
"""


def _ensure_popup_autoclose(page: Page) -> None:
    """이 페이지에서 새 팝업창(window.open 등)이 열리면 자동으로 닫도록 1회 등록.

    'popup'은 Page 이벤트다 (BrowserContext 아님).
    """
    try:
        key = id(page)
        if key in _popup_autoclose_pages:
            return

        def _on_popup(popup):
            try:
                asyncio.create_task(popup.close())
            except Exception:
                pass

        page.on("popup", _on_popup)
        _popup_autoclose_pages.add(key)
    except Exception:
        pass


async def dismiss_popups(page: Page) -> bool:
    """
    지수 조회를 방해하는 모달/배너/팝업을 닫는다 (있으면).

    안전을 위해 '확인' 같이 의미가 모호한 버튼은 누르지 않고,
    명확히 '닫기/오늘 그만 보기/X' 류만 클릭한다.

    Returns:
        무언가 닫았으면 True.
    """
    closed = False

    # 1) ESC — 대부분의 모달이 닫힘
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
    except Exception:
        pass

    close_selectors = [
        'button:has-text("오늘 하루 보지 않기")',
        'button:has-text("오늘 그만 보기")',
        'button:has-text("다시 보지 않기")',
        'button:has-text("닫기")',
        'a:has-text("닫기")',
        '[aria-label="닫기"]',
        '[aria-label*="close" i]',
        'button[class*="close" i]',
        '.modal .close',
        '.popup .close',
        '.layer_close',
        'button:has-text("×")',
        'button:has-text("✕")',
    ]
    for sel in close_selectors:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 3)):
                el = loc.nth(i)
                try:
                    if await el.is_visible(timeout=200):
                        await el.click(timeout=1000)
                        closed = True
                        await page.wait_for_timeout(150)
                except Exception:
                    continue
        except Exception:
            continue

    return closed


async def _wait_for_result(page: Page, blog_id: str, timeout_ms: int = 6000) -> dict:
    """
    검색 결과(등급 or '조회 불가' 신호)가 뜰 때까지 폴링.
    고정 대기 대신 준비되는 즉시 반환 → 속도 ↑.

    Returns: _GRADE_PARSE_JS 결과 dict (grade/reason/bodyTextSample).
    """
    step = 300
    elapsed = 0
    last = {"grade": "", "bodyTextSample": ""}
    while elapsed < timeout_ms:
        try:
            info = await page.evaluate(_GRADE_PARSE_JS, blog_id)
        except Exception:
            info = last
        last = info
        # 등급을 찾았거나, '미등록'/'조회 제한' 신호가 떴으면 즉시 종료
        if info.get("grade") or info.get("reason") in ("notfound", "rate_limited", "session_expired"):
            return info
        await page.wait_for_timeout(step)
        elapsed += step
    return last


# =============================================================================
# 설정 로드
# =============================================================================

def load_qualified_grades() -> set[str]:
    """자격 등급 리스트 로드 (settings.json 또는 기본값)."""
    default_grades = {
        "준최6", "준최7",
        "최적1", "최적2", "최적3",
        "최적1+", "최적2+", "최적3+", "최적4+",
    }
    
    if not SETTINGS_PATH.exists():
        return default_grades
    
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)
        grades = settings.get("blogdex", {}).get("qualified_grades", [])
        if grades:
            return set(grades)
    except Exception:
        pass
    
    return default_grades


# =============================================================================
# URL 정규화
# =============================================================================

def normalize_blog_url(url: str) -> str:
    """
    블덱스에 입력할 형식으로 정규화.
    블덱스는 'https://blog.naver.com/{blogId}' 형식의 블로그 홈 URL을 받음.
    """
    if not url:
        return ""

    url = url.strip()

    # 도메인 없이 blogId만 들어온 경우 (예: 'vicphos', 'vicphos/12345')
    # → 첫 토큰을 네이버 blogId로 간주.
    # (스킴이 없고 첫 경로 토큰에 '.'이 없으면 도메인이 아니라 blogId)
    if not url.startswith(("http://", "https://")):
        first_token = url.split("/")[0]
        if "." not in first_token:
            blog_id = next((p for p in url.split("/") if p), "")
            if blog_id:
                return f"https://blog.naver.com/{blog_id}"

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if "blog.naver.com" not in parsed.netloc.lower():
        return url
    
    # PostView.naver?blogId=xxx 형식
    if "postview" in parsed.path.lower():
        from urllib.parse import parse_qs
        params = parse_qs(parsed.query)
        blog_id = params.get("blogId", [""])[0]
        if blog_id:
            return f"https://blog.naver.com/{blog_id}"
    
    # /blogId/postNo 형식 → /blogId만 남기기
    parts = [p for p in parsed.path.split("/") if p]
    if parts:
        return f"https://blog.naver.com/{parts[0]}"
    
    return url


def extract_blog_id(url: str) -> str:
    """URL에서 blogId만 추출."""
    normalized = normalize_blog_url(url)
    parsed = urlparse(normalized)
    parts = [p for p in parsed.path.split("/") if p]
    return parts[0] if parts else ""


# =============================================================================
# 블덱스 페이지 상호작용
# =============================================================================

async def search_blog_index(page: Page, blog_url: str) -> dict:
    """
    블덱스에서 한 블로그의 지수를 조회.
    
    절차:
    1. 블덱스 메인 페이지로 이동
    2. 검색창에 블로그 URL 입력
    3. 검색 버튼 클릭
    4. 결과 페이지에서 지수 정보 파싱
    
    Returns:
        {
            "url": 정규화된 URL,
            "blog_id": 블로그 ID,
            "grade": "최적3+" 등 지수 텍스트,
            "raw_text": 원본 결과 텍스트 (디버그용),
            "qualified": 자격 등급 해당 여부,
            "error": 에러 메시지 (실패 시),
        }
    """
    normalized_url = normalize_blog_url(blog_url)
    blog_id = extract_blog_id(blog_url)
    
    result = {
        "url": normalized_url,
        "blog_id": blog_id,
        "grade": "",
        "raw_text": "",
        "qualified": False,
        "error": "",
    }
    
    try:
        # 새 팝업창(별도 윈도우)이 뜨면 자동으로 닫도록 등록
        _ensure_popup_autoclose(page)

        # 블로그 전용 페이지로 직접 이동 — 검색창 의존 제거.
        # (검색창 콜드스타트/스테일 결과 문제 회피. 블덱스 URL 패턴: /blog/{blogId})
        direct_url = f"https://blogdex.space/blog/{blog_id}"
        await page.goto(direct_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(800)
        await dismiss_popups(page)

        # === Cloudflare 봇 차단 페이지 감지 + 자동 통과 ===
        cf_check = await page.evaluate("""
            () => {
                const text = document.body.innerText || '';
                const title = document.title || '';
                return {
                    isCloudflareChallenge:
                        text.includes('보안 확인 수행 중') ||
                        text.includes('Checking your browser') ||
                        text.includes('사람인지 확인') ||
                        text.includes('Verifying you are human') ||
                        text.includes('Just a moment') ||
                        title.includes('Just a moment') ||
                        document.querySelector('iframe[src*="challenges.cloudflare"]') !== null,
                };
            }
        """)
        if cf_check.get("isCloudflareChallenge"):
            print("\n  ⏳ Cloudflare 확인 페이지 감지 — 자동 통과 대기(최대 30초)...", flush=True)
            passed = False
            for attempt in range(15):
                await page.wait_for_timeout(2000)
                still = await page.evaluate("""
                    () => {
                        const t = document.body.innerText || '';
                        return t.includes('보안 확인 수행 중') || t.includes('Checking your browser')
                            || t.includes('사람인지 확인') || t.includes('Just a moment');
                    }
                """)
                if not still:
                    passed = True
                    print(f"  ✓ Cloudflare 통과 ({(attempt + 1) * 2}초)")
                    break
            if not passed:
                result["error"] = ("Cloudflare 봇 차단을 통과하지 못했습니다. "
                                   "--show-browser 옵션으로 실행해보세요.")
                return result
            await page.wait_for_timeout(1200)

        # 로그인 확인 (풀렸으면 조회 불가)
        login_check = await page.evaluate("""
            () => {
                const t = document.body.innerText || '';
                if (t.includes('Google로 로그인') || t.includes('구글로 로그인')
                    || t.includes('구글로 계속하기') || t.includes('카카오로 계속하기')
                    || t.includes('Sign in with Google')) {
                    return { logged_in: false };
                }
                return { logged_in: true };
            }
        """)
        if not login_check.get("logged_in"):
            result["error"] = ("로그인이 풀렸습니다. 재로그인: "
                               "python src/blogdex/session.py")
            return result

        # === 지수 로딩 대기 ===
        # 블덱스 3.0은 등급을 비동기로 불러옴('블로그 지수를 불러오는 중...').
        # 로딩이 끝나고 '이 blogId의' 등급/미등록이 확정될 때까지 폴링한다(넉넉히 12초).
        grade_info = await _wait_for_result(page, blog_id, timeout_ms=12000)
        result["grade"] = grade_info.get("grade", "")
        result["raw_text"] = grade_info.get("bodyTextSample", "")
        reason = grade_info.get("reason", "")

        # 조회 제한이면 미달 처리하지 말고 '재시도 대상'으로 둔다.
        # rate_limited 신호 + 남은 대기초(wait_sec)를 호출자(파이프라인)에 전달.
        if reason == "rate_limited":
            result["rate_limited"] = True
            result["wait_sec"] = int(grade_info.get("waitSec") or 0)
            result["error"] = "블덱스 조회 제한 (분당 2회). 대기 후 자동 재시도."
            return result

        # 느린 로딩 대비 — 등급도 미등록도 아니면 한 번 더 길게 대기
        if not result["grade"] and reason != "notfound":
            await dismiss_popups(page)
            await page.wait_for_timeout(1500)
            grade_info2 = await _wait_for_result(page, blog_id, timeout_ms=8000)
            reason = grade_info2.get("reason", reason)
            if grade_info2.get("grade"):
                result["grade"] = grade_info2["grade"]
                result["raw_text"] = grade_info2.get("bodyTextSample", "")
            elif reason == "rate_limited":
                result["rate_limited"] = True
                result["wait_sec"] = int(grade_info2.get("waitSec") or 0)
                result["error"] = "블덱스 조회 제한 (분당 2회). 대기 후 자동 재시도."
                return result

        if reason == "session_expired":
            result["error"] = ("블덱스 로그인이 풀렸습니다(세션 만료). 재로그인: "
                               "python src/blogdex/session.py")
            return result

        # 그래도 등급이 없으면 '조회 불가' (미등록 등)
        if not result["grade"]:
            result["grade"] = LOOKUP_FAILED_LABEL
            result["lookup_failed"] = True
            result["lookup_reason"] = reason

    except Exception as e:
        result["error"] = f"조회 실패: {e}"

    return result


# =============================================================================
# 자격 분류
# =============================================================================

def classify_qualification(grade: str, qualified_grades: set[str]) -> bool:
    """지수가 자격 등급에 해당하는지 판정."""
    if not grade:
        return False
    return grade.strip() in qualified_grades


# =============================================================================
# 분당 조회 제한 선대기 (sheet_pipeline / check_many 공용)
# =============================================================================

_sent: list[float] = []   # 최근 블덱스 조회 시작 시각(monotonic) — 프로세스 내 공유


async def throttle(per_min: int = 2, margin: float = 2) -> None:
    """블덱스 '1분에 N번' 제한을 슬라이딩 윈도우로 선대기. 조회 직전에 호출한다.

    최근 60초 안에 이미 per_min번 조회했으면 가장 오래된 조회가 빠질 때까지만 기다리고,
    이번 조회 시각을 기록한다 (차단 화면 왕복·고정 대기 낭비 제거).
    """
    per_min = max(1, per_min)
    del _sent[:-per_min]
    if len(_sent) == per_min:
        wait = _sent[0] + 60 + margin - time.monotonic()
        if wait > 0:
            print(f"  ⏳ 제한 회피 선대기 {wait:.0f}초", flush=True)
            await asyncio.sleep(wait)
    _sent.append(time.monotonic())


# =============================================================================
# 일괄 조회
# =============================================================================

async def check_many(
    blog_urls: list[str],
    headless: bool = True,
    show_browser: bool = False,
) -> list[dict]:
    """
    여러 블로그의 지수를 한 번에 조회.
    """
    qualified_grades = load_qualified_grades()

    # 전략: 연속 조회하다가 조회 제한이 뜨면 안내된 시간만큼 자동 대기 후 재시도.
    query_delay = 0
    default_wait = 60
    max_retries = 5
    per_min, margin = 2, 2.0
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as _f:
                _bd = json.load(_f).get("blogdex", {})
                query_delay = float(_bd.get("query_delay_seconds", 0))
                per_min = int(_bd.get("rate_limit_per_minute", 2))
                margin = float(_bd.get("rate_limit_margin_seconds", 2))
                default_wait = int(_bd.get("rate_limit_wait_seconds", 60))
                max_retries = int(_bd.get("max_rate_limit_retries", 5))
    except Exception:
        pass

    print(f"\n📥 블덱스에서 {len(blog_urls)}명 연속 조회 시작 (조회 간격 {query_delay:.0f}초)")
    print("   ⏳ 조회 제한이 뜨면 안내 시간만큼 자동 대기 후 재시도합니다.")

    ctx_tuple = await get_logged_in_context(headless=(headless and not show_browser))
    if not ctx_tuple:
        print("❌ 블덱스 로그인 실패")
        return []

    p, browser, context = ctx_tuple

    results = []
    try:
        page = await context.new_page()

        queue = list(blog_urls)
        retries: dict[str, int] = {}
        total = len(blog_urls)
        done = 0

        while queue:
            url = queue.pop(0)
            blog_id = extract_blog_id(url)
            await throttle(per_min, margin)
            print(f"  [{done+1}/{total}] {blog_id} 조회 중...", end="", flush=True)

            result = await search_blog_index(page, url)

            # 조회 제한 → 안내초만큼 대기 후 같은 블로거 재시도
            if result.get("rate_limited"):
                n = retries.get(url, 0) + 1
                retries[url] = n
                if n > max_retries:
                    print(f" ⚠️ 조회 제한 {n}회 초과 — 건너뜀")
                    result["qualified"] = False
                    results.append(result)
                    done += 1
                    continue
                w = result.get("wait_sec") or 0
                w = (w + 2) if w > 0 else default_wait
                print(f" ⏳ 조회 제한 → {w}초 대기 후 재시도({n}/{max_retries})")
                await page.wait_for_timeout(w * 1000)
                _sent.clear()   # 대기 후엔 윈도우가 비었다고 간주
                queue.insert(0, url)
                continue

            result["qualified"] = classify_qualification(result["grade"], qualified_grades)
            if result["error"]:
                print(f" ❌ {result['error']}")
            else:
                mark = "✅" if result["qualified"] else "⚪"
                print(f" {mark} {result['grade'] or '(미확인)'}")
            results.append(result)
            done += 1

            if queue and query_delay > 0:
                await page.wait_for_timeout(int(query_delay * 1000))

    finally:
        await context.close()
        await browser.close()
        await p.stop()
    
    return results


def save_results_csv(results: list[dict], output_path: Path) -> None:
    """결과를 CSV로 저장."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["블로그ID", "블로그 URL", "지수", "자격 여부", "확인일시", "에러"])
        for r in results:
            writer.writerow([
                r.get("blog_id", ""),
                r.get("url", ""),
                r.get("grade", ""),
                "자격" if r.get("qualified") else "미자격",
                datetime.now().isoformat(),
                r.get("error", ""),
            ])
    print(f"\n✅ 결과 CSV 저장: {output_path}")


def print_summary(results: list[dict]) -> None:
    """결과 요약 출력."""
    qualified = [r for r in results if r.get("qualified")]
    unqualified = [r for r in results if not r.get("qualified") and not r.get("error")]
    errors = [r for r in results if r.get("error")]
    
    print(f"\n{'='*60}")
    print(f"📊 조회 결과 요약 (전체 {len(results)}명)")
    print(f"{'='*60}")
    print(f"  ✅ 자격 충족: {len(qualified)}명")
    for r in qualified:
        print(f"      - {r['blog_id']:20s} → {r['grade']}")
    
    if unqualified:
        print(f"\n  ⚪ 자격 미충족: {len(unqualified)}명")
        for r in unqualified:
            print(f"      - {r['blog_id']:20s} → {r['grade'] or '(미확인)'}")
    
    if errors:
        print(f"\n  ❌ 조회 실패: {len(errors)}명")
        for r in errors:
            print(f"      - {r['blog_id']:20s} → {r['error']}")
    
    print(f"{'='*60}\n")


# =============================================================================
# CLI
# =============================================================================

def parse_urls_arg(urls_str: str) -> list[str]:
    """세미콜론 또는 줄바꿈으로 구분된 URL 리스트 파싱."""
    return [u.strip() for u in re.split(r"[;\n]+", urls_str) if u.strip()]


def load_urls_from_file(path: Path) -> list[str]:
    """텍스트 파일에서 URL 리스트 로드 (한 줄에 하나씩, # 주석 지원)."""
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="블덱스 블로그 지수 자동 조회",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:

  [1] 한 명만 조회
    python blogdex_checker.py --url "https://blog.naver.com/blogger1"

  [2] 여러 명 한 번에 조회
    python blogdex_checker.py \\
        --urls "https://blog.naver.com/aaa;https://blog.naver.com/bbb;https://blog.naver.com/ccc"

  [3] 파일로 일괄 (한 줄에 하나씩)
    python blogdex_checker.py --input urls.txt

  [4] 첫 로그인 (세션 만들기 — 1회만)
    python session.py
        """
    )
    
    parser.add_argument("--url", help="단일 블로그 URL")
    parser.add_argument("--urls", help="여러 블로그 URL (세미콜론 구분)")
    parser.add_argument("--input", help="URL 목록 텍스트 파일")
    parser.add_argument("--output", help="결과 CSV 저장 경로 (기본: output/blogdex_지수_TIMESTAMP.csv)")
    parser.add_argument("--show-browser", action="store_true", help="브라우저 창 보기 (디버그용)")
    
    args = parser.parse_args()
    
    # URL 수집
    blog_urls = []
    if args.url:
        blog_urls.append(args.url)
    if args.urls:
        blog_urls.extend(parse_urls_arg(args.urls))
    if args.input:
        blog_urls.extend(load_urls_from_file(Path(args.input)))
    
    if not blog_urls:
        parser.print_help()
        print("\n❌ 조회할 URL이 없습니다. --url, --urls, 또는 --input 중 하나를 사용하세요.")
        sys.exit(1)
    
    # 중복 제거 (정규화 후)
    seen = set()
    unique_urls = []
    for url in blog_urls:
        norm = normalize_blog_url(url)
        if norm and norm not in seen:
            seen.add(norm)
            unique_urls.append(url)
    
    if len(unique_urls) < len(blog_urls):
        print(f"💡 중복 제거: {len(blog_urls)} → {len(unique_urls)}건")
    
    # 조회
    results = asyncio.run(check_many(unique_urls, show_browser=args.show_browser))
    
    # 결과 출력 + 저장
    print_summary(results)
    
    output_path = Path(args.output) if args.output else (
        PROJECT_ROOT / "output" / f"blogdex_지수_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    save_results_csv(results, output_path)


if __name__ == "__main__":
    main()
