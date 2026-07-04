"""
네이버 블로그 포스팅에서 메타정보 추출.

추출 항목:
- 제목 (post_title)
- 작성일자 (post_date) — 'YYYY.MM.DD' 형식

성능:
- Playwright로 한 번에 여러 URL 처리
- 같은 브라우저 세션 재사용
- 모바일 URL을 사용 (PC보다 가볍고 메타데이터 같음)
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright, Page


def to_mobile_url(url: str) -> str:
    """네이버 블로그 URL을 모바일 형식(m.blog.naver.com/...)으로 통일."""
    if not url:
        return url
    
    # PostView 형식 → 일반 형식으로
    if "postview" in url.lower():
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        blog_id = params.get("blogId", [""])[0]
        post_no = params.get("logNo", [""])[0]
        if blog_id and post_no:
            return f"https://m.blog.naver.com/{blog_id}/{post_no}"
    
    # 일반 PC URL → 모바일
    if "m.blog.naver.com" in url:
        return url
    return url.replace("blog.naver.com", "m.blog.naver.com")


async def extract_post_meta(page: Page, url: str) -> dict:
    """
    한 블로그 포스트의 메타정보 추출.
    
    Returns:
        {"title": str, "date": str(YYYY.MM.DD), "url": str}
        실패 시 빈 문자열 채워서 반환.
    """
    mobile_url = to_mobile_url(url)
    result = {"title": "", "date": "", "url": url}

    # 모바일 URL을 먼저 (2번까지 — 첫 시도가 타이밍 문제로 날짜를 못 잡는 경우 재시도),
    # 그래도 안 되면 PC URL로 폴백.
    # (mobile은 1차 빠른 시도, 2차는 더 오래 기다림)
    attempts: list[tuple[str, int]] = [(mobile_url, 1800), (mobile_url, 3500)]
    if "m.blog.naver.com" in mobile_url:
        pc_url = mobile_url.replace("m.blog.naver.com", "blog.naver.com")
        attempts.append((pc_url, 3000))

    # 날짜가 보통 들어있는 셀렉터들 — 이 중 하나라도 뜰 때까지 잠깐 기다린다.
    date_wait_selector = (
        ".se_publishDate, span.se_publishDate, .blog_date, p.blog_date, "
        ".date, .post_date, .se_date, .write_date, time, "
        'meta[property="article:published_time"]'
    )

    last_error = ""
    best_title = ""
    for attempt_url, wait_ms in attempts:
        try:
            await page.goto(attempt_url, wait_until="domcontentloaded", timeout=20000)
            # 날짜 요소가 렌더링될 때까지 잠깐 대기 (없으면 timeout 무시)
            try:
                await page.wait_for_selector(date_wait_selector, timeout=wait_ms, state="attached")
            except Exception:
                await page.wait_for_timeout(wait_ms)

            # iframe 안에 콘텐츠가 있는 경우 (PC URL의 경우 흔함)
            meta = await _try_extract_meta(page)

            # iframe 내부도 시도
            if not meta.get("date"):
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        frame_meta = await _try_extract_meta_in_frame(frame)
                        if frame_meta.get("date"):
                            meta["date"] = frame_meta["date"]
                        if frame_meta.get("title") and not meta.get("title"):
                            meta["title"] = frame_meta["title"]
                    except Exception:
                        continue

            title = meta.get("title", "")
            date = normalize_date(meta.get("date", ""))

            # 제목은 한 번 잡히면 보존 (다음 시도에서 날짜만 다시 노릴 수 있게)
            if title and not best_title:
                best_title = title

            result["title"] = best_title or title
            result["date"] = date

            # 날짜가 잡히면 성공 (제목은 best_title로 채워짐)
            if result["date"]:
                return result

        except Exception as e:
            last_error = str(e)
            continue

    # 모든 시도에서 날짜를 못 잡았으면 — 적어도 제목은 채워서 반환
    result["title"] = best_title
    if last_error and not result["title"]:
        result["error"] = last_error

    return result


async def _try_extract_meta(page) -> dict:
    """페이지에서 메타정보 추출 시도 (페이지/프레임 모두 사용 가능)."""
    return await page.evaluate("""
        () => {
            const out = { title: '', date: '' };
            
            // === 제목 추출 ===
            const titleSelectors = [
                '.se-title-text',                // 스마트에디터 ONE
                '.se-fs-fs28',                   // 스마트에디터 ONE 변형
                '.se-fs-fs26',
                'div.se_title h3',               // 스마트에디터 2
                'h3.tit_h3',
                '.tit_h3',
                'div.post_title',
                '.post_title',
                '.tit_blog',
                'div.htitle span',               // 구버전
                'meta[property="og:title"]',
            ];
            for (const sel of titleSelectors) {
                const el = document.querySelector(sel);
                if (!el) continue;
                const text = sel.startsWith('meta')
                    ? el.getAttribute('content')
                    : el.innerText;
                if (text && text.trim()) {
                    out.title = text.trim().replace(/\\s+/g, ' ');
                    break;
                }
            }
            
            // === 작성일자 추출 ===
            const dateSelectors = [
                // 스마트에디터 ONE
                '.se_publishDate', 'span.se_publishDate',
                // 모바일 블로그
                '.blog_date', 'p.blog_date',
                // 일반
                '.date', '.post_date', 'time',
                // PC 클래식
                '.se_date', '.write_date',
                // OG/article 메타
                'meta[property="article:published_time"]',
                'meta[name="article:published_time"]',
            ];
            for (const sel of dateSelectors) {
                const el = document.querySelector(sel);
                if (!el) continue;
                let text = '';
                if (sel.startsWith('meta')) {
                    text = el.getAttribute('content') || '';
                } else {
                    text = el.innerText || el.getAttribute('datetime') || '';
                }
                if (text && text.trim()) {
                    out.date = text.trim();
                    break;
                }
            }
            
            // 마지막 폴백: 페이지 본문에서 'YYYY.MM.DD' 패턴 직접 검색
            // (블로그 글 상단에 보통 작성일자가 표시됨)
            if (!out.date) {
                const bodyText = (document.body.innerText || '').substring(0, 1000);
                const m = bodyText.match(/(\\d{4})\\.\\s*(\\d{1,2})\\.\\s*(\\d{1,2})/);
                if (m) {
                    out.date = `${m[1]}.${m[2].padStart(2,'0')}.${m[3].padStart(2,'0')}`;
                }
            }
            
            return out;
        }
    """)


async def _try_extract_meta_in_frame(frame) -> dict:
    """iframe 내부에서 메타정보 추출 (PC URL의 경우 본문이 mainFrame 안에 있음)."""
    try:
        return await frame.evaluate("""
            () => {
                const out = { title: '', date: '' };
                
                // 제목
                const titleSels = [
                    '.se-title-text', '.se-fs-fs28', '.se-fs-fs26',
                    'div.se_title h3', 'h3.tit_h3', '.tit_h3',
                    'div.htitle span', '.post_title',
                ];
                for (const sel of titleSels) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.trim()) {
                        out.title = el.innerText.trim().replace(/\\s+/g, ' ');
                        break;
                    }
                }
                
                // 날짜
                const dateSels = [
                    '.se_publishDate', 'span.se_publishDate',
                    '.blog_date', '.date', '.write_date', '.se_date',
                ];
                for (const sel of dateSels) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.trim()) {
                        out.date = el.innerText.trim();
                        break;
                    }
                }
                
                if (!out.date) {
                    const bodyText = (document.body.innerText || '').substring(0, 1000);
                    const m = bodyText.match(/(\\d{4})\\.\\s*(\\d{1,2})\\.\\s*(\\d{1,2})/);
                    if (m) {
                        out.date = `${m[1]}.${m[2].padStart(2,'0')}.${m[3].padStart(2,'0')}`;
                    }
                }
                
                return out;
            }
        """)
    except Exception:
        return {"title": "", "date": ""}


def normalize_date(raw: str) -> str:
    """
    네이버 블로그의 다양한 날짜 형식을 'YYYY.MM.DD'로 통일.
    
    예시 입력:
    - '2026. 2. 23.' → '2026.02.23'
    - '2026.02.23. 14:30' → '2026.02.23'
    - '2026-02-23T14:30:00+09:00' → '2026.02.23'
    - '2시간 전' → '' (상대시간은 비움 — 페이지를 다시 봐야 함)
    """
    if not raw:
        return ""
    
    raw = raw.strip()
    
    # ISO 형식 (meta article:published_time)
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if iso_match:
        y, m, d = iso_match.groups()
        return f"{y}.{m}.{d}"
    
    # 'YYYY. M. D' 또는 'YYYY.MM.DD' 또는 'YYYY/MM/DD'
    date_match = re.search(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", raw)
    if date_match:
        y, m, d = date_match.groups()
        return f"{int(y):04d}.{int(m):02d}.{int(d):02d}"
    
    # 상대시간 ('N시간 전', '어제') 등은 정확한 날짜 알 수 없음
    return ""


async def extract_many(urls: list[str], headless: bool = True) -> dict[str, dict]:
    """
    여러 URL의 메타정보를 한 번에 추출.
    
    Args:
        urls: 블로그 포스트 URL 리스트
        headless: True면 브라우저 창 숨김
    
    Returns:
        {url: {"title": ..., "date": ...}, ...}
    """
    results = {}
    if not urls:
        return results
    
    print(f"\n📥 블로그 포스트 메타정보 추출 중... ({len(urls)}건)")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 480, "height": 800},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()
        
        for i, url in enumerate(urls, start=1):
            meta = await extract_post_meta(page, url)
            results[url] = meta
            status = "✓" if meta.get("title") and meta.get("date") else "△"
            print(f"  {status} [{i}/{len(urls)}] {meta.get('date') or '?':12s} | {(meta.get('title') or '?')[:40]}")
        
        await browser.close()
    
    return results


def extract_many_sync(urls: list[str], headless: bool = True) -> dict[str, dict]:
    """동기 래퍼 (asyncio 외부에서 호출용)."""
    return asyncio.run(extract_many(urls, headless=headless))


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python blog_meta.py <url1> [url2 ...]")
        sys.exit(1)
    
    urls = sys.argv[1:]
    results = extract_many_sync(urls, headless=False)
    print("\n=== 결과 ===")
    for url, meta in results.items():
        print(f"\nURL: {url}")
        print(f"  제목: {meta.get('title', '(없음)')}")
        print(f"  날짜: {meta.get('date', '(없음)')}")
