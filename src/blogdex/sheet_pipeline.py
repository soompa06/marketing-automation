"""
구글 시트 ↔ 블덱스 통합 파이프라인

워크플로우:
1. 구글 시트에서 '지수' 비어있는 행 가져오기
2. 블덱스에서 batch_size명씩 조회
3. 한 배치 끝나면 wait_seconds_between_batches초 대기 (속도 제한 회피)
4. 결과를 시트에 반영:
   - 자격자 → '지수' 컬럼에 값 쓰기
   - 미달자 → 미달자 시트로 이동 (메인에서 삭제)

사용 예시:
    # 식당 캠페인 처리
    python sheet_pipeline.py --campaign restaurant
    
    # 미리 보기 (실제 시트 변경 X)
    python sheet_pipeline.py --campaign restaurant --dry-run
    
    # 두 캠페인 모두 처리
    python sheet_pipeline.py --campaign restaurant --campaign skin
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 같은 폴더 모듈
sys.path.insert(0, str(Path(__file__).resolve().parent))
from session import get_logged_in_context
from blogdex_checker import (
    search_blog_index,
    classify_qualification,
    load_qualified_grades,
    LOOKUP_FAILED_LABEL,
)
from sheet_client import (
    CampaignConfig,
    SheetRow,
    get_campaign_config,
    get_pending_rows,
    batch_write_grades,
    move_to_rejected,
    column_to_index,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"


def load_blogdex_settings() -> dict:
    """블덱스 관련 설정 (조회 간격, 제한 대기 등)."""
    # 전략: 처음부터 느리게 가지 않고 '연속 조회'하다가, 블덱스가 조회 제한을
    # 띄우면 안내된 시간(N초 후 가능)만큼 자동 대기 후 같은 블로거를 재시도한다.
    # - query_delay_seconds: 정상 조회 사이의 짧은 간격
    # - rate_limit_wait_seconds: 제한 메시지에 시간이 안 적혀 있을 때 기본 대기
    # - max_rate_limit_retries: 한 블로거가 제한에 걸렸을 때 최대 재시도 횟수
    defaults = {
        "query_delay_seconds": 2,
        "rate_limit_wait_seconds": 60,
        "max_rate_limit_retries": 5,
        # (구버전 호환 — 더 이상 핵심 로직엔 안 쓰임)
        "batch_size": 1,
        "wait_seconds_between_batches": 40,
    }
    
    if not SETTINGS_PATH.exists():
        return defaults
    
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)
        return {**defaults, **settings.get("blogdex", {})}
    except Exception:
        return defaults


# =============================================================================
# 한 캠페인 처리
# =============================================================================

async def process_campaign(
    campaign_name: str,
    page,  # 외부에서 주입받음 (블덱스 로그인된 페이지)
    dry_run: bool = False,
) -> dict:
    """
    한 캠페인을 처리.
    
    Args:
        campaign_name: 캠페인 이름 (settings.json의 키)
        page: 블덱스에 로그인된 Playwright Page (재사용)
        dry_run: True면 실제 시트 변경 X
    
    Returns:
        통계 dict (전체 건수, 자격자, 미달자, 에러 등)
    """
    print(f"\n{'='*60}")
    print(f"🎯 캠페인 처리: {campaign_name}")
    print(f"{'='*60}")
    
    if dry_run:
        print("⚠️  DRY-RUN 모드: 실제 시트는 수정되지 않습니다.\n")
    
    # 설정 로드
    cfg = get_campaign_config(campaign_name)
    bd_settings = load_blogdex_settings()
    qualified_grades = load_qualified_grades()

    print(f"📋 설정:")
    print(f"   - 시트: {cfg.spreadsheet_id}")
    print(f"   - 메인 시트: '{cfg.main_sheet_name}'")
    print(f"   - 블로그주소 컬럼: {cfg.blog_url_column}")
    print(f"   - 지수 컬럼: {cfg.grade_column}")
    print(f"   - 조회 간격: {bd_settings.get('query_delay_seconds', 2)}초 (연속 조회)")
    print(f"   - 제한 시 자동 대기 후 재시도")
    
    # 1) 시트에서 조회 대상 가져오기
    print(f"\n📥 시트에서 조회 대상 로드 중...")
    pending_rows = get_pending_rows(cfg)
    
    if not pending_rows:
        print(f"   ✓ 조회할 행이 없습니다 (이미 모두 처리됨)")
        return {
            "total": 0, "qualified": 0, "rejected": 0, "unlookup": 0, "errors": 0,
        }
    
    print(f"   ✓ {len(pending_rows)}건 발견 (지수 비어있음)")
    
    # 2) 연속 조회 처리 (외부 page 사용)
    qualified_updates: list[tuple[int, str]] = []   # (row_number, grade) — 시트에 지수 쓰기
    rejected_rows: list[SheetRow] = []               # 미달자 + 조회불가 (미달 시트로 이동)
    rejected_grades: dict[int, str] = {}             # {row_number: grade or '조회 불가'}
    unlookup_count = 0                               # 미달 이동분 중 '조회 불가' 개수 (통계용)
    error_count = 0

    # 조회 전략:
    #  - 처음부터 천천히 가지 않고 '연속'으로 조회한다 (조회 간 짧은 간격만).
    #  - 블덱스가 '1분에 2번 이상 요청할 수 없습니다(N초 후 가능)'를 띄우면,
    #    그 N초(+여유)만큼 자동 대기 후 같은 블로거를 다시 조회한다.
    query_delay = float(bd_settings.get("query_delay_seconds", 2))   # 연속 조회 간 간격
    default_wait = int(bd_settings.get("rate_limit_wait_seconds", 60))  # 대기초 파싱 실패 시
    max_rl_retries = int(bd_settings.get("max_rate_limit_retries", 5))  # 행당 최대 재시도

    print(f"\n🚀 연속 조회 시작 (대상 {len(pending_rows)}명, 조회 간격 {query_delay:.0f}초)")
    print(f"   ⏳ 조회 제한이 뜨면 안내된 시간만큼 자동 대기 후 재시도합니다.\n")

    queue: list[SheetRow] = list(pending_rows)
    rl_retries: dict[int, int] = {}            # row_number → 조회제한 재시도 횟수
    consecutive_unlookup = 0
    early_stop = False
    done = 0
    total = len(pending_rows)

    while queue and not early_stop:
        row = queue.pop(0)
        print(f"  🔎 [{done+1}/{total}] 행 {row.row_number}: {row.blog_url[:46]}", end="", flush=True)

        try:
            result = await search_blog_index(page, row.blog_url)
        except Exception as e:
            msg = str(e)
            print(f"  ❌ 오류: {msg[:100]}")
            error_count += 1
            if "closed" in msg.lower() or "Target page" in msg:
                print("=" * 70)
                print("🛑 브라우저/페이지가 닫혔습니다 — 남은 행 처리 중단")
                print("   (블덱스 조회를 동시에 두 번 실행하지 않았는지 확인하세요.)")
                print("=" * 70)
                early_stop = True
            continue

        # === 조회 제한 → 자동 대기 후 같은 블로거 재시도 ===
        if result.get("rate_limited"):
            n = rl_retries.get(row.row_number, 0) + 1
            rl_retries[row.row_number] = n
            if n > max_rl_retries:
                print(f"  ⚠️ 조회 제한 {n}회 초과 — 이 블로거는 건너뜀")
                error_count += 1
                continue
            wait_s = result.get("wait_sec") or 0
            wait_s = (wait_s + 5) if wait_s > 0 else default_wait   # 안내초 + 여유
            print(f"  ⏳ 조회 제한 감지 → {wait_s}초 대기 후 재시도 (재시도 {n}/{max_rl_retries})")
            await asyncio.sleep(wait_s)
            queue.insert(0, row)        # 같은 블로거를 맨 앞에 다시
            continue

        grade = result.get("grade", "")
        err = result.get("error", "")
        done += 1

        if err and not grade:
            # rate_limited 외의 일반 오류 (로그인 풀림 등)
            print(f"  ❌ {err[:80]}")
            error_count += 1
            if "로그인" in err:
                print("🛑 로그인이 풀려 중단합니다. 재로그인 후 다시 실행하세요.")
                early_stop = True
            continue

        if result.get("lookup_failed") or grade == LOOKUP_FAILED_LABEL:
            rejected_rows.append(row)
            rejected_grades[row.row_number] = LOOKUP_FAILED_LABEL
            unlookup_count += 1
            print(f"  🔁 {LOOKUP_FAILED_LABEL} (미달 시트로 이동)")
            if result.get("lookup_reason") == "notfound":
                consecutive_unlookup = 0
            else:
                consecutive_unlookup += 1
                if consecutive_unlookup >= 3:
                    print("=" * 70)
                    print(f"🛑 원인 불명 '{LOOKUP_FAILED_LABEL}' {consecutive_unlookup}연속 — 중단")
                    print("   지금까지 확인된 조회 불가는 미달 시트에 기록합니다.")
                    print("=" * 70)
                    early_stop = True
        elif not grade:
            print(f"  ❌ 지수 없음")
            error_count += 1
        else:
            if classify_qualification(grade, qualified_grades):
                qualified_updates.append((row.row_number, grade))
                print(f"  ✅ {grade} (자격)")
            else:
                rejected_rows.append(row)
                rejected_grades[row.row_number] = grade
                print(f"  ⚪ {grade} (미달)")
            consecutive_unlookup = 0

        await asyncio.sleep(query_delay)
    
    # 3) 시트 업데이트
    rejected_real = len(rejected_rows) - unlookup_count  # 실제 등급 미달 (조회불가 제외)
    print(f"\n📝 시트 업데이트")
    print(f"   - 자격자: {len(qualified_updates)}건 (지수 컬럼에 쓸 예정)")
    print(f"   - 미달자: {rejected_real}건 (미달 시트로 이동 예정)")
    print(f"   - 조회 불가: {unlookup_count}건 (미달 시트로 이동 + '{LOOKUP_FAILED_LABEL}' 기록)")
    print(f"   - 에러: {error_count}건 (시트는 그대로 둠)")

    if dry_run:
        print(f"\n   💡 DRY-RUN: 실제 변경은 일어나지 않습니다.")
        print(f"   --dry-run 옵션 빼고 다시 실행하면 위 변경이 반영됩니다.")
    else:
        if qualified_updates:
            print(f"\n   📤 자격자 지수 시트에 쓰는 중...")
            batch_write_grades(cfg, qualified_updates)
            print(f"      ✓ {len(qualified_updates)}건 완료")

        # 미달자 + 조회 불가 모두 미달 시트로 이동 (지수 칸은 등급 또는 '조회 불가')
        if rejected_rows:
            print(f"\n   📤 미달 시트로 이동 중... (미달 {rejected_real} + 조회불가 {unlookup_count})")
            move_to_rejected(cfg, rejected_rows, rejected_grades)
            print(f"      ✓ {len(rejected_rows)}건 이동 완료")

    return {
        "total": len(pending_rows),
        "qualified": len(qualified_updates),
        "rejected": rejected_real,
        "unlookup": unlookup_count,
        "errors": error_count,
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="구글 시트 ↔ 블덱스 통합 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:

  [1] 모든 캠페인 처리 (가장 흔한 사용)
    python sheet_pipeline.py --all

  [2] 모든 캠페인 미리보기 (시트 변경 X)
    python sheet_pipeline.py --all --dry-run

  [3] 식당만 처리
    python sheet_pipeline.py --campaign restaurant

  [4] 식당+피부과 처리 (--all과 동일하지만 명시적)
    python sheet_pipeline.py --campaign restaurant --campaign skin

  [5] 디버그 (브라우저 보면서)
    python sheet_pipeline.py --all --show-browser

자격 등급/배치 크기/대기 시간은 config/settings.json에서 조정 가능합니다.
        """
    )
    
    parser.add_argument(
        "--campaign",
        action="append",
        default=[],
        help="처리할 캠페인 이름 (여러 개 가능, 예: --campaign restaurant --campaign skin)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="settings.json의 모든 캠페인을 자동으로 처리"
    )
    parser.add_argument("--dry-run", action="store_true", help="실제 시트 변경 없이 미리보기만")
    parser.add_argument("--show-browser", action="store_true", help="브라우저 창 보기 (디버그)")
    parser.add_argument(
        "--user",
        default="default",
        help="블덱스 로그인 사용자 이름 (여러 계정 사용 시 구분용, 기본: default)"
    )
    
    args = parser.parse_args()
    
    # 캠페인 결정 로직:
    # 1. --campaign 명시 → 그것만
    # 2. --all 플래그 → settings.json의 모든 캠페인
    # 3. 둘 다 없음 → settings.json의 모든 캠페인 자동 처리 + 안내
    if args.campaign:
        campaigns_to_run = args.campaign
        if args.all:
            # --all + --campaign 동시 사용 시 합치기
            from sheet_client import load_settings
            settings = load_settings()
            all_campaigns = list(settings.get("google_sheets", {}).get("campaigns", {}).keys())
            campaigns_to_run = list(dict.fromkeys(args.campaign + all_campaigns))
    else:
        # --campaign 없으면 settings.json의 모든 캠페인 자동 처리
        from sheet_client import load_settings
        settings = load_settings()
        all_campaigns = list(settings.get("google_sheets", {}).get("campaigns", {}).keys())
        if not all_campaigns:
            print("❌ settings.json에 등록된 캠페인이 없습니다.")
            sys.exit(1)
        campaigns_to_run = all_campaigns
        if not args.all:
            print(f"💡 --campaign 옵션 미지정 → settings.json의 모든 캠페인을 자동 처리합니다.")
            print(f"   특정 캠페인만 처리하려면 --campaign restaurant 처럼 지정하세요.")
    
    print(f"\n📋 처리할 캠페인: {', '.join(campaigns_to_run)}")
    
    # 블덱스 로그인 — 모든 캠페인이 공유 (1회 로그인)
    async def run_all():
        print(f"\n🔐 블덱스 로그인 중... (사용자: {args.user})")
        ctx_tuple = await get_logged_in_context(
            headless=not args.show_browser,
            user_name=args.user,
        )
        if not ctx_tuple:
            print("❌ 블덱스 로그인 실패")
            return [(c, None) for c in campaigns_to_run]
        
        p, browser, context = ctx_tuple
        all_stats_local = []
        
        try:
            page = await context.new_page()
            
            for campaign in campaigns_to_run:
                try:
                    stats = await process_campaign(
                        campaign_name=campaign,
                        page=page,
                        dry_run=args.dry_run,
                    )
                    all_stats_local.append((campaign, stats))
                except Exception as e:
                    print(f"\n❌ 캠페인 '{campaign}' 처리 중 오류: {e}")
                    import traceback
                    traceback.print_exc()
                    all_stats_local.append((campaign, None))
        finally:
            try:
                await context.close()
                await browser.close()
                await p.stop()
            except Exception:
                pass
        
        return all_stats_local
    
    all_stats = asyncio.run(run_all())
    
    # 전체 요약
    print(f"\n\n{'='*60}")
    print(f"📊 전체 처리 결과")
    print(f"{'='*60}")
    for campaign, stats in all_stats:
        if stats is None:
            print(f"\n❌ {campaign}: 처리 실패")
        else:
            print(f"\n✓ {campaign}:")
            print(f"   - 조회 대상: {stats['total']}건")
            print(f"   - 자격자: {stats['qualified']}건")
            print(f"   - 미달자: {stats['rejected']}건")
            print(f"   - 조회 불가: {stats.get('unlookup', 0)}건")
            print(f"   - 에러: {stats['errors']}건")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
