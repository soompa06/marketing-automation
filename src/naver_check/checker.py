"""
네이버 상위노출 확인 + 스크린샷 자동화 (1순위 핵심 기능)

핵심 전략:
- SERP HTML 구조가 자주 바뀌므로 특정 셀렉터에 의존하지 않음
- 페이지에 보이는 모든 'blog.naver.com' 링크를 순회하며 타겟과 매칭
- 매칭되면 그 링크의 적절한 부모 컨테이너에 빨간 네모 그리고 스크린샷
"""
from __future__ import annotations  # Python 3.9 호환 (dict | None 같은 타입 힌트)

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs

from playwright.async_api import async_playwright, Page


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"


# =============================================================================
# 설정 로드
# =============================================================================

def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    example_path = PROJECT_ROOT / "config" / "settings.example.json"
    with open(example_path, encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 월(月) 라벨 정규화
# =============================================================================

def normalize_month(raw: str) -> str:
    """
    사용자가 입력한 '월'을 1~12 숫자 문자열로 정규화.

    예시:
    - '5' / '05' / '5월' / '2026-05' / '5月' → '5'
    - '' / 'abc' / '13' → ''  (인식 불가/범위 밖이면 빈 값)

    반환값은 폴더명·결과CSV에 '{n}월' 형태로 쓰기 좋게 정수 문자열.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    # 'YYYY-MM' / 'YYYY.MM' 형태면 뒤쪽 월만
    ym = re.search(r"\d{4}\s*[.\-/]\s*(\d{1,2})", s)
    if ym:
        n = int(ym.group(1))
        return str(n) if 1 <= n <= 12 else ""
    # 그 외에는 첫 번째 1~2자리 숫자
    m = re.search(r"\d{1,2}", s)
    if not m:
        return ""
    n = int(m.group())
    return str(n) if 1 <= n <= 12 else ""


def month_folder_prefix(month: str, folder_name: str) -> str:
    """월이 있으면 'N월 폴더명', 없으면 폴더명 그대로."""
    m = normalize_month(month)
    if m:
        return f"{m}월 {folder_name}"
    return folder_name


# =============================================================================
# URL 정규화 (PC/모바일/PostView 모두 동일하게 인식)
# =============================================================================

def extract_blog_id_and_post(url: str) -> tuple[str, str]:
    """
    네이버 블로그 URL에서 (블로그ID, 포스트번호) 추출.

    반환 규칙:
    - 글 URL (post 번호 있음) → ("blogId", "postNo")
    - 블로그 홈 URL          → ("blogId", "")    ← 신규: 빈 post_no 허용
    - 네이버 블로그가 아님   → ("", "")

    지원 형식:
    - https://blog.naver.com/blogId/postNo
    - https://m.blog.naver.com/blogId/postNo
    - https://blog.naver.com/PostView.naver?blogId=xxx&logNo=yyy
    - https://m.blog.naver.com/blogId   (← 블로그 홈)
    """
    if not url:
        return "", ""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return "", ""

    host = parsed.netloc.lower()
    if "blog.naver.com" not in host:
        return "", ""

    # PostView 형식
    if "postview" in parsed.path.lower():
        params = parse_qs(parsed.query)
        blog_id = params.get("blogId", [""])[0]
        post_no = params.get("logNo", [""])[0]
        return blog_id.strip(), post_no.strip()

    parts = [p for p in parsed.path.split("/") if p]
    # /blogId/postNo 형식
    if len(parts) >= 2:
        blog_id, post_no = parts[0], parts[1]
        if post_no.isdigit():
            return blog_id, post_no
    # /blogId 형식 (블로그 홈)
    if len(parts) == 1 and parts[0]:
        return parts[0], ""

    return "", ""


def is_same_post(target_url: str, candidate_url: str) -> bool:
    t_blog, t_post = extract_blog_id_and_post(target_url)
    c_blog, c_post = extract_blog_id_and_post(candidate_url)
    if not t_blog or not t_post:
        return False
    return t_blog == c_blog and t_post == c_post


# =============================================================================
# 페이지 내 모든 블로그 링크 수집 (셀렉터 무관)
# =============================================================================

async def find_target_in_page(page: Page, target_url: str) -> dict | None:
    """
    현재 페이지에서 타겟 URL과 매칭되는 첫 번째 블로그 포스트 링크 찾기.
    
    카드 감지 알고리즘 (개선):
    1. 페이지의 모든 블로그 포스트 링크의 좌표를 미리 수집
    2. 타겟 링크에서 시작해 부모를 한 단계씩 올라감
    3. 부모가 "다른 포스트 링크의 영역과 겹치는 순간" 직전 단계가 최종 카드
    4. 추가 안전장치: 부모 컨테이너의 면적이 페이지 전체의 1/2를 넘으면 즉시 중단
    
    제외 대상: 클립 동영상, 시스템 페이지, 화면에 안 보이는 링크
    """
    target_blog, target_post = extract_blog_id_and_post(target_url)
    if not target_blog:
        return None
    # target_post가 비어있으면 "이 블로거의 어느 글이든" 매칭 모드 (블로그 홈 URL)

    matches = await page.evaluate("""
        ({ targetBlog, targetPost }) => {
            // === 1단계: 페이지의 모든 블로그 포스트 링크 수집 ===
            const links = document.querySelectorAll('a[href*="blog.naver.com"]');
            const allPosts = [];  // {link, blogId, postNo, isTarget}

            for (const link of links) {
                const href = link.href || '';
                if (/\\/clip\\/\\d+/.test(href)) continue;

                let blogId = '', postNo = '';
                const postViewMatch = href.match(/blogId=([^&]+)/);
                const logNoMatch = href.match(/logNo=(\\d+)/);
                if (postViewMatch && logNoMatch) {
                    blogId = postViewMatch[1];
                    postNo = logNoMatch[1];
                } else {
                    const pathMatch = href.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                    if (pathMatch) {
                        blogId = pathMatch[1];
                        postNo = pathMatch[2];
                    }
                }

                if (!blogId || !postNo) continue;
                if (blogId === 'MyBlog.naver') continue;

                // 화면에 안 보이는 링크 스킵
                const r = link.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;

                // 매칭 규칙:
                // - targetPost 있음: (blogId, postNo) 둘 다 일치
                // - targetPost 없음(홈 URL): blogId만 일치 (이 블로거의 어느 글이든)
                const isTarget = targetPost
                    ? (blogId === targetBlog && postNo === targetPost)
                    : (blogId === targetBlog);

                allPosts.push({ link, blogId, postNo, isTarget });
            }

            // === 2단계: 타겟 링크 찾기 ===
            // 홈 URL 모드일 땐 페이지에 노출된 가장 위쪽 글을 선택
            const targetEntry = allPosts.find(p => p.isTarget);
            if (!targetEntry) return null;

            const targetLink = targetEntry.link;

            // === 3단계: 카드 경계 찾기 ===
            // 홈 URL 모드: 같은 blogId의 다른 글들은 "한 카드 안의 부속글"일 수도 있어 제외 X
            //              (다른 blogId의 글들만 카드 경계 판단에 사용)
            const otherPosts = allPosts.filter(p => p.blogId !== targetEntry.blogId);
            
            // 페이지 면적
            const pageArea = document.documentElement.scrollWidth * 
                            document.documentElement.scrollHeight;
            const maxAllowedArea = pageArea / 2;  // 페이지의 절반 넘으면 너무 큼
            
            let bestCard = targetLink;
            let parent = targetLink.parentElement;
            
            while (parent && parent !== document.body) {
                const parentRect = parent.getBoundingClientRect();
                const parentArea = parentRect.width * parentRect.height;
                
                // 너무 크면 즉시 중단
                if (parentRect.height > 600) break;
                if (parentArea > maxAllowedArea) break;
                
                // 이 부모가 다른 포스트 링크를 포함하는지 확인
                let containsOtherPost = false;
                for (const other of otherPosts) {
                    if (parent.contains(other.link)) {
                        containsOtherPost = true;
                        break;
                    }
                }
                
                if (containsOtherPost) break;  // 다른 포스트 들어오기 시작 → 직전이 최선
                
                // 의미 있는 크기일 때만 후보 갱신 (아주 작은 wrapper div 제외)
                if (parentRect.height >= 80 && parentRect.width >= 200) {
                    bestCard = parent;
                }
                
                parent = parent.parentElement;
            }
            
            const rect = bestCard.getBoundingClientRect();
            return {
                matchedUrl: targetLink.href,
                box: {
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height,
                }
            };
        }
    """, {"targetBlog": target_blog, "targetPost": target_post})
    
    if matches:
        return {
            "highlight_box": matches["box"],
            "matched_url": matches["matchedUrl"],
        }
    return None


# =============================================================================
# 블로그탭 내 순위 매기기
# =============================================================================

async def find_target_in_blog_tab(page: Page, target_url: str, top_n: int = 10) -> dict | None:
    """
    블로그탭에서 타겟의 1~top_n위 노출 여부 확인.
    
    네이버 블로그탭은 한 결과 카드(블로거 1명)에 대표글 + 같은 블로거의 다른 글이
    함께 보이므로, "블로거당 1번"으로 카운트해야 실제 순위와 일치함.
    
    제외 대상:
    - 블로그 홈 링크 (포스트 번호 없음)
    - 클립 동영상 (/clip/숫자)
    - 시스템 페이지 (MyBlog.naver 등)
    - 화면에 안 보이는 숨김 링크
    """
    target_blog, target_post = extract_blog_id_and_post(target_url)
    if not target_blog:
        return None
    # target_post == "" 인 경우(블로그 홈 URL): blogId만 매칭

    result = await page.evaluate("""
        ({ targetBlog, targetPost, topN }) => {
            const links = document.querySelectorAll('a[href*="blog.naver.com"]');
            const seenBloggers = new Set();  // 이미 카운트한 블로거
            const ranked = [];
            let targetEntry = null;

            for (const link of links) {
                const href = link.href || '';

                // 클립 동영상 제외
                if (/\\/clip\\/\\d+/.test(href)) continue;

                // blogId/postNo 추출
                let blogId = '', postNo = '';
                const postViewMatch = href.match(/blogId=([^&]+)/);
                const logNoMatch = href.match(/logNo=(\\d+)/);
                if (postViewMatch && logNoMatch) {
                    blogId = postViewMatch[1];
                    postNo = logNoMatch[1];
                } else {
                    const pathMatch = href.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                    if (pathMatch) {
                        blogId = pathMatch[1];
                        postNo = pathMatch[2];
                    }
                }

                if (!blogId || !postNo) continue;
                if (blogId === 'MyBlog.naver') continue;

                // 화면에 보이는 링크만
                const rect = link.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) continue;

                // 매칭 규칙:
                // - targetPost 있음: (blogId, postNo) 둘 다 일치
                // - targetPost 없음(홈 URL): blogId만 일치
                const isTargetPost = targetPost
                    ? (blogId === targetBlog && postNo === targetPost)
                    : (blogId === targetBlog);
                
                // 이미 카운트한 블로거면 스킵 (단, 타겟이면 그 블로거의 카운트된 순위를 기록)
                if (seenBloggers.has(blogId)) {
                    if (isTargetPost && !targetEntry) {
                        // 이미 카운트된 블로거의 글 중 타겟 포스트 발견
                        // → 그 블로거의 순위 = 타겟 순위
                        const existingEntry = ranked.find(e => e.blogId === blogId);
                        if (existingEntry) {
                            targetEntry = {
                                ...existingEntry,
                                href,
                                link,
                                isTargetExactMatch: true
                            };
                        }
                    }
                    continue;
                }
                
                seenBloggers.add(blogId);
                
                const entry = {
                    blogId,
                    postNo,
                    href,
                    rank: ranked.length + 1,
                    link
                };
                ranked.push(entry);
                
                if (isTargetPost && !targetEntry) {
                    targetEntry = { ...entry, isTargetExactMatch: true };
                }
                
                if (ranked.length >= topN) break;
            }
            
            const topResults = ranked.slice(0, topN).map(e => ({
                rank: e.rank,
                blogId: e.blogId,
                postNo: e.postNo
            }));
            
            if (targetEntry) {
                // 카드 찾기: 다른 블로거의 포스트를 포함하지 않는 가장 큰 컨테이너
                // (블로그탭은 같은 블로거의 다른 글들은 같은 카드 안에 있을 수 있음)
                const link = targetEntry.link;
                let bestCard = link;
                let parent = link.parentElement;
                
                // 다른 블로거의 모든 포스트 링크 수집 (한 번만)
                const otherBloggerLinks = [];
                for (const checkLink of links) {
                    if (checkLink === link) continue;
                    const h = checkLink.href || '';
                    if (/\\/clip\\/\\d+/.test(h)) continue;
                    
                    let bId = '', pNo = '';
                    const pvMatch = h.match(/blogId=([^&]+)/);
                    const lnMatch = h.match(/logNo=(\\d+)/);
                    if (pvMatch && lnMatch) {
                        bId = pvMatch[1]; pNo = lnMatch[1];
                    } else {
                        const pMatch = h.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                        if (pMatch) { bId = pMatch[1]; pNo = pMatch[2]; }
                    }
                    
                    if (!bId || !pNo) continue;
                    if (bId === 'MyBlog.naver') continue;
                    if (bId === targetBlog) continue;  // 같은 블로거 글은 같은 카드일 수 있음
                    
                    otherBloggerLinks.push(checkLink);
                }
                
                while (parent && parent !== document.body) {
                    const parentRect = parent.getBoundingClientRect();
                    if (parentRect.height > 800) break;
                    
                    let containsOtherBlogger = false;
                    for (const ol of otherBloggerLinks) {
                        if (parent.contains(ol)) {
                            containsOtherBlogger = true;
                            break;
                        }
                    }
                    
                    if (containsOtherBlogger) break;
                    
                    if (parentRect.height >= 50 && parentRect.width >= 100) {
                        bestCard = parent;
                    }
                    
                    parent = parent.parentElement;
                }
                
                const rect = bestCard.getBoundingClientRect();
                return {
                    rank: targetEntry.rank,
                    matchedUrl: targetEntry.href,
                    box: {
                        x: rect.left + window.scrollX,
                        y: rect.top + window.scrollY,
                        width: rect.width,
                        height: rect.height,
                    },
                    topResults
                };
            }
            
            return { notFound: true, topResults };
        }
    """, {"targetBlog": target_blog, "targetPost": target_post, "topN": top_n})

    return result


# =============================================================================
# 가게명(store) 모드 — 제목에 가게명이 포함된 포스팅을 모두 수집
# =============================================================================
#
# 블로그 URL이 아니라 '가게명'(예: 가게A)으로 검수한다.
# 키워드를 검색했을 때 통합검색/블로그탭 결과 중 '포스팅 제목에 가게명이
# 포함된 글'을 전부 찾아 월간보고서 데이터로 모은다. (여러 개 매칭 가능)

# SERP 카드에서 (blogId, postNo, 제목, 카드 박스)를 뽑아 제목에 가게명이
# 포함된 것만 리턴하는 공용 JS. 블로거당 1개(첫 글)만 — 블로그탭 순위 계산용.
_STORE_SCAN_JS = r"""
    ({ storeName, topN }) => {
        const norm = (s) => (s || '').replace(/\s+/g, '').toLowerCase();
        const target = norm(storeName);
        const links = document.querySelectorAll('a[href*="blog.naver.com"]');
        const seen = new Set();          // blogId 기준 (블로거당 1번 = 순위)
        const seenPost = new Set();      // blogId/postNo 중복 제거
        const ranked = [];               // 블로거당 1개 (순위)
        const matches = [];              // 제목에 가게명 포함된 글

        for (const link of links) {
            const href = link.href || '';
            if (/\/clip\/\d+/.test(href)) continue;
            let blogId = '', postNo = '';
            const pv = href.match(/blogId=([^&]+)/);
            const ln = href.match(/logNo=(\d+)/);
            if (pv && ln) { blogId = pv[1]; postNo = ln[1]; }
            else {
                const pm = href.match(/blog\.naver\.com\/([^\/\?]+)\/(\d+)/);
                if (pm) { blogId = pm[1]; postNo = pm[2]; }
            }
            if (!blogId || !postNo) continue;
            if (blogId === 'MyBlog.naver') continue;
            const rect = link.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) continue;

            // 블로거당 1번만 순위 부여 (블로그탭 순위와 일치)
            if (!seen.has(blogId)) {
                seen.add(blogId);
                ranked.push(blogId);
            }
            const rank = ranked.indexOf(blogId) + 1;
            if (topN && rank > topN) continue;

            // 제목 텍스트: 링크 innerText > title 속성 > aria-label
            let title = (link.innerText || link.getAttribute('title')
                         || link.getAttribute('aria-label') || '').trim();
            if (!title) continue;
            if (!norm(title).includes(target)) continue;   // 제목에 가게명 포함만

            const key = blogId + '/' + postNo;
            if (seenPost.has(key)) continue;
            seenPost.add(key);

            // 카드 박스: 다른 블로거 글을 포함하지 않는 적당한 부모
            let bestCard = link, parent = link.parentElement;
            while (parent && parent !== document.body) {
                const pr = parent.getBoundingClientRect();
                if (pr.height > 600) break;
                // 다른 블로거의 글 링크를 포함하면 중단
                let crossed = false;
                for (const ol of links) {
                    if (ol === link) continue;
                    const oh = ol.href || '';
                    const om = oh.match(/blog\.naver\.com\/([^\/\?]+)\/(\d+)/)
                              || (oh.match(/blogId=([^&]+)/) && oh.match(/logNo=(\d+)/) ? true : null);
                    let obid = '';
                    const opm = oh.match(/blog\.naver\.com\/([^\/\?]+)\//);
                    const opv = oh.match(/blogId=([^&]+)/);
                    obid = opm ? opm[1] : (opv ? opv[1] : '');
                    if (obid && obid !== blogId && parent.contains(ol)) { crossed = true; break; }
                }
                if (crossed) break;
                if (pr.height >= 50 && pr.width >= 100) bestCard = parent;
                parent = parent.parentElement;
            }
            const rc = bestCard.getBoundingClientRect();
            matches.push({
                blogId, postNo, rank,
                url: 'https://blog.naver.com/' + blogId + '/' + postNo,
                title: title.slice(0, 120),
                box: {
                    x: rc.left + window.scrollX, y: rc.top + window.scrollY,
                    width: rc.width, height: rc.height,
                },
            });
        }
        return matches;
    }
"""


async def find_store_in_page(page: Page, store_name: str) -> list[dict]:
    """통합검색에서 제목에 가게명이 포함된 포스팅들(전부) 반환."""
    if not store_name:
        return []
    try:
        return await page.evaluate(_STORE_SCAN_JS, {"storeName": store_name, "topN": 0})
    except Exception:
        return []


async def find_store_in_blog_tab(page: Page, store_name: str, top_n: int = 20) -> list[dict]:
    """블로그탭 1~top_n위 중 제목에 가게명이 포함된 포스팅들(전부) 반환 (순위 포함)."""
    if not store_name:
        return []
    try:
        return await page.evaluate(_STORE_SCAN_JS, {"storeName": store_name, "topN": top_n})
    except Exception:
        return []


# =============================================================================
# Lazy loading 대응 스크롤
# =============================================================================

async def scroll_to_load(page: Page, max_scrolls: int = 3) -> None:
    """페이지 끝까지 스크롤하여 lazy-loaded 콘텐츠를 강제 로드. 빠른 스크롤."""
    for _ in range(max_scrolls):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(250)  # 600 → 250ms
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(150)


async def smart_load_for_target(page: Page, target_url: str, max_scrolls: int = 3) -> bool:
    """
    타겟 URL이 페이지에 등장할 때까지만 스크롤 (조기 종료).
    
    이미 보이면 즉시 True 반환.
    Lazy-loading 페이지에서는 타겟이 나타날 때까지만 스크롤.
    
    Returns:
        True: 타겟 발견 (또는 페이지 끝까지 스크롤 완료)
    """
    target_blog, target_post = extract_blog_id_and_post(target_url)
    if not target_blog:
        await scroll_to_load(page, max_scrolls)
        return True

    # 매칭 식: 글 URL이면 (blogId, postNo) 둘 다, 홈 URL이면 blogId만
    js_find = """
        ({ targetBlog, targetPost }) => {
            const links = document.querySelectorAll('a[href*="blog.naver.com"]');
            for (const link of links) {
                const h = link.href || '';
                if (/\\/clip\\/\\d+/.test(h)) continue;
                const pv = h.match(/blogId=([^&]+)/);
                const ln = h.match(/logNo=(\\d+)/);
                let bId = '', pNo = '';
                if (pv && ln) { bId = pv[1]; pNo = ln[1]; }
                else {
                    const pm = h.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                    if (pm) { bId = pm[1]; pNo = pm[2]; }
                }
                const match = targetPost
                    ? (bId === targetBlog && pNo === targetPost)
                    : (bId === targetBlog && pNo);  // 홈 URL은 글 후보 중 같은 blogId
                if (match) return true;
            }
            return false;
        }
    """

    found = await page.evaluate(js_find, {"targetBlog": target_blog, "targetPost": target_post})

    # 발견하면 즉시 종료 (스크롤 불필요 — 큰 시간 절약)
    if found:
        return True

    # 못 찾으면 스크롤하면서 매 단계마다 다시 확인
    for _ in range(max_scrolls):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(250)
        found = await page.evaluate(js_find, {"targetBlog": target_blog, "targetPost": target_post})
        if found:
            break
    
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(150)
    return True


# =============================================================================
# 빨간 네모 그리고 스크린샷
# =============================================================================

async def take_screenshot_with_box(
    page: Page,
    box: dict,
    save_path: Path,
) -> None:
    """
    미리 계산된 box 좌표(절대 좌표)로 빨간 네모를 그리고 스크린샷 저장.
    
    블로그탭처럼 카드 감지가 안정적인 경우 사용.
    box.x, box.y는 페이지 절대 좌표 (window.scrollX/Y 포함됨).
    """
    await page.evaluate("""
        (box) => {
            const old = document.getElementById('__claude_highlight__');
            if (old) old.remove();
            
            const overlay = document.createElement('div');
            overlay.id = '__claude_highlight__';
            overlay.style.position = 'absolute';
            overlay.style.left = box.x + 'px';
            overlay.style.top = box.y + 'px';
            overlay.style.width = box.width + 'px';
            overlay.style.height = box.height + 'px';
            overlay.style.border = '4px solid red';
            overlay.style.borderRadius = '4px';
            overlay.style.pointerEvents = 'none';
            overlay.style.zIndex = '99999';
            overlay.style.boxSizing = 'border-box';
            document.body.appendChild(overlay);
        }
    """, box)
    
    await page.evaluate("""
        (box) => {
            const targetY = Math.max(0, box.y - 150);
            window.scrollTo({ top: targetY, behavior: 'instant' });
        }
    """, box)
    await page.wait_for_timeout(250)
    
    save_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(save_path), full_page=False)
    
    await page.evaluate("""
        () => {
            const el = document.getElementById('__claude_highlight__');
            if (el) el.remove();
        }
    """)


async def take_screenshot_with_highlight(
    page: Page,
    target_url: str,
    save_path: Path,
) -> None:
    """
    타겟 URL의 카드를 다시 찾아서 빨간 네모를 정확히 그리고 스크린샷 저장.
    
    핵심: 좌표를 미리 계산해서 넘기지 않고, 스크린샷 직전에 페이지 안에서
    카드를 다시 찾아 좌표를 사용함. 이렇게 하면 페이지 레이아웃이 변해도
    오차가 누적되지 않음.
    
    빨간 네모는 스크롤된 후 viewport 기준 좌표(fixed)로 그려서, 
    overlay와 카드의 위치가 항상 일치하도록 보장.
    """
    target_blog, target_post = extract_blog_id_and_post(target_url)
    if not target_blog:
        return
    # target_post == "" 면 이 블로거 어느 글이든 매칭

    # 1) 페이지 안에서 카드를 다시 찾고, 화면에 보이도록 스크롤한 후
    #    viewport 기준 좌표로 overlay 그리기 (한 번에 처리)
    drew = await page.evaluate("""
        ({ targetBlog, targetPost }) => {
            // 기존 overlay 제거
            const oldOverlay = document.getElementById('__claude_highlight__');
            if (oldOverlay) oldOverlay.remove();
            
            // 카드 찾기 (find_target_in_page와 동일한 알고리즘)
            const links = document.querySelectorAll('a[href*="blog.naver.com"]');
            const allPosts = [];
            for (const link of links) {
                const href = link.href || '';
                if (/\\/clip\\/\\d+/.test(href)) continue;
                let blogId = '', postNo = '';
                const pv = href.match(/blogId=([^&]+)/);
                const ln = href.match(/logNo=(\\d+)/);
                if (pv && ln) { blogId = pv[1]; postNo = ln[1]; }
                else {
                    const pm = href.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                    if (pm) { blogId = pm[1]; postNo = pm[2]; }
                }
                if (!blogId || !postNo) continue;
                if (blogId === 'MyBlog.naver') continue;
                const r = link.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                allPosts.push({ link, blogId, postNo });
            }
            
            const targetEntry = allPosts.find(p =>
                targetPost
                    ? (p.blogId === targetBlog && p.postNo === targetPost)
                    : (p.blogId === targetBlog)
            );
            if (!targetEntry) return false;

            const targetLink = targetEntry.link;
            // 홈 URL 모드: 같은 blogId 글들은 같은 카드 안일 수 있어 제외 X
            const otherPosts = targetPost
                ? allPosts.filter(p => !(p.blogId === targetBlog && p.postNo === targetPost))
                : allPosts.filter(p => p.blogId !== targetEntry.blogId);
            
            // 카드 경계 찾기
            const pageArea = document.documentElement.scrollWidth * 
                            document.documentElement.scrollHeight;
            const maxAllowedArea = pageArea / 2;
            
            let bestCard = targetLink;
            let parent = targetLink.parentElement;
            
            while (parent && parent !== document.body) {
                const parentRect = parent.getBoundingClientRect();
                const parentArea = parentRect.width * parentRect.height;
                
                if (parentRect.height > 600) break;
                if (parentArea > maxAllowedArea) break;
                
                let containsOther = false;
                for (const other of otherPosts) {
                    if (parent.contains(other.link)) {
                        containsOther = true;
                        break;
                    }
                }
                if (containsOther) break;
                
                if (parentRect.height >= 80 && parentRect.width >= 200) {
                    bestCard = parent;
                }
                parent = parent.parentElement;
            }
            
            // === 스크롤: 카드를 viewport 중앙에 위치시키기 ===
            const cardRect = bestCard.getBoundingClientRect();
            const absoluteTop = cardRect.top + window.scrollY;
            const targetScrollY = Math.max(0, absoluteTop - 150);
            window.scrollTo({ top: targetScrollY, behavior: 'instant' });
            
            return true;
        }
    """, {"targetBlog": target_blog, "targetPost": target_post})
    
    if not drew:
        return
    
    # 스크롤 안정화 대기
    await page.wait_for_timeout(300)
    
    # 2) 스크롤 후 viewport 기준으로 다시 좌표 계산하여 overlay 그리기
    drawn = await page.evaluate("""
        ({ targetBlog, targetPost }) => {
            // 카드 다시 찾기 (스크롤 후)
            const links = document.querySelectorAll('a[href*="blog.naver.com"]');
            const allPosts = [];
            for (const link of links) {
                const href = link.href || '';
                if (/\\/clip\\/\\d+/.test(href)) continue;
                let blogId = '', postNo = '';
                const pv = href.match(/blogId=([^&]+)/);
                const ln = href.match(/logNo=(\\d+)/);
                if (pv && ln) { blogId = pv[1]; postNo = ln[1]; }
                else {
                    const pm = href.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                    if (pm) { blogId = pm[1]; postNo = pm[2]; }
                }
                if (!blogId || !postNo) continue;
                if (blogId === 'MyBlog.naver') continue;
                const r = link.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                allPosts.push({ link, blogId, postNo });
            }
            
            const targetEntry = allPosts.find(p =>
                targetPost
                    ? (p.blogId === targetBlog && p.postNo === targetPost)
                    : (p.blogId === targetBlog)
            );
            if (!targetEntry) return null;

            const targetLink = targetEntry.link;
            // 홈 URL 모드: 같은 blogId 글들은 같은 카드 안일 수 있어 제외 X
            const otherPosts = targetPost
                ? allPosts.filter(p => !(p.blogId === targetBlog && p.postNo === targetPost))
                : allPosts.filter(p => p.blogId !== targetEntry.blogId);
            
            const pageArea = document.documentElement.scrollWidth * 
                            document.documentElement.scrollHeight;
            const maxAllowedArea = pageArea / 2;
            
            let bestCard = targetLink;
            let parent = targetLink.parentElement;
            
            while (parent && parent !== document.body) {
                const parentRect = parent.getBoundingClientRect();
                const parentArea = parentRect.width * parentRect.height;
                
                if (parentRect.height > 600) break;
                if (parentArea > maxAllowedArea) break;
                
                let containsOther = false;
                for (const other of otherPosts) {
                    if (parent.contains(other.link)) {
                        containsOther = true;
                        break;
                    }
                }
                if (containsOther) break;
                
                if (parentRect.height >= 80 && parentRect.width >= 200) {
                    bestCard = parent;
                }
                parent = parent.parentElement;
            }
            
            // viewport 기준 좌표 (스크린샷은 viewport만 찍으므로 이게 맞음)
            const rect = bestCard.getBoundingClientRect();
            
            // 좌표 검증: 카드가 viewport 안에 (또는 부분적으로) 있어야 함
            // 0보다 작거나 viewport 밖에 완전히 있으면 실패
            if (rect.bottom < 0 || rect.top > window.innerHeight) {
                return null;  // 카드가 화면 밖
            }
            
            // overlay를 fixed 포지션으로 (viewport 기준)
            const overlay = document.createElement('div');
            overlay.id = '__claude_highlight__';
            overlay.style.position = 'fixed';
            overlay.style.left = rect.left + 'px';
            overlay.style.top = rect.top + 'px';
            overlay.style.width = rect.width + 'px';
            overlay.style.height = rect.height + 'px';
            overlay.style.border = '4px solid red';
            overlay.style.borderRadius = '4px';
            overlay.style.pointerEvents = 'none';
            overlay.style.zIndex = '99999';
            overlay.style.boxSizing = 'border-box';
            document.body.appendChild(overlay);
            
            return { 
                top: rect.top, 
                left: rect.left, 
                width: rect.width, 
                height: rect.height 
            };
        }
    """, {"targetBlog": target_blog, "targetPost": target_post})
    
    if not drawn:
        return
    
    # 3) 스크린샷 저장
    save_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(save_path), full_page=False)
    
    # 4) overlay 정리
    await page.evaluate("""
        () => {
            const el = document.getElementById('__claude_highlight__');
            if (el) el.remove();
        }
    """)


# =============================================================================
# 한 키워드에 대해 통합검색 + 블로그탭 모두 확인
# =============================================================================

async def _check_store_keyword(page, keyword, store_name, folder, safe_keyword,
                               debug=False) -> list:
    """
    가게명 모드: 키워드를 통합검색/블로그탭에서 검색해
    '제목에 가게명이 포함된 포스팅'을 전부 찾아 결과 리스트로 반환.

    반환: [{keyword, integrated_found, blog_tab_rank, matched_url, store_title, blog_id}, ...]
          (포스팅 1개당 1개 — 통합/블로그탭 동시 매칭은 병합)
    """
    def _safe(s):
        return unicodedata.normalize("NFC", re.sub(r"[^\w가-힣]+", "_", s).strip("_"))

    by_url: dict[str, dict] = {}

    # 1) 통합검색
    print(f"\n  🔍 [통합검색] '{keyword}' — 제목에 '{store_name}' 포함 글 찾는 중...")
    await page.goto(f"https://search.naver.com/search.naver?query={quote(keyword)}",
                    wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(300)
    await scroll_to_load(page, max_scrolls=3)
    integ = await find_store_in_page(page, store_name)
    for mtc in integ:
        rec = by_url.setdefault(mtc["url"], {
            "keyword": keyword, "integrated_found": False, "blog_tab_rank": None,
            "matched_url": mtc["url"], "store_title": mtc["title"], "blog_id": mtc["blogId"],
        })
        rec["integrated_found"] = True
        try:
            path = folder / f"통합검색_{safe_keyword}_{_safe(mtc['blogId'])}.png"
            await take_screenshot_with_box(page, mtc["box"], path)
        except Exception:
            pass
    print(f"    {'✅' if integ else '❌'} 통합검색 제목 매칭: {len(integ)}건")

    # 2) 블로그탭 (상위 20위)
    print(f"  🔍 [블로그탭] '{keyword}' — 제목에 '{store_name}' 포함 글 찾는 중...")
    await page.goto(
        f"https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_jum&query={quote(keyword)}",
        wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(300)
    await scroll_to_load(page, max_scrolls=3)
    btab = await find_store_in_blog_tab(page, store_name, top_n=20)
    for mtc in btab:
        rec = by_url.setdefault(mtc["url"], {
            "keyword": keyword, "integrated_found": False, "blog_tab_rank": None,
            "matched_url": mtc["url"], "store_title": mtc["title"], "blog_id": mtc["blogId"],
        })
        rec["blog_tab_rank"] = mtc["rank"]
        if not rec.get("store_title"):
            rec["store_title"] = mtc["title"]
        try:
            path = folder / f"블로그탭_{safe_keyword}_{mtc['rank']}_{_safe(mtc['blogId'])}.png"
            await take_screenshot_with_box(page, mtc["box"], path)
        except Exception:
            pass
    print(f"    {'✅' if btab else '❌'} 블로그탭 제목 매칭: {len(btab)}건")

    results = list(by_url.values())
    if not results:
        # 매칭 0건이어도 키워드 결과 1개는 남겨 요약에 표시
        results = [{
            "keyword": keyword, "integrated_found": False, "blog_tab_rank": None,
            "matched_url": "", "store_title": "", "blog_id": "",
        }]
    return results


async def check_one_keyword(
    page: Page,
    keyword: str,
    target_url: str,
    campaign: str,
    folder_name: str,
    screenshot_base: Path,
    debug: bool = False,
    month: str = "",
    mode: str = "business",
    store_name: str = "",
) -> dict:
    today = datetime.now().strftime("%Y%m%d")
    # 경로·파일명은 NFC로 정규화 (macOS NFD 저장 시 한글 glob이 못 찾는 문제 방지)
    campaign = unicodedata.normalize("NFC", campaign)
    folder_name = unicodedata.normalize("NFC", folder_name)
    safe_keyword = unicodedata.normalize("NFC", re.sub(r"[^\w가-힣]+", "_", keyword).strip("_"))
    safe_blogger = unicodedata.normalize("NFC", re.sub(r"[^\w가-힣]+", "_", folder_name).strip("_"))
    m = normalize_month(month)

    # 폴더는 여기서 미리 만들지 않는다. 실제 스크린샷을 저장할 때만
    # (take_screenshot_*가 parent.mkdir 수행) 생성 → 노출 없으면 빈 폴더가 안 생김.
    if mode == "business" and m:
        # 가게별 + 월: campaign/{N}월/ 평면 구조. 파일명 끝에 블로거 이름을 붙인다.
        # 예) 성형외과/3월/통합검색_강남_리투오_내돈내산_나정민.png
        #     성형외과/3월/블로그탭_강남_리투오_후기_10_최시온.png
        folder = screenshot_base / campaign / f"{m}월"
        integrated_filename = f"통합검색_{safe_keyword}_{safe_blogger}.png"
        def blogtab_filename(rank: int) -> str:
            return f"블로그탭_{safe_keyword}_{rank}_{safe_blogger}.png"
    else:
        # 기존 동작: 단일 블로그 모드, 또는 월 미지정 가게별.
        # campaign/{today}/{leaf}/ 아래 블로거별 폴더, 파일명엔 블로거 미포함.
        leaf = month_folder_prefix(month, folder_name)
        folder = screenshot_base / campaign / today / leaf
        integrated_filename = f"통합검색_{safe_keyword}.png"
        def blogtab_filename(rank: int) -> str:
            return f"블로그탭_{safe_keyword}_{rank}위.png"

    # === 가게명(store) 모드: 제목에 가게명이 포함된 글들을 전부 수집 ===
    if mode == "store":
        return await _check_store_keyword(
            page, keyword, store_name or folder_name, folder,
            safe_keyword, debug=debug,
        )

    # 1) 통합검색
    print(f"\n  🔍 [통합검색] '{keyword}' 검색 중...")
    integrated_url = f"https://search.naver.com/search.naver?query={quote(keyword)}"
    # domcontentloaded 후 smart_load가 자체 폴링하므로 추가 대기는 짧게만
    await page.goto(integrated_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(300)  # 800 → 300ms (smart_load가 보완)
    await smart_load_for_target(page, target_url, max_scrolls=3)
    
    if debug:
        debug_info = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="blog.naver.com"]');
                const samples = [];
                const seen = new Set();
                for (const link of links) {
                    const href = link.href;
                    if (!seen.has(href)) {
                        seen.add(href);
                        samples.push(href);
                        if (samples.length >= 5) break;
                    }
                }
                return { count: links.length, samples: samples };
            }
        """)
        print(f"    🐛 통합검색에 blog.naver.com 링크 {debug_info['count']}개 발견")
        print(f"    🐛 처음 5개 링크 샘플:")
        for i, url in enumerate(debug_info['samples'], 1):
            print(f"       {i}. {url}")
    
    integrated = await find_target_in_page(page, target_url)

    if integrated:
        path = folder / integrated_filename
        # 매칭된 실제 글 URL을 하이라이트 대상으로 넘김.
        # (홈 URL 입력일 때 input은 postNo가 없어서 스크롤 후 재탐색이 실패함)
        highlight_url = integrated.get("matched_url") or target_url
        try:
            await take_screenshot_with_highlight(page, highlight_url, path)
            if path.exists():
                print(f"    ✅ 통합검색 노출! 스크린샷: {path.name}")
            else:
                print(f"    ⚠️ 통합검색 매칭은 됐으나 스크린샷 저장 실패: {path.name}")
        except Exception as e:
            print(f"    ⚠️ 통합검색 스크린샷 오류: {e}")
    else:
        print(f"    ❌ 통합검색에서 미노출")
    
    # 2) 블로그탭
    print(f"  🔍 [블로그탭] '{keyword}' 검색 중...")
    blog_tab_url = (
        f"https://search.naver.com/search.naver"
        f"?ssc=tab.blog.all&sm=tab_jum&query={quote(keyword)}"
    )
    await page.goto(blog_tab_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(300)  # 800 → 300ms
    await smart_load_for_target(page, target_url, max_scrolls=3)
    
    if debug:
        debug_info = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="blog.naver.com"]');
                const samples = [];
                const seen = new Set();
                for (const link of links) {
                    const href = link.href;
                    if (!seen.has(href)) {
                        seen.add(href);
                        samples.push(href);
                        if (samples.length >= 5) break;
                    }
                }
                return { count: links.length, samples: samples };
            }
        """)
        print(f"    🐛 블로그탭에 blog.naver.com 링크 {debug_info['count']}개 발견")
        print(f"    🐛 처음 5개 링크 샘플:")
        for i, url in enumerate(debug_info['samples'], 1):
            print(f"       {i}. {url}")
    
    blog_tab = await find_target_in_blog_tab(page, target_url, top_n=10)
    
    # 매칭 성공 시: rank, highlight_box, matchedUrl, topResults 가짐
    # 매칭 실패 시: notFound=True, topResults 가짐
    matched = blog_tab and not blog_tab.get("notFound")
    
    if matched:
        path = folder / blogtab_filename(blog_tab["rank"])
        await take_screenshot_with_box(page, blog_tab["box"], path)
        print(f"    ✅ 블로그탭 {blog_tab['rank']}위 노출! 스크린샷: {path.name}")
    else:
        print(f"    ❌ 블로그탭 1~10위 미노출")
    
    # 디버그: 1~10위 실제 결과 출력 (매칭 성공/실패 모두)
    if debug and blog_tab and blog_tab.get("topResults"):
        print(f"    🐛 블로그탭 실제 1~10위:")
        t_blog, t_post = extract_blog_id_and_post(target_url)
        for r in blog_tab["topResults"]:
            if t_post:
                is_target = (r["blogId"] == t_blog and r["postNo"] == t_post)
            else:
                # 홈 URL: blogId만 일치하면 타겟
                is_target = (r["blogId"] == t_blog)
            mark = " ⬅️ 타겟" if is_target else ""
            print(f"       {r['rank']:2d}. {r['blogId']}/{r['postNo']}{mark}")
    
    # 매칭된 실제 글 URL (홈 URL을 입력한 경우 SERP에서 잡힌 그 블로거의 실제 포스트 URL)
    # 통합검색이 우선, 없으면 블로그탭 매칭 URL.
    matched_url = ""
    if integrated and integrated.get("matched_url"):
        matched_url = integrated["matched_url"]
    elif matched and blog_tab.get("matchedUrl"):
        matched_url = blog_tab["matchedUrl"]

    return {
        "keyword": keyword,
        "integrated_found": integrated is not None,
        "blog_tab_rank": blog_tab["rank"] if matched else None,
        "matched_url": matched_url,  # 빈 문자열 = 둘 다 매칭 실패
    }


def format_sheet_summary(results: list[dict]) -> str:
    # 키워드 중복 제거 (가게명 모드는 한 키워드에 여러 글이 매칭될 수 있음)
    integrated_keywords = list(dict.fromkeys(
        r["keyword"] for r in results if r.get("integrated_found")))
    blog_tab_parts = list(dict.fromkeys(
        f"{r['keyword']} {r['blog_tab_rank']}위"
        for r in results if r.get("blog_tab_rank") is not None))
    
    parts = []
    parts.append(f"상위노출: {', '.join(integrated_keywords) if integrated_keywords else '없음'}")
    parts.append(f"블로그탭 : {', '.join(blog_tab_parts) if blog_tab_parts else '없음'}")
    return " / ".join(parts)


async def run_one_blogger(
    page,
    target_url: str,
    keywords: list[str],
    campaign: str,
    folder_name: str,
    screenshot_base: Path,
    debug: bool = False,
    progress_label: str = "",
    business_name: str = "",
    month: str = "",
    mode: str = "business",
    store_name: str = "",
) -> dict:
    """한 블로거의 포스팅을 검수 (브라우저는 외부에서 받음 — 여러 명 처리 시 재사용)."""
    label_prefix = f"{progress_label} " if progress_label else ""

    # 가게명 모드: URL 없이 가게명(store_name)으로 제목 매칭
    is_store = (mode == "store")
    if is_store:
        store_name = store_name or business_name or folder_name
        print(f"\n{label_prefix}🟢 시작: [{folder_name}] 가게명 '{store_name}' "
              f"— 키워드 검색 결과 제목에 가게명 포함 글 수집")
    else:
        blog_id, post_no = extract_blog_id_and_post(target_url)
        if not blog_id:
            print(f"⚠️  {progress_label} URL을 인식할 수 없습니다: {target_url}")
            return {
                "folder_name": folder_name,
                "business_name": business_name,
                "campaign": campaign,
                "month": month,
                "url": target_url,
                "summary": "URL 인식 실패",
                "results": [],
                "checked_at": datetime.now().isoformat(),
            }
        if post_no:
            print(f"\n{label_prefix}🟢 시작: [{folder_name}] blog.naver.com/{blog_id}/{post_no}")
        else:
            print(f"\n{label_prefix}🟢 시작: [{folder_name}] blog.naver.com/{blog_id} (블로그 홈 — 이 블로거의 어느 글이든 매칭)")

    results = []
    for keyword in keywords:
        try:
            result = await check_one_keyword(
                page=page,
                keyword=keyword,
                target_url=target_url,
                campaign=campaign,
                folder_name=folder_name,
                screenshot_base=screenshot_base,
                debug=debug,
                month=month,
                mode=mode,
                store_name=store_name,
            )
            # store 모드는 리스트(여러 글) 반환 → 평탄화
            if isinstance(result, list):
                results.extend(result)
            else:
                results.append(result)
        except Exception as e:
            print(f"    ⚠️  '{keyword}' 처리 중 오류: {e}")
            if debug:
                import traceback
                traceback.print_exc()
            results.append({
                "keyword": keyword,
                "integrated_found": False,
                "blog_tab_rank": None,
                "matched_url": "",
                "error": str(e),
            })
    
    summary = format_sheet_summary(results)
    print(f"\n{label_prefix}🏁 완료: [{folder_name}] {summary}")

    return {
        "folder_name": folder_name,
        "business_name": business_name,
        "campaign": campaign,
        "month": month,
        "url": target_url,
        "results": results,
        "summary": summary,
        "checked_at": datetime.now().isoformat(),
    }


async def run(
    bloggers: list[dict],
    headless: bool = False,
    debug: bool = False,
    concurrency: int = 3,
) -> list[dict]:
    """
    여러 블로거를 병렬로 처리.
    
    Args:
        bloggers: [{"url": ..., "keywords": [...], "campaign": ..., "folder_name": ...}, ...]
        concurrency: 동시 처리할 블로거 수 (기본 3, 최대 5 권장)
    """
    settings = load_settings()
    sshot_cfg = settings.get("screenshot", {}) if isinstance(settings, dict) else {}
    screenshot_base = PROJECT_ROOT / sshot_cfg.get("base_dir", "screenshots")
    viewport = {
        "width": int(sshot_cfg.get("viewport_width", 1280)),
        "height": int(sshot_cfg.get("viewport_height", 900)),
    }
    
    # debug나 화면 표시 모드일 때는 순차 처리 (출력 가독성)
    if debug or not headless:
        concurrency = 1
    
    # 너무 많이 동시 실행하면 네이버에서 차단 가능성 → 최대 5
    concurrency = min(max(1, concurrency), 5, len(bloggers))
    
    print(f"\n📋 총 {len(bloggers)}명 처리 시작 (동시 처리: {concurrency}개)")
    
    all_results = [None] * len(bloggers)  # 입력 순서 유지
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        
        # 동시성 제어용 세마포어
        semaphore = asyncio.Semaphore(concurrency)
        completed_count = [0]  # mutable for closure
        
        async def process_one(idx: int, b: dict):
            async with semaphore:
                # 각 블로거마다 독립된 컨텍스트/페이지 사용
                context = await browser.new_context(
                    viewport=viewport,
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="ko-KR",
                )
                page = await context.new_page()
                
                # 속도 개선: 분석에 불필요한 리소스 차단
                # 폰트, 미디어, 외부 트래킹 스크립트 차단
                # (이미지는 유지 — 스크린샷에 필요)
                async def _block_unnecessary(route):
                    req = route.request
                    rtype = req.resource_type
                    url = req.url
                    
                    # 폰트와 미디어는 분석에 불필요
                    if rtype in ("font", "media"):
                        await route.abort()
                        return
                    
                    # 광고/트래킹/분석 도메인 차단
                    if any(d in url for d in [
                        "google-analytics.com", "googletagmanager.com",
                        "doubleclick.net", "googlesyndication.com",
                        "facebook.com/tr", "connect.facebook.net",
                        "ad.naver.com", "adcr.naver.com",
                    ]):
                        await route.abort()
                        return
                    
                    await route.continue_()
                
                await page.route("**/*", _block_unnecessary)
                
                completed_count[0] += 1
                progress = f"[{completed_count[0]}/{len(bloggers)}]"
                
                try:
                    result = await run_one_blogger(
                        page=page,
                        target_url=b["url"],
                        keywords=b["keywords"],
                        campaign=b["campaign"],
                        folder_name=b["folder_name"],
                        screenshot_base=screenshot_base,
                        debug=debug,
                        progress_label=progress,
                        business_name=b.get("business_name", ""),
                        month=b.get("month", ""),
                        mode=b.get("mode", "business"),
                        store_name=b.get("store_name", ""),
                    )
                    # 결과에 mode/월 메타 보존 (CSV 컬럼으로 저장됨)
                    if isinstance(result, dict):
                        result["mode"] = b.get("mode", "business")
                        result.setdefault("month", b.get("month", ""))
                    all_results[idx] = result
                except Exception as e:
                    print(f"\n⚠️  {progress} [{b.get('folder_name', '?')}] 실패: {e}")
                    if debug:
                        import traceback
                        traceback.print_exc()
                    all_results[idx] = {
                        "folder_name": b.get("folder_name", ""),
                        "business_name": b.get("business_name", ""),
                        "campaign": b.get("campaign", ""),
                        "month": b.get("month", ""),
                        "mode": b.get("mode", "business"),
                        "url": b.get("url", ""),
                        "summary": f"오류: {e}",
                        "results": [],
                        "checked_at": datetime.now().isoformat(),
                    }
                finally:
                    await context.close()
        
        # 모든 블로거를 동시에 시작 (semaphore가 동시 실행 수 제한)
        tasks = [process_one(i, b) for i, b in enumerate(bloggers)]
        await asyncio.gather(*tasks)
        
        await browser.close()
    
    # 전체 요약 출력
    print(f"\n\n{'='*60}")
    print(f"📊 전체 요약 ({len(all_results)}명)")
    print(f"{'='*60}")
    for r in all_results:
        print(f"\n[{r['folder_name']}]")
        print(f"  {r.get('summary', '없음')}")
    print(f"\n{'='*60}\n")
    
    # CSV 저장 — 가게(폴더명 앞부분)별로 파일 분리
    # 예: '가게A 홍길동' → 가게명 '가게A' → '가게A_노출결과_20260502_085215.csv'
    if len(all_results) >= 1:
        import csv
        from collections import defaultdict

        def _resolve_business(r: dict) -> str:
            """
            결과 dict에서 가게명(체험명) 추출.

            우선순위:
            1. business_name 필드 (CSV에서 명시적으로 지정한 경우)
            2. mode == 'blog' (단일 블로그 모드) → folder_name 그대로 사용
               (가게명 자동 추출하지 말 것 — 단일 블로그는 그대로 1개 파일)
            3. folder_name 앞부분 (스페이스/언더스코어 분리)
            4. folder_name 그대로
            """
            # 1순위: business_name 명시
            bn = (r.get("business_name") or "").strip()
            if bn:
                return bn

            folder = (r.get("folder_name") or "").strip()
            if not folder:
                return "기타"

            # 2순위: 단일 블로그 모드는 폴더명 그대로
            if (r.get("mode") or "").strip() == "blog":
                return folder

            # 3순위: folder_name에서 자동 추출 (가게별 기본 동작)
            for sep in ["_", " "]:
                if sep in folder:
                    return folder.split(sep, 1)[0].strip()
            return folder

        def _normalize_post_url(u: str) -> str:
            """매칭된 URL을 정규형으로 (캐시 키 일관성)."""
            bid, pno = extract_blog_id_and_post(u)
            if bid and pno:
                return f"https://blog.naver.com/{bid}/{pno}"
            return u

        # === 블로거별 → (매칭된 글 URL)별로 분할 ===
        # 한 블로거가 입력으로 홈 URL을 줬을 때, 키워드마다 서로 다른 글에 매칭될 수 있음.
        # CSV는 (블로거, 매칭 URL) 단위로 1행씩 발행 → 작성월별 보고서가 정확히 분리됨.
        #
        # rows_for_csv: list of dict {
        #   "business", "folder_name", "campaign", "mode",
        #   "post_url" (정규형, 매칭 결과), "keyword_results" (해당 url로 매칭된 키워드 결과들),
        #   "checked_at", "input_url"
        # }
        rows_for_csv: list[dict] = []
        for r in all_results:
            business = _resolve_business(r)
            kw_results = r.get("results", []) or []
            input_url = (r.get("url") or "").strip()

            # 키워드별 매칭 URL로 그룹핑
            by_matched: dict[str, list[dict]] = defaultdict(list)
            unmatched: list[dict] = []
            for kr in kw_results:
                m_url = (kr.get("matched_url") or "").strip()
                if m_url:
                    by_matched[_normalize_post_url(m_url)].append(kr)
                else:
                    unmatched.append(kr)

            # 매칭된 글 URL별로 1행씩
            for post_url, krs in by_matched.items():
                rows_for_csv.append({
                    "business": business,
                    "folder_name": r.get("folder_name", ""),
                    "campaign": r.get("campaign", ""),
                    "mode": r.get("mode", ""),
                    "month": r.get("month", ""),
                    "post_url": post_url,
                    "keyword_results": krs,
                    "checked_at": r.get("checked_at", ""),
                    "input_url": input_url,
                })

            # 매칭된 게 하나도 없으면 입력 URL을 그대로 1행 (legacy 동작 — '결과 요약: 없음/없음')
            if not by_matched:
                # 입력이 글 URL이면 그것을, 홈 URL이면 정규형 못 만드므로 입력 그대로
                fallback_url = (
                    _normalize_post_url(input_url) if extract_blog_id_and_post(input_url)[1]
                    else input_url
                )
                rows_for_csv.append({
                    "business": business,
                    "folder_name": r.get("folder_name", ""),
                    "campaign": r.get("campaign", ""),
                    "mode": r.get("mode", ""),
                    "month": r.get("month", ""),
                    "post_url": fallback_url,
                    "keyword_results": unmatched,  # 매칭 실패 키워드들 (요약은 '없음')
                    "checked_at": r.get("checked_at", ""),
                    "input_url": input_url,
                })

        # === 포스트 작성일자/제목 메타 추출 (매칭된 실제 글 URL 기준) ===
        post_meta: dict[str, dict] = {}
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "src" / "monthly_report"))
            # run()이 이미 async 컨텍스트이므로 동기 래퍼(extract_many_sync→asyncio.run)는
            # "cannot be called from a running event loop" 에러가 난다. async 함수를 직접 await.
            from blog_meta import extract_many  # type: ignore

            import json as _json
            meta_cache_path = PROJECT_ROOT / "output" / ".blog_meta_cache.json"
            existing_cache: dict = {}
            if meta_cache_path.exists():
                try:
                    existing_cache = _json.loads(meta_cache_path.read_text(encoding="utf-8"))
                except Exception:
                    existing_cache = {}

            urls_to_fetch: list[str] = []
            for row in rows_for_csv:
                pu = row["post_url"]
                bid, pno = extract_blog_id_and_post(pu)
                if not bid or not pno:
                    continue  # 매칭 실패 → 글 URL 아님 → 스킵
                cached = existing_cache.get(pu, {}) or {}
                if cached.get("manual") or cached.get("date"):
                    post_meta[pu] = cached
                    continue
                urls_to_fetch.append(pu)

            if urls_to_fetch:
                print(f"\n📥 포스트 메타 추출 중... ({len(set(urls_to_fetch))}건)")
                new_meta = await extract_many(list(set(urls_to_fetch)), headless=True)
                for u, m in new_meta.items():
                    if existing_cache.get(u, {}).get("manual"):
                        continue
                    existing_cache[u] = m
                try:
                    meta_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    meta_cache_path.write_text(
                        _json.dumps(existing_cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            for row in rows_for_csv:
                post_meta[row["post_url"]] = existing_cache.get(row["post_url"], {}) or {}
        except Exception as e:
            print(f"⚠️ 포스트 메타 추출 스킵: {e}")

        # === 가게별로 CSV 분리 발행 ===
        by_business: dict[str, list[dict]] = defaultdict(list)
        for row in rows_for_csv:
            by_business[row["business"]].append(row)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_paths = []
        for business, items in by_business.items():
            # 파일명은 NFC로 정규화 (macOS에서 NFD로 저장되면 한글 glob이 못 찾음)
            safe_business = unicodedata.normalize("NFC", business)
            output_path = output_dir / f"{safe_business}_노출결과_{timestamp}.csv"
            with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                # 신형 컬럼: 체험명/폴더명/월/캠페인/모드/입력URL/포스트 URL/작성일자/제목/결과 요약/확인일시
                writer.writerow([
                    "체험명", "폴더명", "월", "캠페인", "모드",
                    "입력 URL", "포스트 URL", "작성일자", "제목",
                    "결과 요약", "확인일시",
                ])
                for row in items:
                    summary = format_sheet_summary(row["keyword_results"])
                    meta = post_meta.get(row["post_url"], {}) or {}
                    m = normalize_month(row.get("month", ""))
                    month_label = f"{m}월" if m else ""
                    writer.writerow([
                        business,
                        row["folder_name"],
                        month_label,
                        row["campaign"],
                        row["mode"],
                        row.get("input_url", ""),
                        row["post_url"],
                        meta.get("date", ""),
                        meta.get("title", ""),
                        summary,
                        row["checked_at"],
                    ])
            saved_paths.append(output_path)
            print(f"✅ [{business}] 결과 CSV 저장: {output_path.name} ({len(items)}건)")
        print()

    return all_results


def parse_bloggers_arg(urls_arg: str, names_arg: str) -> list[tuple[str, str]]:
    """
    --urls와 --folder-names를 파싱해서 [(url, folder_name), ...] 반환.
    
    구분자: 세미콜론(;) 또는 줄바꿈
    """
    urls = [u.strip() for u in re.split(r"[;\n]+", urls_arg) if u.strip()]
    names = [n.strip() for n in re.split(r"[;\n]+", names_arg) if n.strip()]
    
    if len(urls) != len(names):
        raise ValueError(
            f"URL 개수({len(urls)})와 폴더명 개수({len(names)})가 일치하지 않습니다.\n"
            f"  URLs: {urls}\n"
            f"  Names: {names}"
        )
    
    return list(zip(urls, names))


def _read_csv_with_encoding(csv_path: Path) -> str:
    """
    CSV 파일을 여러 인코딩으로 시도하며 텍스트로 읽기.
    
    한국 환경에서 자주 만나는 인코딩들을 우선순위대로 시도:
    1. UTF-8 with BOM (Excel for Mac, Google Sheets 다운로드)
    2. UTF-8 (표준)
    3. CP949 (Windows Excel 한국어 — 가장 흔한 깨짐 원인)
    4. EUC-KR (구형 한국어 인코딩)
    """
    encodings_to_try = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    last_error = None
    
    with open(csv_path, "rb") as f:
        data = f.read()
    
    for encoding in encodings_to_try:
        try:
            text = data.decode(encoding)
            if encoding != "utf-8-sig" and encoding != "utf-8":
                print(f"💡 CSV 인코딩 자동 감지: {encoding}")
                print(f"   (UTF-8로 다시 저장하시면 더 빠르게 처리됩니다)")
            return text
        except UnicodeDecodeError as e:
            last_error = e
            continue
    
    raise UnicodeDecodeError(
        "utf-8", b"", 0, 1,
        f"CSV 파일 인코딩을 인식할 수 없습니다. UTF-8로 저장해주세요. (시도한 인코딩: {encodings_to_try})"
    )


def excel_to_csv(excel_path: Path) -> Path:
    """Excel(.xls/.xlsx) 첫 시트를 숨김 폴더(output/.run_inputs)의 CSV로 변환해 경로 반환.

    Streamlit 검수 페이지의 엑셀 업로드와 같은 방식(첫 줄=헤더, 모든 값 문자열).
    .xls는 xlrd, .xlsx는 openpyxl 사용.
    """
    import pandas as pd

    engine = "openpyxl" if excel_path.suffix.lower() == ".xlsx" else "xlrd"
    df = pd.read_excel(excel_path, dtype=str, engine=engine).fillna("")
    df.columns = [str(c).strip() for c in df.columns]
    out_dir = Path(__file__).resolve().parent.parent.parent / "output" / ".run_inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load_csv_input(csv_path: Path) -> list[dict]:
    """
    CSV에서 블로거 리스트 로드.
    
    필수 컬럼: folder_name, url, keywords
    선택 컬럼:
    - business_name: 체험명/가게명 (예: '가게A', '가게B'). 결과 CSV 파일명에 사용됨.
                    없으면 폴더명 앞부분에서 자동 추출.
    - campaign: 종류 라벨 (restaurant/skin 등). 스크린샷 폴더 분류용.
    - mode: 'business'(가게별) 또는 'blog'(단일 블로그). 없으면 'business'.
    - month: 모집·마케팅 월 (예: 5, 5월). 결과 CSV '월' 컬럼 + 스크린샷 폴더('N월 폴더명').
    """
    import csv
    import io
    
    text = _read_csv_with_encoding(csv_path)
    reader = csv.DictReader(io.StringIO(text))
    
    bloggers = []
    for i, row in enumerate(reader, start=2):  # 1행은 헤더
        # 빈 행 스킵
        if not any((v or "").strip() for v in row.values()):
            continue
        
        # 필수 필드 검증
        url = (row.get("url") or "").strip()
        folder_name = (row.get("folder_name") or "").strip()
        keywords_raw = (row.get("keywords") or "").strip()
        row_mode = (row.get("mode") or "business").strip() or "business"
        store_name = (row.get("store_name") or "").strip()
        business_name = (row.get("business_name") or "").strip()

        if row_mode == "store":
            # 가게명 모드: url 불필요. 가게명(store_name 또는 business_name) + 폴더 + 키워드 필요.
            if not (store_name or business_name) or not folder_name or not keywords_raw:
                print(f"⚠️  CSV {i}행: 가게명 모드 필수(가게명/folder_name/keywords) 누락 — 스킵")
                continue
        else:
            if not url or not folder_name or not keywords_raw:
                print(f"⚠️  CSV {i}행: 필수 필드(folder_name, url, keywords) 누락 — 스킵")
                continue

        bloggers.append({
            "url": url,
            "folder_name": folder_name,
            "business_name": business_name,
            "store_name": store_name,
            "campaign": (row.get("campaign") or "general").strip() or "general",
            "keywords": [k.strip() for k in keywords_raw.split(",") if k.strip()],
            # 검수 모드 ('business' / 'blog' / 'store'). CSV에 없으면 'business'.
            "mode": row_mode,
            # 모집·마케팅 월 (선택). 결과 CSV·스크린샷 폴더에 'N월'로 기록.
            "month": (row.get("month") or "").strip(),
        })
    
    return bloggers


def main():
    parser = argparse.ArgumentParser(
        description="네이버 블로그 포스팅 상위노출 자동 확인 (1명 또는 여러 명 일괄)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:

  [1] 한 명 검수
    python checker.py \\
      --urls "https://blog.naver.com/aaa/123" \\
      --folder-names "가게A_홍길동" \\
      --keywords "둔산동 회식,대전 가성비 맛집"
      # --campaign 생략 가능 (스크린샷 폴더 분류용 라벨일 뿐)

  [2] 여러 명 같은 키워드로 한꺼번에 (URL과 폴더명을 ; 으로 구분)
    python checker.py \\
      --urls "https://blog.naver.com/aaa/111;https://blog.naver.com/bbb/222;https://blog.naver.com/ccc/333" \\
      --folder-names "가게A_홍길동;가게A_김영희;가게A_박철수" \\
      --keywords "둔산동 회식,대전 가성비 맛집" \\
      --campaign restaurant

  [3] CSV 파일로 여러 명 처리 (캠페인·키워드도 다양하게)
    python checker.py --input bloggers.csv

    CSV 형식 (campaign 컬럼은 선택사항):
        folder_name,url,campaign,keywords
        가게A_홍길동,https://blog.naver.com/aaa/111,restaurant,"둔산동 회식,대전 가성비 맛집"
        가게B_김영희_얼굴전체,https://blog.naver.com/bbb/222,skin,"강남 리투오,신논현역 성형외과"
    
    💡 CSV 인코딩은 UTF-8 권장. CP949(Windows Excel)도 자동 처리됩니다.
        """
    )
    
    # 입력 방식 1: --urls + --folder-names (+ 공통 keywords/campaign)
    parser.add_argument("--urls", help="블로그 포스팅 URL (여러 개는 ; 으로 구분)")
    parser.add_argument("--folder-names", help="스크린샷 저장 폴더명 (여러 개는 ; 으로 구분)")
    parser.add_argument("--keywords", help="키워드 (콤마 구분, 모든 블로거에 공통 적용)")
    parser.add_argument(
        "--campaign",
        default="general",
        help="캠페인 이름 (스크린샷 폴더 분류용, 자유 입력. 예: restaurant, skin, cafe 등). "
             "생략 시 'general' 사용."
    )
    parser.add_argument(
        "--month",
        default="",
        help="모집·마케팅 월 (예: 5 또는 5월). 결과 CSV의 '월' 컬럼과 "
             "스크린샷 폴더명('N월 폴더명')에 사용. 생략 가능."
    )
    
    # 입력 방식 2: CSV 파일
    parser.add_argument("--input", help="CSV 또는 Excel(.xls/.xlsx) 파일 경로 (블로거별로 다른 캠페인·키워드 가능)")
    
    # 공통 옵션
    parser.add_argument("--headless", action="store_true", help="브라우저 창 숨기기 (병렬 처리 가능)")
    parser.add_argument("--debug", action="store_true", help="디버그 정보 출력")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="동시 처리할 블로거 수 (기본 3, 최대 5). --debug 또는 --headless 미사용 시 자동 1"
    )
    
    args = parser.parse_args()
    
    # 입력 방식 분기
    if args.input:
        # CSV 모드
        csv_path = Path(args.input)
        if not csv_path.exists():
            print(f"❌ CSV 파일을 찾을 수 없습니다: {csv_path}")
            sys.exit(1)
        if csv_path.suffix.lower() in (".xls", ".xlsx"):
            csv_path = excel_to_csv(csv_path)
        bloggers = load_csv_input(csv_path)
        print(f"📄 CSV에서 {len(bloggers)}명 로드: {csv_path}")
    
    elif args.urls and args.folder_names and args.keywords:
        # 명령줄 다중 모드 (campaign은 선택사항, 기본값 'general')
        try:
            url_name_pairs = parse_bloggers_arg(args.urls, args.folder_names)
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)
        
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        bloggers = [
            {
                "url": url,
                "campaign": args.campaign,
                "folder_name": name,
                "keywords": keywords,
                "month": args.month or "",
            }
            for url, name in url_name_pairs
        ]
    
    else:
        parser.print_help()
        print("\n❌ 필수 인자가 부족합니다.")
        print("   방식 1: --urls, --folder-names, --keywords 모두 필요 (--campaign은 선택)")
        print("   방식 2: --input <CSV파일>")
        sys.exit(1)
    
    asyncio.run(run(
        bloggers=bloggers,
        headless=args.headless,
        debug=args.debug,
        concurrency=args.concurrency,
    ))


if __name__ == "__main__":
    main()
