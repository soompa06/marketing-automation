"""
네이버 댓글 이력 저장소

용도:
1. 블로거(blogId) 단위 3개월 재방문 금지 판정
2. 하루 작성 건수 카운트 (일일 한도)
3. UI 실시간 표시 (어느 블로거에 달았는지)

저장 위치: config/comment_history.json (.gitignore 등록)

각 기록:
{
  "account": 댓글 단 우리 계정 별칭,
  "blog_id": 대상 블로거 ID,
  "post_url": 글 URL,
  "keyword": 검색 키워드,
  "status": "success" | "skipped_dedup" | "no_comment_box" | "blocked" | "error",
  "detail": 상태 부가 설명,
  "at": ISO 시각,
}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_PATH = PROJECT_ROOT / "config" / "comment_history.json"

# 성공으로 간주(=재방문 금지 대상)할 상태
SUCCESS_STATUSES = {"success"}


def _load() -> dict:
    if not HISTORY_PATH.exists():
        return {"comments": []}
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if "comments" not in data:
            data["comments"] = []
        return data
    except Exception:
        return {"comments": []}


def _save(data: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record(
    account: str,
    blog_id: str,
    post_url: str,
    keyword: str,
    status: str,
    detail: str = "",
    message_preview: str = "",
) -> None:
    """댓글 시도 결과 1건 기록 (즉시 디스크 반영 → UI가 실시간으로 읽음)."""
    data = _load()
    data["comments"].append({
        "account": account,
        "blog_id": blog_id,
        "post_url": post_url,
        "keyword": keyword,
        "status": status,
        "detail": detail,
        "at": datetime.now().isoformat(timespec="seconds"),
        # 삭제 검증용
        "message_preview": message_preview[:60] if message_preview else "",
        "alive_checked_at": None,
        "deleted_at": None,
    })
    _save(data)


def update_check(blog_id: str, post_url: str, at_iso: str,
                 alive: bool, checked_at: Optional[str] = None) -> bool:
    """
    삭제 검증 결과 반영.
    (blog_id, post_url, at)로 해당 성공 레코드를 찾아 alive_checked_at / deleted_at 갱신.
    """
    from datetime import datetime as _dt
    data = _load()
    now = checked_at or _dt.now().isoformat(timespec="seconds")
    updated = False
    for c in data["comments"]:
        if (c.get("blog_id") == blog_id and c.get("post_url") == post_url
                and c.get("at") == at_iso and c.get("status") in SUCCESS_STATUSES):
            c["alive_checked_at"] = now
            if alive:
                c["deleted_at"] = None
            else:
                # 이미 삭제로 마킹된 게 있으면 그대로 유지(최초 발견 시각 보존)
                if not c.get("deleted_at"):
                    c["deleted_at"] = now
            updated = True
            break
    if updated:
        _save(data)
    return updated


def to_verify(max_age_days: int = 14, recheck_after_hours: int = 24) -> list[dict]:
    """
    삭제 여부를 확인해야 할 성공 레코드 목록.
    - 이미 deleted_at 표시된 건 제외 (이미 확인됨)
    - max_age_days보다 오래된 건도 제외 (지난 일 추적 의미 낮음)
    - 마지막 확인이 recheck_after_hours 전이면 재확인 대상
    """
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now()
    out = []
    for c in _load()["comments"]:
        if c.get("status") not in SUCCESS_STATUSES:
            continue
        if c.get("deleted_at"):
            continue
        dt = _parse_at(c.get("at", ""))
        if not dt:
            continue
        age = now - dt
        if age > _td(days=max_age_days):
            continue
        last = _parse_at(c.get("alive_checked_at") or "")
        if last and (now - last) < _td(hours=recheck_after_hours):
            continue
        out.append(c)
    return out


def _parse_at(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def last_success_at(blog_id: str) -> Optional[datetime]:
    """이 블로거에게 마지막으로 '성공' 댓글을 단 시각 (없으면 None)."""
    latest: Optional[datetime] = None
    for c in _load()["comments"]:
        if c.get("blog_id") != blog_id:
            continue
        if c.get("status") not in SUCCESS_STATUSES:
            continue
        dt = _parse_at(c.get("at", ""))
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest


def was_commented_recently(blog_id: str, within_days: int = 90) -> bool:
    """
    이 블로거에게 within_days(기본 90=3개월) 이내에 댓글을 단 적이 있으면 True.
    → True면 이번엔 건너뛴다.
    """
    last = last_success_at(blog_id)
    if not last:
        return False
    return (datetime.now() - last) <= timedelta(days=within_days)


def recently_commented_blog_ids(within_days: int = 90) -> set[str]:
    """within_days 이내 댓글 단 블로거 ID 집합 (사전 필터용)."""
    cutoff = datetime.now() - timedelta(days=within_days)
    out: set[str] = set()
    for c in _load()["comments"]:
        if c.get("status") not in SUCCESS_STATUSES:
            continue
        dt = _parse_at(c.get("at", ""))
        if dt and dt >= cutoff:
            out.add(c.get("blog_id", ""))
    out.discard("")
    return out


def count_on_day(day: Optional[datetime] = None, account: Optional[str] = None) -> int:
    """해당 날짜(기본 오늘)에 '성공'한 댓글 수. account 지정 시 그 계정만."""
    day = day or datetime.now()
    target = day.date()
    n = 0
    for c in _load()["comments"]:
        if c.get("status") not in SUCCESS_STATUSES:
            continue
        if account and c.get("account") != account:
            continue
        dt = _parse_at(c.get("at", ""))
        if dt and dt.date() == target:
            n += 1
    return n


def recent(limit: int = 100) -> list[dict]:
    """최근 기록 (최신순)."""
    items = _load()["comments"]
    return list(reversed(items[-limit:]))


def success_records(limit: int = 1000) -> list[dict]:
    """'성공'(실제 작성) 기록만 최신순으로."""
    out = [c for c in _load()["comments"] if c.get("status") in SUCCESS_STATUSES]
    return list(reversed(out))[:limit]


def summary() -> dict:
    """누적 통계: 총 성공 수, 고유 블로거 수, 오늘 수, 계정별 성공 수."""
    items = _load()["comments"]
    succ = [c for c in items if c.get("status") in SUCCESS_STATUSES]
    by_account: dict[str, int] = {}
    blog_ids = set()
    today = datetime.now().date()
    today_n = 0
    for c in succ:
        by_account[c.get("account", "")] = by_account.get(c.get("account", ""), 0) + 1
        blog_ids.add(c.get("blog_id", ""))
        dt = _parse_at(c.get("at", ""))
        if dt and dt.date() == today:
            today_n += 1
    blog_ids.discard("")
    return {
        "total_success": len(succ),
        "unique_bloggers": len(blog_ids),
        "today": today_n,
        "by_account": by_account,
    }


def all_records() -> list[dict]:
    return list(_load()["comments"])
