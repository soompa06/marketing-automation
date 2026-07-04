"""
Streamlit 웹앱 공통 유틸리티

모든 페이지에서 공유하는 기능:
- 프로젝트 경로 설정
- 사이드바 렌더링 (메뉴 + 가이드)
- 결과 파일 관리 (목록 표시 + 삭제)
- 설정 로드
"""
from __future__ import annotations

import json
import sys
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st


# =============================================================================
# 프로젝트 경로 (streamlit_app/utils.py 기준 상위 폴더가 marketing_automation)
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "output"
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# src를 Python 경로에 추가 (기존 모듈 import용)
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# =============================================================================
# 페이지 설정 (모든 페이지 첫 줄에서 호출)
# =============================================================================

@st.cache_resource(show_spinner=False)
def _bootstrap_cloud_browsers() -> bool:
    """클라우드(예: Streamlit Community Cloud)에서 Playwright Chromium을 1회 설치.

    컨테이너에는 브라우저가 미리 설치돼 있지 않으므로, 검수/블덱스 기능이
    동작하려면 한 번 설치가 필요하다. 로컬처럼 이미 설치돼 있으면 즉시 통과한다.
    @st.cache_resource 로 컨테이너당 1회만 실행. 실패해도 앱은 계속 뜬다.
    """
    import os
    import subprocess
    import sys
    # 클라우드 환경에서만 시도 (로컬 개발에선 불필요한 서브프로세스 방지)
    is_cloud = bool(os.environ.get("STREAMLIT_SERVER_HEADLESS")) or \
        str(Path.home()).startswith(("/home/appuser", "/home/adminuser"))
    if not is_cloud:
        return False
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False, capture_output=True, timeout=600,
        )
        return True
    except Exception:
        return False


def setup_page(title: str, icon: str = "📊", feature: Optional[str] = None):
    """
    모든 페이지의 첫 줄에서 호출 — 공통 설정 + 스타일 + 인증 + (설치형) 라이선스 게이팅.

    Args:
        feature: 이 페이지가 요구하는 기능 키(plans.FEATURES). 지정 시,
                 라이선스가 그 기능을 포함하지 않으면 잠금 화면 후 중단.
                 (개발 환경=공개키 없음 또는 .licensing_off 이면 게이팅 비활성)
    """
    st.set_page_config(
        page_title=f"{title} | 마케팅 자동화",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get Help": None,
            "Report a bug": None,
            "About": "Soom 체험단 마케팅 자동화 도구",
        },
    )
    _inject_global_css()

    # 클라우드 배포 시 Playwright 브라우저 1회 설치 (로컬은 즉시 통과)
    _bootstrap_cloud_browsers()

    # 비밀번호 인증 (auth.json이 존재할 때만 활성화)
    try:
        from auth import require_auth
        require_auth()  # 인증 안 됐으면 여기서 stop
    except ImportError:
        pass  # auth 모듈 없으면 패스 (로컬 사용)

    # 설치형 라이선스 게이팅 (공개키가 내장된 '판매 빌드'에서만 작동)
    _enforce_license(feature)


# =============================================================================
# 라이선스 (설치형 판매용)
# =============================================================================

def _licensing_active() -> bool:
    """게이팅을 적용할지: 공개키(pubkey.pem)가 있고, .licensing_off 가 없을 때만."""
    pubkey = SRC_DIR / "licensing" / "pubkey.pem"
    off = CONFIG_DIR / ".licensing_off"
    return pubkey.exists() and not off.exists()


def license_status() -> dict:
    """현재 라이선스 상태 (캐시). 게이팅 비활성이면 전 기능 허용."""
    if not _licensing_active():
        return {"valid": True, "enforced": False, "features": "ALL",
                "reason": "", "expired": False, "days_left": None, "plan": "dev"}
    if "_license_status" not in st.session_state:
        try:
            from licensing import license_core
            res = license_core.load_active()
        except Exception as e:
            res = {"valid": False, "reason": f"라이선스 모듈 오류: {e}",
                   "features": [], "expired": False, "days_left": None, "plan": ""}
        res["enforced"] = True
        st.session_state["_license_status"] = res
    return st.session_state["_license_status"]


def feature_enabled(feature: str) -> bool:
    """해당 기능이 현재 라이선스에서 사용 가능한지."""
    s = license_status()
    if not s.get("enforced"):
        return True
    if not s.get("valid"):
        return False
    feats = s.get("features", [])
    return feats == "ALL" or feature in feats


def _enforce_license(feature: Optional[str]):
    """라이선스 만료/무효/기능없음 시 잠금 화면 표시 후 중단."""
    s = license_status()
    if not s.get("enforced"):
        return  # 개발/비게이팅

    # 만료일 임박 배너 (전 페이지 공통)
    days = s.get("days_left")
    if s.get("valid") and isinstance(days, int) and days <= 7:
        st.warning(f"⏳ 라이선스가 **{days}일** 후 만료됩니다. 갱신이 필요해요.")

    # 라이선스 자체가 무효/만료 → 설정(라이선스 등록) 외 전부 차단
    if not s.get("valid"):
        # ALWAYS_ON 화면은 통과 (라이선스 등록을 위해 설정/홈은 열려야 함)
        if feature is None:
            st.error(f"🔒 라이선스가 필요합니다 — {s.get('reason','')}")
            st.info("좌측 **설정 → 라이선스** 탭에서 라이선스 키를 등록하세요.")
            return
        _locked_screen(s.get("reason", "라이선스가 없습니다."))

    # 유효하지만 이 기능이 플랜에 없음
    if feature and not feature_enabled(feature):
        _locked_screen("현재 플랜에 포함되지 않은 기능입니다. 상위 플랜으로 업그레이드하세요.",
                       upgrade=True)


def _locked_screen(reason: str, upgrade: bool = False):
    """기능 잠금 화면 + 중단."""
    st.markdown(
        "<div class='ma-hero' style='background:linear-gradient(135deg,#64748B,#334155)'>"
        "<h1>🔒 잠긴 기능</h1><p>" + reason + "</p></div>",
        unsafe_allow_html=True,
    )
    if upgrade:
        st.info("플랜 업그레이드 문의는 판매처에 연락하세요.")
    else:
        st.info("좌측 **설정 → 라이선스** 탭에서 라이선스 키를 등록하세요.")
    st.stop()


# =============================================================================
# 전역 디자인 시스템
# =============================================================================

_BRAND = {
    "primary": "#4F46E5",      # 인디고
    "primary_2": "#7C3AED",    # 보라
    "accent": "#10B981",       # 에메랄드
    "warn": "#F59E0B",
    "danger": "#EF4444",
    "muted": "#64748B",
    "bg": "#F8FAFC",
    "card": "#FFFFFF",
    "border": "#E2E8F0",
    "text": "#0F172A",
    "subtext": "#475569",
}


def _inject_global_css() -> None:
    """페이지 전체에 적용되는 한 번뿐인 미세 스타일."""
    css = f"""
    <style>
      /* 본문 폭과 상단 여백을 살짝 정돈 */
      .block-container {{ padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1280px; }}

      /* 사이드바 폭 */
      [data-testid="stSidebar"] > div:first-child {{ width: 270px; }}

      /* Streamlit 기본 헤더 살짝 가벼워지게 */
      header[data-testid="stHeader"] {{ background: transparent; }}
      #MainMenu {{ visibility: hidden; }}
      footer {{ visibility: hidden; }}

      /* 메트릭 카드: 옅은 카드 + 부드러운 그림자 */
      [data-testid="stMetric"] {{
        background: {_BRAND['card']};
        border: 1px solid {_BRAND['border']};
        padding: 16px 18px;
        border-radius: 12px;
        box-shadow: 0 1px 2px rgba(15,23,42,.04);
      }}
      [data-testid="stMetricLabel"] {{ color: {_BRAND['subtext']}; font-weight: 500; }}
      [data-testid="stMetricValue"] {{ color: {_BRAND['text']}; font-weight: 700; }}

      /* st.container(border=True) 컨테이너 — 가볍고 평면적인 카드 */
      div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: {_BRAND['card']};
        border-radius: 12px !important;
        border: 1px solid {_BRAND['border']} !important;
      }}

      /* 버튼 모서리·강조 */
      .stButton > button {{
        border-radius: 10px;
        border: 1px solid {_BRAND['border']};
        font-weight: 600;
        transition: all .15s ease;
      }}
      .stButton > button:hover {{
        border-color: {_BRAND['primary']};
        color: {_BRAND['primary']};
      }}
      .stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, {_BRAND['primary']}, {_BRAND['primary_2']});
        border: 0; color: white;
      }}
      .stButton > button[kind="primary"]:hover {{
        filter: brightness(1.04);
        box-shadow: 0 6px 16px rgba(79,70,229,.30);
      }}

      /* 다운로드 버튼도 동일 톤 */
      [data-testid="stDownloadButton"] > button {{ border-radius: 10px; font-weight: 600; }}

      /* 입력류 */
      input, textarea, [data-baseweb="select"] > div {{ border-radius: 10px !important; }}

      /* 익스팬더 */
      details {{ border-radius: 12px !important; }}
      summary {{ font-weight: 600; }}

      /* 사용자 헤더 — 페이지 hero */
      .ma-hero {{
        background: linear-gradient(135deg, {_BRAND['primary']} 0%, {_BRAND['primary_2']} 100%);
        color: white;
        padding: 28px 30px;
        border-radius: 18px;
        margin-bottom: 18px;
        box-shadow: 0 10px 28px rgba(79,70,229,.18);
      }}
      .ma-hero h1 {{ margin: 0; font-size: 1.85rem; font-weight: 800; letter-spacing: -.01em; }}
      .ma-hero p {{ margin: 6px 0 0; opacity: .92; font-size: .98rem; }}

      /* 페이지 헤더 (소형) */
      .ma-page-head {{ margin: 4px 0 14px; }}
      .ma-page-head h1 {{
        margin: 0; font-size: 1.55rem; font-weight: 800; color: {_BRAND['text']};
        letter-spacing: -.01em;
      }}
      .ma-page-head .sub {{
        color: {_BRAND['subtext']}; font-size: .93rem; margin-top: 4px;
      }}

      /* 작은 라벨/뱃지 */
      .ma-badge {{
        display: inline-block; padding: 2px 9px; border-radius: 999px;
        background: #EEF2FF; color: {_BRAND['primary']}; font-size: .78rem; font-weight: 600;
      }}
      .ma-badge.warn {{ background: #FEF3C7; color: #B45309; }}
      .ma-badge.ok {{ background: #DCFCE7; color: #166534; }}
      .ma-badge.danger {{ background: #FEE2E2; color: #B91C1C; }}

      /* 사이드바 브랜드 */
      .ma-brand {{
        display: flex; align-items: center; gap: 10px;
        padding: 10px 4px 14px; border-bottom: 1px solid {_BRAND['border']};
        margin-bottom: 6px;
      }}
      .ma-brand .logo {{
        width: 36px; height: 36px; border-radius: 10px;
        background: linear-gradient(135deg, {_BRAND['primary']}, {_BRAND['primary_2']});
        color: white; font-weight: 800; display: flex; align-items: center;
        justify-content: center; font-size: 1.1rem;
        box-shadow: 0 4px 10px rgba(79,70,229,.25);
      }}
      .ma-brand .name {{ font-weight: 800; color: {_BRAND['text']}; letter-spacing: -.01em; }}
      .ma-brand .sub {{ color: {_BRAND['subtext']}; font-size: .78rem; }}

      /* 사이드바 섹션 라벨 */
      .ma-side-label {{
        font-size: .72rem; text-transform: uppercase; letter-spacing: .08em;
        color: {_BRAND['muted']}; font-weight: 700; margin: 14px 0 4px;
      }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def page_header(title: str, icon: str = "", subtitle: str = "") -> None:
    """모든 페이지에서 통일된 상단 제목."""
    head = f"<div class='ma-page-head'><h1>{icon} {title}</h1>"
    if subtitle:
        head += f"<div class='sub'>{subtitle}</div>"
    head += "</div>"
    st.markdown(head, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "") -> None:
    """홈 화면용 큰 hero 배너."""
    h = f"<div class='ma-hero'><h1>{title}</h1>"
    if subtitle:
        h += f"<p>{subtitle}</p>"
    h += "</div>"
    st.markdown(h, unsafe_allow_html=True)


# =============================================================================
# 사이드바 — 모든 페이지에서 동일하게 보임
# =============================================================================

def render_sidebar(current_page: str = ""):
    """
    좌측 사이드바 추가 정보 렌더링.
    
    Streamlit이 pages/ 폴더의 파일들을 자동으로 사이드바에 추가하므로,
    여기서는 제목 + 워크플로우 안내만 표시.
    
    Args:
        current_page: 현재 페이지 식별자 ('home', 'check', 'report' 등)
    """
    with st.sidebar:
        # 브랜드 로고/이름
        st.markdown(
            "<div class='ma-brand'>"
            "<div class='logo'>S</div>"
            "<div><div class='name'>Soom Marketing</div>"
            "<div class='sub'>체험단 자동화 스튜디오</div></div>"
            "</div>",
            unsafe_allow_html=True,
        )

        # Streamlit이 자동으로 페이지 메뉴를 여기 아래에 삽입함

        # 하단 — 메타 정보만
        st.markdown(
            "<div class='ma-side-label'>현황</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        st.caption("v1.0 · 로컬 실행")

        # 인증 활성화 시 로그아웃 버튼
        try:
            from auth import render_logout_button
            render_logout_button()
        except ImportError:
            pass


# =============================================================================
# 설정 파일 관리
# =============================================================================

def _settings_from_secrets() -> dict:
    """Streamlit Cloud Secrets에서 설정을 읽는다 (파일이 없을 때 폴백).

    클라우드 배포(예: Streamlit Community Cloud)에서는 config/settings.json을
    커밋할 수 없으므로, 앱 Secrets에 settings.json 전체 내용을 문자열로 넣어둔다:

        settings_json = '''{ "campaigns": {...}, "blogdex": {...} }'''

    (또는 Secrets의 키들이 곧 settings dict가 되도록 그대로 사용)
    """
    try:
        secrets = st.secrets
    except Exception:
        return {}
    try:
        if "settings_json" in secrets:
            return json.loads(secrets["settings_json"])
    except Exception as e:
        st.error(f"⚠️ Secrets의 settings_json 파싱 오류: {e}")
        return {}
    # settings_json 키가 없으면 Secrets 전체를 dict로 변환해 사용
    try:
        return {k: v for k, v in secrets.items()}
    except Exception:
        return {}


def load_settings() -> dict:
    """설정 로드. 우선순위: config/settings.json → Streamlit Secrets → 빈 dict."""
    if not SETTINGS_PATH.exists():
        return _settings_from_secrets()
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        st.error(f"⚠️ settings.json 파일에 문법 오류: {e.msg} (line {e.lineno})")
        return {}
    except Exception as e:
        st.error(f"⚠️ 설정 로드 오류: {e}")
        return {}


def save_settings(settings: dict) -> bool:
    """settings.json에 저장."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False


# =============================================================================
# 결과 파일 관리
# =============================================================================

def list_csv_results() -> list[Path]:
    """output 폴더의 결과 CSV 목록 (최신 순).

    파일명이 macOS에서 NFD(자모 분리)로 저장되면 NFC 패턴 glob이 한글 부분을
    놓치므로, 모든 *.csv를 NFC로 정규화해 부분일치로 거른다.
    """
    if not OUTPUT_DIR.exists():
        return []

    def _nfc(s: str) -> str:
        return unicodedata.normalize("NFC", s)

    csvs = []
    for p in OUTPUT_DIR.glob("*.csv"):
        name = _nfc(p.name)
        if name.startswith("_temp_input_"):
            continue  # 과거 버전이 남긴 임시 입력 파일 — 결과 목록에서 제외
        if (
            "_노출결과_" in name
            or name.startswith("check_results_")
            or name.startswith("blogdex_지수_")
        ):
            csvs.append(p)

    return sorted(csvs, key=lambda p: p.stat().st_mtime, reverse=True)


def list_empty_screenshot_campaigns() -> list[Path]:
    """
    스크린샷 폴더 중 PNG가 하나도 없는 캠페인 폴더(빈 껍데기) 목록.
    날짜 폴더만 지운 뒤 남아있는 병원/restaurant 같은 부모 디렉토리를 찾기 위함.
    """
    if not SCREENSHOT_DIR.exists():
        return []
    out = []
    for campaign_dir in SCREENSHOT_DIR.iterdir():
        if not campaign_dir.is_dir():
            continue
        # PNG가 한 장도 없으면 빈 캠페인 폴더로 간주
        has_png = any(True for _ in campaign_dir.rglob("*.png"))
        if not has_png:
            out.append(campaign_dir)
    return sorted(out, key=lambda p: p.name)


def delete_screenshot_date_folder(date_dir: Path) -> bool:
    """
    날짜 폴더를 삭제하고, 부모 캠페인 폴더가 비면 그것도 함께 삭제.

    Args:
        date_dir: screenshots/{캠페인}/{YYYYMMDD} 형태의 경로

    Returns:
        삭제 성공 여부
    """
    try:
        parent = date_dir.parent
        if date_dir.exists():
            shutil.rmtree(date_dir)
        # 부모 캠페인 폴더가 비었으면 같이 정리
        if parent != SCREENSHOT_DIR and parent.exists():
            try:
                remaining = [p for p in parent.iterdir() if p.name != ".DS_Store"]
                if not remaining:
                    shutil.rmtree(parent)
            except Exception:
                pass
        return True
    except Exception as e:
        st.error(f"삭제 실패: {e}")
        return False


def list_reports() -> list[Path]:
    """월간보고서 .docx 목록 (최신 순)."""
    reports_dir = OUTPUT_DIR / "reports"
    if not reports_dir.exists():
        return []
    return sorted(
        reports_dir.glob("*.docx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def list_screenshot_folders() -> list[tuple[Path, int]]:
    """
    스크린샷 폴더 목록 + 각 폴더의 파일 개수.
    
    Returns:
        [(folder_path, file_count), ...] (최신 순)
    """
    if not SCREENSHOT_DIR.exists():
        return []
    
    folders = []
    # screenshots/{캠페인}/{날짜}/{블로거}/ 구조
    for campaign_dir in SCREENSHOT_DIR.iterdir():
        if not campaign_dir.is_dir():
            continue
        for date_dir in campaign_dir.iterdir():
            if not date_dir.is_dir():
                continue
            count = sum(1 for f in date_dir.rglob("*.png"))
            if count > 0:
                folders.append((date_dir, count))
    
    return sorted(folders, key=lambda x: x[0].stat().st_mtime, reverse=True)


def delete_file(path: Path) -> bool:
    """파일 또는 폴더 삭제."""
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return True
    except Exception as e:
        st.error(f"삭제 실패: {e}")
        return False


# =============================================================================
# 출력 디렉토리 보장
# =============================================================================

def ensure_directories():
    """필수 디렉토리 생성."""
    for d in [OUTPUT_DIR, OUTPUT_DIR / "reports", SCREENSHOT_DIR, CONFIG_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 친숙한 마케팅 용어로 변환 (사용자가 마케터라서)
# =============================================================================

def format_file_size(size_bytes: int) -> str:
    """파일 크기를 읽기 쉽게."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def format_relative_time(timestamp: float) -> str:
    """파일 수정 시간을 한국어로."""
    now = datetime.now()
    file_time = datetime.fromtimestamp(timestamp)
    delta = now - file_time
    
    if delta.days > 7:
        return file_time.strftime("%Y-%m-%d %H:%M")
    elif delta.days > 0:
        return f"{delta.days}일 전"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600}시간 전"
    elif delta.seconds > 60:
        return f"{delta.seconds // 60}분 전"
    else:
        return "방금 전"


# =============================================================================
# Subprocess 실행 헬퍼 (검수/보고서 실행 시 사용)
# =============================================================================

def get_python_executable() -> str:
    """현재 Python 인터프리터 경로 (venv의 python)."""
    return sys.executable


# =============================================================================
# 작업 완료 알림 (검수/보고서/블덱스 페이지 공통)
# =============================================================================

def notify_job_completion(
    active_jobs: list,
    recent_jobs: list,
    state_key: str,
    title: str = "작업",
) -> None:
    """
    백그라운드 작업이 '실행 중 → 완료'로 바뀌었을 때 사용자에게 분명한 신호를 줍니다.

    Args:
        active_jobs: 현재 실행 중인 작업 리스트 (각 dict에 'job_id', 'description')
        recent_jobs: 최근 완료된 작업 리스트
        state_key: 이 페이지에서 사용할 session_state 키 (예: "seen_check_jobs")
        title: 알림 메시지에 들어갈 제목 (예: '검수', '보고서', '블덱스')
    """
    seen = st.session_state.setdefault(state_key, set())

    # 1) 현재 실행 중인 작업은 'seen'에 등록만 (다음 단계에서 완료 감지에 쓰임)
    for j in active_jobs:
        jid = j.get("job_id")
        if jid:
            seen.add(jid)

    # 2) recent_jobs 중에서 'seen에 있던 → 더 이상 active 아님'인 항목 = 새로 완료
    active_ids = {j.get("job_id") for j in active_jobs}
    newly_done = []
    for j in recent_jobs:
        jid = j.get("job_id")
        if jid and jid in seen and jid not in active_ids:
            # 아직 알림을 보낸 적 없으면 알림
            done_key = f"{state_key}_done_{jid}"
            if not st.session_state.get(done_key):
                newly_done.append(j)
                st.session_state[done_key] = True
                seen.discard(jid)  # 알림 후 더 이상 추적할 필요 없음

    if not newly_done:
        return

    # 시각·청각 알림
    for j in newly_done:
        exit_code = j.get("exit_code")
        if exit_code is None or exit_code == 0:
            st.success(
                f"🎉 **{title} 완료!** {j.get('description', j.get('job_id', ''))}"
            )
            try:
                st.toast(f"✅ {title} 완료", icon="🎉")
                st.balloons()
            except Exception:
                pass
        else:
            st.error(
                f"❌ **{title} 실패** (exit={exit_code}): "
                f"{j.get('description', j.get('job_id', ''))}"
            )
            try:
                st.toast(f"❌ {title} 실패", icon="⚠️")
            except Exception:
                pass
