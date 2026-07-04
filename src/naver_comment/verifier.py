"""
달았던 비밀댓글이 아직 살아있는지(삭제됐는지) 검증.

흐름:
1. history_store에서 성공 기록 중 검증이 필요한 항목들을 가져옴
2. 각 항목의 post_url을 방문 (해당 계정 세션) — 비밀댓글은 작성자에게만 보임
3. 댓글 영역을 열고 모든 댓글을 로딩 → 우리 댓글이 있는지 확인
   - 우리 닉네임(예: 다채구→ekcorn) 또는 message_preview의 고유 토큰으로 매칭
4. 없으면 deleted_at 표시, 있으면 alive_checked_at 갱신

UI에서 "🔍 삭제 여부 확인" 버튼이나 CLI로 실행.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naver_session import get_logged_in_context  # noqa: E402
import history_store as hist  # noqa: E402
import templates_store as tmpl  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _default_message_token() -> str:
    """기본 모집 문구에서 고유 토큰 한 단어 추출.

    닉네임 매칭이 불안정할 때 본문 단어로 매칭하기 위함.
    예: 사용자가 '가게A에 초대합니다' 같은 고유 단어를 쓰면 그것 우선.
    """
    msg = (tmpl.get_all().get("default") or "")
    if not msg:
        return ""
    for kw in ("가게A", "신청링크", "초대합니다", "체험단"):
        if kw in msg:
            return kw
    # 폴백: 본문 앞 14자
    cleaned = msg.replace("\n", " ").strip()
    return cleaned[:14]


async def _open_comments(page) -> bool:
    """모바일 블로그 페이지에서 댓글 영역을 펼치고 모든 댓글을 로딩."""
    # 스크롤로 본문 끝까지
    for _ in range(8):
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(220)
    # '댓글' 버튼 클릭 (새 모바일 레이아웃)
    for sel in ['button[class*="comment_btn"]', 'a[class*="comment_btn"]',
                'a.btn_comment']:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(timeout=2500)
                break
        except Exception:
            continue
    await page.wait_for_timeout(2200)
    # 댓글 영역에서 '더보기' 무한 스크롤 시도 (한 화면 가량)
    for _ in range(10):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(350)
    # 더보기 버튼 누르기 (있으면)
    for _ in range(4):
        try:
            more = page.locator('a.u_cbox_btn_view_comment, button.u_cbox_btn_view_comment').first
            if await more.count() and await more.is_visible(timeout=400):
                await more.click(timeout=1500)
                await page.wait_for_timeout(900)
            else:
                break
        except Exception:
            break
    return True


async def _find_my_comment(page, my_nick: str, message_token: str) -> bool:
    """
    페이지의 모든 댓글에서 우리 댓글이 있는지.
    - 닉네임(my_nick) 또는 메시지 토큰(message_token)이 댓글 본문/작성자에 보이면 살아있음.
    """
    if not (my_nick or message_token):
        return False
    return await page.evaluate("""(args) => {
        const {nick, token} = args;
        const blocks = document.querySelectorAll('.u_cbox_comment, .u_cbox_area');
        const list = blocks.length ? blocks : [document.body];
        const n = (nick||'').trim().toLowerCase();
        const t = (token||'').trim();
        // 본문 토큰 매칭이 가장 신뢰 가능. 닉네임은 m.naver.com 노이즈로 잘못 잡힐 수 있어
        // 둘 중 하나라도 매칭되면 살아있는 걸로 본다.
        for (const b of list) {
            const txt = (b.innerText || '');
            const lowtxt = txt.toLowerCase();
            if (t && txt.includes(t)) return true;
            if (n && lowtxt.includes(n)) return true;
        }
        return false;
    }""", {"nick": my_nick or "", "token": message_token or ""})


async def _get_my_nickname(page) -> str:
    """네이버 메인에서 현재 로그인된 사용자의 별명 추출 (최선의 노력)."""
    try:
        await page.goto("https://m.naver.com/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1200)
        nick = await page.evaluate("""() => {
            const cand = document.querySelector('[class*="MyArea"] [class*="name"], [class*="UserName"], .gnb_nick, .nickname');
            if (cand) return (cand.innerText || '').trim();
            const m = (document.body.innerText || '').match(/([\\w가-힣_.-]+)\\s*님/);
            return m ? m[1] : '';
        }""")
        return nick or ""
    except Exception:
        return ""


async def verify_account(account: str, headless: bool = True,
                          max_age_days: int = 14, recheck_after_hours: int = 24) -> dict:
    """
    한 계정의 미확인/재확인 대상 비밀댓글들을 검증.

    Returns: {checked, alive, deleted, errors}
    """
    targets = [t for t in hist.to_verify(max_age_days=max_age_days,
                                          recheck_after_hours=recheck_after_hours)
               if t.get("account") == account]
    print(f"[{account}] 검증 대상 {len(targets)}건")
    if not targets:
        return {"checked": 0, "alive": 0, "deleted": 0, "errors": 0}

    ctx_tuple = await get_logged_in_context(headless=headless, user_name=account)
    if not ctx_tuple:
        print(f"❌ [{account}] 세션이 없습니다.")
        return {"checked": 0, "alive": 0, "deleted": 0, "errors": len(targets)}

    p, browser, context = ctx_tuple
    alive_n = deleted_n = err_n = 0
    try:
        page = await context.new_page()
        # 닉네임 자동 추출은 m.naver.com에서 노이즈(예: '회장님')를 잡기 쉬워 신뢰도 낮음.
        # 본문의 고유 단어(예: '가게A') 매칭을 우선으로 사용한다.
        my_nick = await _get_my_nickname(page)
        default_token = _default_message_token()
        print(f"  현재 닉네임: {my_nick or '(자동 추출 실패)'}"
              f" / 본문 토큰: {default_token!r}")

        for i, rec in enumerate(targets, 1):
            url = rec.get("post_url", "")
            preview = rec.get("message_preview") or ""
            # 메시지 토큰: 레코드에 preview가 있으면 우선, 없으면 기본 문구 토큰
            token = ""
            for k in ("가게A", "신청링크", "초대합니다", "체험단"):
                if (preview and k in preview) or (not preview and default_token == k):
                    token = k; break
            if not token:
                token = default_token or (preview[:14] if preview else "")
            print(f"  [{i}/{len(targets)}] {rec.get('blog_id'):18s} 확인...", end=" ", flush=True)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1800)
                await _open_comments(page)
                alive = await _find_my_comment(page, my_nick, token)
                hist.update_check(rec["blog_id"], rec["post_url"], rec["at"], alive)
                if alive:
                    alive_n += 1; print("✅ 살아있음")
                else:
                    deleted_n += 1; print("🗑️ 삭제됨")
            except Exception as e:
                err_n += 1
                print(f"⚠️ 오류 {str(e)[:60]}")
            # 페이지 간 약간의 휴지 (자동화 의심 완화)
            await asyncio.sleep(2.5)

    finally:
        try:
            await context.close(); await browser.close(); await p.stop()
        except Exception:
            pass

    return {"checked": alive_n + deleted_n, "alive": alive_n,
            "deleted": deleted_n, "errors": err_n}


def main():
    parser = argparse.ArgumentParser(description="달았던 비밀댓글 삭제 여부 검증")
    parser.add_argument("--account", required=True, help="계정 별칭(세션)")
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--max-age-days", type=int, default=14,
                        help="이보다 오래된 건은 검증 대상에서 제외 (기본 14일)")
    parser.add_argument("--recheck-after-hours", type=int, default=24,
                        help="마지막 확인이 이 시간 이내면 재확인 안 함 (기본 24시간)")
    args = parser.parse_args()
    stats = asyncio.run(verify_account(args.account,
                                        headless=not args.show_browser,
                                        max_age_days=args.max_age_days,
                                        recheck_after_hours=args.recheck_after_hours))
    print(f"\n결과: 확인 {stats['checked']}건 — ✅ 살아있음 {stats['alive']} / "
          f"🗑️ 삭제 {stats['deleted']} / ⚠️ 오류 {stats['errors']}")


if __name__ == "__main__":
    main()
