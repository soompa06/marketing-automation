"""
💬 카톡 모집문구 리마인더 페이지

정책: 자동 발송 금지 (CLAUDE.md). 알림 + 클립보드 복사 보조까지만.

기능:
- 캠페인별 모집문구 템플릿 추가/수정/삭제
- 오늘 보낼 템플릿 한눈에 보기 + 클립보드 복사
- '오늘 보냄' 마킹/취소
- 자동 스케줄(매일 N시) 등록 도우미
"""
import sys
from datetime import datetime, date, time as dtime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import setup_page, render_sidebar, ensure_directories, PROJECT_ROOT, load_settings, page_header

setup_page("카톡 리마인더", "💬")
ensure_directories()
render_sidebar("reminder")

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from reminder.templates import (  # noqa: E402
    list_templates,
    add_template,
    update_template,
    delete_template,
    is_sent_today,
    mark_sent,
    unmark_sent,
    pending_today,
    recent_history,
)
from reminder.notifier import copy_to_clipboard  # noqa: E402
from scheduler.jobs_store import (  # noqa: E402
    list_jobs as list_sched_jobs,
    add_job as add_sched_job,
    delete_job as delete_sched_job,
)

page_header(
    "카톡 모집문구 리마인더",
    "💬",
    "자동 발송 안 함 · 매일 정해진 시간 알림 → 클립보드로 복사 → 카톡에 직접 붙여넣기.",
)

st.divider()

# =============================================================================
# 오늘 미발송 알림 배지
# =============================================================================

pending = pending_today()
if pending:
    st.warning(
        f"📨 **오늘 보낼 모집문구 {len(pending)}개가 아직 안 보내졌어요.** "
        "아래 '오늘의 발송' 섹션에서 확인하세요."
    )
else:
    if list_templates(only_active=True):
        st.success("✅ 오늘 보낼 활성 템플릿을 모두 발송 완료했어요. 수고하셨습니다!")
    else:
        st.info(
            "ℹ️ 아직 등록된 활성 템플릿이 없어요. 아래에서 첫 모집문구를 등록해주세요."
        )

st.divider()

# =============================================================================
# 오늘의 발송
# =============================================================================

st.markdown("### 📋 오늘의 발송")

active_templates = list_templates(only_active=True)
if not active_templates:
    st.caption("활성화된 템플릿이 없습니다.")
else:
    for t in active_templates:
        tid = t["id"]
        sent = is_sent_today(tid)

        with st.container(border=True):
            col_t, col_a = st.columns([5, 2])
            with col_t:
                badge = "✅ 발송 완료" if sent else "🔴 미발송"
                st.markdown(
                    f"**{badge}** · `[{t.get('campaign', '?')}]` **{t.get('name', '?')}**"
                )
                with st.expander("본문 보기"):
                    st.code(t.get("body", ""), language="text")
            with col_a:
                if not sent:
                    if st.button(
                        "📋 복사 + 발송 완료",
                        key=f"copy_{tid}",
                        type="primary",
                        use_container_width=True,
                    ):
                        ok = copy_to_clipboard(t.get("body", ""))
                        mark_sent(tid)
                        if ok:
                            st.success("✓ 클립보드에 복사됨. 카카오톡에 붙여넣으세요.")
                        else:
                            st.info("✓ 발송 완료로 마킹됨 (복사 실패 — 본문 직접 복사 필요)")
                        st.rerun()
                    if st.button(
                        "📋 복사만 (마킹 X)",
                        key=f"copyonly_{tid}",
                        use_container_width=True,
                    ):
                        ok = copy_to_clipboard(t.get("body", ""))
                        if ok:
                            st.toast("📋 복사 완료")
                        else:
                            st.warning("복사 실패 — 본문 직접 선택 후 Cmd+C")
                else:
                    if st.button(
                        "↩️ 발송 마킹 취소",
                        key=f"unmark_{tid}",
                        use_container_width=True,
                    ):
                        unmark_sent(tid)
                        st.rerun()

st.divider()

# =============================================================================
# 템플릿 관리
# =============================================================================

st.markdown("### 🗂️ 템플릿 관리")

all_templates = list_templates()
if all_templates:
    st.markdown(f"**등록된 템플릿: {len(all_templates)}개**")
    for t in all_templates:
        tid = t["id"]
        with st.container(border=True):
            col_h, col_x = st.columns([5, 1])
            with col_h:
                act_mark = "🟢" if t.get("active", True) else "⚪ 비활성"
                st.markdown(f"#### {act_mark} `[{t.get('campaign')}]` {t.get('name')}")
                st.caption(f"id `{tid}` · 수정: {t.get('updated_at', '')[:19].replace('T', ' ')}")
            with col_x:
                if st.button("🗑️ 삭제", key=f"del_t_{tid}"):
                    delete_template(tid)
                    st.success("삭제됨")
                    st.rerun()

            with st.expander("✏️ 편집"):
                new_campaign = st.text_input(
                    "캠페인",
                    value=t.get("campaign", ""),
                    key=f"e_camp_{tid}",
                )
                new_name = st.text_input(
                    "이름",
                    value=t.get("name", ""),
                    key=f"e_name_{tid}",
                )
                new_body = st.text_area(
                    "본문",
                    value=t.get("body", ""),
                    key=f"e_body_{tid}",
                    height=200,
                )
                new_active = st.checkbox(
                    "활성",
                    value=t.get("active", True),
                    key=f"e_act_{tid}",
                )

                changed = (
                    new_campaign != t.get("campaign", "")
                    or new_name != t.get("name", "")
                    or new_body != t.get("body", "")
                    or new_active != t.get("active", True)
                )
                if changed and st.button(
                    "💾 변경 저장",
                    key=f"save_t_{tid}",
                    type="primary",
                ):
                    update_template(
                        tid,
                        campaign=new_campaign,
                        name=new_name,
                        body=new_body,
                        active=new_active,
                    )
                    st.success("저장됨")
                    st.rerun()
else:
    st.info("아직 등록된 템플릿이 없어요. 아래에서 추가해주세요.")

# 새 템플릿 추가 폼
st.markdown("#### ➕ 새 템플릿 추가")
with st.form("add_kakao_template"):
    # 설정에서 등록된 캠페인 목록을 옵션으로 (없으면 자유 입력)
    settings = load_settings()
    camp_options = list(settings.get("google_sheets", {}).get("campaigns", {}).keys())
    if camp_options:
        camp_choice = st.selectbox(
            "캠페인",
            options=camp_options + ["(직접 입력)"],
            index=0,
        )
        if camp_choice == "(직접 입력)":
            new_t_campaign = st.text_input("캠페인 이름 (직접 입력)", placeholder="예: 식당, 피부과")
        else:
            new_t_campaign = camp_choice
    else:
        new_t_campaign = st.text_input(
            "캠페인 이름",
            placeholder="예: restaurant, skin, 병원",
        )

    new_t_name = st.text_input(
        "템플릿 이름",
        placeholder="예: 둔산동 회식 5월 모집",
    )
    new_t_body = st.text_area(
        "모집문구 본문",
        placeholder=(
            "안녕하세요 ☺\n"
            "둔산동 위치한 회식하기 좋은 식당입니다.\n"
            "5월 체험단 모집 중이에요!\n"
            "..."
        ),
        height=200,
    )

    if st.form_submit_button("➕ 추가", type="primary"):
        if not (new_t_campaign and new_t_name and new_t_body):
            st.error("캠페인 / 이름 / 본문은 모두 필수입니다.")
        else:
            try:
                tid = add_template(new_t_campaign, new_t_name, new_t_body)
                st.success(f"✅ 추가됨 ({tid}). 자동 알림을 받으려면 아래에서 스케줄을 등록하세요.")
                st.rerun()
            except Exception as e:
                st.error(f"추가 실패: {e}")

st.divider()

# =============================================================================
# 매일 알림 스케줄 등록
# =============================================================================

st.markdown("### ⏰ 매일 알림 스케줄 등록")
st.caption(
    "지정한 시각이 되면 데스크톱 알림이 떠서 '오늘 N개 보낼 시간'을 알려줍니다. "
    "동작하려면 **⏰ 자동 스케줄** 페이지에서 데몬을 실행해두세요."
)

# 기존 등록된 리마인더 스케줄 표시
existing_reminder_jobs = [
    j for j in list_sched_jobs()
    if j.get("type") == "custom_command"
    and "reminder/runner.py" in (j.get("params", {}) or {}).get("command_line", "")
]

if existing_reminder_jobs:
    st.markdown("**현재 등록된 리마인더 스케줄**")
    for j in existing_reminder_jobs:
        sch = j.get("schedule", {}) or {}
        kind = sch.get("kind")
        sch_text = (
            f"매일 {sch.get('time')}" if kind == "daily"
            else f"매주 {sch.get('weekday')} {sch.get('time')}" if kind == "weekly"
            else str(sch)
        )
        with st.container(border=True):
            col_t, col_d = st.columns([5, 1])
            with col_t:
                en = "🟢" if j.get("enabled", True) else "⚪"
                st.markdown(f"{en} **{j.get('name')}** — {sch_text}")
                st.caption(f"id `{j.get('id')}` · 마지막 실행: {j.get('last_run') or '-'}")
            with col_d:
                if st.button("🗑️", key=f"del_rem_sch_{j['id']}"):
                    delete_sched_job(j["id"])
                    st.success("삭제됨")
                    st.rerun()
else:
    st.info("아직 리마인더 스케줄이 없습니다.")

with st.form("add_reminder_schedule"):
    col_t, col_o = st.columns([2, 2])
    with col_t:
        remind_time = st.time_input(
            "알림 시각 (매일)",
            value=dtime(9, 0),
        )
    with col_o:
        copy_first = st.checkbox(
            "📋 첫 미발송 본문을 자동으로 클립보드에 복사",
            value=True,
            help="알림이 뜨면서 첫 템플릿이 클립보드에 바로 들어가 있어요.",
        )

    if st.form_submit_button("⏰ 매일 알림 등록", type="primary"):
        runner_path = PROJECT_ROOT / "src" / "reminder" / "runner.py"
        cmd_line = f'"{sys.executable}" "{runner_path}"'
        if copy_first:
            cmd_line += " --copy-first"

        try:
            jid = add_sched_job(
                name=f"카톡 리마인더 (매일 {remind_time.strftime('%H:%M')})",
                job_type="custom_command",
                params={"command_line": cmd_line, "via_shell": True},
                schedule={"kind": "daily", "time": remind_time.strftime("%H:%M")},
                enabled=True,
            )
            st.success(
                f"✅ 등록됨 ({jid}). "
                "**⏰ 자동 스케줄** 페이지에서 데몬이 켜져 있는지 확인하세요."
            )
            st.rerun()
        except Exception as e:
            st.error(f"등록 실패: {e}")

st.divider()

# =============================================================================
# 발송 이력
# =============================================================================

st.markdown("### 📅 최근 발송 이력")
hist = recent_history(limit=30)
if not hist:
    st.caption("아직 발송 이력이 없어요.")
else:
    # 템플릿 ID → 이름 매핑
    id_to_name = {t["id"]: f"[{t.get('campaign')}] {t.get('name')}" for t in list_templates()}
    for h in hist:
        tid = h.get("template_id", "")
        name = id_to_name.get(tid, f"(삭제된 템플릿 {tid})")
        at = (h.get("at") or "")[:19].replace("T", " ")
        st.caption(f"✅ {h.get('date')}  ·  {name}  ·  {at}")
