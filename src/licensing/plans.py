"""
판매 플랜 ↔ 기능(feature) 매핑.

설치형 판매 시 라이선스에 'plan'을 담고, 앱은 이 표로 어떤 기능을
열어줄지 결정한다. 플랜을 바꾸려면 여기만 수정.
"""
from __future__ import annotations

# 게이팅 대상 기능 키 → 사람이 읽는 이름
FEATURES: dict[str, str] = {
    "check": "검수 (네이버 노출 + 스크린샷)",
    "report": "월간보고서",
    "files": "결과 파일 관리",
    "blogdex": "블덱스 지수 + 구글 시트",
    "schedule": "자동 스케줄",
    "kakao": "카톡 리마인더",
    "comment": "네이버 댓글 모집",
}

# 라이선스와 무관하게 항상 열려 있는 화면 (홈/가이드/설정)
# - 설정: 라이선스 키를 입력해야 하므로 항상 접근 가능해야 함
ALWAYS_ON: set[str] = {"home", "guide", "settings", "license"}

# 플랜 → 포함 기능
PLANS: dict[str, list[str]] = {
    "basic": ["check", "report", "files"],
    "pro": ["check", "report", "files", "blogdex", "schedule", "kakao"],
    "all": ["check", "report", "files", "blogdex", "schedule", "kakao", "comment"],
}

PLAN_LABELS: dict[str, str] = {
    "basic": "Basic — 검수 + 월간보고서",
    "pro": "Pro — Basic + 블덱스 + 스케줄 + 카톡",
    "all": "All — 전 기능 (+ 댓글 모집)",
}


def features_for_plan(plan: str) -> list[str]:
    """플랜 이름으로 포함 기능 목록 반환 (모르는 플랜이면 빈 목록)."""
    return list(PLANS.get((plan or "").lower(), []))


def plan_includes(plan: str, feature: str) -> bool:
    """해당 플랜이 특정 기능을 포함하는지."""
    return feature in PLANS.get((plan or "").lower(), [])
