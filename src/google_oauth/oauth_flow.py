"""
Google OAuth 인증 흐름 (Installed App / Desktop)

용도:
  서비스 계정으로 시트에 일일이 권한 추가하지 않고,
  사용자 본인의 Google 계정으로 직접 시트에 접근하고 싶을 때.

흐름:
  1. config/google_oauth_client.json 에 OAuth 2.0 클라이언트 ID 파일 (Desktop 앱)
  2. 첫 실행: 브라우저 띄워 동의 → 사용자 토큰 발급 → config/oauth_tokens/{user}.json
  3. 이후: 토큰 자동 로드 + 만료 시 refresh

토큰 파일은 사용자별로 저장되어 여러 구글 계정 동시 사용 가능.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import gspread

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
OAUTH_CLIENT_PATH = CONFIG_DIR / "google_oauth_client.json"
TOKENS_DIR = CONFIG_DIR / "oauth_tokens"

# Sheets + Drive 읽기/쓰기 (서비스 계정 모듈과 동일)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]


# =============================================================================
# 상태 조회
# =============================================================================

def is_oauth_client_configured() -> bool:
    """OAuth 클라이언트(.json) 파일이 등록됐는지."""
    if not OAUTH_CLIENT_PATH.exists():
        return False
    try:
        with open(OAUTH_CLIENT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Desktop 앱은 'installed' 키, 웹앱은 'web' 키
        return "installed" in data or "web" in data
    except Exception:
        return False


def list_oauth_users() -> list[str]:
    """저장된 사용자 토큰 목록."""
    if not TOKENS_DIR.exists():
        return []
    return sorted(p.stem for p in TOKENS_DIR.glob("*.json"))


def token_path_for(user_name: str) -> Path:
    return TOKENS_DIR / f"{user_name}.json"


def get_user_email(user_name: str) -> Optional[str]:
    """저장된 토큰에서 연결된 이메일을 추출 (없으면 None)."""
    p = token_path_for(user_name)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("_email")  # 우리가 별도로 저장
    except Exception:
        return None


# =============================================================================
# 인증 / 토큰 발급
# =============================================================================

def _save_credentials(user_name: str, creds: Credentials, email: Optional[str] = None):
    """Credentials 객체를 사용자별 토큰 파일로 저장."""
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    p = token_path_for(user_name)

    # google-auth가 제공하는 to_json은 string. 우리가 추가 메타(_email)를 더 보관.
    raw = json.loads(creds.to_json())
    if email:
        raw["_email"] = email
    with open(p, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def _load_credentials(user_name: str) -> Optional[Credentials]:
    """저장된 토큰 로드 + 필요 시 refresh."""
    p = token_path_for(user_name)
    if not p.exists():
        return None

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    # _email 같은 우리 추가 키는 Credentials.from_authorized_user_info가 무시함
    creds = Credentials.from_authorized_user_info(data, scopes=SCOPES)

    # refresh
    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_credentials(user_name, creds, email=data.get("_email"))
            except Exception:
                return None
        else:
            return None
    return creds


def start_login_flow(user_name: str, port: int = 0) -> dict:
    """
    Installed App 흐름으로 로그인.
    브라우저가 자동으로 열리고 사용자가 구글 동의 페이지를 거치면 콜백으로 토큰을 받음.

    Args:
        user_name: 토큰을 어떤 이름으로 저장할지
        port: 0이면 임의 포트 자동 선택 (권장)

    Returns:
        { "ok": bool, "email": str or None, "error": str or None }
    """
    if not is_oauth_client_configured():
        return {
            "ok": False,
            "email": None,
            "error": (
                f"OAuth 클라이언트 파일이 없습니다: {OAUTH_CLIENT_PATH}\n"
                "Google Cloud Console에서 OAuth 2.0 클라이언트(Desktop)를 만들고 "
                "다운받은 JSON을 위 경로에 저장하세요."
            ),
        }

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(OAUTH_CLIENT_PATH),
            scopes=SCOPES,
        )
        creds = flow.run_local_server(
            port=port,
            prompt="consent",
            access_type="offline",
            authorization_prompt_message=(
                "👉 브라우저에서 Google 로그인 + 동의를 완료해주세요..."
            ),
            success_message=(
                "✅ 로그인 완료! 이 창은 닫으셔도 됩니다."
            ),
            open_browser=True,
        )
    except Exception as e:
        return {"ok": False, "email": None, "error": f"OAuth 흐름 오류: {e}"}

    # 이메일 알아내기 (userinfo)
    email = None
    try:
        from googleapiclient.discovery import build
        oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = oauth2.userinfo().get().execute()
        email = info.get("email")
    except Exception:
        # 패키지 없거나 호출 실패해도 토큰 자체는 저장
        pass

    _save_credentials(user_name, creds, email=email)
    return {"ok": True, "email": email, "error": None}


def revoke_user(user_name: str) -> bool:
    """저장된 토큰 삭제 (= 이 앱에서 로그아웃)."""
    p = token_path_for(user_name)
    if p.exists():
        try:
            p.unlink()
            return True
        except Exception:
            return False
    return False


# =============================================================================
# gspread 클라이언트 만들기
# =============================================================================

def get_gspread_client(user_name: str) -> Optional[gspread.Client]:
    """
    OAuth 사용자 토큰으로 gspread 클라이언트 생성.
    토큰 없거나 refresh 실패 시 None.
    """
    creds = _load_credentials(user_name)
    if not creds:
        return None
    return gspread.authorize(creds)


# =============================================================================
# CLI 진입점 (테스트용)
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google OAuth 로그인")
    parser.add_argument("--user", default="default", help="사용자 식별자")
    args = parser.parse_args()

    print(f"[OAuth] 사용자 '{args.user}' 로그인 시작...")
    result = start_login_flow(args.user)
    if result["ok"]:
        print(f"✅ 로그인 성공 (email: {result.get('email') or '(불명)'})")
    else:
        print(f"❌ {result['error']}")
