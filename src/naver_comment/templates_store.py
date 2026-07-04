"""
키워드별 모집 댓글 문구 저장소

- 키워드마다 다른 모집글을 지정 (예: '대전 맛집' → 식당 모집글)
- 매칭되는 키워드 문구가 없으면 기본 문구 사용

저장 위치: config/comment_templates.json (.gitignore 등록)
구조:
{
  "default": "기본 모집 문구",
  "by_keyword": { "대전 맛집": "...", "만년동 맛집": "..." }
}
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_PATH = PROJECT_ROOT / "config" / "comment_templates.json"


def _load() -> dict:
    if not TEMPLATES_PATH.exists():
        return {"default": "", "by_keyword": {}}
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        data.setdefault("default", "")
        data.setdefault("by_keyword", {})
        return data
    except Exception:
        return {"default": "", "by_keyword": {}}


def _save(data: dict) -> None:
    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_message(keyword: str) -> str:
    """키워드에 매칭되는 문구, 없으면 기본 문구."""
    data = _load()
    kw = (keyword or "").strip()
    msg = (data["by_keyword"].get(kw) or "").strip()
    return msg or (data.get("default") or "").strip()


def get_all() -> dict:
    return _load()


def set_default(text: str) -> None:
    data = _load()
    data["default"] = text or ""
    _save(data)


def set_keyword(keyword: str, text: str) -> None:
    kw = (keyword or "").strip()
    if not kw:
        return
    data = _load()
    data["by_keyword"][kw] = text or ""
    _save(data)


def delete_keyword(keyword: str) -> None:
    data = _load()
    data["by_keyword"].pop((keyword or "").strip(), None)
    _save(data)


def has_message_for(keyword: str) -> bool:
    """키워드 문구 또는 기본 문구가 하나라도 있으면 True."""
    return bool(get_message(keyword))
