"""
블연플(lablog.co.kr) 점수 검증

블덱스에서 자격 등급(준최5 이상)으로 나온 행의 지수 칸에 블연플 '블로그 진단' 점수를 덧붙인다.
    D열: "준최5"  →  "준최5 / 41"

- 대상: 메인 시트에서 지수 칸이 '자격 등급 그대로'인 행 (이미 "/ 점수"가 붙은 행은 건너뜀)
- 블연플 계정은 config/settings.json 의 "lablog": {"user_id", "password"} (gitignore됨)

사용 예시:
    python lablog_verify.py --all             # 모든 캠페인
    python lablog_verify.py --campaign skin --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright, Page
from blogdex_checker import extract_blog_id, load_qualified_grades
from sheet_client import (
    get_campaign_config,
    get_all_rows,
    batch_write_grades,
    load_settings,
)

DIAGNOSE_URL = "https://lablog.co.kr/blog/blogDiagnose"
# 차트 라벨 예: "점수 :   [ 41 / 100 ]"
_SCORE_RE = re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*/\s*100\s*\]")


def pending_verify_rows(campaign_name: str, qualified: set[str]) -> tuple:
    """지수 칸이 자격 등급 그대로인 행만 골라 (cfg, rows) 반환."""
    cfg = get_campaign_config(campaign_name)
    rows = [r for r in get_all_rows(cfg) if r.blog_url and r.grade in qualified]
    return cfg, rows


async def _login(page: Page, user_id: str, password: str) -> None:
    """블연플 로그인 (blogDiagnose 접근 시 로그인 화면으로 이동됨)."""
    await page.goto(DIAGNOSE_URL, wait_until="domcontentloaded")
    await page.fill("input[name=id]", user_id)
    await page.fill("input[name=pwd]", password)
    await page.click("button[type=submit]")
    await page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)


async def fetch_score(page: Page, blog_id: str) -> str | None:
    """블로그 ID 하나의 진단 점수. 못 찾으면 None.

    직전 결과가 남는 스테일을 막으려고 매번 진단 페이지를 새로 연다.
    """
    await page.goto(DIAGNOSE_URL, wait_until="domcontentloaded")
    box = page.locator("input[type=text]").first
    await box.fill(blog_id)
    await box.press("Enter")
    label = page.locator("text.apexcharts-datalabel", has_text="점수")
    try:
        await label.first.wait_for(timeout=20000)
    except Exception:
        return None
    m = _SCORE_RE.search((await label.first.text_content()) or "")
    return m.group(1) if m else None


async def verify_campaigns(campaign_names: list[str], dry_run: bool = False) -> dict:
    """캠페인들의 대상 행에 점수를 붙여 시트에 반영. 반환: {캠페인: (대상, 성공, 실패)}"""
    qualified = load_qualified_grades()
    targets = {c: pending_verify_rows(c, qualified) for c in campaign_names}
    stats = {c: (len(rows), 0, 0) for c, (_, rows) in targets.items()}
    if not any(rows for _, rows in targets.values()):
        print("   ✓ 점수 검증할 행이 없습니다")
        return stats

    creds = load_settings().get("lablog") or {}
    if not creds.get("user_id") or not creds.get("password"):
        raise RuntimeError("settings.json 에 lablog 계정(user_id/password)이 없습니다")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1300, "height": 900})
            await _login(page, creds["user_id"], creds["password"])
            for name, (cfg, rows) in targets.items():
                if not rows:
                    continue
                print(f"\n🔍 [{name}] 점수 검증 {len(rows)}건")
                updates, ok, fail = [], 0, 0
                for r in rows:
                    bid = extract_blog_id(r.blog_url)
                    score = await fetch_score(page, bid)
                    if score is None:
                        fail += 1
                        print(f"  ❌ 행 {r.row_number} {bid}: 점수 없음 (시트 유지)")
                        continue
                    ok += 1
                    updates.append((r.row_number, f"{r.grade} / {score}"))
                    print(f"  ✅ 행 {r.row_number} {bid}: {r.grade} / {score}")
                if updates and not dry_run:
                    batch_write_grades(cfg, updates)
                    print(f"   📤 시트 {len(updates)}건 반영")
                elif dry_run:
                    print("   💡 DRY-RUN: 시트 변경 없음")
                stats[name] = (len(rows), ok, fail)
        finally:
            await browser.close()
    return stats


def main():
    ap = argparse.ArgumentParser(description="블연플 점수로 지수 검증 (준최5 → 준최5 / 41)")
    ap.add_argument("--campaign", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    names = args.campaign or list(load_settings().get("google_sheets", {}).get("campaigns", {}))
    stats = asyncio.run(verify_campaigns(names, args.dry_run))
    print("\n📊 점수 검증 결과")
    for c, (total, ok, fail) in stats.items():
        print(f"   - {c}: 대상 {total}건 / 성공 {ok}건 / 실패 {fail}건")


if __name__ == "__main__":
    main()
