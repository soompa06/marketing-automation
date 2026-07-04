"""
마케팅 자동화 — 홈 (가볍고 깔끔한 대시보드)

설계 원칙:
- 무겁지 않게: 섹션 최소화, 큰 표/반복 렌더 없음, 가벼운 KPI + 런처 그리드
- 모든 기능 접근: 9개 페이지를 카드 런처로 한눈에 (클릭 이동)
- 익숙한 UI: 모던 SaaS 대시보드(앱 런처) 패턴
"""
from pathlib import Path

import streamlit as st

from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    list_csv_results,
    list_reports,
    list_screenshot_folders,
    load_settings,
    format_relative_time,
    hero,
)

setup_page("홈", "🏠")
ensure_directories()
render_sidebar("home")

PAGES_DIR = Path(__file__).resolve().parent / "pages"


def _page_path(prefix):
    """번호 접두어로 실제 페이지 파일 경로를 찾음 (NFC/NFD 매칭 안전)."""
    for f in PAGES_DIR.glob(f"{prefix}*.py"):
        return f"pages/{f.name}"
    return None


# =============================================================================
# Hero (가벼운 그라데이션 배너)
# =============================================================================

hero(
    "마케팅 자동화 스튜디오",
    "체험단 검수 · 월간보고서 · 블덱스 지수 · 댓글 모집을 한 곳에서.",
)

# =============================================================================
# KPI (한 줄, 가볍게)
# =============================================================================

csvs = list_csv_results()
reports = list_reports()
total_shots = sum(c for _, c in list_screenshot_folders())
last_check = format_relative_time(csvs[0].stat().st_mtime) if csvs else "—"

k1, k2, k3, k4 = st.columns(4)
k1.metric("검수 결과", f"{len(csvs)}건")
k2.metric("월간보고서", f"{len(reports)}개")
k3.metric("스크린샷", f"{total_shots:,}장")
k4.metric("마지막 검수", last_check)

st.write("")

# =============================================================================
# 앱 런처 — 모든 기능을 카드 그리드로 (클릭 이동)
# =============================================================================

st.markdown("#### 바로가기")

CARDS = [
    ("1_", "검수", "📥", "네이버 노출 + 스크린샷"),
    ("2_", "월간보고서", "📝", "워드 보고서 자동 생성"),
    ("3_", "댓글 모집", "💬", "블로그탭 비밀댓글"),
    ("4_", "블덱스 지수", "🎯", "자격/미달 자동 분류"),
    ("5_", "결과 파일", "📁", "CSV·보고서·스크린샷"),
    ("6_", "사용 가이드", "📚", "처음 사용 안내"),
    ("7_", "설정", "⚙️", "시트·자격·인증"),
    ("8_", "자동 스케줄", "⏰", "정해진 시각 자동 실행"),
    ("9_", "카톡 리마인더", "💬", "모집문구 알림·복사"),
]

# 4열 그리드로 가볍게 배치
for row_start in range(0, len(CARDS), 4):
    cols = st.columns(4)
    for col, (prefix, title, icon, desc) in zip(cols, CARDS[row_start:row_start + 4]):
        with col, st.container(border=True):
            st.markdown(f"**{icon} {title}**")
            st.caption(desc)
            p = _page_path(prefix)
            if p:
                st.page_link(p, label="열기 →", use_container_width=True)

st.write("")

# =============================================================================
# 최근 활동 (슬림 — 최신 3건씩)
# =============================================================================

c_left, c_right = st.columns(2)


def _recent_list(items, empty_msg):
    if not items:
        st.caption(empty_msg)
        return
    for it in items[:3]:
        t = format_relative_time(it.stat().st_mtime)
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"padding:5px 0;border-bottom:1px solid #F1F5F9;'>"
            f"<span style='font-weight:600;font-size:.9rem'>{it.stem[:34]}</span>"
            f"<span style='color:#94A3B8;font-size:.8rem'>{t}</span></div>",
            unsafe_allow_html=True,
        )


with c_left:
    with st.container(border=True):
        st.markdown("**🗂️ 최근 검수 결과**")
        _recent_list(csvs, "아직 검수 결과가 없어요. **검수**에서 시작해보세요.")

with c_right:
    with st.container(border=True):
        st.markdown("**📄 최근 보고서**")
        _recent_list(reports, "아직 보고서가 없어요. **월간보고서**에서 만들어보세요.")

# =============================================================================
# 설정 안내 (필요할 때만)
# =============================================================================

if not load_settings():
    st.warning("⚙️ 설정이 비어있어요. 좌측 **설정**에서 가게 정보·구글 시트 ID를 입력해주세요.")
