"""
Streamlit 비밀번호 인증

용도: 인터넷에 노출된 웹앱(예: ngrok 터널)을 안전하게 보호.
원리: 첫 접속 시 비밀번호 입력 → session_state에 인증 저장.

설정 방법:
- config/auth.json 파일에 비밀번호 저장 (해시됨)
- auth.json이 없으면 인증 OFF (로컬 사용 시)

사용 방법 (각 페이지 첫 줄에서):
    from auth import require_auth
    require_auth()  # 인증 안 됐으면 로그인 화면 표시 후 stop
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Optional

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTH_PATH = PROJECT_ROOT / "config" / "auth.json"


def _hash_password(password: str, salt: str) -> str:
    """SHA-256 + salt로 해시."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _secret_password() -> str:
    """Streamlit Secrets에 설정된 공용 비밀번호 (클라우드 배포용).

    클라우드(예: Streamlit Community Cloud)는 파일시스템이 재배포 시 초기화되므로
    config/auth.json이 유지되지 않는다. 대신 앱 Secrets에 다음을 넣으면 영구 적용된다:

        app_password = "원하는비밀번호"
    """
    try:
        return str(st.secrets.get("app_password", "") or "")
    except Exception:
        return ""


def is_auth_enabled() -> bool:
    """비밀번호 인증이 활성화됐는지 (Secrets app_password 또는 auth.json 존재)."""
    return bool(_secret_password()) or AUTH_PATH.exists()


def set_password(password: str) -> bool:
    """
    비밀번호 설정 (또는 변경).
    
    auth.json에 솔트 + 해시값 저장.
    """
    try:
        AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        salt = secrets.token_hex(16)
        hashed = _hash_password(password, salt)
        with open(AUTH_PATH, "w", encoding="utf-8") as f:
            json.dump({"salt": salt, "hash": hashed}, f, indent=2)
        return True
    except Exception:
        return False


def disable_auth() -> bool:
    """비밀번호 인증 비활성화."""
    try:
        if AUTH_PATH.exists():
            AUTH_PATH.unlink()
        return True
    except Exception:
        return False


def verify_password(password: str) -> bool:
    """비밀번호 검증. Secrets의 app_password가 있으면 그것을 우선 사용."""
    secret_pw = _secret_password()
    if secret_pw:
        return secrets.compare_digest(str(password), secret_pw)

    if not AUTH_PATH.exists():
        return True  # 인증 비활성화 상태

    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            auth_data = json.load(f)
        salt = auth_data.get("salt", "")
        expected = auth_data.get("hash", "")
        actual = _hash_password(password, salt)
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def require_auth():
    """
    인증되지 않은 사용자에게 로그인 화면 표시.
    인증되면 일반 페이지 진행.
    
    각 페이지의 setup_page() 직후에 호출:
        setup_page("...")
        require_auth()
        ...
    """
    # 인증이 비활성화면 패스
    if not is_auth_enabled():
        return
    
    # 이미 인증된 세션이면 패스
    if st.session_state.get("authenticated", False):
        return
    
    # 로그인 화면 (사이드바도 숨김 + 메인 영역에 폼)
    st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none; }
        [data-testid="collapsedControl"] { display: none; }
        </style>
    """, unsafe_allow_html=True)
    
    # 가운데 정렬을 위한 빈 컬럼
    col_pad1, col_main, col_pad2 = st.columns([1, 2, 1])
    
    with col_main:
        st.markdown("# 🔒 마케팅 자동화 도구")
        st.markdown("##### 비밀번호 입력")
        st.caption("인증된 사용자만 접근 가능합니다.")
        
        with st.form("login_form"):
            password = st.text_input(
                "비밀번호",
                type="password",
                placeholder="비밀번호를 입력하세요",
                label_visibility="collapsed",
            )
            submit = st.form_submit_button("🔓 로그인", type="primary", use_container_width=True)
            
            if submit:
                if verify_password(password):
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("❌ 비밀번호가 틀렸습니다.")
        
        st.caption(
            "💡 비밀번호를 잊으셨다면 본인 PC의 관리자에게 문의하세요. "
            "또는 PC에서 직접 `config/auth.json` 파일을 삭제하면 인증이 해제됩니다."
        )
    
    st.stop()


def render_logout_button():
    """사이드바에 로그아웃 버튼 표시 (인증 활성화 시)."""
    if not is_auth_enabled() or not st.session_state.get("authenticated"):
        return
    
    if st.sidebar.button("🚪 로그아웃", help="현재 세션 종료"):
        st.session_state["authenticated"] = False
        st.rerun()
