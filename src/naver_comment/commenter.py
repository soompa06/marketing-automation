"""
네이버 블로그탭 모집 비밀댓글 자동 작성 엔진

흐름:
1. 네이버 검색 → 블로그탭에서 키워드별 1~20위 포스팅(블로거) 수집
2. 각 블로거에 대해:
   - 블로거(blogId) 단위로 3개월 이내 이미 댓글 달았으면 건너뜀
   - 비밀댓글로 모집 문구 작성
   - 댓글창이 없거나(작성 불가) 차단된 경우 안전하게 건너뜀
3. 진행 상황을 콘솔로 출력 + 이력 저장(UI 실시간 표시)

⚠️ 사람처럼:
- 댓글 사이에 2~5분(설정값) 랜덤 대기
- 한 글자씩 랜덤 속도로 타이핑
- 회당/하루 한도 적용
→ 네이버 스팸/로봇 차단 회피

⚠️ 네이버 댓글창(cbox) DOM은 자주 바뀝니다. 셀렉터가 안 맞으면
   --show-browser 로 실행해 확인 후 SELECTOR 목록 상단에 추가하세요
   (기존 셀렉터는 호환성 위해 유지).
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naver_session import get_logged_in_context, DEFAULT_USER  # noqa: E402
import history_store as hist  # noqa: E402
import templates_store as tmpl  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 댓글 입력창 / 비밀 체크 / 등록 버튼 셀렉터 후보 (위에서부터 우선)
# ⚠️ 네이버 모바일 블로그는 입력창이 textarea가 아니라 contenteditable DIV임
#    (id=naverComment__write_textarea, class=u_cbox_text). 셀렉터 변경 시 상단에 추가.
COMMENT_TEXT_SELECTORS = [
    "#naverComment__write_textarea",
    "div.u_cbox_text[contenteditable='true']",
    "div.u_cbox_text",
    "textarea.u_cbox_text",
    ".u_cbox_inbox textarea",
    ".u_cbox_write_area textarea",
]
SUBMIT_SELECTORS = [
    "button.u_cbox_btn_upload",
    ".u_cbox_btn_upload",
    "a.u_cbox_btn_upload",
]
# 댓글 영역을 펼치는 버튼 — 새 모바일 레이아웃은 해시 클래스(comment_btn__xxxx)라 prefix 매칭
OPEN_COMMENT_SELECTORS = [
    'button[class*="comment_btn"]',
    'a[class*="comment_btn"]',
    'div[class*="comment_area"] button',
    "button:has-text('댓글')",
    "a.btn_comment",
    "button.u_cbox_btn_view_comment",
]


def _rand(a: float, b: float) -> float:
    return random.uniform(a, b)


async def _human_pause(a: float, b: float) -> None:
    await asyncio.sleep(_rand(a, b))


# 자연스럽게 매 댓글마다 조금씩 달라 보이도록 — 동일 문구 대량 작성을
# 도배로 인식하고 삭제하는 패턴을 줄인다. 본문 내용은 그대로 유지.
_TAIL_VARIATIONS = [
    "\n\n잘 보고 갑니다 :)",
    "\n\n좋은 정보 감사합니다!",
    "\n\n응원합니다 ~",
    "\n\n좋은 하루 되세요!",
    "\n\n잘 읽고 갑니다 ☺",
    "\n\n포스팅 잘 봤어요 ~",
    "\n\n수고하셨어요!",
    "",  # 가끔은 변형 없음
]


def humanize_message(base: str, salt: str = "") -> str:
    """
    동일 문구 반복으로 인한 도배 판정/삭제를 줄이기 위해
    끝에 가벼운 자연스러운 한 줄을 덧붙인다. salt(블로거 id 등)로 안정적 변형.
    """
    if not base:
        return base
    # salt가 있으면 deterministic(같은 블로거는 같은 변형) → 매번 바뀌어 의심 사는 거 방지
    if salt:
        idx = sum(ord(c) for c in salt) % len(_TAIL_VARIATIONS)
    else:
        idx = random.randrange(len(_TAIL_VARIATIONS))
    tail = _TAIL_VARIATIONS[idx]
    return base.rstrip() + tail


async def _editor_text_len(page) -> int:
    try:
        return await page.evaluate("""() => {
            const el = document.querySelector('#naverComment__write_textarea')
                    || document.querySelector("div.u_cbox_text[contenteditable='true']")
                    || document.querySelector("textarea.u_cbox_text");
            return el ? (el.innerText || el.value || '').trim().length : 0;
        }""")
    except Exception:
        return 0


async def _focus_editor(page, text_loc=None):
    """입력창에 실제 클릭으로 포커스."""
    try:
        if text_loc is not None:
            await text_loc.click(timeout=3000)
        else:
            await page.click("#naverComment__write_textarea", timeout=3000)
        return True
    except Exception:
        try:
            await page.evaluate("""() => {
                const el = document.querySelector('#naverComment__write_textarea')
                        || document.querySelector("div.u_cbox_text[contenteditable='true']");
                if (el) el.focus();
            }""")
            return True
        except Exception:
            return False


async def _clear_editor(page, mod):
    """기존 내용 비우기 (실제 키: 전체선택 후 삭제)."""
    try:
        await page.keyboard.press(f"{mod}+A")
        await asyncio.sleep(_rand(0.05, 0.15))
        await page.keyboard.press("Backspace")
        await asyncio.sleep(_rand(0.1, 0.25))
    except Exception:
        pass


async def human_type(page, message: str, text_loc=None) -> bool:
    """
    Naver cbox에 사용자가 한 방식 그대로 — '실제 클립보드 붙여넣기(Cmd/Ctrl+V)'로 입력.

    ⚠️ 핵심: execCommand/innerText 주입은 신뢰되지 않은 입력이라 네이버 어뷰징
       탐지가 '봇'으로 보고 삭제/차단했다. 사용자는 '복사-붙여넣기'로 달아도
       삭제되지 않았으므로, 동일하게 OS 클립보드에 복사 후 진짜 Cmd/Ctrl+V 를
       눌러 trusted paste 이벤트를 발생시킨다.
       (붙여넣기 실패 시 한 글자 타이핑 → 그래도 안 되면 JS 주입 순으로 폴백)

    Returns: 입력 성공(본문 길이>0).
    """
    import sys as _sys
    mod = "Meta" if _sys.platform == "darwin" else "Control"

    # 1) 포커스 + 비우기
    await _focus_editor(page, text_loc)
    await asyncio.sleep(_rand(0.3, 0.7))
    await _clear_editor(page, mod)

    # 2) 실제 클립보드 붙여넣기 (사용자가 한 방식)
    pasted = False
    try:
        import pyperclip
        pyperclip.copy(message)
        await asyncio.sleep(_rand(0.2, 0.5))
        await page.keyboard.press(f"{mod}+V")
        await asyncio.sleep(_rand(0.6, 1.2))
        if (await _editor_text_len(page)) > 0:
            pasted = True
    except Exception:
        pasted = False

    # 2-b) pyperclip이 안 되는 환경이면 브라우저 clipboard API로 붙여넣기 시도
    if not pasted:
        try:
            await page.evaluate("(t) => navigator.clipboard.writeText(t)", message)
            await asyncio.sleep(_rand(0.2, 0.4))
            await _focus_editor(page, text_loc)
            await page.keyboard.press(f"{mod}+V")
            await asyncio.sleep(_rand(0.6, 1.2))
            if (await _editor_text_len(page)) > 0:
                pasted = True
        except Exception:
            pasted = False

    if pasted:
        await asyncio.sleep(_rand(0.3, 0.7))
        return True

    # 3) 폴백: 한 글자씩 키보드 타이핑 (줄바꿈은 Shift+Enter)
    await _focus_editor(page, text_loc)
    await _clear_editor(page, mod)
    lines = message.split("\n")
    for li, line in enumerate(lines):
        if li > 0:
            await page.keyboard.down("Shift")
            await page.keyboard.press("Enter")
            await page.keyboard.up("Shift")
            await asyncio.sleep(_rand(0.08, 0.25))
        for ch in line:
            await page.keyboard.type(ch)
            await asyncio.sleep(_rand(0.04, 0.16))
            if random.random() < 0.06:
                await asyncio.sleep(_rand(0.4, 1.1))

    await asyncio.sleep(_rand(0.3, 0.7))
    return (await _editor_text_len(page)) > 0


async def _force_set_text(page, message: str) -> bool:
    """
    JS 폴백: contenteditable/textarea에 텍스트를 강제 입력.
    네이버 cbox는 React 기반이라 innerText 직접 세팅은 무시될 수 있어
    document.execCommand('insertText')로 '사용자가 타이핑한 것처럼' 넣는다.

    Returns: 입력 후 본문 길이>0 이면 True.
    """
    try:
        ok = await page.evaluate("""(msg) => {
            const el = document.querySelector('#naverComment__write_textarea')
                    || document.querySelector("div.u_cbox_text[contenteditable='true']");
            if (!el) return false;
            el.focus();
            try { el.click(); } catch(e) {}

            // textarea/input은 native setter로 set + input 이벤트 (React용)
            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                const proto = el.tagName === 'TEXTAREA'
                    ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                setter.call(el, msg);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            } else {
                // contenteditable: execCommand가 가장 호환성 좋다 (React/Vue 컨트롤 입력도 인식)
                // 기존 내용 비우기
                el.innerText = '';
                el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'deleteContentBackward'}));
                let inserted = false;
                try {
                    inserted = document.execCommand('insertText', false, msg);
                } catch (e) {}
                if (!inserted || !(el.innerText || '').trim()) {
                    // 최후 수단: innerText 직접 + InputEvent
                    el.innerText = msg;
                    el.dispatchEvent(new InputEvent('input', {
                        bubbles: true, inputType: 'insertText', data: msg
                    }));
                }
            }
            const txt = (el.innerText || el.value || '').trim();
            return txt.length > 0;
        }""", message)
        return bool(ok)
    except Exception:
        return False


async def _find_in_page_or_frames(page, selectors: list[str]):
    """본문 또는 iframe들에서 셀렉터 후보를 순서대로 찾아 (locator, frame) 반환."""
    contexts = [page] + list(page.frames)
    for sel in selectors:
        for ctx in contexts:
            try:
                loc = ctx.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible(timeout=600):
                    return loc, ctx
            except Exception:
                continue
    return None, None


async def _ensure_secret_on(page) -> bool:
    """
    '비밀댓글'을 켜고 실제로 켜졌는지 검증해서 반환.

    네이버 cbox 비밀 체크박스는 커스텀 스타일이고, 작성 툴바가 펼쳐져야 보인다.
    툴바를 펼치려면 입력창을 '실제 마우스 클릭'해야 하는 경우가 있다.
    그래서 (1) Playwright 클릭으로 툴바를 펼치고 (2) 라벨/체크박스를 클릭한다.
    이미 켜져 있으면 토글하지 않는다.
    """
    async def _state() -> bool | None:
        try:
            return await page.evaluate(
                "() => { const c = document.querySelector('input.u_cbox_secret_check');"
                " return c ? !!c.checked : null; }"
            )
        except Exception:
            return None

    if (await _state()) is True:
        return True

    # 1) 입력창을 진짜 클릭해서 작성 툴바를 펼침 (비밀 옵션 노출)
    for sel in ("#naverComment__write_textarea", "div.u_cbox_text[contenteditable='true']"):
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(timeout=2000, force=True)
                break
        except Exception:
            continue
    await page.wait_for_timeout(400)

    # 2) 라벨 Playwright 클릭(force) → JS 라벨 클릭 → 체크박스 JS 클릭 순서로 시도
    methods = [
        ("playwright label click",
         lambda: page.locator("label.u_cbox_secret_label").first.click(timeout=2000, force=True)),
        ("js label click", lambda: page.evaluate(
            "() => { const l = document.querySelector('label.u_cbox_secret_label'); if (l) l.click(); }")),
        ("playwright checkbox click", lambda: page.locator(
            "input.u_cbox_secret_check").first.click(timeout=2000, force=True)),
        ("js checkbox click", lambda: page.evaluate(
            "() => { const c = document.querySelector('input.u_cbox_secret_check'); if (c) c.click(); }")),
    ]
    for name, action in methods:
        try:
            await action()
        except Exception:
            pass
        await page.wait_for_timeout(350)
        if (await _state()) is True:
            return True
    return False


# =============================================================================
# 블로그탭 1~20위 수집
# =============================================================================

_ENUM_JS = """
    (topN) => {
        const links = document.querySelectorAll('a[href*="blog.naver.com"]');
        const seen = new Set();
        const ranked = [];
        for (const link of links) {
            const href = link.href || '';
            if (/\\/clip\\/\\d+/.test(href)) continue;  // 클립 영상 제외
            let blogId = '', postNo = '';
            const bv = href.match(/blogId=([^&]+)/);
            const ln = href.match(/logNo=(\\d+)/);
            if (bv && ln) { blogId = bv[1]; postNo = ln[1]; }
            else {
                const m = href.match(/blog\\.naver\\.com\\/([^\\/\\?]+)\\/(\\d+)/);
                if (m) { blogId = m[1]; postNo = m[2]; }
            }
            if (!blogId || !postNo) continue;
            if (blogId === 'MyBlog.naver') continue;
            const r = link.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue;  // 보이는 것만
            if (seen.has(blogId)) continue;                 // 블로거당 1개
            seen.add(blogId);
            ranked.push({ rank: ranked.length + 1, blogId, postNo });
            if (ranked.length >= topN) break;
        }
        return ranked;
    }
"""


async def enumerate_blog_tab(page, keyword: str, top_n: int = 20) -> list[dict]:
    """키워드의 블로그탭 상위 top_n 블로거 수집 → [{rank, blog_id, post_no, url}]."""
    url = (
        "https://search.naver.com/search.naver"
        f"?ssc=tab.blog.all&sm=tab_jum&query={quote(keyword)}"
    )
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await _human_pause(0.6, 1.2)
    # 결과를 충분히 로드 (사람처럼 스크롤)
    for _ in range(6):
        cur = await page.evaluate(_ENUM_JS, top_n)
        if len(cur) >= top_n:
            break
        await page.mouse.wheel(0, random.randint(700, 1100))
        await _human_pause(0.4, 0.9)
    raw = await page.evaluate(_ENUM_JS, top_n)
    out = []
    for e in raw:
        out.append({
            "rank": e["rank"],
            "blog_id": e["blogId"],
            "post_no": e["postNo"],
            # 댓글 작성은 모바일 페이지가 더 안정적
            "url": f"https://m.blog.naver.com/{e['blogId']}/{e['postNo']}",
        })
    return out


# =============================================================================
# 비밀댓글 작성
# =============================================================================

async def post_secret_comment(page, post_url: str, message: str) -> dict:
    """
    한 포스팅에 비밀댓글 작성.

    Returns: {"status": ..., "detail": ...}
      status:
        success         - 작성 성공
        no_comment_box  - 댓글창 없음(댓글 버튼 없음/막힘)
        blocked         - 차단/권한없음/스팸 경고 등
        error           - 기타 오류
    """
    result = {"status": "error", "detail": ""}

    # 네이버가 띄우는 alert/confirm(스팸 경고 등) 자동 감지 + 내용 캡처
    dialog_msgs: list[str] = []

    def _on_dialog(dialog):
        dialog_msgs.append(dialog.message or "")
        try:
            asyncio.create_task(dialog.dismiss())
        except Exception:
            pass

    page.on("dialog", _on_dialog)

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await _human_pause(2.0, 4.0)

        # === 사람처럼 본문 읽기 (총 15~40초) ===
        # 페이지 진입 → 즉시 댓글은 자동화 패턴이라 도배·삭제 위험.
        # 실제 사용자처럼 스크롤·일시정지를 섞어 본문을 '읽는' 듯한 시간을 보낸다.
        scroll_passes = random.randint(6, 12)
        for i in range(scroll_passes):
            # 가끔은 조금 위로도 스크롤 (다시 보기) → 더 사람스러움
            if i > 2 and random.random() < 0.15:
                await page.mouse.wheel(0, -random.randint(200, 500))
                await _human_pause(0.6, 1.6)
            await page.mouse.wheel(0, random.randint(400, 900))
            # 가끔 본문을 '읽느라' 길게 머무름 (3~7초)
            if random.random() < 0.3:
                await _human_pause(3.0, 7.0)
            else:
                await _human_pause(0.8, 2.0)

        # 댓글 영역 펼치기 — 새 모바일 레이아웃은 '댓글' 버튼을 눌러야 입력창이 생김
        open_loc, _ = await _find_in_page_or_frames(page, OPEN_COMMENT_SELECTORS)
        if open_loc:
            try:
                await open_loc.click(timeout=3000)
                await _human_pause(1.2, 2.2)
            except Exception:
                pass

        # 입력창(contenteditable)이 뜰 때까지 잠깐 대기
        try:
            await page.wait_for_selector(
                "#naverComment__write_textarea, div.u_cbox_text[contenteditable='true']",
                timeout=6000, state="visible",
            )
        except Exception:
            pass

        # cbox(댓글 서비스)에서 로그아웃 상태로 보이면 작성 불가 — 세션 만료.
        # (네이버 메인은 로그인 상태여도 댓글 서비스 세션은 별도로 만료될 수 있음)
        try:
            logged_out = await page.evaluate("""() => {
                const wb = document.querySelector('.u_cbox_write_box, .u_cbox_write_wrap');
                if (!wb) return false;
                const cls = (wb.className || '').toString();
                const txt = (wb.innerText || '');
                return /type_logged_out|로그인\\s*해주세요/.test(cls + ' ' + txt);
            }""")
        except Exception:
            logged_out = False
        if logged_out:
            result.update(status="error",
                          detail="댓글 서비스 세션이 만료됐습니다. 다채구 계정으로 다시 로그인해주세요 (네이버 로그인 창 열기).")
            return result

        # 댓글 입력창 찾기
        text_loc, ctx = await _find_in_page_or_frames(page, COMMENT_TEXT_SELECTORS)
        if not text_loc:
            # 한 번 더 펼치기 시도 후 재탐색
            open_loc, _ = await _find_in_page_or_frames(page, OPEN_COMMENT_SELECTORS)
            if open_loc:
                try:
                    await open_loc.click(timeout=2500)
                    await _human_pause(1.0, 1.8)
                except Exception:
                    pass
            text_loc, ctx = await _find_in_page_or_frames(page, COMMENT_TEXT_SELECTORS)

        if not text_loc:
            result.update(status="no_comment_box",
                          detail="댓글 입력창을 찾지 못함(댓글 비허용/구조 변경 가능)")
            return result

        # 입력창에 포커스 — 스크롤 후 강제 클릭, 안 되면 JS focus 폴백
        # (contenteditable DIV라 일반 클릭이 '보임/안정' 체크에서 막히는 경우가 있음)
        try:
            await text_loc.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        focused = False
        try:
            await text_loc.click(timeout=3000, force=True)
            focused = True
        except Exception:
            try:
                await page.evaluate("""() => {
                    const el = document.querySelector('#naverComment__write_textarea')
                            || document.querySelector("div.u_cbox_text[contenteditable='true']");
                    if (el) el.focus();
                }""")
                focused = True
            except Exception:
                pass
        if not focused:
            result.update(status="no_comment_box", detail="입력창 포커스 실패")
            return result

        await _human_pause(0.5, 1.1)
        # 진짜 키보드 타이핑 (사람처럼) — 봇 탐지/삭제 회피의 핵심.
        typed_ok = await human_type(page, message, text_loc=text_loc)
        if not typed_ok:
            # 키 입력이 끝내 안 먹으면, 한 번 더 클릭 후 재시도
            try:
                await text_loc.click(timeout=2000)
            except Exception:
                pass
            await _human_pause(0.3, 0.7)
            typed_ok = await human_type(page, message, text_loc=text_loc)
        if not typed_ok:
            # 마지막 수단(JS 주입) — 입력은 되지만 봇 탐지로 삭제될 수 있어 경고.
            print("      ⚠️ 키보드 입력 실패 → JS 주입 폴백(삭제 위험 있음)", flush=True)
            await _force_set_text(page, message)
            typed_ok = (await _editor_text_len(page)) > 0
        if not typed_ok:
            result.update(status="error", detail="본문 입력이 반영되지 않음(포커스/입력 실패)")
            return result
        await _human_pause(0.5, 1.0)

        # 비밀댓글 켜기 + 실제로 켜졌는지 검증 (핵심: 공개로 달리면 안 됨)
        if not await _ensure_secret_on(page):
            result.update(status="no_comment_box",
                          detail="비밀댓글 체크를 확인하지 못해 작성 중단(공개 방지)")
            return result
        await _human_pause(0.3, 0.8)

        # 등록 버튼
        submit_loc, _ = await _find_in_page_or_frames(page, SUBMIT_SELECTORS)
        if not submit_loc:
            result.update(status="no_comment_box", detail="등록 버튼을 찾지 못함")
            return result

        # 제출 전 잠깐 대기 — 사람은 '쓴 글을 한 번 더 읽고' 등록한다.
        # (즉시 등록은 자동화 패턴, 도배 판정·삭제 위험 증가)
        await _human_pause(4.0, 9.0)

        await submit_loc.click(timeout=3000)
        await _human_pause(1.5, 3.0)

        # 차단/스팸/권한 경고 감지
        blocked_words = ["차단", "권한", "스팸", "도배", "작성할 수 없", "등록할 수 없",
                         "이용이 제한", "잠시 후", "비정상"]
        joined = " ".join(dialog_msgs)
        if any(w in joined for w in blocked_words):
            result.update(status="blocked", detail=joined[:120])
            return result

        # 페이지 본문에도 경고 문구가 있는지 확인
        try:
            body_text = await page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body_text = ""
        if any(w in body_text for w in ["댓글 작성이 제한", "차단되어", "스팸으로"]):
            result.update(status="blocked", detail="페이지에 작성 제한 안내")
            return result

        result.update(status="success", detail=joined[:120])
        return result

    except Exception as e:
        result.update(status="error", detail=str(e)[:160])
        return result
    finally:
        try:
            page.remove_listener("dialog", _on_dialog)
        except Exception:
            pass


# =============================================================================
# 캠페인 실행
# =============================================================================

async def _open_account(account: str, headless: bool, use_chrome: bool = False):
    """
    작업용 컨텍스트+페이지 열기. 실패 시 None.

    use_chrome=True 면 사용자가 띄운 '진짜 Chrome'(CDP 9222)에 연결한다.
    (자동화 탐지 회피 — 댓글 사후 삭제 방지의 핵심)
    그 외엔 저장 세션(Playwright Chromium)을 사용.

    반환 handle: (p, browser, context, page, is_cdp)
    """
    if use_chrome:
        import chrome_cdp
        ct = await chrome_cdp.connect()
        if not ct:
            return None
        p, browser, context = ct
        if not await chrome_cdp.is_logged_in(context):
            print("❌ 연결된 Chrome 이 네이버 로그인 상태가 아닙니다. "
                  "그 Chrome 창에서 네이버에 로그인하세요.")
            await p.stop()
            return None
        page = await context.new_page()
        return p, browser, context, page, True

    ctx_tuple = await get_logged_in_context(headless=headless, user_name=account)
    if not ctx_tuple:
        return None
    p, browser, context = ctx_tuple
    page = await context.new_page()
    return p, browser, context, page, False


async def _close_account(handle) -> None:
    if not handle:
        return
    p, browser, context, page, is_cdp = handle
    try:
        if is_cdp:
            # 사용자 Chrome 은 닫지 않는다! 우리가 연 page 만 닫고 playwright 분리.
            try:
                await page.close()
            except Exception:
                pass
            await p.stop()
        else:
            await context.close()
            await browser.close()
            await p.stop()
    except Exception:
        pass


async def run(
    keywords: list[str],
    accounts: list[str],
    top_n: int = 20,
    dedup_days: int = 90,
    per_run_cap: int = 100,
    daily_cap: int = 60,
    per_account_cap: int = 50,
    min_delay: float = 120,
    max_delay: float = 300,
    headless: bool = True,
    use_chrome: bool = False,
) -> None:
    accounts = [a.strip() for a in accounts if a and a.strip()]
    if not accounts:
        print("❌ 사용할 계정이 없습니다.")
        return

    # CDP(실제 Chrome) 모드: 로그인된 그 Chrome 한 곳만 사용 → 계정 로테이션 없음
    if use_chrome:
        accounts = accounts[:1]

    print(f"\n📋 네이버 모집 비밀댓글 시작")
    if use_chrome:
        print(f"   모드: 🟢 실제 Chrome 연결(CDP) — 자동화 탐지 회피")
        print(f"   계정: {accounts[0]} (Chrome 로그인 계정)")
    else:
        print(f"   계정 {len(accounts)}개(로테이션): {', '.join(accounts)}")
    print(f"   키워드 {len(keywords)}개 / 블로그탭 상위 {top_n}")
    print(f"   계정당 {per_account_cap}건마다 교체 / 회당 총 {per_run_cap}건 / 계정별 하루 {daily_cap}건")
    print(f"   재방문 금지: {dedup_days}일(블로거 단위) / 댓글 간격 {min_delay:.0f}~{max_delay:.0f}초\n")

    # 첫 계정 컨텍스트 열기 (수집 + 첫 작성에 사용)
    acct_idx = 0
    handle = await _open_account(accounts[acct_idx], headless, use_chrome=use_chrome)
    if not handle:
        if use_chrome:
            print("❌ 실제 Chrome 연결 실패. 디버그 모드 Chrome 실행 + 네이버 로그인을 확인하세요.")
        else:
            print(f"❌ '{accounts[acct_idx]}' 세션이 없습니다. 먼저 로그인하세요.")
        return
    cur_account = accounts[acct_idx]
    run_count: dict[str, int] = {a: 0 for a in accounts}  # 이번 실행 계정별 작성 수
    posted_this_run = 0

    def _has_capacity(acct: str) -> bool:
        # 이번 실행 계정당 한도 + 계정별 하루 한도(과거 포함) 둘 다 만족해야 함
        if run_count.get(acct, 0) >= per_account_cap:
            return False
        if hist.count_on_day(account=acct) >= daily_cap:
            return False
        return True

    try:
        page = handle[3]

        # === 1) 작성 대상 수집 (계정 무관 — 검색 결과 동일) ===
        work: list[dict] = []
        seen_blog: set[str] = set()
        for keyword in keywords:
            keyword = keyword.strip()
            if not keyword:
                continue
            if not tmpl.get_message(keyword):
                print(f"⚠️ [{keyword}] 모집 문구가 없어 건너뜀 (기본/키워드 문구 등록 필요)")
                continue
            print(f"🔍 키워드 '{keyword}' — 블로그탭 상위 {top_n} 수집 중...")
            try:
                entries = await enumerate_blog_tab(page, keyword, top_n=top_n)
            except Exception as e:
                print(f"  ⚠️ 블로그탭 수집 실패: {e}")
                continue
            for e in entries:
                bid = e["blog_id"]
                if bid in seen_blog:
                    continue
                seen_blog.add(bid)
                if hist.was_commented_recently(bid, within_days=dedup_days):
                    print(f"  ⏭️  {bid} — 최근 {dedup_days}일 내 작성 → 건너뜀")
                    hist.record(cur_account, bid, e["url"], keyword,
                                "skipped_dedup", f"{dedup_days}일 내 중복")
                    continue
                e["keyword"] = keyword
                work.append(e)
        print(f"\n📝 작성 대상 {len(work)}명 (중복·최근작성 제외)\n")

        # === 2) 작성 (계정 로테이션) ===
        for e in work:
            if posted_this_run >= per_run_cap:
                print(f"\n🛑 회당 총 한도({per_run_cap}건) 도달 — 종료")
                break

            # 현재 계정이 한도 도달이면 여유 있는 다음 계정으로 교체
            # (CDP 모드는 단일 Chrome이라 로테이션 없음 — 한도 도달 시 종료)
            if not _has_capacity(cur_account):
                if use_chrome:
                    print(f"\n🛑 한도 도달 — 종료 (Chrome 모드는 단일 계정)")
                    break
                rotated = False
                for _ in range(len(accounts)):
                    acct_idx = (acct_idx + 1) % len(accounts)
                    nxt = accounts[acct_idx]
                    if _has_capacity(nxt):
                        print(f"\n🔄 '{cur_account}' 한도 도달 → '{nxt}' 계정으로 교체")
                        await _close_account(handle)
                        handle = await _open_account(nxt, headless)
                        if not handle:
                            print(f"  ⚠️ '{nxt}' 세션 열기 실패 — 다음 계정 시도")
                            continue
                        cur_account, page = nxt, handle[3]
                        rotated = True
                        break
                if not rotated:
                    print(f"\n🛑 모든 계정이 한도에 도달 — 종료")
                    break

            base_message = tmpl.get_message(e["keyword"])
            bid = e["blog_id"]
            # 매 댓글마다 가벼운 끝맺음 변형 — 동일 문구 반복으로 인한 도배 판정·삭제 완화.
            # salt=blog_id로 deterministic → 한 블로그에 대해선 일관 (의심 X), 블로그마다는 다름.
            message = humanize_message(base_message, salt=bid)
            print(f"  ✍️  [{cur_account}] {bid} (키워드 {e['keyword']}) 비밀댓글 시도...", flush=True)
            res = await post_secret_comment(page, e["url"], message)
            hist.record(cur_account, bid, e["url"], e["keyword"],
                        res["status"], res.get("detail", ""),
                        message_preview=message[:60])

            if res["status"] == "success":
                posted_this_run += 1
                run_count[cur_account] += 1
                print(f"      ✅ 작성 완료 (총 {posted_this_run} / {cur_account} {run_count[cur_account]}건)")
            elif res["status"] == "no_comment_box":
                print(f"      ⚠️ 댓글 작성 불가 → 건너뜀")
            elif res["status"] == "blocked":
                print(f"      🚫 차단/제한 → 건너뜀 ({res.get('detail','')})")
            else:
                print(f"      ❌ 오류 → 건너뜀 ({res.get('detail','')})")

            delay = _rand(min_delay, max_delay)
            print(f"      ⏳ 다음까지 {delay:.0f}초 대기...", flush=True)
            await asyncio.sleep(delay)

        print(f"\n🏁 완료 — 이번 실행 총 {posted_this_run}건 작성")
        for a in accounts:
            if run_count[a]:
                print(f"   · {a}: {run_count[a]}건")

    finally:
        await _close_account(handle)


def main():
    parser = argparse.ArgumentParser(description="네이버 블로그탭 모집 비밀댓글 작성")
    parser.add_argument("--keywords", required=True, help="키워드들 (쉼표 구분)")
    parser.add_argument("--accounts", help="네이버 계정 별칭들 (쉼표 구분, 순서대로 로테이션)")
    parser.add_argument("--account", default=DEFAULT_USER, help="(단일 계정) --accounts 없을 때 사용")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--dedup-days", type=int, default=90)
    parser.add_argument("--per-run", type=int, default=100, help="이번 실행 총 작성 한도")
    parser.add_argument("--per-account", type=int, default=50, help="계정당 몇 건 후 다음 계정으로 교체")
    parser.add_argument("--daily", type=int, default=60, help="계정별 하루 한도")
    parser.add_argument("--min-delay", type=float, default=120)
    parser.add_argument("--max-delay", type=float, default=300)
    parser.add_argument("--show-browser", action="store_true", help="브라우저 창 보기")
    parser.add_argument("--use-chrome", action="store_true",
                        help="실제 Chrome(CDP 9222)에 연결 — 자동화 탐지 회피(권장)")
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.accounts:
        accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    else:
        accounts = [args.account]
    asyncio.run(run(
        keywords=keywords,
        accounts=accounts,
        top_n=args.top_n,
        dedup_days=args.dedup_days,
        per_run_cap=args.per_run,
        daily_cap=args.daily,
        per_account_cap=args.per_account,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        headless=not args.show_browser,
        use_chrome=args.use_chrome,
    ))


if __name__ == "__main__":
    main()
