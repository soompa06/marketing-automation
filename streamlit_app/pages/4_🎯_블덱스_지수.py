"""
③ 블덱스 + 시트 페이지

사용자 흐름:
1. 캠페인 선택 (식당 / 피부과 / 모두)
2. 미리보기 (DRY-RUN) 또는 실제 실행
3. 진행 상황 실시간 표시
4. 자격자/미달자 결과 표시
"""
import sys
import time
import subprocess
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    PROJECT_ROOT,
    SRC_DIR,
    SETTINGS_PATH,
    load_settings,
    get_python_executable,
    notify_job_completion,
    page_header,
)
from background_jobs import start_job, list_jobs, read_log, stop_job, job_outcome, clear_job_logs

# 블덱스 세션 사용자 목록 가져오기 (src/blogdex/session.py의 함수)
sys.path.insert(0, str(SRC_DIR / "blogdex"))
try:
    from session import list_users as list_blogdex_users
except ImportError:
    def list_blogdex_users():
        return []

setup_page("블덱스 + 시트", "🎯", feature="blogdex")
ensure_directories()
render_sidebar("blogdex")


# =============================================================================
# 헤더
# =============================================================================

page_header(
    "③ 블덱스 + 구글 시트 통합",
    "🎯",
    "구글 시트 신청자 중 지수 비어있는 행을 블덱스에서 자동 조회·기록. 미달/조회 불가는 별도 시트로 이동.",
)

st.divider()

# =============================================================================
# 사전 점검 — 설정과 세션 파일 확인
# =============================================================================

st.markdown("### 🔍 사전 점검")

settings = load_settings()
campaigns_in_settings = settings.get("google_sheets", {}).get("campaigns", {})
credentials_path = PROJECT_ROOT / "config" / "google_credentials.json"

# 블덱스 사용자 목록 가져오기
blogdex_users = list_blogdex_users()
has_session = len(blogdex_users) > 0

col_check1, col_check2, col_check3 = st.columns(3)

with col_check1:
    if SETTINGS_PATH.exists() and campaigns_in_settings:
        st.success(f"✓ settings.json\n\n캠페인 {len(campaigns_in_settings)}개 등록")
    else:
        st.error("❌ settings.json\n\n[⚙️ 설정] 메뉴에서 작성")

with col_check2:
    if credentials_path.exists():
        st.success("✓ google_credentials.json\n\n구글 시트 접근 가능")
    else:
        st.error("❌ google_credentials.json\n\ndocs/SHEET_SETUP_GUIDE.md 참고")

with col_check3:
    if has_session:
        users_str = ", ".join(blogdex_users)
        st.success(f"✓ 블덱스 로그인\n\n등록된 사용자: {users_str}")
    else:
        st.error(
            "❌ 블덱스 미로그인\n\n아래 '블덱스 사용자' 섹션에서 로그인"
        )

# 점검 실패 시 안내 후 중단
if not (SETTINGS_PATH.exists() and campaigns_in_settings 
        and credentials_path.exists() and has_session):
    st.warning("위 점검 항목을 모두 통과해야 실행할 수 있어요.")
    
    with st.expander("🆘 도움말 — 점검 실패 시 해결 방법"):
        st.markdown(
            """
**1. settings.json이 없거나 캠페인 미등록**
→ 좌측 [⚙️ 설정] 메뉴에서 작성

**2. google_credentials.json이 없음**
→ 프로젝트 폴더의 `docs/SHEET_SETUP_GUIDE.md` 파일을 열어서 1~5단계 진행
- Google Cloud Console에서 Service Account 키 생성
- 다운로드한 JSON 파일을 `config/google_credentials.json`으로 저장
- 시트에 서비스 계정 이메일을 **편집자 권한**으로 공유

**3. 블덱스 미로그인**
→ 터미널에서 다음 명령으로 첫 로그인 (1회만):
```
python src/blogdex/session.py
```
또는 다른 사용자 추가:
```
python src/blogdex/session.py --user 이름
```
브라우저 창이 열리면 본인 구글 계정으로 직접 로그인 후 Enter
"""
        )
    st.stop()

st.divider()

# =============================================================================
# 블덱스 사용자 선택 (다중 사용자 지원)
# =============================================================================

st.markdown("### 👤 블덱스 사용자 선택")
st.caption(
    "여러 명이 같은 PC를 공유하시거나 여러 블덱스 계정을 쓰실 때 사용자별로 로그인 세션을 관리할 수 있어요."
)

if len(blogdex_users) == 1:
    selected_user = blogdex_users[0]
    st.info(f"등록된 사용자: **{selected_user}** (1명)")
else:
    selected_user = st.selectbox(
        "이번 작업에 사용할 계정",
        options=blogdex_users,
        index=0,
        format_func=lambda x: f"👤 {x}",
        help="이 계정의 블덱스 세션으로 조회합니다.",
    )

with st.expander("➕ 새 사용자 추가하려면"):
    st.markdown(
        """
**터미널에서 다음 명령을 실행하세요**:

```
python src/blogdex/session.py --user 이름
```

예시 (이름은 영문/숫자/한글 모두 가능):
- `python src/blogdex/session.py --user soom`
- `python src/blogdex/session.py --user 직원1`
- `python src/blogdex/session.py --user account_b`

브라우저 창이 열리면 해당 구글 계정으로 직접 로그인 후 터미널에서 **Enter**.
"""
    )

st.divider()

# =============================================================================
# 캠페인 선택
# =============================================================================

st.markdown("### 📋 캠페인 선택")

campaign_keys = list(campaigns_in_settings.keys())

selected_campaigns = st.multiselect(
    "처리할 캠페인",
    options=campaign_keys,
    default=campaign_keys,  # 기본: 모두 선택
    format_func=lambda x: f"🏷️ {x}",
    help="선택한 캠페인의 시트만 처리합니다. 비워두면 실행 못 해요.",
)

# 선택된 캠페인의 시트 ID 미리 보기
if selected_campaigns:
    with st.expander("📊 선택된 시트 정보"):
        for cname in selected_campaigns:
            cinfo = campaigns_in_settings[cname]
            st.markdown(
                f"**🏷️ {cname}**  \n"
                f"- 시트 ID: `{cinfo.get('spreadsheet_id', '?')[:30]}...`  \n"
                f"- 메인 시트: `{cinfo.get('main_sheet_name', '?')}`  \n"
                f"- 미달자 시트: `{cinfo.get('rejected_sheet_name', '미달자')}`  \n"
                f"- 블로그주소 컬럼: `{cinfo.get('blog_url_column', 'C')}`  \n"
                f"- 지수 컬럼: `{cinfo.get('grade_column', 'D')}`"
            )

st.divider()

# =============================================================================
# 옵션
# =============================================================================

st.markdown("### ⚙️ 실행 옵션")

col1, col2 = st.columns(2)

with col1:
    show_browser = st.checkbox(
        "🪟 브라우저 창 보기 (권장)",
        value=True,  # 블덱스는 Cloudflare 때문에 거의 무조건 True 필요
        help=(
            "**중요**: 블덱스는 봇 차단(Cloudflare)이 강력해서 "
            "브라우저 창이 보이는 모드에서만 안정적으로 작동합니다. "
            "체크 해제하면 거의 100% 실패합니다."
        ),
    )
    
    if not show_browser:
        st.warning(
            "⚠️ Cloudflare 봇 차단 때문에 백그라운드 모드는 거의 100% 실패합니다. "
            "브라우저 창을 보이게 켜시는 것을 강력 권장합니다."
        )

with col2:
    dry_run = st.checkbox(
        "🧪 미리보기 (DRY-RUN)",
        value=False,
        help=(
            "체크하면 시트를 실제로 수정하지 않고 어떤 작업이 일어날지만 보여줍니다. "
            "처음 실행하실 때 미리보기로 확인 후 실제 실행 권장."
        ),
    )

# 블덱스 설정 미리 보기
bd_settings = settings.get("blogdex", {})
query_delay = bd_settings.get("query_delay_seconds", 2)
qualified_grades = bd_settings.get(
    "qualified_grades",
    ["준최6", "준최7", "최적1", "최적2", "최적3", "최적1+", "최적2+", "최적3+", "최적4+"],
)

with st.expander("📐 블덱스 설정 (수정은 [⚙️ 설정] 메뉴에서)"):
    st.markdown(
        f"- **조회 방식**: 연속 조회 (조회 간격 {query_delay}초)  \n"
        f"- **조회 제한 시**: 블덱스가 '1분에 2번…' 안내를 띄우면 그 시간만큼 "
        f"자동 대기 후 같은 블로거를 재시도합니다.  \n"
        f"- **자격 등급**: {', '.join(qualified_grades)}"
    )

st.divider()

# =============================================================================
# 실행
# =============================================================================

st.markdown("### 🚀 실행")

# 이미 실행 중인 블덱스 작업이 있으면 중복 실행 금지
# (동시에 두 번 돌리면 브라우저 충돌로 조회가 깨질 수 있음)
_running_blogdex = [j for j in list_jobs(job_type="블덱스", limit=5) if j.get("running")]

if not selected_campaigns:
    st.button("실행", disabled=True, type="primary", use_container_width=True)
    st.caption("⚠️ 처리할 캠페인을 하나 이상 선택해주세요.")
elif _running_blogdex:
    st.button("실행", disabled=True, type="primary", use_container_width=True)
    st.warning("⚠️ 이미 블덱스 조회가 진행 중입니다. 동시에 두 번 실행하면 "
               "브라우저 충돌로 조회가 깨질 수 있어요. 진행 중인 작업이 끝난 뒤 다시 시도하세요.")
else:
    btn_label = "🧪 미리보기 실행" if dry_run else "✅ 실제 실행"
    btn_type = "secondary" if dry_run else "primary"

    if st.button(btn_label, type=btn_type, use_container_width=True):
        cmd = [
            get_python_executable(),
            str(SRC_DIR / "blogdex" / "sheet_pipeline.py"),
        ]
        for cname in selected_campaigns:
            cmd.extend(["--campaign", cname])
        if show_browser:
            cmd.append("--show-browser")
        if dry_run:
            cmd.append("--dry-run")
        # 사용자 지정
        cmd.extend(["--user", selected_user])
        
        # 백그라운드 작업 시작
        try:
            mode_label = "미리보기" if dry_run else "실제"
            job_id = start_job(
                cmd=cmd,
                job_type="블덱스",
                description=(
                    f"[{selected_user}] {', '.join(selected_campaigns)} "
                    f"캠페인 {mode_label} 처리"
                ),
            )
            st.session_state["current_blogdex_job"] = job_id
            st.success(f"✓ 블덱스 작업이 백그라운드에서 시작됐습니다!")
            st.info(
                "💡 다른 페이지로 이동하셔도 작업은 계속 진행됩니다. "
                "이 페이지로 돌아오시면 진행 상황을 확인할 수 있어요."
            )
            st.rerun()
        except Exception as e:
            st.error(f"실행 오류: {e}")

# 진행 중/최근 블덱스 작업 표시
st.markdown("---")
st.markdown("### 📺 진행 상황")

all_blogdex_jobs = list_jobs(job_type="블덱스", limit=5)
active_jobs = [j for j in all_blogdex_jobs if j.get("running")]
recent_jobs = [j for j in all_blogdex_jobs if not j.get("running")][:3]

# 작업 완료 알림 (실행 중 → 완료 전환 감지)
notify_job_completion(active_jobs, recent_jobs, "seen_blogdex_jobs", title="블덱스")

if active_jobs:
    for job in active_jobs:
        with st.container(border=True):
            col_t, col_s = st.columns([5, 1])
            with col_t:
                st.markdown(
                    f"**🟢 진행 중**: {job.get('description', job['job_id'])}"
                )
                st.caption(f"시작: {job['started_at'][:19].replace('T', ' ')}")
            with col_s:
                if st.button("⏹️ 중지", key=f"stop_blogdex_{job['job_id']}"):
                    if stop_job(job['job_id']):
                        st.success("작업 중지됨")
                        st.rerun()
            
            log = read_log(job['job_id'], max_lines=30)
            
            # 실시간 통계 추출
            qualified = log.count("(자격)")
            rejected = log.count("(미달)")
            unlookup = log.count("조회 불가 (미달 시트로 이동)")
            errors = sum(1 for line in log.split("\n") if "❌" in line and "행" in line)

            col_q, col_r, col_u, col_e = st.columns(4)
            with col_q:
                st.metric("✅ 자격자", f"{qualified}명")
            with col_r:
                st.metric("⚪ 미달자", f"{rejected}명")
            with col_u:
                st.metric("🔁 조회 불가", f"{unlookup}명")
            with col_e:
                st.metric("❌ 오류", f"{errors}건")
            
            st.code(log, language="text")
    
    st.caption("🔄 5초마다 자동 새로고침됩니다.")
    time.sleep(5)
    st.rerun()

elif recent_jobs:
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown("**📋 최근 블덱스 작업**")
    with col_h2:
        if st.button("🧹 기록 정리", key="clear_blogdex_logs",
                     help="완료된 블덱스 작업 기록을 모두 지웁니다. 실행 중인 작업은 유지."):
            n = clear_job_logs(job_type="블덱스")
            st.success(f"작업 기록 {n}건 정리됨")
            st.rerun()
    for job in recent_jobs:
        outcome = job_outcome(job['job_id'])
        with st.container(border=True):
            finished_at = job.get('finished_at', '')[:19].replace('T', ' ') if job.get('finished_at') else "?"
            if outcome["ok"]:
                st.markdown(f"**✅ {job.get('description', job['job_id'])}**")
            else:
                st.markdown(f"**❌ 실패 · {job.get('description', job['job_id'])}**")
                st.caption(f"사유: {outcome['reason'] or '작업 중 오류'} "
                           "(과거 기록일 수 있어요. '🧹 기록 정리'로 지울 수 있습니다)")
            st.caption(f"완료: {finished_at}")

            with st.expander("로그 + 결과 보기"):
                log = read_log(job['job_id'], max_lines=200)
                
                # 통계
                qualified = log.count("(자격)")
                rejected = log.count("(미달)")
                unlookup = log.count("조회 불가 (미달 시트로 이동)")
                col_q, col_r, col_u = st.columns(3)
                with col_q:
                    st.metric("✅ 자격자", f"{qualified}명")
                with col_r:
                    st.metric("⚪ 미달자", f"{rejected}명")
                with col_u:
                    st.metric("🔁 조회 불가", f"{unlookup}명")
                
                st.code(log, language="text")
                
                # 시트 바로가기
                for cname in campaigns_in_settings:
                    cinfo = campaigns_in_settings[cname]
                    sheet_id = cinfo.get("spreadsheet_id", "")
                    if sheet_id:
                        st.markdown(
                            f"🔗 [{cname} 시트 열기]"
                            f"(https://docs.google.com/spreadsheets/d/{sheet_id})"
                        )
else:
    st.info("아직 진행 중이거나 최근 완료된 블덱스 작업이 없어요.")

st.divider()

# =============================================================================
# 도움말
# =============================================================================

with st.expander("📚 사용 팁"):
    st.markdown(
        """
**처음 사용 시 추천 흐름**:
1. **🧪 미리보기**로 한 번 실행해서 어떤 행이 처리될지 확인
2. 결과 OK면 미리보기 해제하고 실제 실행
3. 구글 시트에서 결과 확인

**자격 등급 변경하고 싶을 때**:
[⚙️ 설정] 메뉴에서 `qualified_grades` 수정

**시트 업데이트가 안 보일 때**:
구글 시트는 자동 새로고침이 늦을 수 있어요. F5로 새로고침해보세요.

**중복 조회 방지**:
지수 컬럼이 비어있는 행만 조회하므로, 같은 행을 두 번 조회하지 않습니다.
재조회하려면 시트에서 그 행의 지수 셀을 직접 비워주세요.
"""
    )
