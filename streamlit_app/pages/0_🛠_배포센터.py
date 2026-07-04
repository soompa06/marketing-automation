"""
🛠 배포센터 (판매자 전용)

여기서:
1. 고객 라이선스 키 발급 (플랜·기간 지정, 개인키로 서명)
2. 설치형 빌드 안내/명령

⚠️ 이 페이지는 '판매자 모드'에서만 열립니다.
   - 환경변수 MKT_SELLER=1  또는  config/.seller 파일이 있을 때
   - 고객에게 배포하는 빌드에서는 이 파일을 제외하세요 (deploy/build 가이드 참고).
"""
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import setup_page, render_sidebar, ensure_directories, page_header, PROJECT_ROOT, SRC_DIR

setup_page("배포센터", "🛠")
ensure_directories()
render_sidebar("deploy")

sys.path.insert(0, str(SRC_DIR))


def _seller_mode() -> bool:
    return os.environ.get("MKT_SELLER") == "1" or (PROJECT_ROOT / "config" / ".seller").exists()


page_header("배포센터", "🛠", "판매자 전용 — 라이선스 발급 + 설치형 빌드")

if not _seller_mode():
    st.error("🔒 판매자 전용 페이지입니다.")
    st.info("판매자라면 프로젝트에 `config/.seller` 파일을 만들거나 "
            "환경변수 `MKT_SELLER=1`로 실행하세요.")
    st.stop()

tab_issue, tab_build = st.tabs(["🔑 라이선스 발급", "📦 설치형 빌드"])

# =============================================================================
# 1) 라이선스 발급
# =============================================================================
with tab_issue:
    st.markdown("### 🔑 고객 라이선스 발급")

    try:
        from licensing import license_core
        from licensing.plans import PLANS, PLAN_LABELS, FEATURES
    except Exception as e:
        st.error(f"라이선스 모듈 로드 실패: {e}")
        st.stop()

    # 개인키 확보 (기본 경로 또는 업로드)
    default_priv = Path.home() / ".soom_marketing_keys" / "private_key.pem"
    st.caption("서명에는 **판매자 개인키**가 필요합니다. (절대 고객에게 주지 마세요)")

    priv_pem = None
    if default_priv.exists():
        st.success(f"개인키 자동 인식: `{default_priv}`")
        priv_pem = default_priv.read_bytes()
    else:
        up = st.file_uploader("개인키 파일 (private_key.pem)", type=["pem"])
        if up:
            priv_pem = up.getvalue()
        st.caption("개인키가 없다면 터미널에서 먼저 생성: "
                   "`python src/licensing/keygen.py`")

    mode = st.radio(
        "기능 선택 방식", ["기능 직접 선택 (커스텀)", "플랜 프리셋"],
        horizontal=True,
        help="고객마다 원하는 기능만 골라 발급하거나, 미리 정한 플랜으로 발급합니다.",
    )

    with st.form("issue_form"):
        customer = st.text_input("고객 (이름/이메일)", placeholder="hong@example.com")

        sel_plan = ""
        sel_feats: list[str] = []
        if mode == "플랜 프리셋":
            sel_plan = st.selectbox("플랜", options=list(PLANS.keys()),
                                    format_func=lambda k: PLAN_LABELS.get(k, k))
            st.caption("포함 기능: " + ", ".join(FEATURES.get(f, f) for f in PLANS.get(sel_plan, [])))
        else:
            st.caption("이 고객에게 열어줄 기능을 직접 고르세요:")
            cols = st.columns(2)
            keys = list(FEATURES.keys())
            for i, fkey in enumerate(keys):
                with cols[i % 2]:
                    if st.checkbox(FEATURES[fkey], key=f"feat_{fkey}"):
                        sel_feats.append(fkey)

        months = st.number_input("이용 기간(개월)", 0, 60, 12, help="0이면 무기한")
        submitted = st.form_submit_button("🔑 라이선스 키 생성", type="primary")

    if submitted:
        if not priv_pem:
            st.error("개인키가 필요합니다.")
        elif not customer.strip():
            st.error("고객 정보를 입력하세요.")
        elif mode != "플랜 프리셋" and not sel_feats:
            st.error("기능을 하나 이상 선택하세요.")
        else:
            exp = "" if months == 0 else (date.today() + timedelta(days=int(months) * 30)).isoformat()
            try:
                key = license_core.issue_license(
                    priv_pem, customer=customer.strip(),
                    plan=sel_plan,                      # 커스텀이면 빈 문자열
                    extra_features=sel_feats,           # 커스텀 선택 기능
                    expires=exp or None, license_id=uuid.uuid4().hex[:12],
                )
                # 발급 내용 미리보기 (검증으로 실제 기능 확인)
                chk = license_core.parse_and_verify(key)
                st.success("✅ 라이선스 키 생성 완료 — 아래를 고객에게 전달하세요.")
                st.code(key, language="text")
                st.caption(
                    f"고객 {customer} · 만료 {exp or '무기한'} · "
                    f"기능: {', '.join(FEATURES.get(f, f) for f in chk.get('features', []))}"
                )
                st.download_button("📥 키 파일로 저장", data=key,
                                   file_name=f"license_{customer.split('@')[0]}.key",
                                   mime="text/plain")
            except Exception as e:
                st.error(f"발급 실패: {e}")

# =============================================================================
# 2) 설치형 빌드
# =============================================================================
with tab_build:
    st.markdown("### 📦 설치형 빌드 (PyInstaller)")
    st.caption("Windows exe / macOS .app 은 각 OS에서 따로 빌드해야 합니다 (크로스 빌드 불가).")

    st.markdown(
        """
**준비 (한 번)**
```
# 1) 판매자 키페어 (최초 1회) — 공개키가 앱에 내장됩니다
python src/licensing/keygen.py

# 2) 빌드 도구
pip install pyinstaller
```

**빌드 실행**
```
# macOS
bash deploy/build/build_mac.sh

# Windows (PowerShell/cmd)
deploy\\build\\build_win.bat
```

결과물:
- macOS: `dist/마케팅자동화.app` (+ 압축해 배포)
- Windows: `dist/마케팅자동화/마케팅자동화.exe`

자세한 단계·코드서명·공증은 `deploy/build/README.md` 참고.
        """
    )
    pubkey = SRC_DIR / "licensing" / "pubkey.pem"
    if pubkey.exists():
        st.success("✅ 공개키 내장됨 — 빌드 시 라이선스 게이팅이 활성화됩니다.")
    else:
        st.warning("⚠️ 공개키(pubkey.pem)가 없습니다. `python src/licensing/keygen.py` 먼저 실행하세요. "
                   "(없으면 빌드해도 라이선스 게이팅이 꺼진 상태로 배포됩니다)")
