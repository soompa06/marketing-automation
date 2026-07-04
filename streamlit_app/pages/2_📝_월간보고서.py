"""
② 월간보고서 페이지

사용자 흐름:
1. 보고서 단위 선택 (가게별 / 블로거별 / 단일 블로그)
2. 년/월 선택
3. 옵션 (메타 추출 여부, 작성일 미상 포함 여부)
4. "보고서 생성" → 워드 파일 자동 생성
5. 다운로드 + 미리보기
"""
import sys
import json
import re
import time
import subprocess
from datetime import datetime, date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    PROJECT_ROOT,
    SRC_DIR,
    OUTPUT_DIR,
    list_csv_results,
    list_reports,
    get_python_executable,
    format_relative_time,
    format_file_size,
    notify_job_completion,
    page_header,
)
from background_jobs import start_job, list_jobs, read_log, stop_job, clear_job_logs

setup_page("월간보고서", "📝", feature="report")
ensure_directories()
render_sidebar("report")


# =============================================================================
# 헤더
# =============================================================================

page_header(
    "② 월간보고서 자동 생성",
    "📝",
    "검수 결과를 모아서 워드(.docx) 보고서로 자동 생성합니다. 표지·검색순위 요약표·스크린샷 포함.",
)

st.divider()

# =============================================================================
# CSV 결과 파일 미리 확인 (없으면 검수부터 안내)
# =============================================================================

available_csvs = list_csv_results()
if not available_csvs:
    st.warning(
        "📥 **검수 결과가 없습니다.** "
        "월간보고서를 만들려면 먼저 검수를 진행해야 해요."
    )
    st.info("👈 좌측 사이드바에서 **'검수'** 메뉴를 클릭해서 진행하세요.")
    st.stop()

st.success(f"✓ 검수 결과 {len(available_csvs)}개 파일 발견")

# =============================================================================
# 사용할 결과 파일 선택 (메인 UI로 끌어올림)
# =============================================================================

st.markdown("### 📂 보고서에 포함할 결과 CSV 선택")
st.caption(
    "기본은 **전체 사용** (output/ 폴더의 모든 결과 CSV 합산). "
    "특정 파일만 골라서 그 결과만 보고서에 넣을 수도 있습니다 "
    "(예: 단일 블로거 보고서 작성 시)."
)

csv_select_mode = st.radio(
    "선택 방식",
    options=["all", "pick"],
    format_func=lambda x: {
        "all": "📦 전체 사용 (output 폴더의 모든 결과 CSV)",
        "pick": "✅ 특정 파일들만 선택",
    }[x],
    horizontal=True,
    label_visibility="collapsed",
)

selected_csvs = []
if csv_select_mode == "pick":
    # ⚠️ 옵션 라벨은 '파일명'으로 고정 (상대시간을 넣으면 시간이 지나며 라벨이 바뀌어
    #    리런 시 선택값이 옵션과 어긋나는 버그가 생김). 시간은 별도 캡션으로 표시.
    name_to_path = {}
    for p in available_csvs:
        name_to_path[p.name] = p   # 파일명은 list_csv_results에서 고유

    picked_names = st.multiselect(
        "사용할 CSV (여러 개 선택 가능)",
        options=list(name_to_path.keys()),
        help="검수 결과 파일을 골라 그 파일들만 보고서에 넣습니다. 1개만 골라도 됩니다.",
    )
    selected_csvs = [name_to_path[n] for n in picked_names if n in name_to_path]

    if not selected_csvs:
        st.warning("⚠️ 한 개 이상의 CSV를 선택하거나 위에서 '전체 사용'을 선택하세요.")
    else:
        st.success(f"✓ 선택한 **{len(selected_csvs)}개 파일만** 사용합니다. (나머지는 제외)")
        for p in selected_csvs:
            st.caption(f"  • {p.name}  ·  {format_relative_time(p.stat().st_mtime)}")
else:
    # 전체 모드 — 미리보기 expander로
    with st.expander("📋 전체 결과 파일 목록 보기"):
        for csv_path in available_csvs[:20]:
            st.markdown(
                f"- **{csv_path.name}**  \n"
                f"  <small>{format_relative_time(csv_path.stat().st_mtime)}</small>",
                unsafe_allow_html=True,
            )
        if len(available_csvs) > 20:
            st.caption(f"... 외 {len(available_csvs) - 20}개 더 있음")

st.divider()

# =============================================================================
# 수동 작성일 매핑 (메타 추출 실패하는 URL 보정)
# =============================================================================

META_CACHE_PATH = OUTPUT_DIR / ".blog_meta_cache.json"


def _load_meta_cache() -> dict:
    if META_CACHE_PATH.exists():
        try:
            return json.loads(META_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_meta_cache(cache: dict):
    META_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _normalize_naver_url(url: str) -> str:
    """data_aggregator의 _normalize_url과 동일 규칙 (캐시 키 일치를 위해)."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    host = parsed.netloc.lower()
    if "blog.naver.com" not in host:
        return url
    if "postview" in parsed.path.lower():
        params = parse_qs(parsed.query)
        bid = params.get("blogId", [""])[0]
        pno = params.get("logNo", [""])[0]
        if bid and pno:
            return f"https://blog.naver.com/{bid}/{pno}"
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[1].isdigit():
        return f"https://blog.naver.com/{parts[0]}/{parts[1]}"
    return url


with st.expander(
    "📅 작성일 자동 추출이 실패한 URL을 수동으로 지정 (선택)",
    expanded=False,
):
    st.caption(
        "네이버가 메타 추출을 차단하는 경우 작성일이 추출 안 돼서 월 필터에 안 잡힙니다. "
        "여기서 직접 URL + 작성일을 등록하면 자동 추출보다 **우선** 적용됩니다. "
        "여러 줄에 `URL,YYYY-MM-DD` 또는 `URL YYYY-MM-DD` 형식으로 입력하세요."
    )

    raw_input = st.text_area(
        "URL + 작성일",
        placeholder=(
            "https://blog.naver.com/hong_star222/224276864258, 2026-05-03\n"
            "https://m.blog.naver.com/yezzang3353/224257828181, 2026-04-22"
        ),
        height=120,
    )

    col_save, col_show = st.columns([1, 2])
    with col_save:
        if st.button("💾 수동 작성일 저장", type="primary"):
            cache = _load_meta_cache()
            saved = 0
            errors = []
            for line in (raw_input or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                # URL + 날짜 분리 (쉼표/공백/탭)
                parts = re.split(r"[,\s\t]+", line, maxsplit=1)
                if len(parts) != 2:
                    errors.append(f"형식 오류: `{line}`")
                    continue
                url_part, date_part = parts[0].strip(), parts[1].strip()
                m = re.match(r"^(\d{4})[\-./](\d{1,2})[\-./](\d{1,2})", date_part)
                if not m:
                    errors.append(f"날짜 형식 오류: `{date_part}`")
                    continue
                y, mo, d = m.groups()
                norm_url = _normalize_naver_url(url_part)
                if not norm_url:
                    errors.append(f"URL 인식 실패: `{url_part}`")
                    continue
                existing = cache.get(norm_url, {})
                cache[norm_url] = {
                    **existing,
                    "date": f"{int(y):04d}.{int(mo):02d}.{int(d):02d}",
                    "manual": True,
                }
                saved += 1
            if saved:
                _save_meta_cache(cache)
                st.success(f"✅ {saved}건 저장 완료. 보고서 생성 시 이 값들이 우선 적용됩니다.")
            if errors:
                st.error("일부 줄 처리 실패:\n- " + "\n- ".join(errors))

    with col_show:
        cache = _load_meta_cache()
        manual = {u: v for u, v in cache.items() if v.get("manual")}
        if manual:
            st.caption(f"📌 등록된 수동 작성일: **{len(manual)}건**")
            with st.expander("등록된 항목 보기"):
                for u, v in list(manual.items())[:20]:
                    st.caption(f"`{v.get('date')}` — {u[:80]}")
                if len(manual) > 20:
                    st.caption(f"... 외 {len(manual) - 20}건")

st.divider()

# =============================================================================
# 보고서 옵션
# =============================================================================

st.markdown("### 📋 보고서 옵션")

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 보고서 단위")
    scope = st.radio(
        "단위 선택",
        options=["business", "blog"],
        format_func=lambda x: {
            "business": "🏪 가게별 (한 가게당 1개 보고서) - 가장 일반적",
            "blog": "📰 단일 블로그 (특정 블로그 URL의 모든 글)",
        }[x],
        label_visibility="collapsed",
        help=(
            "**가게별**: 한 가게(예: 가게A)에 속한 모든 블로거의 결과를 하나로.\n"
            "**단일 블로그**: 특정 블로그 URL의 결과만 따로."
        ),
    )
    
    # blog scope일 때 URL 입력
    blog_url = ""
    if scope == "blog":
        blog_url = st.text_input(
            "블로그 URL",
            placeholder="https://blog.naver.com/ruca41",
            help="본인 블로그처럼 특정 블로그의 노출 현황만 보고 싶을 때",
        )
        if not blog_url:
            st.caption("⚠️ 블로그 URL을 입력해주세요.")

with col2:
    st.markdown("#### 대상 기간")
    
    today = date.today()
    col_y, col_m = st.columns(2)
    with col_y:
        year = st.number_input(
            "년도",
            min_value=2020,
            max_value=2030,
            value=today.year,
            step=1,
        )
    with col_m:
        month = st.number_input(
            "월",
            min_value=1,
            max_value=12,
            value=today.month,
            step=1,
        )

st.markdown("---")

# 고급 옵션
with st.expander("⚙️ 고급 옵션"):
    col_adv1, col_adv2 = st.columns(2)

    with col_adv1:
        no_meta = st.checkbox(
            "📄 메타 추출 스킵 (빠름)",
            value=False,
            help=(
                "체크하면 블로그 제목/작성일자를 자동 추출하지 않습니다. "
                "보고서 생성이 훨씬 빨라지지만, 표에 제목/작성일자가 비어있게 됩니다."
            ),
        )

    with col_adv2:
        include_undated = st.checkbox(
            "📅 작성일자 미상도 포함",
            value=False,
            help=(
                "메타 추출이 실패한 글도 보고서에 포함시킵니다. "
                "네이버가 일부 페이지를 차단할 때 유용해요."
            ),
        )

    show_browser = st.checkbox(
        "🪟 브라우저 창 보기 (메타 추출 시)",
        value=False,
    )

    specific_name = st.text_input(
        "특정 이름만 (선택)",
        placeholder="예: 가게A, 홍길동",
        help="비워두면 모든 그룹의 보고서를 만듭니다.",
    )

    # (입력 CSV 범위는 페이지 상단의 '📂 보고서에 포함할 결과 CSV 선택' 섹션에서 제어)

st.divider()

# =============================================================================
# 보고서 생성 실행
# =============================================================================

st.markdown("### 🚀 보고서 생성")

# blog scope일 때 URL 검증
can_run = True
if scope == "blog" and not blog_url:
    st.button("보고서 생성", disabled=True, type="primary", use_container_width=True)
    st.caption("⚠️ 블로그 URL을 입력해주세요.")
    can_run = False

if can_run:
    # 옵션 요약
    info_lines = [
        f"📋 **단위**: {scope}",
        f"📅 **기간**: {year}년 {month}월",
    ]
    if scope == "blog":
        info_lines.append(f"📰 **블로그**: {blog_url}")
    if specific_name:
        info_lines.append(f"🎯 **특정 이름**: {specific_name}")
    if no_meta:
        info_lines.append("⚡ **메타 추출 스킵**: 활성")
    if include_undated:
        info_lines.append("📅 **작성일자 미상 포함**: 활성")
    # 사용할 CSV 범위를 버튼 바로 위에서 명확히
    if csv_select_mode == "pick":
        if selected_csvs:
            names = ", ".join(p.name for p in selected_csvs)
            info_lines.append(f"📂 **사용 파일**: 선택한 {len(selected_csvs)}개만 — {names}")
        else:
            info_lines.append("📂 **사용 파일**: (선택 안 됨)")
    else:
        info_lines.append("📂 **사용 파일**: output 폴더 전체")

    st.info("  \n".join(info_lines))
    
    # CSV 선택 모드인데 아무것도 안 골랐으면 차단
    block_run = (csv_select_mode == "pick") and not selected_csvs

    if st.button(
        "📝 보고서 생성",
        type="primary",
        use_container_width=True,
        disabled=block_run,
    ):
        # 명령어 구성
        cmd = [
            get_python_executable(),
            str(SRC_DIR / "monthly_report" / "generate.py"),
            "--year", str(year),
            "--month", str(month),
            "--scope", scope,
        ]

        if scope == "blog" and blog_url:
            cmd.extend(["--blog-url", blog_url])
        if specific_name:
            cmd.extend(["--name", specific_name])
        if no_meta:
            cmd.append("--no-meta")
        if include_undated:
            cmd.append("--include-undated")
        if show_browser:
            cmd.append("--show-browser")
        # 특정 CSV만 사용
        for csv_path in selected_csvs:
            cmd.extend(["--input-csv", str(csv_path)])
        
        try:
            job_id = start_job(
                cmd=cmd,
                job_type="보고서",
                description=f"{year}년 {month}월 ({scope}) 보고서 생성",
            )
            st.session_state["current_report_job"] = job_id
            st.success(f"✓ 보고서 생성이 백그라운드에서 시작됐습니다!")
            st.info(
                "💡 다른 페이지로 이동하셔도 작업은 계속 진행됩니다. "
                "이 페이지로 돌아오시면 진행 상황을 확인할 수 있어요."
            )
            st.rerun()
        except Exception as e:
            st.error(f"실행 오류: {e}")

# 진행 중/최근 보고서 작업 표시
st.markdown("---")
st.markdown("### 📺 진행 상황")

all_report_jobs = list_jobs(job_type="보고서", limit=5)
active_jobs = [j for j in all_report_jobs if j.get("running")]
recent_jobs = [j for j in all_report_jobs if not j.get("running")][:3]

# 작업 완료 알림 (실행 중 → 완료 전환 감지)
notify_job_completion(active_jobs, recent_jobs, "seen_report_jobs", title="보고서")

if active_jobs:
    for job in active_jobs:
        with st.container(border=True):
            col_t, col_s = st.columns([5, 1])
            with col_t:
                st.markdown(f"**🟢 진행 중**: {job.get('description', job['job_id'])}")
                st.caption(f"시작: {job['started_at'][:19].replace('T', ' ')}")
            with col_s:
                if st.button("⏹️ 중지", key=f"stop_report_{job['job_id']}"):
                    if stop_job(job['job_id']):
                        st.success("작업 중지됨")
                        st.rerun()
            
            log = read_log(job['job_id'], max_lines=30)
            st.code(log, language="text")
    
    st.caption("🔄 4초마다 자동 새로고침됩니다.")
    time.sleep(4)
    st.rerun()
elif recent_jobs:
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown("**📋 최근 보고서 작업**")
    with col_h2:
        if st.button("🧹 기록 정리", key="clear_report_logs",
                     help="완료된 보고서 작업 기록(진행상황 로그)을 모두 지웁니다. 실행 중인 작업은 유지."):
            n = clear_job_logs(job_type="보고서")
            st.success(f"작업 기록 {n}건 정리됨")
            st.rerun()
    for job in recent_jobs:
        with st.container(border=True):
            finished_at = job.get('finished_at', '')[:19].replace('T', ' ') if job.get('finished_at') else "?"
            st.markdown(f"**✓ {job.get('description', job['job_id'])}**")
            st.caption(f"완료: {finished_at}")
            with st.expander("로그 보기"):
                log = read_log(job['job_id'], max_lines=100)
                st.code(log, language="text")
else:
    st.info("아직 진행 중이거나 최근 완료된 보고서 작업이 없어요.")

st.divider()

# =============================================================================
# 기존 보고서 목록
# =============================================================================

st.markdown("### 📚 이전에 만든 보고서")

existing_reports = list_reports()
if not existing_reports:
    st.caption("아직 만든 보고서가 없어요.")
else:
    for report in existing_reports[:10]:
        col_a, col_b, col_c = st.columns([4, 2, 1])
        with col_a:
            st.markdown(f"**📝 {report.stem}**")
        with col_b:
            size = format_file_size(report.stat().st_size)
            time_str = format_relative_time(report.stat().st_mtime)
            st.caption(f"{size} · {time_str}")
        with col_c:
            with open(report, "rb") as f:
                st.download_button(
                    "다운로드",
                    data=f.read(),
                    file_name=report.name,
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.wordprocessingml.document"
                    ),
                    key=f"existing_{report.name}",
                )
    
    if len(existing_reports) > 10:
        st.caption(f"... 외 {len(existing_reports) - 10}개 더 있음. **📁 결과 파일 관리**에서 모두 보실 수 있어요.")
