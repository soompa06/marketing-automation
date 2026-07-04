"""
💬 네이버 블로그탭 모집 비밀댓글 페이지

흐름:
1. 댓글 달 네이버 계정으로 로그인(1회) → 세션 저장
2. 키워드별 모집 문구 등록
3. 키워드 입력 + 안전 설정 → 실행
4. 블로그탭 1~20위 포스팅에 비밀댓글(모집글) 자동 작성
   - 블로거 단위 3개월 이내 중복 방지
   - 댓글창 없음/차단은 안전하게 건너뜀
   - 사람처럼 천천히 (스팸/차단 회피)
5. 어느 블로거에 달았는지 실시간 확인
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import setup_page, render_sidebar, ensure_directories, PROJECT_ROOT, SRC_DIR, get_python_executable, page_header
from background_jobs import start_job, list_jobs, read_log, stop_job

setup_page("네이버 댓글모집", "💬", feature="comment")
ensure_directories()
render_sidebar("comment")

sys.path.insert(0, str(SRC_DIR / "naver_comment"))
import history_store as hist  # noqa: E402
import templates_store as tmpl  # noqa: E402
import naver_session as nsession  # noqa: E402
import chrome_cdp  # noqa: E402

page_header(
    "네이버 블로그탭 모집 비밀댓글",
    "💬",
    "키워드 블로그탭 1~20위 포스팅에 비밀댓글. 블로거 단위 3개월 중복 방지·사람처럼 천천히 작성.",
)
st.warning(
    "⚠️ 짧은 시간에 많이 달면 네이버가 스팸/로봇으로 보고 계정을 제한할 수 있어요. "
    "기본값(보통)은 댓글 간 2~5분, 하루 60건으로 보수적으로 잡혀 있습니다. "
    "본인 계정/책임 하에 신중하게 사용하세요."
)
with st.expander("📋 네이버 정책 요약 (꼭 읽어주세요)", expanded=False):
    st.markdown(
        "네이버는 자동화 도구로 댓글을 다는 행위를 정책상 허용하지 않습니다. "
        "탐지되면 단계적으로 제재됩니다.\n\n"
        "- **3단계 제재**: 1차 경고 → 2차 30일 글쓰기 정지 → 3차 영구 금지\n"
        "- **AI 클린봇 + Xi 등 자동화 탐지 봇**이 **비밀댓글까지** 잡아냅니다 (작성자 자체를 차단)\n"
        "- 동일/유사 문구 반복, 단시간 다량 작성, 같은 IP의 다중 계정은 명확한 신호\n"
        "- 뉴스 댓글의 명시 기준: 1인 1일 20개·60초 간격. 블로그는 명시는 없지만 **더 낮은 내부 한도 가능성**\n\n"
        "**다채구 계정이 차단됐다면 이미 2차 단계일 수 있습니다.** "
        "다른 계정으로 잠시 사용하지 않고 두면(쿨다운) 회복되기도 하지만 보장은 안 됩니다. "
        "본 도구의 안전 설정(긴 대기·낮은 한도·문구 변형·자동화 신호 숨김)은 위험을 **줄일 뿐 없애지 못합니다**."
    )

# 최근 이력에 '세션 만료' 에러가 있으면 상단에 명확히 안내
_recent_err = [r for r in hist.recent(8)
               if r.get("status") == "error" and "세션이 만료" in (r.get("detail") or "")]
if _recent_err:
    accs = sorted({r.get("account", "") for r in _recent_err})
    st.error(
        f"🔒 **댓글 서비스 세션 만료 감지** — 계정: {', '.join(accs)}  \n"
        "네이버 메인은 로그인 상태여도 댓글 서비스 세션은 따로 만료될 수 있어요. "
        "위 1️⃣에서 해당 계정으로 **다시 로그인**해주세요. (로그인 후 댓글 작성이 다시 정상 동작합니다.)"
    )

st.divider()

# =============================================================================
# 1) 계정 세션
# =============================================================================
st.markdown("### 1️⃣ 댓글 작성 계정 (네이버 로그인)")

users = nsession.list_users()
col_a, col_b = st.columns([3, 2])
with col_a:
    if users:
        selected_accounts = st.multiselect(
            "사용할 계정(세션) — 위에서부터 순서대로 로테이션",
            options=users,
            default=users,
            help="여러 계정을 고르면 한 계정이 한도(아래 '계정당 교체')에 도달할 때마다 "
                 "다음 계정으로 자동 교체합니다. 한 계정만 고르면 단일 계정으로 동작합니다.",
        )
        account = selected_accounts[0] if selected_accounts else "default"
    else:
        selected_accounts = []
        account = st.text_input("계정 별칭", value="default",
                                help="여러 네이버 계정을 쓸 때 구분용 이름")
        st.info("아직 저장된 네이버 세션이 없습니다. 오른쪽에서 로그인하세요.")
    if st.button("🔄 세션 목록 새로고침"):
        st.rerun()
    if users:
        st.caption("저장된 세션: " + ", ".join(f"`{u}`" for u in users))
        if selected_accounts:
            st.caption("로테이션 순서: " + " → ".join(f"`{a}`" for a in selected_accounts))
with col_b:
    new_user = st.text_input("새 계정 별칭", value=(account or "default"), key="new_naver_user")
    if st.button("🔐 네이버 로그인 창 열기", use_container_width=True):
        cmd = [get_python_executable(), str(SRC_DIR / "naver_comment" / "naver_session.py"),
               "--user", new_user.strip() or "default"]
        try:
            start_job(cmd=cmd, job_type="네이버로그인",
                      description=f"네이버 로그인: {new_user}")
            st.success("브라우저 창이 곧 열립니다. 그 창에서 네이버에 직접 로그인하세요. "
                       "로그인되면 세션이 자동 저장되고, 이 목록이 갱신됩니다.")
        except Exception as e:
            st.error(f"실행 오류: {e}")
    st.caption("창이 안 열리면 터미널에서 `! "
               f"{get_python_executable()} src/naver_comment/naver_session.py --user {new_user}` 실행")

# 로그인 작업이 진행 중이면 자동 새로고침 (끝나면 세션이 목록에 뜨도록)
_login_jobs = [j for j in list_jobs(job_type="네이버로그인", limit=3) if j.get("running")]
if _login_jobs:
    st.info("🔐 네이버 로그인 진행 중... 브라우저 창에서 로그인을 완료하세요. "
            "(완료되면 자동으로 목록이 갱신됩니다)")
    time.sleep(4)
    st.rerun()

st.divider()

# =============================================================================
# 2) 키워드별 모집 문구
# =============================================================================
st.markdown("### 2️⃣ 모집 문구 (비밀댓글 내용)")
st.caption("키워드마다 다른 문구를 넣을 수 있어요. 매칭되는 키워드 문구가 없으면 기본 문구가 쓰입니다.")

templates = tmpl.get_all()

with st.expander("📝 기본 문구", expanded=not templates.get("default")):
    new_default = st.text_area("기본 모집 문구", value=templates.get("default", ""),
                               height=140, placeholder="안녕하세요 ☺ 체험단 모집 중입니다 ...")
    if st.button("💾 기본 문구 저장"):
        tmpl.set_default(new_default)
        st.success("저장됨")
        st.rerun()

with st.expander("🏷️ 키워드별 문구"):
    by_kw = templates.get("by_keyword", {})
    if by_kw:
        for kw, msg in list(by_kw.items()):
            with st.container(border=True):
                st.markdown(f"**`{kw}`**")
                edited = st.text_area("문구", value=msg, key=f"kwmsg_{kw}", height=100,
                                      label_visibility="collapsed")
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("💾 저장", key=f"savekw_{kw}"):
                        tmpl.set_keyword(kw, edited)
                        st.success("저장됨")
                        st.rerun()
                with c2:
                    if st.button("🗑️ 삭제", key=f"delkw_{kw}"):
                        tmpl.delete_keyword(kw)
                        st.rerun()
    else:
        st.caption("등록된 키워드별 문구가 없습니다.")

    st.markdown("**➕ 키워드 문구 추가**")
    with st.form("add_kw_msg"):
        nk = st.text_input("키워드", placeholder="예: 대전 맛집")
        nm = st.text_area("문구", height=100)
        if st.form_submit_button("추가", type="primary"):
            if nk.strip() and nm.strip():
                tmpl.set_keyword(nk, nm)
                st.success("추가됨")
                st.rerun()
            else:
                st.error("키워드와 문구를 모두 입력하세요.")

st.divider()

# =============================================================================
# 3) 실행 설정
# =============================================================================
st.markdown("### 3️⃣ 실행")

run_keywords = st.text_area(
    "이번에 돌릴 키워드 (쉼표 또는 줄바꿈으로 구분)",
    placeholder="대전 맛집\n만년동 맛집",
    height=90,
)

with st.expander("⚙️ 안전 설정 (스팸/차단 방지)", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        top_n = st.number_input("블로그탭 상위 N위", 1, 30, 20)
        dedup_days = st.number_input("재방문 금지(일)", 7, 365, 90,
                                     help="이 기간 내 댓글 단 블로거는 건너뜀 (기본 90일=3개월)")
    with c2:
        per_account = st.number_input("계정당 교체 기준(건)", 1, 200, 50,
                                      help="한 계정이 이만큼 달면 다음 계정으로 자동 교체 (기본 50)")
        daily = st.number_input("계정별 하루 한도(건)", 1, 200, 60)
    with c3:
        per_run = st.number_input("이번 실행 총 한도(건)", 1, 1000, 200,
                                  help="여러 계정 합산 이번 실행 총 작성 한도")
        min_delay = st.number_input("댓글 간 최소 대기(초)", 10, 600, 120)
        max_delay = st.number_input("댓글 간 최대 대기(초)", 20, 1200, 300)
    show_browser = st.checkbox("🪟 브라우저 창 보기", value=False,
                               help="처음엔 켜두고 댓글이 잘 달리는지 직접 확인하길 권장")

st.divider()

# =============================================================================
# 실행 방식: 실제 Chrome 연결(CDP) — 차단 회피 (권장)
# =============================================================================
st.markdown("### 🟢 실행 방식")
use_chrome = st.checkbox(
    "실제 Chrome 연결(CDP) 방식 사용 — 자동화 탐지/삭제 회피 (강력 권장)",
    value=True,
    help="자동화 브라우저로 달면 네이버가 비밀댓글을 사후 삭제합니다. "
         "평소 쓰는 진짜 Chrome에 연결해 달면 삭제 위험이 크게 줄어듭니다.",
)
if use_chrome:
    chrome_up = chrome_cdp.is_chrome_up()
    cc1, cc2 = st.columns([3, 2])
    with cc1:
        if chrome_up:
            logged = False
            try:
                # 로그인 여부까지 빠르게 확인
                import asyncio as _aio
                async def _chk():
                    ct = await chrome_cdp.connect()
                    if not ct:
                        return False
                    p, b, ctx = ct
                    ok = await chrome_cdp.is_logged_in(ctx)
                    await p.stop()
                    return ok
                logged = _aio.run(_chk())
            except Exception:
                logged = False
            if logged:
                st.success("✅ 디버그 Chrome 연결됨 + 네이버 로그인 확인")
            else:
                st.warning("🟡 디버그 Chrome은 떠 있지만 네이버 로그인이 안 보입니다. "
                           "그 Chrome 창에서 네이버에 로그인하세요.")
        else:
            st.error("🔴 디버그 모드 Chrome이 실행돼 있지 않습니다. 오른쪽 안내대로 실행하세요.")
    with cc2:
        with st.expander("Chrome 디버그 실행 방법"):
            st.markdown(
                "터미널에서 한 번 실행 (창 닫지 말 것):\n"
                f"```\nbash {SRC_DIR}/naver_comment/start_chrome_mac.sh\n```\n"
                "Windows: `src\\naver_comment\\start_chrome_win.bat`\n\n"
                "→ 뜨는 Chrome에서 **네이버 로그인** 후 이 페이지에서 실행하세요."
            )

# 선택 계정들의 오늘 작성 현황
if selected_accounts:
    today_lines = " · ".join(
        f"`{a}` {hist.count_on_day(account=a)}건" for a in selected_accounts
    )
    st.info(f"📊 오늘 작성(계정별): {today_lines}  /  계정별 하루 한도 {daily}건")

if max_delay < min_delay:
    st.error("최대 대기는 최소 대기보다 커야 합니다.")
elif st.button("🚀 모집 댓글 시작", type="primary", use_container_width=True):
    kws = [k.strip() for k in run_keywords.replace(",", "\n").split("\n") if k.strip()]
    # CDP 모드: 저장 세션 불필요(크롬 로그인 사용). 기록용 계정 라벨만 필요.
    if use_chrome:
        valid_accounts = selected_accounts or ["chrome"]
    else:
        valid_accounts = [a for a in selected_accounts if nsession.has_user(a)]

    blocker = None
    if not kws:
        blocker = "키워드를 한 개 이상 입력하세요."
    elif use_chrome and not chrome_cdp.is_chrome_up():
        blocker = ("디버그 모드 Chrome이 실행돼 있지 않습니다. "
                   "위 '🟢 실행 방식'의 안내대로 Chrome을 먼저 실행하고 네이버에 로그인하세요.")
    elif not use_chrome and not valid_accounts:
        avail = nsession.list_users()
        blocker = ("선택한 계정의 세션이 없습니다. 저장된 세션: "
                   + (", ".join(f"`{u}`" for u in avail) if avail else "(없음)")
                   + " — 계정을 선택하거나 1단계에서 로그인하세요.")

    if blocker:
        st.error(blocker)
    else:
        cmd = [
            get_python_executable(), str(SRC_DIR / "naver_comment" / "commenter.py"),
            "--keywords", ",".join(kws),
            "--accounts", ",".join(valid_accounts),
            "--top-n", str(int(top_n)),
            "--dedup-days", str(int(dedup_days)),
            "--per-run", str(int(per_run)),
            "--per-account", str(int(per_account)),
            "--daily", str(int(daily)),
            "--min-delay", str(int(min_delay)),
            "--max-delay", str(int(max_delay)),
        ]
        if show_browser:
            cmd.append("--show-browser")
        if use_chrome:
            cmd.append("--use-chrome")
        try:
            mode_label = "실제 Chrome(CDP)" if use_chrome else f"{len(valid_accounts)}계정 로테이션"
            jid = start_job(cmd=cmd, job_type="네이버댓글",
                            description=f"{mode_label} · {len(kws)}개 키워드")
            st.success(f"✓ 백그라운드에서 시작됐습니다 (ID: {jid}). 모드: {mode_label}. "
                       "아래에서 실시간 확인하세요.")
            st.rerun()
        except Exception as e:
            st.error(f"실행 오류: {e}")

st.divider()

# =============================================================================
# 4) 댓글 단 블로거 (누적) — 항상 표시, 실행 중엔 실시간 갱신
# =============================================================================
st.markdown("### 4️⃣ 댓글 단 블로거 (누적·삭제 확인)")

_sm = hist.summary()
_succ = hist.success_records(limit=1000)
_deleted_n = sum(1 for r in _succ if r.get("deleted_at"))
_checked_n = sum(1 for r in _succ if r.get("alive_checked_at"))
_alive_n = _checked_n - _deleted_n

m1, m2, m3, m4 = st.columns(4)
m1.metric("✅ 총 작성", f"{_sm['total_success']}건")
m2.metric("👤 고유 블로거", f"{_sm['unique_bloggers']}명")
m3.metric("📅 오늘", f"{_sm['today']}건")
m4.metric("🗑️ 삭제 확인", f"{_deleted_n}건",
          delta=(f"-살아있음 {_alive_n}" if _checked_n else "미확인"),
          delta_color="off")
if _sm["by_account"]:
    st.caption("계정별 누적: " + " · ".join(
        f"`{a or '?'}` {n}건" for a, n in sorted(_sm["by_account"].items())))

# 삭제 여부 확인 버튼 — 백그라운드 작업으로 검증기 실행
cdel1, cdel2 = st.columns([3, 2])
with cdel1:
    verify_acc = st.selectbox(
        "확인할 계정", options=(users or ["default"]), index=0,
        key="verify_acc", help="해당 계정 세션으로 글을 다시 방문해 비밀댓글이 살아있는지 확인합니다.")
with cdel2:
    if st.button("🔍 삭제 여부 확인 (백그라운드)", use_container_width=True):
        cmd = [get_python_executable(), str(SRC_DIR / "naver_comment" / "verifier.py"),
               "--account", verify_acc]
        try:
            jid = start_job(cmd=cmd, job_type="댓글검증",
                            description=f"{verify_acc} 댓글 삭제 확인")
            st.success(f"✓ 검증 시작됨 ({jid}). 완료되면 위 표가 갱신됩니다.")
            st.rerun()
        except Exception as e:
            st.error(f"실행 오류: {e}")

if _succ:
    import pandas as _pd
    rows = []
    for r in _succ:
        if r.get("deleted_at"):
            status = "🗑️ 삭제됨"
        elif r.get("alive_checked_at"):
            status = "✅ 살아있음"
        else:
            status = "—"
        rows.append({
            "상태": status,
            "블로거": r.get("blog_id", ""),
            "키워드": r.get("keyword", ""),
            "계정": r.get("account", ""),
            "작성일시": (r.get("at") or "")[:16].replace("T", " "),
            "확인일시": (r.get("alive_checked_at") or "")[:16].replace("T", " "),
            "글주소": r.get("post_url", ""),
        })
    df = _pd.DataFrame(rows)
    kw_filter = st.text_input("🔎 블로거/키워드 검색", placeholder="비우면 전체",
                              key="blogger_search")
    if kw_filter.strip():
        q = kw_filter.strip()
        df = df[df["블로거"].str.contains(q, case=False, na=False)
                | df["키워드"].str.contains(q, case=False, na=False)]
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={"글주소": st.column_config.LinkColumn("글주소", width="small")},
    )
    st.download_button(
        "📥 CSV로 내려받기",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="commented_bloggers.csv", mime="text/csv",
    )
else:
    st.caption("아직 작성한 블로거가 없습니다.")

st.divider()

# =============================================================================
# 5) 실시간 진행 상황
# =============================================================================
st.markdown("### 5️⃣ 실시간 진행 상황")

jobs = list_jobs(job_type="네이버댓글", limit=5)
active = [j for j in jobs if j.get("running")]
recent_jobs = [j for j in jobs if not j.get("running")][:2]

# 최근 활동 피드 — 상태별 아이콘
STATUS_ICON = {
    "success": "✅ 작성", "skipped_dedup": "⏭️ 중복건너뜀",
    "no_comment_box": "🚫 댓글불가", "blocked": "🛑 차단/제한", "error": "❌ 오류",
}
records = hist.recent(limit=25)

if records:
    succ = sum(1 for r in records if r["status"] == "success")
    st.markdown(f"**최근 활동** (표시 {len(records)}건 중 작성 성공 {succ}건)")
    for r in records:
        icon = STATUS_ICON.get(r["status"], r["status"])
        at = (r.get("at") or "")[:19].replace("T", " ")
        st.caption(f"{icon} · `{r.get('blog_id','')}` · 키워드 `{r.get('keyword','')}` · {at}"
                   + (f" · {r['detail']}" if r.get("detail") else ""))
else:
    st.caption("아직 작성 이력이 없습니다.")

if active:
    for job in active:
        with st.container(border=True):
            ct, cs = st.columns([5, 1])
            with ct:
                st.markdown(f"**🟢 진행 중**: {job.get('description', job['job_id'])}")
                st.caption(f"시작: {job['started_at'][:19].replace('T',' ')}")
            with cs:
                if st.button("⏹️ 중지", key=f"stop_{job['job_id']}"):
                    if stop_job(job['job_id']):
                        st.success("중지됨")
                        st.rerun()
            st.code(read_log(job['job_id'], max_lines=25), language="text")
    st.caption("🔄 6초마다 자동 새로고침")
    time.sleep(6)
    st.rerun()
elif recent_jobs:
    st.markdown("**📋 최근 실행**")
    for job in recent_jobs:
        with st.container(border=True):
            fin = (job.get('finished_at') or '')[:19].replace('T', ' ')
            st.markdown(f"**✓ {job.get('description', job['job_id'])}**")
            st.caption(f"완료: {fin}")
            with st.expander("로그 보기"):
                st.code(read_log(job['job_id'], max_lines=200), language="text")
