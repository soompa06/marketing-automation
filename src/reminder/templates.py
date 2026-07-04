"""
카톡 모집문구 템플릿 저장소

캠페인별로 여러 템플릿을 보관하고, 매일 어느 캠페인에 어떤 템플릿을 사용할지 정합니다.

파일 구조 (config/kakao_templates.json):
{
  "templates": [
    {
      "id": "abc12345",
      "campaign": "restaurant",
      "name": "둔산동 회식 모집",
      "body": "안녕하세요! 둔산동 회식 체험단 모집...",
      "active": true,
      "created_at": "2026-05-07T09:00:00",
      "updated_at": "2026-05-07T09:00:00"
    }
  ]
}

이력 (output/.reminder/history.json):
{
  "sends": [
    {"date": "2026-05-07", "template_id": "abc12345", "sent": true, "at": "..."}
  ]
}
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_PATH = PROJECT_ROOT / "config" / "kakao_templates.json"
HISTORY_PATH = PROJECT_ROOT / "output" / ".reminder" / "history.json"


# =============================================================================
# 템플릿 CRUD
# =============================================================================

def _read_templates_raw() -> dict:
    if not TEMPLATES_PATH.exists():
        return {"templates": []}
    try:
        with open(TEMPLATES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "templates" in data:
            return data
    except Exception:
        pass
    return {"templates": []}


def _write_templates_raw(data: dict):
    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMPLATES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_templates(campaign: Optional[str] = None, only_active: bool = False) -> list[dict]:
    """모든 템플릿을 반환. campaign 필터 + 활성화만 필터 옵션."""
    items = _read_templates_raw().get("templates", [])
    if campaign:
        items = [t for t in items if t.get("campaign") == campaign]
    if only_active:
        items = [t for t in items if t.get("active", True)]
    return items


def get_template(template_id: str) -> Optional[dict]:
    for t in list_templates():
        if t.get("id") == template_id:
            return t
    return None


def add_template(campaign: str, name: str, body: str, active: bool = True) -> str:
    """새 템플릿 추가. 반환: 새 template_id"""
    if not campaign or not name or not body:
        raise ValueError("campaign, name, body는 필수입니다.")

    new_id = uuid.uuid4().hex[:8]
    now = datetime.now().isoformat()
    item = {
        "id": new_id,
        "campaign": campaign.strip(),
        "name": name.strip(),
        "body": body,
        "active": bool(active),
        "created_at": now,
        "updated_at": now,
    }
    data = _read_templates_raw()
    data.setdefault("templates", []).append(item)
    _write_templates_raw(data)
    return new_id


def update_template(template_id: str, **changes) -> bool:
    data = _read_templates_raw()
    items = data.get("templates", [])
    for i, t in enumerate(items):
        if t.get("id") == template_id:
            allowed = {"campaign", "name", "body", "active"}
            merged = {**t, **{k: v for k, v in changes.items() if k in allowed}}
            merged["updated_at"] = datetime.now().isoformat()
            items[i] = merged
            data["templates"] = items
            _write_templates_raw(data)
            return True
    return False


def delete_template(template_id: str) -> bool:
    data = _read_templates_raw()
    items = data.get("templates", [])
    new_items = [t for t in items if t.get("id") != template_id]
    if len(new_items) == len(items):
        return False
    data["templates"] = new_items
    _write_templates_raw(data)
    return True


# =============================================================================
# 발송 이력 (오늘 보냈는지 추적)
# =============================================================================

def _read_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"sends": []}
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("sends", [])
            return data
    except Exception:
        pass
    return {"sends": []}


def _write_history(data: dict):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_sent_today(template_id: str, day: Optional[date] = None) -> bool:
    """특정 템플릿을 오늘(또는 지정한 날) '보냄'으로 마크했는지."""
    target = (day or date.today()).isoformat()
    for s in _read_history().get("sends", []):
        if s.get("template_id") == template_id and s.get("date") == target and s.get("sent"):
            return True
    return False


def mark_sent(template_id: str, day: Optional[date] = None) -> None:
    """오늘(또는 지정 날) 이 템플릿을 발송 완료로 기록."""
    target = (day or date.today()).isoformat()
    data = _read_history()
    sends = data.get("sends", [])
    # 같은 날 + 같은 템플릿 항목이 있으면 갱신
    for s in sends:
        if s.get("template_id") == template_id and s.get("date") == target:
            s["sent"] = True
            s["at"] = datetime.now().isoformat()
            _write_history(data)
            return
    sends.append({
        "date": target,
        "template_id": template_id,
        "sent": True,
        "at": datetime.now().isoformat(),
    })
    data["sends"] = sends
    _write_history(data)


def unmark_sent(template_id: str, day: Optional[date] = None) -> None:
    """발송 마크 취소 (실수로 눌렀을 때)."""
    target = (day or date.today()).isoformat()
    data = _read_history()
    new_sends = [
        s for s in data.get("sends", [])
        if not (s.get("template_id") == template_id and s.get("date") == target)
    ]
    data["sends"] = new_sends
    _write_history(data)


def pending_today() -> list[dict]:
    """오늘 아직 안 보낸 활성 템플릿 목록."""
    return [
        t for t in list_templates(only_active=True)
        if not is_sent_today(t["id"])
    ]


def recent_history(limit: int = 30) -> list[dict]:
    """최근 발송 이력 (최신순)."""
    items = _read_history().get("sends", [])
    return sorted(
        items,
        key=lambda s: (s.get("date", ""), s.get("at", "")),
        reverse=True,
    )[:limit]
