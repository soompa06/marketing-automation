"""
⏰ 자동 스케줄 페이지

등록된 작업을 정해진 시간에 자동 실행.
백그라운드 데몬(`src/scheduler/runner.py`)이 실행 중일 때만 자동 실행이 동작합니다.
"""
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import setup_page, render_sidebar, ensure_directories, PROJECT_ROOT, page_header

setup_page("자동 스케줄", "⏰", feature="schedule")
ensure_directories()
render_sidebar("schedule")

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from scheduler.jobs_store import (  # type: ignore  # noqa: E402
    JOB_TYPES,
    SCHEDULE_KINDS,
    WEEKDAYS,
    list_jobs,
    add_job,
    update_job,
    delete_job,
    JOBS_PATH,
)
from scheduler.runner import run_job_once  # type: ignore  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "streamlit_app"))
from background_jobs import start_job, get_job_status, read_log, list_jobs as list_bg  # noqa: E402

page_header("자동 스케줄", "⏰", "매일/매주 정해진 시각에 작업을 자동 실행합니다.")

st.divider()

# =============================================================================
# 데몬 상태
# =============================================================================

st.markdown("### 🤖 스케줄러 데몬 상태")

# 데몬은 background_jobs 시스템을 통해 시작/추적
def _running_daemon_job():
    for j in list_bg(job_type="스케줄러", limit=10):
        if j.get("running"):
            return j
    return None


daemon_job = _running_daemon_job()

col_d1, col_d2 = st.columns([3, 1])
with col_d1:
    if daemon_job:
        st.success(
            f"✅ 데몬 실행 중 (시작: {daemon_job['started_at'][:19].replace('T', ' ')})"
        )
        st.caption(
            "백그라운드에서 등록된 스케줄을 감시 중입니다. 새로 등록한 작업은 60초 안에 자동 반영됩니다."
        )
    else:
        st.warning(
            "⚠️ 스케줄러 데몬이 실행되고 있지 않습니다. "
            "오른쪽 버튼으로 시작하세요. (시작하면 본인 PC가 켜져 있을 때 자동 실행됩니다.)"
        )

with col_d2:
    if daemon_job:
        if st.button("🛑 데몬 중지", use_container_width=True):
            from background_jobs import stop_job
            if stop_job(daemon_job["job_id"]):
                st.success("중지됨")
                st.rerun()
    else:
        if st.button("▶️ 데몬 시작", type="primary", use_container_width=True):
            cmd = [
                sys.executable,
                str(PROJECT_ROOT / "src" / "scheduler" / "runner.py"),
            ]
            try:
                jid = start_job(cmd=cmd, job_type="스케줄러", description="자동 스케줄러 데몬")
                st.success(f"✓ 데몬 시작됨 ({jid})")
                st.rerun()
            except Exception as e:
                st.error(f"데몬 시작 실패: {e}")

if daemon_job:
    with st.expander("📺 데몬 로그 (최근 30줄)"):
        st.code(read_log(daemon_job["job_id"], max_lines=30) or "(로그 없음)", language="text")

st.divider()

# =============================================================================
# 등록된 작업 목록
# =============================================================================

st.markdown("### 📋 등록된 작업")

jobs = list_jobs()

if not jobs:
    st.info("아직 등록된 자동 작업이 없어요. 아래에서 추가해주세요.")
else:
    for j in jobs:
        with st.container(border=True):
            col_t, col_a = st.columns([4, 2])
            with col_t:
                enabled_mark = "🟢" if j.get("enabled", True) else "⚪"
                st.markdown(
                    f"#### {enabled_mark} {j['name']}  \n"
                    f"`{j['id']}` · 종류: **{JOB_TYPES.get(j['type'], j['type'])}**"
                )
                sch = j.get("schedule", {})
                kind = sch.get("kind")
                if kind == "daily":
                    sch_text = f"매일 **{sch.get('time')}**"
                elif kind == "weekly":
                    sch_text = f"매주 **{sch.get('weekday')} {sch.get('time')}**"
                elif kind == "hourly":
                    sch_text = f"매시 **:{int(sch.get('minute', 0)):02d}**"
                elif kind == "every":
                    sch_text = f"**{sch.get('n')}{sch.get('unit')}**마다"
                else:
                    sch_text = str(sch)
                st.caption(f"⏰ {sch_text}")

                last = j.get("last_run")
                last_status = j.get("last_status")
                if last:
                    icon = "✅" if last_status == "success" else "❌" if last_status == "failed" else "⏺"
                    st.caption(f"{icon} 마지막 실행: {last[:19].replace('T', ' ')} ({last_status or '?'})")
                else:
                    st.caption("⏺ 아직 실행된 적 없음")

                # 파라미터 미리보기
                with st.expander("파라미터 보기"):
                    st.json(j.get("params", {}))

            with col_a:
                # 활성/비활성
                new_enabled = st.toggle(
                    "활성",
                    value=j.get("enabled", True),
                    key=f"en_{j['id']}",
                )
                if new_enabled != j.get("enabled", True):
                    update_job(j["id"], enabled=new_enabled)
                    st.rerun()

                # 즉시 실행
                if st.button("▶️ 지금 실행", key=f"run_now_{j['id']}", use_container_width=True):
                    with st.spinner("실행 중..."):
                        result = run_job_once(j["id"])
                    if result["ok"]:
                        st.success(f"✅ 완료 (exit={result['exit_code']})")
                    else:
                        st.error(f"❌ 실패 (exit={result['exit_code']})")
                    if result.get("log_path"):
                        st.caption(f"로그: `{result['log_path']}`")
                    st.rerun()

                # 삭제
                if st.button("🗑️ 삭제", key=f"del_sch_{j['id']}", use_container_width=True):
                    if delete_job(j["id"]):
                        st.success("삭제됨")
                        st.rerun()

st.divider()

# =============================================================================
# 새 작업 추가
# =============================================================================

st.markdown("### ➕ 새 자동 작업 추가")

with st.form("add_scheduled_job"):
    name = st.text_input("작업 이름", placeholder="예: 매일 아침 식당 시트 자동 분류")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        job_type = st.selectbox(
            "어떤 작업?",
            options=list(JOB_TYPES.keys()),
            format_func=lambda k: JOB_TYPES[k],
        )
    with col_t2:
        schedule_kind = st.selectbox(
            "언제?",
            options=list(SCHEDULE_KINDS.keys()),
            format_func=lambda k: SCHEDULE_KINDS[k],
        )

    # 종류별 파라미터 입력
    st.markdown("##### 작업 파라미터")
    params = {}

    if job_type == "blogdex_pipeline":
        # 캠페인 다중 선택 (settings.json에서 로드)
        from utils import load_settings
        settings = load_settings()
        camp_options = list(settings.get("google_sheets", {}).get("campaigns", {}).keys())
        if camp_options:
            params["campaigns"] = st.multiselect(
                "처리할 캠페인",
                options=camp_options,
                default=camp_options[:1],
            )
        else:
            st.warning("⚠️ 등록된 캠페인이 없습니다. 먼저 [설정 → 캠페인]에서 추가하세요.")
        params["dry_run"] = st.checkbox("Dry run (실제 시트 변경 X)", value=False)

    elif job_type == "naver_check":
        params["input_csv"] = st.text_input(
            "입력 CSV 경로",
            placeholder="예: src/naver_check/batch_input.csv",
            help="PROJECT_ROOT 기준 상대경로 또는 절대경로",
        )

    elif job_type == "custom_command":
        params["command_line"] = st.text_input(
            "실행할 명령어",
            placeholder="예: python src/blogdex/sheet_pipeline.py --campaign skin",
        )
        params["via_shell"] = st.checkbox(
            "shell로 실행 (파이프·리다이렉트 사용 시)", value=False
        )

    # 스케줄 입력
    st.markdown("##### 시간 설정")

    schedule_dict = {"kind": schedule_kind}
    if schedule_kind == "daily":
        t = st.time_input("실행 시각", value=datetime.strptime("09:00", "%H:%M").time())
        schedule_dict["time"] = t.strftime("%H:%M")
    elif schedule_kind == "weekly":
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            schedule_dict["weekday"] = st.selectbox("요일", options=WEEKDAYS)
        with col_w2:
            t = st.time_input("실행 시각", value=datetime.strptime("09:00", "%H:%M").time())
            schedule_dict["time"] = t.strftime("%H:%M")
    elif schedule_kind == "hourly":
        schedule_dict["minute"] = int(st.number_input("매시 몇 분에?", min_value=0, max_value=59, value=0))
    elif schedule_kind == "every":
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            schedule_dict["n"] = int(st.number_input("간격 N", min_value=1, value=30))
        with col_e2:
            schedule_dict["unit"] = st.selectbox("단위", options=["minutes", "hours"])

    submitted = st.form_submit_button("➕ 작업 추가", type="primary")

    if submitted:
        if not name:
            st.error("작업 이름을 입력해주세요.")
        else:
            try:
                jid = add_job(
                    name=name,
                    job_type=job_type,
                    params=params,
                    schedule=schedule_dict,
                )
                st.success(f"✅ 작업 추가됨 ({jid}). 데몬이 켜져 있으면 60초 안에 반영됩니다.")
                st.rerun()
            except Exception as e:
                st.error(f"추가 실패: {e}")

st.divider()

# =============================================================================
# 도움말
# =============================================================================

with st.expander("💡 자동 실행이 안 되나요? (데몬 + 24시간 가동)"):
    st.markdown(
        f"""
**자동 실행 조건**:
- 본 페이지 위쪽의 **▶️ 데몬 시작** 버튼으로 스케줄러를 켜야 합니다
- 데몬이 켜진 PC는 **켜져 있어야** 자동 실행됨 (절전 모드 OFF 권장)

**24시간 가동을 원하면**:
- macOS는 launchd로 데몬 자동 시작 가능
- Linux/NAS는 systemd / Docker 컨테이너로 영구 실행 가능

**작업 정의 파일**:
```
{JOBS_PATH}
```
직접 JSON으로 편집해도 됩니다 (60초 안에 데몬이 자동 재로드).
"""
    )

# 사용법 가이드 — docs/SCHEDULER_GUIDE.md 직접 표시
guide_path = PROJECT_ROOT / "docs" / "SCHEDULER_GUIDE.md"
if guide_path.exists():
    with st.expander("📖 자동 스케줄 사용법 (가이드 전문)", expanded=False):
        try:
            st.markdown(guide_path.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"가이드 로드 실패: {e}")
else:
    st.caption("ℹ️ 자세한 가이드: `docs/SCHEDULER_GUIDE.md` 참조")
