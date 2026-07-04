"""
카톡 리마인더 러너

스케줄러(`src/scheduler/runner.py`)가 이 스크립트를 시각에 맞춰 실행합니다.
역할:
1. 오늘 아직 안 보낸 활성 템플릿 목록 추출
2. 데스크톱 알림 띄움 ('오늘 카톡 모집문구 N개 보낼 시간!')
3. (옵션) 클립보드에 첫 번째 템플릿 본문 복사

자동 발송은 절대 하지 않습니다 (CLAUDE.md 정책).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reminder.templates import pending_today, list_templates, mark_sent  # noqa: E402
from reminder.notifier import notify, copy_to_clipboard  # noqa: E402


def fire_today_reminder(copy_first: bool = False) -> int:
    """
    오늘의 리마인더 1회 발생.

    Returns:
        미발송 템플릿 개수 (= 알림에 표시된 수). 0이면 알림 생략.
    """
    pending = pending_today()
    if not pending:
        print("[reminder] 오늘 보낼 템플릿이 없습니다 (모두 발송 완료 or 비활성).")
        return 0

    # 캠페인별 그룹핑 표시
    by_campaign: dict[str, list[str]] = {}
    for t in pending:
        by_campaign.setdefault(t.get("campaign", "?"), []).append(t.get("name", "?"))

    summary_lines = []
    for camp, names in by_campaign.items():
        summary_lines.append(f"[{camp}] " + ", ".join(names))
    summary = " · ".join(summary_lines)

    notify(
        title=f"📨 카톡 모집문구 {len(pending)}개 보낼 시간",
        message=summary[:300],
    )

    if copy_first:
        first = pending[0]
        ok = copy_to_clipboard(first.get("body", ""))
        if ok:
            print(f"[reminder] 클립보드 복사: '{first.get('name')}'")

    for t in pending:
        print(f"  · [{t.get('campaign')}] {t.get('name')} (id={t.get('id')})")

    return len(pending)


def main():
    parser = argparse.ArgumentParser(description="카톡 모집문구 리마인더")
    parser.add_argument(
        "--copy-first",
        action="store_true",
        help="첫 번째 미발송 템플릿의 본문을 클립보드에 자동 복사",
    )
    parser.add_argument(
        "--mark-sent",
        help="해당 template_id를 '발송 완료'로 마킹만 하고 종료",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="등록된 모든 템플릿 목록 출력",
    )
    args = parser.parse_args()

    if args.list:
        items = list_templates()
        if not items:
            print("등록된 템플릿이 없습니다.")
            return
        for t in items:
            active = "🟢" if t.get("active", True) else "⚪"
            print(f"  {active} [{t.get('campaign')}] {t.get('name')} (id={t.get('id')})")
        return

    if args.mark_sent:
        mark_sent(args.mark_sent)
        print(f"[reminder] 발송 완료 마킹: {args.mark_sent}")
        return

    count = fire_today_reminder(copy_first=args.copy_first)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
