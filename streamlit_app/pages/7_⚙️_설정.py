"""
⚙️ 설정 페이지

settings.json을 GUI로 안전하게 편집.
JSON 직접 수정으로 인한 문법 오류 방지.
"""
import sys
import json
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    SETTINGS_PATH,
    PROJECT_ROOT,
    load_settings,
    save_settings,
    page_header,
)

setup_page("설정", "⚙️")
ensure_directories()
render_sidebar("settings")


# =============================================================================
# 헤더
# =============================================================================

page_header("설정", "⚙️",
            "구글 시트·가게 정보·자격 등급을 관리합니다. 변경하면 settings.json에 자동 저장됩니다.")

st.divider()

# 설정 로드
settings = load_settings()

# 빈 설정일 때 기본값 채우기
if not settings:
    settings = {
        "google_sheets": {
            "credentials_path": "config/google_credentials.json",
            "campaigns": {},
        },
        "blogdex": {
            "qualified_grades": [
                "준최6", "준최7",
                "최적1", "최적2", "최적3",
                "최적1+", "최적2+", "최적3+", "최적4+",
            ],
            "batch_size": 3,
            "wait_seconds_between_batches": 60,
        },
    }

# =============================================================================
# 탭
# =============================================================================

(
    tab_campaigns,
    tab_credentials,
    tab_blogdex,
    tab_blogdex_login,
    tab_security,
    tab_backup,
    tab_license,
    tab_advanced,
) = st.tabs([
    "🏪 캠페인 (시트)",
    "🔑 Google 인증",
    "🎯 블덱스 설정",
    "👤 블덱스 로그인",
    "🔒 보안 / 외부 접속",
    "💾 백업 / 복원",
    "🔑 라이선스",
    "🔧 고급 (JSON 직접 편집)",
])

with tab_license:
    st.markdown("### 🔑 라이선스")
    try:
        from licensing import license_core
        from licensing.plans import FEATURES, PLAN_LABELS
        from utils import _licensing_active
        _lic_ok = True
    except Exception:
        _lic_ok = False
        st.info("이 빌드에는 라이선스 모듈이 없습니다 (개발 버전).")

    if _lic_ok:
        if not _licensing_active():
            st.success("✅ 개발/무제한 모드 — 라이선스 게이팅이 꺼져 있습니다.")
            st.caption("판매 빌드에는 공개키(pubkey.pem)가 내장되어 라이선스가 필요합니다.")
        else:
            status = license_core.load_active()
            if status.get("valid"):
                p = status.get("payload", {}) or {}
                st.success(f"✅ 유효한 라이선스 · **{PLAN_LABELS.get(status.get('plan',''), status.get('plan','') or '커스텀')}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("고객", p.get("cust", "—"))
                c2.metric("만료일", p.get("exp") or "무기한")
                dl = status.get("days_left")
                c3.metric("남은 기간", f"{dl}일" if isinstance(dl, int) else "—")
                st.caption("사용 가능 기능: " + ", ".join(
                    FEATURES.get(f, f) for f in status.get("features", [])))
            else:
                st.error(f"❌ 라이선스 없음/무효 — {status.get('reason','')}")

        st.markdown("#### 라이선스 키 등록")
        with st.form("register_license_form"):
            key_in = st.text_area("라이선스 키 (MKT1.... 형식)", height=110,
                                  placeholder="MKT1.xxxxx.yyyyy")
            if st.form_submit_button("등록", type="primary"):
                res = license_core.save_active(key_in.strip())
                if res.get("valid"):
                    st.session_state.pop("_license_status", None)
                    st.success("✅ 등록되었습니다.")
                    st.rerun()
                else:
                    st.error(f"등록 실패: {res.get('reason','')}")
        if st.button("🗑️ 등록된 라이선스 제거"):
            license_core.remove_active()
            st.session_state.pop("_license_status", None)
            st.rerun()


# =============================================================================
# 탭 1: 캠페인
# =============================================================================

with tab_campaigns:
    st.markdown("### 🏪 캠페인 (가게 / 구글 시트)")
    st.caption(
        "각 가게에 대응하는 구글 시트 정보를 등록합니다. "
        "여러 가게를 운영하시면 여러 캠페인을 등록하면 돼요."
    )
    
    # 현재 등록된 캠페인 목록
    campaigns = settings.get("google_sheets", {}).get("campaigns", {})
    
    if campaigns:
        st.markdown(f"**현재 등록된 캠페인: {len(campaigns)}개**")
        
        for cname, cinfo in list(campaigns.items()):
            with st.container(border=True):
                col_t, col_d = st.columns([5, 1])
                with col_t:
                    st.markdown(f"#### 🏷️ {cname}")
                with col_d:
                    if st.button("🗑️ 삭제", key=f"del_camp_{cname}"):
                        del settings["google_sheets"]["campaigns"][cname]
                        if save_settings(settings):
                            st.success(f"✓ '{cname}' 삭제됨")
                            st.rerun()
                
                # 편집 필드들
                col1, col2 = st.columns(2)
                
                with col1:
                    new_sheet_id = st.text_input(
                        "구글 시트 ID",
                        value=cinfo.get("spreadsheet_id", ""),
                        key=f"sid_{cname}",
                        help="구글 시트 URL의 /d/ 와 /edit 사이 부분",
                    )
                    new_main_sheet = st.text_input(
                        "메인 시트 탭 이름",
                        value=cinfo.get("main_sheet_name", ""),
                        key=f"main_{cname}",
                        help="예: 4월, 5월, 시트1 등",
                    )
                    new_rejected_sheet = st.text_input(
                        "미달자 시트 탭 이름",
                        value=cinfo.get("rejected_sheet_name", "미달자"),
                        key=f"rej_{cname}",
                    )
                
                with col2:
                    new_url_col = st.text_input(
                        "블로그주소 컬럼",
                        value=cinfo.get("blog_url_column", "C"),
                        key=f"url_{cname}",
                        help="알파벳 (예: C, D)",
                    )
                    new_grade_col = st.text_input(
                        "지수 컬럼",
                        value=cinfo.get("grade_column", "D"),
                        key=f"gr_{cname}",
                        help="알파벳 (예: C, D)",
                    )
                
                # 변경사항 저장
                if (new_sheet_id != cinfo.get("spreadsheet_id", "") or
                    new_main_sheet != cinfo.get("main_sheet_name", "") or
                    new_rejected_sheet != cinfo.get("rejected_sheet_name", "미달자") or
                    new_url_col != cinfo.get("blog_url_column", "C") or
                    new_grade_col != cinfo.get("grade_column", "D")):
                    
                    if st.button(f"💾 '{cname}' 저장", key=f"save_{cname}", type="primary"):
                        settings["google_sheets"]["campaigns"][cname] = {
                            "spreadsheet_id": new_sheet_id,
                            "main_sheet_name": new_main_sheet,
                            "rejected_sheet_name": new_rejected_sheet,
                            "blog_url_column": new_url_col.upper(),
                            "grade_column": new_grade_col.upper(),
                        }
                        if save_settings(settings):
                            st.success(f"✓ '{cname}' 저장됨")
                            st.rerun()
                
                # 시트 바로가기
                if cinfo.get("spreadsheet_id"):
                    st.markdown(
                        f"🔗 [시트 열기](https://docs.google.com/spreadsheets/d/"
                        f"{cinfo['spreadsheet_id']})"
                    )
    else:
        st.info("아직 등록된 캠페인이 없어요. 아래에서 새 캠페인을 추가해주세요.")
    
    # 새 캠페인 추가
    st.markdown("---")
    st.markdown("### ➕ 새 캠페인 추가")
    
    with st.form("add_campaign"):
        col1, col2 = st.columns(2)
        
        with col1:
            new_cname = st.text_input(
                "캠페인 이름 (영문 권장)",
                placeholder="예: restaurant, skin, cafe 등",
                help="알파벳/숫자만 사용 권장",
            )
            new_spreadsheet_id = st.text_input(
                "구글 시트 ID",
                placeholder="예: 1ABC...XYZ",
            )
            new_main = st.text_input(
                "메인 시트 탭 이름",
                placeholder="예: 4월",
            )
        
        with col2:
            new_rejected = st.text_input(
                "미달자 시트 탭 이름",
                value="미달자",
            )
            new_url_c = st.text_input("블로그주소 컬럼", value="C")
            new_grade_c = st.text_input("지수 컬럼", value="D")
        
        submitted = st.form_submit_button("➕ 캠페인 추가", type="primary")
        
        if submitted:
            if not new_cname:
                st.error("캠페인 이름을 입력해주세요.")
            elif new_cname in campaigns:
                st.error(f"'{new_cname}' 캠페인이 이미 존재합니다.")
            elif not new_spreadsheet_id:
                st.error("구글 시트 ID를 입력해주세요.")
            elif not new_main:
                st.error("메인 시트 탭 이름을 입력해주세요.")
            else:
                if "google_sheets" not in settings:
                    settings["google_sheets"] = {}
                if "campaigns" not in settings["google_sheets"]:
                    settings["google_sheets"]["campaigns"] = {}
                
                settings["google_sheets"]["campaigns"][new_cname] = {
                    "spreadsheet_id": new_spreadsheet_id,
                    "main_sheet_name": new_main,
                    "rejected_sheet_name": new_rejected,
                    "blog_url_column": new_url_c.upper(),
                    "grade_column": new_grade_c.upper(),
                }
                
                if save_settings(settings):
                    st.success(f"✓ '{new_cname}' 캠페인이 추가되었어요!")
                    st.rerun()
    
    # 추가 안내
    with st.expander("💡 시트 ID는 어디서 보나요?"):
        st.markdown(
            """
구글 시트 URL 예시:
```
https://docs.google.com/spreadsheets/d/  여기에_구글시트_ID  /edit
                                          ↑ 이 부분이 시트 ID ↑
```

**중요**: 시트에 서비스 계정 이메일을 **편집자 권한**으로 공유해야 합니다.
서비스 계정 이메일은 `config/google_credentials.json` 파일 안의 `client_email` 필드에서 확인할 수 있어요.
"""
        )


# =============================================================================
# 탭 2: Google 인증 (credentials.json 업로드)
# =============================================================================

with tab_credentials:
    st.markdown("### 🔑 Google 시트 접근 방식")

    auth_mode_now = settings.get("google_sheets", {}).get("auth_mode", "service")
    st.caption(
        f"현재 활성 모드: **{'OAuth (본인 구글 계정)' if auth_mode_now == 'oauth' else '서비스 계정 (봇)'}**"
    )

    sub_service, sub_oauth = st.tabs([
        "🤖 서비스 계정 (기본)",
        "👤 본인 구글 계정 (OAuth)",
    ])

    # ============================================================
    # 서비스 계정 탭
    # ============================================================
    with sub_service:
        st.caption(
            "**서비스 계정**은 별도 봇 계정으로 시트에 접근합니다. "
            "각 시트에 봇의 이메일을 **편집자 권한**으로 공유해야 사용할 수 있어요."
        )

        if auth_mode_now != "service":
            if st.button("🤖 이 모드(서비스 계정)를 활성화", key="switch_to_service"):
                settings.setdefault("google_sheets", {})["auth_mode"] = "service"
                if save_settings(settings):
                    st.success("✓ 서비스 계정 모드로 전환됨")
                    st.rerun()

        credentials_path = PROJECT_ROOT / "config" / "google_credentials.json"

        # 현재 상태 표시
        if credentials_path.exists():
            try:
                with open(credentials_path, encoding="utf-8") as f:
                    cred_data = json.load(f)
                client_email = cred_data.get("client_email", "(이메일 정보 없음)")
                project_id = cred_data.get("project_id", "(프로젝트 정보 없음)")

                st.success("✅ 인증 파일이 등록되어 있습니다.")
                with st.container(border=True):
                    st.markdown(
                        f"**서비스 계정 이메일** (시트 공유 시 사용):  \n"
                        f"`{client_email}`"
                    )
                    st.markdown(f"**프로젝트 ID**: `{project_id}`")

                    col_copy, col_del = st.columns([3, 1])
                    with col_copy:
                        st.code(client_email, language="text")
                        st.caption("👆 이 이메일을 본인의 구글 시트에 **편집자 권한**으로 공유하세요.")
                    with col_del:
                        if st.button("🗑️ 인증 삭제", key="del_creds", help="현재 인증 파일을 삭제합니다"):
                            try:
                                credentials_path.unlink()
                                st.success("✓ 삭제됨")
                                st.rerun()
                            except Exception as e:
                                st.error(f"삭제 실패: {e}")
            except Exception as e:
                st.error(f"❌ 인증 파일이 손상됐습니다: {e}")
                st.caption("아래에서 새 파일을 업로드해주세요.")
        else:
            st.warning("⚠️ 아직 인증 파일이 없습니다. 아래에서 업로드해주세요.")

        st.markdown("---")
        st.markdown("#### 📤 인증 파일 업로드")

        with st.expander("📚 인증 파일은 어떻게 만드나요? (처음이라면 꼭 읽어주세요)"):
            st.markdown(
                """
**Google Cloud Console에서 서비스 계정 키 받기**:

1. https://console.cloud.google.com/ 접속 (구글 계정 로그인)
2. 새 프로젝트 만들기
3. **API 활성화**: Google Sheets API + Google Drive API
4. **서비스 계정 생성** → "키 추가" → **JSON 선택** → 다운로드
5. 받은 .json 파일을 아래에 업로드
6. 업로드 후 표시되는 **서비스 계정 이메일**을 본인 시트에 **편집자**로 공유
"""
            )

        uploaded_creds = st.file_uploader(
            "Google 서비스 계정 키 파일 (.json)",
            type=["json"],
            key="creds_uploader",
            help="Google Cloud Console에서 다운받은 .json 파일을 그대로 올려주세요.",
        )

        if uploaded_creds is not None:
            try:
                content = uploaded_creds.read()
                cred_data = json.loads(content.decode("utf-8"))

                required_fields = ["type", "client_email", "private_key", "project_id"]
                missing = [f for f in required_fields if f not in cred_data]

                if missing:
                    st.error(f"❌ 누락된 필드: {', '.join(missing)}")
                elif cred_data.get("type") != "service_account":
                    st.error(f"❌ 서비스 계정 키 파일이어야 합니다 (받은 타입: {cred_data.get('type')})")
                else:
                    st.success("✅ 파일 검증 통과")
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        st.markdown(f"**서비스 계정**: `{cred_data['client_email']}`")
                    with col_p2:
                        st.markdown(f"**프로젝트**: `{cred_data['project_id']}`")

                    if st.button("💾 이 파일을 저장하기", type="primary", key="save_creds"):
                        try:
                            credentials_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(credentials_path, "w", encoding="utf-8") as f:
                                json.dump(cred_data, f, ensure_ascii=False, indent=2)
                            st.success("✅ 저장 완료!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {e}")
            except json.JSONDecodeError:
                st.error("❌ 올바른 JSON 파일이 아닙니다.")
            except Exception as e:
                st.error(f"❌ 파일 처리 오류: {e}")

    # ============================================================
    # OAuth 탭
    # ============================================================
    with sub_oauth:
        st.caption(
            "**OAuth**는 본인 구글 계정으로 직접 시트에 접근합니다. "
            "본인이 권한 가진 시트는 추가 공유 없이 바로 쓸 수 있어요. "
            "(NAS 등 무인 서버에선 첫 로그인 시 한 번 사람이 직접 동의해야 합니다.)"
        )

        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        try:
            from google_oauth.oauth_flow import (
                is_oauth_client_configured,
                list_oauth_users,
                start_login_flow as oauth_login,
                revoke_user as oauth_revoke,
                get_user_email as oauth_user_email,
                OAUTH_CLIENT_PATH,
            )
            oauth_available = True
        except Exception as e:
            oauth_available = False
            st.error(f"OAuth 모듈 로드 실패: {e}")

        if oauth_available:
            # 모드 전환
            if auth_mode_now != "oauth":
                if st.button("👤 이 모드(OAuth)를 활성화", key="switch_to_oauth"):
                    settings.setdefault("google_sheets", {})["auth_mode"] = "oauth"
                    if "oauth_user" not in settings["google_sheets"]:
                        users = list_oauth_users()
                        settings["google_sheets"]["oauth_user"] = users[0] if users else "default"
                    if save_settings(settings):
                        st.success("✓ OAuth 모드로 전환됨")
                        st.rerun()

            st.markdown("---")
            st.markdown("#### 🔧 OAuth 클라이언트 등록 (1회만)")

            with st.expander("📚 OAuth 클라이언트는 어떻게 만드나요?"):
                st.markdown(
                    """
1. https://console.cloud.google.com/ → API 및 서비스 → **OAuth 동의 화면**
   - User Type: **외부** (External)
   - 본인 이메일을 **테스트 사용자**에 추가
2. **사용자 인증 정보** → "+ 사용자 인증 정보 만들기" → **OAuth 클라이언트 ID**
   - 애플리케이션 유형: **데스크톱 앱** (Desktop app)
3. 생성된 항목의 **JSON 다운로드** 버튼 클릭
4. 받은 .json 파일을 아래에 업로드
"""
                )

            if is_oauth_client_configured():
                st.success("✅ OAuth 클라이언트가 등록되어 있습니다.")
                if st.button("🗑️ OAuth 클라이언트 삭제", key="del_oauth_client"):
                    try:
                        OAUTH_CLIENT_PATH.unlink(missing_ok=True)
                        st.success("✓ 삭제됨")
                        st.rerun()
                    except Exception as e:
                        st.error(f"삭제 실패: {e}")
            else:
                st.warning("⚠️ OAuth 클라이언트 파일이 없습니다.")

            uploaded_oauth = st.file_uploader(
                "Desktop OAuth 클라이언트 (.json)",
                type=["json"],
                key="oauth_client_uploader",
            )
            if uploaded_oauth is not None:
                # getvalue()는 파일 포인터를 소비하지 않음 (read()는 첫 호출 후 비어있을 수 있음)
                try:
                    raw = uploaded_oauth.getvalue()
                    parsed = json.loads(raw.decode("utf-8"))
                except Exception as e:
                    parsed = None
                    st.error(f"❌ JSON 파싱 실패: {e}")

                if parsed is not None:
                    if "installed" not in parsed and "web" not in parsed:
                        st.error("❌ Desktop 앱 OAuth 클라이언트 JSON이 아닙니다 ('installed' 또는 'web' 키 필요).")
                    else:
                        # 미리보기
                        client_id = (
                            parsed.get("installed", {}).get("client_id")
                            or parsed.get("web", {}).get("client_id", "")
                        )
                        st.info(f"📦 client_id: `{client_id[:30]}…`")

                        # 자동 저장 X — 버튼 확인 방식 (무한 리로드 방지)
                        if st.button(
                            "💾 이 OAuth 클라이언트를 저장",
                            type="primary",
                            key="save_oauth_client_btn",
                        ):
                            try:
                                OAUTH_CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
                                with open(OAUTH_CLIENT_PATH, "w", encoding="utf-8") as f:
                                    json.dump(parsed, f, ensure_ascii=False, indent=2)
                                st.success("✅ OAuth 클라이언트 저장 완료")
                                st.rerun()
                            except Exception as e:
                                st.error(f"저장 실패: {e}")

            st.markdown("---")
            st.markdown("#### 👥 OAuth 사용자 (구글 계정)")

            existing_oauth_users = list_oauth_users()
            current_oauth_user = (
                settings.get("google_sheets", {}).get("oauth_user", "default")
            )

            if existing_oauth_users:
                for u in existing_oauth_users:
                    with st.container(border=True):
                        col_u, col_a, col_d = st.columns([4, 2, 1])
                        with col_u:
                            email = oauth_user_email(u) or "(이메일 정보 없음)"
                            mark = "🟢 활성" if u == current_oauth_user and auth_mode_now == "oauth" else ""
                            st.markdown(f"**{u}** {mark}")
                            st.caption(f"📧 {email}")
                        with col_a:
                            if u != current_oauth_user:
                                if st.button("이 계정 사용", key=f"use_oauth_{u}"):
                                    settings.setdefault("google_sheets", {})["oauth_user"] = u
                                    if save_settings(settings):
                                        st.success(f"✓ '{u}' 활성화")
                                        st.rerun()
                        with col_d:
                            if st.button("🗑️", key=f"del_oauth_{u}", help="이 계정의 토큰 제거"):
                                if oauth_revoke(u):
                                    st.success("✓ 제거됨")
                                    st.rerun()
            else:
                st.info("아직 OAuth 로그인한 구글 계정이 없어요.")

            st.markdown("##### ➕ 새 구글 계정 로그인")
            st.caption(
                "버튼을 누르면 브라우저가 열려 Google 동의 페이지가 뜹니다. "
                "동의 후 자동으로 토큰이 저장됩니다."
            )
            new_oauth_user = st.text_input(
                "이 계정을 어떤 이름으로 저장할까요?",
                value="default",
                key="new_oauth_user_input",
                help="여러 구글 계정을 쓰시면 각자 다른 이름 (예: soom, sub_account 등)",
            )

            if not is_oauth_client_configured():
                st.warning("먼저 위에서 OAuth 클라이언트 파일을 업로드해주세요.")
            else:
                if st.button(
                    "🚀 브라우저 열어서 Google 로그인",
                    type="primary",
                    disabled=not new_oauth_user,
                    key="start_oauth_login",
                ):
                    cmd = [
                        sys.executable,
                        str(PROJECT_ROOT / "src" / "google_oauth" / "oauth_flow.py"),
                        "--user", new_oauth_user,
                    ]
                    sys.path.insert(0, str(PROJECT_ROOT / "streamlit_app"))
                    try:
                        from background_jobs import start_job as bg_start_job
                        job_id = bg_start_job(
                            cmd=cmd,
                            job_type="OAuth로그인",
                            description=f"OAuth: {new_oauth_user}",
                        )
                        st.session_state["current_oauth_job"] = job_id
                        st.success(
                            "✅ 브라우저가 곧 열립니다!\n\n"
                            "Google 동의 화면이 뜨면 본인 계정으로 로그인+허용해주세요. "
                            "완료되면 자동으로 토큰이 저장됩니다."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"로그인 시작 실패: {e}")

            # 진행 중 OAuth 작업 상태
            current_oauth_job = st.session_state.get("current_oauth_job")
            if current_oauth_job:
                sys.path.insert(0, str(PROJECT_ROOT / "streamlit_app"))
                try:
                    from background_jobs import get_job_status, read_log
                    status = get_job_status(current_oauth_job)
                    if status.get("running"):
                        st.info("🔄 OAuth 진행 중... 브라우저에서 동의해주세요.")
                        st.button("🔄 새로고침", key="refresh_oauth")
                    else:
                        ec = status.get("exit_code")
                        if ec == 0 or ec is None:
                            st.success("✅ OAuth 완료!")
                        else:
                            st.error(f"❌ OAuth 실패 (코드 {ec})")
                        if st.button("닫기", key="close_oauth_msg"):
                            st.session_state.pop("current_oauth_job", None)
                            st.rerun()
                    with st.expander("📺 OAuth 로그", expanded=True):
                        st.code(read_log(current_oauth_job, max_lines=30) or "(로그 대기)", language="text")
                except Exception:
                    pass


# =============================================================================
# 탭 3: 블덱스 설정
# =============================================================================

with tab_blogdex:
    st.markdown("### 🎯 블덱스 설정")
    
    blogdex = settings.get("blogdex", {})
    
    st.markdown("#### 자격 등급")
    st.caption("이 등급에 해당하는 블로거만 자격자로 분류됩니다.")
    
    current_grades = blogdex.get(
        "qualified_grades",
        ["준최6", "준최7", "최적1", "최적2", "최적3", "최적1+", "최적2+", "최적3+", "최적4+"],
    )
    
    # 기본 등급 옵션
    all_possible_grades = [
        "준최1", "준최2", "준최3", "준최4", "준최5", "준최6", "준최7",
        "최적1", "최적2", "최적3", "최적4",
        "최적1+", "최적2+", "최적3+", "최적4+",
    ]
    
    new_grades = st.multiselect(
        "자격 등급 선택",
        options=all_possible_grades,
        default=[g for g in current_grades if g in all_possible_grades],
    )
    
    # 추가 등급 (사용자 정의)
    custom_grade = st.text_input(
        "기타 등급 추가 (선택)",
        placeholder="목록에 없는 등급을 추가하려면 여기에",
    )
    if custom_grade and custom_grade not in new_grades:
        new_grades.append(custom_grade)
        st.caption(f"추가됨: {custom_grade}")
    
    st.markdown("---")
    
    st.markdown("#### 조회 속도 (Cloudflare 차단 회피)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_batch_size = st.number_input(
            "배치 크기 (한 번에 조회할 블로거 수)",
            min_value=1,
            max_value=10,
            value=blogdex.get("batch_size", 3),
            help="블덱스가 짧은 시간에 많이 조회하면 차단할 수 있어서 배치로 나눠 조회합니다.",
        )
    
    with col2:
        new_wait = st.number_input(
            "배치 간 대기 시간 (초)",
            min_value=10,
            max_value=300,
            value=blogdex.get("wait_seconds_between_batches", 60),
            help="배치와 배치 사이 대기 시간. 너무 짧으면 차단될 수 있어요.",
        )
    
    if st.button("💾 블덱스 설정 저장", type="primary"):
        if "blogdex" not in settings:
            settings["blogdex"] = {}
        settings["blogdex"]["qualified_grades"] = new_grades
        settings["blogdex"]["batch_size"] = int(new_batch_size)
        settings["blogdex"]["wait_seconds_between_batches"] = int(new_wait)
        
        if save_settings(settings):
            st.success("✓ 블덱스 설정 저장됨")
            st.rerun()


# =============================================================================
# 탭 4: 블덱스 로그인 (UI에서 직접 시작)
# =============================================================================

with tab_blogdex_login:
    st.markdown("### 👤 블덱스 로그인")
    st.caption(
        "터미널 없이 여기서 클릭만으로 블덱스 로그인을 진행할 수 있어요. "
        "여러 사용자가 같은 PC를 쓰신다면 사용자별로 따로 로그인하세요."
    )
    
    # 현재 등록된 사용자 목록
    sys.path.insert(0, str(PROJECT_ROOT / "src" / "blogdex"))
    try:
        from session import list_users as list_blogdex_users
        existing_users = list_blogdex_users()
    except Exception:
        existing_users = []
    
    # 등록된 사용자 표시
    st.markdown("#### 📋 현재 등록된 사용자")
    if existing_users:
        for user in existing_users:
            with st.container(border=True):
                col_u, col_d = st.columns([4, 1])
                with col_u:
                    st.markdown(f"👤 **{user}**")
                    sessions_dir = PROJECT_ROOT / "config" / "blogdex_sessions"
                    legacy_path = PROJECT_ROOT / "config" / "blogdex_session.json"
                    user_path = sessions_dir / f"{user}.json"
                    if user_path.exists():
                        from datetime import datetime as _dt
                        mtime = _dt.fromtimestamp(user_path.stat().st_mtime)
                        st.caption(f"마지막 로그인: {mtime.strftime('%Y-%m-%d %H:%M')}")
                    elif user == "default" and legacy_path.exists():
                        from datetime import datetime as _dt
                        mtime = _dt.fromtimestamp(legacy_path.stat().st_mtime)
                        st.caption(f"마지막 로그인: {mtime.strftime('%Y-%m-%d %H:%M')}")
                with col_d:
                    if st.button("🗑️", key=f"del_user_{user}", help="이 사용자 삭제"):
                        try:
                            sessions_dir = PROJECT_ROOT / "config" / "blogdex_sessions"
                            user_path = sessions_dir / f"{user}.json"
                            legacy_path = PROJECT_ROOT / "config" / "blogdex_session.json"
                            if user_path.exists():
                                user_path.unlink()
                            elif user == "default" and legacy_path.exists():
                                legacy_path.unlink()
                            st.success(f"✓ '{user}' 삭제됨")
                            st.rerun()
                        except Exception as e:
                            st.error(f"삭제 실패: {e}")
    else:
        st.info("아직 등록된 사용자가 없어요. 아래에서 첫 사용자를 추가해주세요.")
    
    st.markdown("---")
    
    # 새 로그인
    st.markdown("#### ➕ 새 사용자 로그인")
    st.caption(
        "**작동 방식**: 버튼을 누르면 자동으로 브라우저 창이 열립니다. "
        "본인의 구글 계정으로 로그인하시면 끝!"
    )
    
    new_user_name = st.text_input(
        "사용자 이름 (영문/숫자/한글 가능)",
        placeholder="예: soom, 영희, account_b",
        help="이 이름으로 세션이 저장됩니다. 여러 명이 사용하시면 각자 다른 이름 사용.",
        key="new_user_name_input",
    )
    
    # 백그라운드 작업 진행 상황
    sys.path.insert(0, str(PROJECT_ROOT / "streamlit_app"))
    try:
        from background_jobs import (
            start_job as bg_start_job,
            get_job_status,
            read_log,
            list_jobs,
        )
        bg_available = True
    except Exception as e:
        bg_available = False
        st.error(f"백그라운드 작업 모듈 로드 실패: {e}")
    
    if bg_available:
        col_login_btn, col_status = st.columns([1, 1])
        
        with col_login_btn:
            login_disabled = not new_user_name
            if st.button(
                "🚀 브라우저 열어서 로그인 시작",
                disabled=login_disabled,
                type="primary",
                use_container_width=True,
            ):
                # 블덱스 로그인 명령 실행
                cmd = [
                    sys.executable,
                    str(PROJECT_ROOT / "src" / "blogdex" / "session.py"),
                    "--user", new_user_name,
                    "--auto-confirm",  # UI에서 시작하므로 Enter 입력 없이 자동 진행
                ]
                
                try:
                    job_id = bg_start_job(
                        cmd=cmd,
                        job_type="블덱스로그인",
                        description=f"사용자 '{new_user_name}' 로그인",
                    )
                    st.session_state["current_login_job"] = job_id
                    st.success(
                        "✅ 브라우저가 곧 열립니다!\n\n"
                        "1. 새 브라우저 창에서 본인 구글 계정으로 로그인\n"
                        "2. 블덱스 메인 페이지가 보이면 로그인 완료\n"
                        "3. 자동으로 세션이 저장되고 창이 닫힙니다"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"로그인 시작 실패: {e}")
            
            if login_disabled:
                st.caption("⚠️ 사용자 이름을 입력해주세요")
        
        # 진행 중인 작업 표시
        current_job_id = st.session_state.get("current_login_job")
        if current_job_id:
            with col_status:
                status = get_job_status(current_job_id)
                if status:
                    if status.get("running"):
                        st.info("🔄 로그인 진행 중...")
                        # 자동 새로고침 (3초마다)
                        st.button("🔄 새로고침", key="refresh_login")
                    else:
                        exit_code = status.get("exit_code")
                        if exit_code == 0:
                            st.success("✅ 로그인 완료!")
                            if st.button("확인 (이 메시지 닫기)", key="close_login_msg"):
                                st.session_state.pop("current_login_job", None)
                                st.rerun()
                        else:
                            st.error(f"❌ 로그인 실패 (코드: {exit_code})")
                            if st.button("다시 시도", key="retry_login"):
                                st.session_state.pop("current_login_job", None)
                                st.rerun()
        
        # 로그 표시
        if current_job_id:
            with st.expander("📺 로그인 진행 로그", expanded=True):
                log_text = read_log(current_job_id, max_lines=30)
                if log_text:
                    st.code(log_text, language="text")
                else:
                    st.caption("로그 대기 중...")


# =============================================================================
# 탭 5: 보안 / 외부 접속 (비밀번호 + ngrok 안내)
# =============================================================================

with tab_security:
    st.markdown("### 🔒 보안 설정 + 외부 접속")
    st.caption(
        "재택근무 동료가 인터넷으로 접속할 수 있게 하려면 "
        "**비밀번호를 꼭 설정**하세요."
    )
    
    # auth 모듈 임포트
    sys.path.insert(0, str(PROJECT_ROOT / "streamlit_app"))
    try:
        from auth import is_auth_enabled, set_password, disable_auth, AUTH_PATH
        auth_available = True
    except Exception as e:
        st.error(f"auth 모듈 로드 실패: {e}")
        auth_available = False
    
    if auth_available:
        # 현재 인증 상태
        st.markdown("#### 🔐 비밀번호 인증")
        
        if is_auth_enabled():
            st.success("✅ 비밀번호 인증이 **활성화**되어 있습니다.")
            st.caption("새로 접속하는 사용자는 비밀번호를 입력해야 들어올 수 있어요.")
        else:
            st.warning(
                "⚠️ 비밀번호 인증이 **비활성화**되어 있습니다.\n\n"
                "본인 PC에서만 사용하시면 OK이지만, "
                "**외부에서 접속하실 거라면 꼭 비밀번호를 설정하세요.**"
            )
        
        st.markdown("---")
        
        # 비밀번호 설정/변경
        col_pw1, col_pw2 = st.columns(2)
        
        with col_pw1:
            st.markdown("##### 비밀번호 설정 / 변경")
            with st.form("set_password_form"):
                new_pw = st.text_input("새 비밀번호", type="password")
                new_pw_confirm = st.text_input("비밀번호 확인", type="password")
                
                submitted = st.form_submit_button("💾 저장", type="primary")
                
                if submitted:
                    if not new_pw:
                        st.error("비밀번호를 입력해주세요.")
                    elif len(new_pw) < 4:
                        st.error("비밀번호는 4자 이상으로 해주세요.")
                    elif new_pw != new_pw_confirm:
                        st.error("두 비밀번호가 일치하지 않습니다.")
                    else:
                        if set_password(new_pw):
                            st.success(
                                "✅ 비밀번호가 저장되었습니다!\n\n"
                                "다음 접속부터 비밀번호를 입력해야 합니다. "
                                "동료들에게 비밀번호를 안전하게 전달하세요."
                            )
                        else:
                            st.error("저장 실패")
        
        with col_pw2:
            st.markdown("##### 인증 비활성화")
            st.caption(
                "비밀번호 인증을 끄고 싶을 때 사용. "
                "본인 PC만 쓰시면 OK이지만 외부 접속 시 **위험**."
            )
            if is_auth_enabled():
                if st.button("🔓 비밀번호 인증 해제", help="외부 접속 안 하실 때만"):
                    if disable_auth():
                        st.success("✓ 인증이 해제되었습니다.")
                        st.rerun()
            else:
                st.info("이미 인증이 비활성화되어 있어요.")
    
    st.info(
        "☁️ **클라우드(Streamlit) 배포에서는** 비밀번호를 위 폼이 아니라 "
        "**앱 Secrets**에 넣어야 영구 유지됩니다. (배포 환경은 재시작 시 파일이 초기화되기 때문)\n\n"
        "Streamlit 대시보드 → App settings → **Secrets** 에 아래 한 줄을 추가하세요:\n"
        "```toml\napp_password = \"원하는비밀번호\"\n```"
    )

    st.divider()

    # 외부 접속 안내 — 무료 클라우드 공유
    st.markdown("### 🌐 다른 사람이 접속하게 하기 (무료 클라우드)")
    st.caption(
        "코드를 무료 클라우드(Streamlit Community Cloud)에 올리면 고정 주소(URL)가 생기고, "
        "그 링크만 공유하면 누구나 설치 없이 브라우저로 접속합니다."
    )

    with st.expander("📚 무료 클라우드 배포 — 핵심 5단계", expanded=False):
        st.markdown(
            """
1. **GitHub 공개 저장소**에 코드 push
   *(push 전 `git status`에 `config/settings.json`·세션 파일이 없어야 함 — `.gitignore`가 막아줌)*
2. <https://share.streamlit.io> 접속 → **Create app** → 저장소 선택
   → Main file: **`streamlit_app/홈.py`** → Deploy
3. **Settings → Secrets** 에 설정 넣기:
   ```toml
   settings_json = '''{ ... config/settings.json 내용 ... }'''
   app_password  = "원하는비밀번호"   # (선택) 아는 사람만 접속하게
   ```
4. 만들어진 주소 **`https://<앱이름>.streamlit.app`** 를 카톡 등으로 공유
5. 받은 사람은 **링크 클릭 → (비번 설정 시) 비밀번호 입력** 만으로 사용

> 📄 자세한 단계·주의사항: 프로젝트의 **`docs/DEPLOY_STREAMLIT.md`**

#### ⚠️ 알아둘 점
- 링크를 아는 사람은 누구나 접속 → **위 `app_password` 로 보호** 권장
- 모두 **같은 화면·데이터·네이버 세션을 공유** (계정 분리 X)
- **네이버 댓글모집(실제 크롬 연결)** 은 클라우드에 데스크톱 크롬이 없어 작동 안 함 → 본인 PC 전용
- 무료 메모리가 작으니 검수 **동시 처리 수 1~2** 권장
"""
        )

    st.divider()

    # NAS 배포 안내
    st.markdown("### 🏠 NAS 배포 (24시간 자동 운영)")
    st.caption(
        "본인 PC를 24시간 켜두지 않아도 자동 검수·시트 분류가 매일 돌아가게 하려면 "
        "시놀로지/QNAP NAS에 Docker 컨테이너로 배포하세요."
    )

    nas_guide_path = PROJECT_ROOT / "deploy" / "NAS_DEPLOY_GUIDE.md"
    if nas_guide_path.exists():
        with st.expander("📖 NAS 배포 가이드 (Docker / 시놀로지 / QNAP)", expanded=False):
            try:
                st.markdown(nas_guide_path.read_text(encoding="utf-8"))
            except Exception as e:
                st.error(f"가이드 로드 실패: {e}")

    st.markdown("**관련 파일**:")
    st.code(
        "deploy/Dockerfile          # 이미지 정의 (Playwright + Streamlit)\n"
        "deploy/docker-compose.yml  # NAS 영구 실행 설정\n"
        "deploy/supervisor.sh       # 컨테이너 안에서 웹앱+스케줄러 동시 실행\n"
        "deploy/NAS_DEPLOY_GUIDE.md # 단계별 배포 가이드",
        language="text",
    )


# =============================================================================
# 탭 6: 백업 / 복원
# =============================================================================

with tab_backup:
    st.markdown("### 💾 백업 / 복원")
    st.caption(
        "설정·인증·세션·결과 파일을 zip 하나로 묶어 안전하게 보관하고, "
        "PC 교체나 NAS 이전 시 한 번에 복원할 수 있어요."
    )

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    try:
        from backup.manager import (
            AVAILABLE_TARGETS,
            create_backup,
            inspect_backup,
            restore_backup,
            list_backups,
            delete_backup,
            BACKUP_DIR,
        )
        backup_available = True
    except Exception as e:
        backup_available = False
        st.error(f"백업 모듈 로드 실패: {e}")

    if backup_available:
        # ---------------- 백업 생성 ----------------
        st.markdown("#### 📦 새 백업 만들기")

        col_t, col_t2 = st.columns([3, 2])
        with col_t:
            st.caption("어떤 항목을 백업에 포함할지 선택하세요.")
            selected_targets = []
            for tgt in AVAILABLE_TARGETS:
                checked = st.checkbox(
                    f"**{tgt.name}** — {tgt.description}",
                    value=tgt.default_selected,
                    key=f"bk_target_{tgt.relative_path}",
                )
                if checked:
                    selected_targets.append(tgt.relative_path)

        with col_t2:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button(
                "📦 백업 생성",
                type="primary",
                use_container_width=True,
                disabled=not selected_targets,
            ):
                try:
                    with st.spinner("백업 생성 중..."):
                        zip_path = create_backup(selected_targets=selected_targets)
                    info = inspect_backup(zip_path)
                    size_mb = zip_path.stat().st_size / (1024 * 1024)
                    st.success(
                        f"✅ 백업 생성 완료!\n\n"
                        f"- 파일: `{zip_path.name}`\n"
                        f"- 용량: {size_mb:.2f} MB\n"
                        f"- 포함 파일: {info['manifest']['file_count']}개"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"백업 실패: {e}")

        st.divider()

        # ---------------- 기존 백업 목록 + 복원 ----------------
        st.markdown("#### 📚 저장된 백업")

        backups = list_backups()
        if not backups:
            st.info("아직 백업이 없어요. 위에서 첫 백업을 만들어보세요.")
        else:
            for bp in backups:
                with st.container(border=True):
                    info = inspect_backup(bp)
                    manifest = info.get("manifest") or {}
                    size_mb = bp.stat().st_size / (1024 * 1024)
                    created = manifest.get("created_at", "")[:19].replace("T", " ")

                    col_meta, col_actions = st.columns([4, 2])
                    with col_meta:
                        st.markdown(f"**📦 {bp.name}**")
                        st.caption(
                            f"생성: {created or '(불명)'} · "
                            f"용량: {size_mb:.2f} MB · "
                            f"파일: {manifest.get('file_count', '?')}개 · "
                            f"대상: {', '.join(manifest.get('targets', [])) or '?'}"
                        )

                    with col_actions:
                        # 다운로드
                        try:
                            with open(bp, "rb") as f:
                                st.download_button(
                                    "⬇️ 다운로드",
                                    data=f.read(),
                                    file_name=bp.name,
                                    mime="application/zip",
                                    key=f"dl_{bp.name}",
                                    use_container_width=True,
                                )
                        except Exception as e:
                            st.caption(f"다운로드 준비 실패: {e}")

                    # 복원/삭제
                    col_r, col_d = st.columns([4, 1])
                    with col_r:
                        if st.button(
                            "♻️ 이 백업으로 복원",
                            key=f"restore_{bp.name}",
                            help="현재 상태가 안전 백업으로 자동 저장된 후 복원됩니다.",
                        ):
                            with st.spinner("복원 중..."):
                                summary = restore_backup(bp, create_safety_backup=True)
                            if summary.get("error"):
                                st.error(f"복원 실패: {summary['error']}")
                            else:
                                msg = (
                                    f"✅ 복원 완료! "
                                    f"({summary['restored_files']}개 파일)"
                                )
                                if summary.get("safety_backup"):
                                    msg += (
                                        f"\n\n안전 백업: "
                                        f"`{summary['safety_backup'].name}`"
                                    )
                                if summary.get("skipped"):
                                    msg += (
                                        f"\n\n⚠️ 건너뛴 항목 "
                                        f"{len(summary['skipped'])}개"
                                    )
                                st.success(msg)
                                st.info("페이지를 새로고침하면 복원된 설정이 반영됩니다.")
                    with col_d:
                        if st.button("🗑️", key=f"del_{bp.name}", help="이 백업 삭제"):
                            if delete_backup(bp):
                                st.success("삭제됨")
                                st.rerun()

        st.divider()

        # ---------------- 외부 zip 업로드로 복원 ----------------
        st.markdown("#### 📤 외부 백업 파일로 복원")
        st.caption(
            "다른 PC/NAS에서 받아온 백업 zip을 업로드해 복원할 수 있어요. "
            "복원 전 현재 상태가 자동으로 안전 백업됩니다."
        )

        uploaded_backup = st.file_uploader(
            "백업 zip 파일 (.zip)",
            type=["zip"],
            key="backup_uploader",
        )

        if uploaded_backup is not None:
            # 임시로 backups 폴더에 저장 후 검사
            tmp_path = BACKUP_DIR / f"_uploaded_{uploaded_backup.name}"
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "wb") as f:
                f.write(uploaded_backup.read())

            info = inspect_backup(tmp_path)
            if not info["valid"]:
                st.error(f"❌ {info.get('error') or '유효하지 않은 백업'}")
                tmp_path.unlink(missing_ok=True)
            else:
                manifest = info.get("manifest") or {}
                st.success(
                    f"✓ 백업 검증 통과 — 파일 {manifest.get('file_count', '?')}개, "
                    f"대상: {', '.join(manifest.get('targets', [])) or '?'}"
                )
                with st.expander("포함된 항목 미리보기"):
                    st.code("\n".join(info["entries"]), language="text")
                if st.button("♻️ 업로드한 백업으로 복원", type="primary", key="upload_restore"):
                    with st.spinner("복원 중..."):
                        summary = restore_backup(tmp_path, create_safety_backup=True)
                    if summary.get("error"):
                        st.error(f"복원 실패: {summary['error']}")
                    else:
                        st.success(
                            f"✅ 복원 완료! ({summary['restored_files']}개 파일). "
                            "페이지를 새로고침해주세요."
                        )
                        # 임시 파일 삭제
                        tmp_path.unlink(missing_ok=True)


# =============================================================================
# 탭 7: 고급 — JSON 직접 편집 (백업/복원용)
# =============================================================================

with tab_advanced:
    st.markdown("### 🔧 고급 — JSON 직접 편집")
    st.warning(
        "⚠️ **고급 사용자용**입니다. JSON 문법 오류가 있으면 다른 메뉴들이 작동하지 않을 수 있어요. "
        "위 [캠페인], [블덱스] 탭으로 편집하시는 것을 권장합니다."
    )
    
    st.markdown("#### 현재 설정 (읽기 전용)")
    st.code(json.dumps(settings, ensure_ascii=False, indent=2), language="json")
    
    st.markdown("---")
    
    st.markdown("#### JSON 다운로드 (백업)")
    st.download_button(
        "📥 settings.json 백업 다운로드",
        data=json.dumps(settings, ensure_ascii=False, indent=2),
        file_name="settings.json.backup",
        mime="application/json",
    )
    
    st.markdown("---")
    
    st.markdown("#### settings.json 파일 위치")
    st.code(str(SETTINGS_PATH), language="text")
    st.caption(
        "터미널에서 직접 편집하시려면 위 경로의 파일을 VS Code 등으로 여시면 됩니다."
    )
