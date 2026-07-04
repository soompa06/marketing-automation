"""
① 검수 페이지 — 네이버 노출 자동 확인

사용자 흐름:
1. CSV 파일 업로드 (또는 직접 입력)
2. 옵션 선택 (브라우저 보임/안보임, 디버그 등)
3. "검수 시작" 버튼 클릭
4. 진행 상황 실시간 표시
5. 완료되면 결과 CSV 자동 다운로드 + 다음 단계 안내
"""
import sys
import csv
import io
import time
import subprocess
from datetime import datetime
from pathlib import Path

import streamlit as st

# utils import (parent 폴더)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    PROJECT_ROOT,
    SRC_DIR,
    OUTPUT_DIR,
    list_csv_results,
    get_python_executable,
    format_relative_time,
    notify_job_completion,
    page_header,
)
from background_jobs import start_job, list_jobs, read_log, stop_job, job_outcome, clear_job_logs

setup_page("검수", "📥", feature="check")
ensure_directories()
render_sidebar("check")


# =============================================================================
# 헤더
# =============================================================================

page_header(
    "① 검수 — 네이버 노출 + 스크린샷",
    "📥",
    "체험단 블로거들의 글이 네이버 통합검색과 블로그탭에 어떻게 노출되는지 자동으로 확인합니다.",
)

# =============================================================================
# 검수 모드 선택 (가게별 / 단일 블로그)
# =============================================================================

st.markdown("### 🎯 검수 모드 선택")
check_mode = st.radio(
    "어떤 방식으로 검수할까요?",
    options=["business", "blog"],
    index=0,
    format_func=lambda x: {
        "business": "🏪 가게별 — 한 가게(체험명)의 여러 블로거를 일괄 검수",
        "blog": "📰 단일 블로그 — 특정 블로거 1명만 검수",
    }[x],
    horizontal=True,
    help=(
        "**가게별**: '가게A = 홍길동/김영희/박철수' 처럼 한 가게에 여러 블로거를 묶어서 처리.\n"
        "**단일 블로그**: 특정 블로거 1명만 빠르게 점검."
    ),
)

st.divider()

# =============================================================================
# 입력 방법 선택 (모드에 따라 다름)
# =============================================================================

bloggers_to_check = []

# 가게별: CSV·Excel 업로드 또는 직접 입력 / 단일 블로그: 직접 입력만
if check_mode == "business":
    tab_upload, tab_manual = st.tabs([
        "📂 CSV/Excel 업로드 (권장)",
        "✏️ 직접 입력 (한 줄씩)",
    ])
    show_upload_tab = True
else:
    # 단일 블로그 모드는 한 명만 빠르게 점검 → 엑셀 업로드 없이 직접 입력만
    show_upload_tab = False
    tab_manual = st.container()
    with tab_manual:
        st.caption("👤 한 명의 블로거만 검수합니다. 아래에 정보 입력 후 시작하세요. "
                   "(여러 명을 한 번에 처리하려면 위에서 **🏪 가게별** 모드를 선택해 엑셀을 업로드하세요.)")

if show_upload_tab:
  with tab_upload:
    if check_mode == "blog":
        st.info(
            "📰 **단일 블로그 모드 업로드**: 파일의 각 행이 블로그 1개로 처리됩니다 "
            "(`business_name`은 비워도 됨 — `folder_name`이 결과 파일명·폴더명이 됩니다)."
        )
    st.markdown("#### CSV 파일 형식")
    st.caption("아래와 같은 형식의 CSV 파일을 업로드하세요. 첫 줄은 헤더입니다.")
    
    # 예시 표시
    example_csv = """business_name,folder_name,month,url,campaign,keywords
가게A,홍길동,5,https://m.blog.naver.com/example/12345,restaurant,"둔산동 회식,대전 가성비 맛집"
가게A,김영희,5,https://m.blog.naver.com/example2/67890,restaurant,"둔산동 회식,대전 가성비 맛집"
가게B,박철수,4,https://m.blog.naver.com/example3/11111,skin,"강남 리투오,신논현역 성형외과"
"""

    with st.expander("📋 컬럼 설명"):
        st.markdown(
            """
- **business_name**: 가게/체험명 (예: `가게A`, `가게B`) — 결과 파일명과 보고서 그룹핑에 사용
- **folder_name**: 블로거 폴더명 (예: `홍길동`, `김영희`) — 스크린샷 저장 폴더 이름
- **month**: 모집·마케팅한 월 (예: `5` 또는 `5월`) — *선택*. 결과 파일의 `월` 컬럼에 들어가고,
  스크린샷이 **`{campaign}/{월}월/`** 폴더에 모입니다(예: `성형외과/3월/`).
  이때 파일명 끝에 블로거 이름이 붙어요 (`통합검색_강남_리투오_내돈내산_나정민.png`).
  월을 비우면 기존처럼 날짜·블로거 폴더 구조로 저장됩니다.
- **url**: 블로그 글 URL (모바일/PC 둘 다 가능)
- **campaign**: 종류 (예: `restaurant`, `skin`) — 스크린샷 분류용
- **keywords**: 검수할 키워드들, **쉼표로 구분** (큰따옴표로 감싸야 함)

> 💡 CSV 외에 **Excel(.xlsx, .xls)** 파일도 업로드할 수 있어요. 첫 시트의 첫 줄을 헤더로 읽습니다.
"""
        )
    
    st.code(example_csv, language="csv")
    
    # 예시 파일 다운로드 — 한글 깨짐 방지를 위해 두 가지 인코딩 모두 제공
    col_dl1, col_dl2 = st.columns(2)
    
    with col_dl1:
        # UTF-8 with BOM (Excel 신버전 + 텍스트 에디터 호환)
        csv_with_bom = "\ufeff" + example_csv
        st.download_button(
            label="📥 예시 CSV 다운로드 (UTF-8)",
            data=csv_with_bom.encode("utf-8"),
            file_name="batch_input_example.csv",
            mime="text/csv",
            help="대부분의 환경에서 잘 열립니다. (Excel, VS Code, 메모장 등)",
            use_container_width=True,
        )
    
    with col_dl2:
        # CP949/EUC-KR (한국 Excel 구버전 호환)
        try:
            csv_cp949 = example_csv.encode("cp949")
            st.download_button(
                label="📥 예시 CSV 다운로드 (한국 Excel 호환)",
                data=csv_cp949,
                file_name="batch_input_example_cp949.csv",
                mime="text/csv",
                help="한국 Excel 구버전에서 한글이 깨질 때 이걸 사용하세요.",
                use_container_width=True,
            )
        except UnicodeEncodeError:
            st.caption("(CP949 변환 불가)")
    
    st.markdown("---")
    
    uploaded_file = st.file_uploader(
        "CSV / Excel 파일 업로드",
        type=["csv", "xlsx", "xls"],
        help="CSV(UTF-8/EUC-KR), Excel(.xlsx 또는 .xls) 모두 지원합니다.",
    )

    if uploaded_file:
        try:
            rows = []
            fieldnames = []
            fname = (uploaded_file.name or "").lower()

            if fname.endswith((".xlsx", ".xls")):
                # Excel 파일 → pandas로 첫 시트 읽기
                # .xlsx → openpyxl, .xls(구버전 BIFF) → xlrd
                import pandas as pd
                engine = "openpyxl" if fname.endswith(".xlsx") else "xlrd"
                df = pd.read_excel(uploaded_file, dtype=str, engine=engine)
                df = df.fillna("")
                fieldnames = [str(c).strip() for c in df.columns]
                df.columns = fieldnames
                rows = df.to_dict(orient="records")
                # 모든 값을 문자열로 정리
                rows = [{k: str(v).strip() for k, v in r.items()} for r in rows]
                st.caption(f"✓ Excel({'.xls' if engine=='xlrd' else '.xlsx'}) 첫 시트를 읽었습니다.")
            else:
                # CSV → 인코딩 자동 감지
                content = uploaded_file.read()
                text = None
                for encoding in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
                    try:
                        text = content.decode(encoding)
                        st.caption(f"✓ 인코딩 감지: `{encoding}`")
                        break
                    except UnicodeDecodeError:
                        continue
                if text is None:
                    st.error("CSV 파일 인코딩을 알 수 없습니다.")
                    rows = None
                else:
                    reader = csv.DictReader(io.StringIO(text))
                    rows = list(reader)
                    fieldnames = reader.fieldnames or []

            if rows is None:
                pass
            elif not rows:
                st.warning("파일에 데이터 행이 없습니다.")
            else:
                # 필수 컬럼 확인
                required = {"folder_name", "url", "keywords"}
                actual = set(fieldnames)
                missing = required - actual

                if missing:
                    st.error(f"필수 컬럼 누락: {', '.join(missing)}")
                else:
                    # 업로드 행의 모드는 현재 선택한 검수 모드를 따름
                    # (파일에 mode 컬럼이 있으면 그 값을 우선)
                    for r in rows:
                        if not (r.get("mode") or "").strip():
                            r["mode"] = check_mode
                    has_month = "month" in actual
                    mode_label = "가게별 모드" if check_mode == "business" else "단일 블로그 모드"
                    # 미리보기
                    st.markdown(
                        f"**📊 총 {len(rows)}명 검수 예정** ({mode_label})"
                        + ("  ·  `month` 컬럼 인식됨 ✅" if has_month else "")
                    )
                    with st.expander("미리보기 (처음 10명)"):
                        for i, row in enumerate(rows[:10], 1):
                            bn = row.get("business_name", "")
                            bn_str = f"[{bn}] " if bn else ""
                            mon = (row.get("month") or "").strip()
                            mon_str = f"🗓️ {mon}월 · " if mon else ""
                            st.markdown(
                                f"**{i}.** {bn_str}{mon_str}{row['folder_name']} — "
                                f"{row['url'][:60]}...  \n"
                                f"  <small>키워드: {row['keywords']}</small>",
                                unsafe_allow_html=True,
                            )
                    bloggers_to_check = rows
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")

with tab_manual:
    if check_mode == "business":
        st.markdown("#### ✏️ 한 명씩 직접 입력 (가게별 모드)")
    else:
        st.markdown("#### 👤 단일 블로그 정보 입력")

    col1, col2 = st.columns(2)

    store_mode = False
    with col1:
        if check_mode == "business":
            manual_business = st.text_input(
                "체험명(가게명)*",
                placeholder="예: 가게A, 가게B, ○○한의원",
                help="가게명. 가게명 모드에선 이 이름이 '제목 매칭' 기준이 됩니다.",
            )
            store_mode = st.checkbox(
                "🏷️ 가게명으로 노출 확인 (URL 대신 제목에 가게명이 들어간 글 모두 찾기)",
                value=False,
                help="체크하면 블로그 URL 없이, 키워드 검색 결과 중 '포스팅 제목에 "
                     "위 가게명이 포함된 글'을 통합검색·블로그탭에서 전부 수집합니다.",
            )
        else:
            manual_business = ""  # 단일 블로그 모드에선 비움
        manual_folder = st.text_input(
            "폴더명*",
            placeholder="홍길동" if check_mode == "business" else "예: ○○한의원_본인블로그",
            help="스크린샷이 저장될 폴더 이름. 결과 CSV 파일명에도 사용",
        )
        if store_mode:
            manual_url = ""
            st.caption("ℹ️ 가게명 모드: 블로그 URL 입력이 필요 없습니다. "
                       "위 가게명이 제목에 들어간 글을 자동으로 찾습니다.")
        else:
            manual_url = st.text_input(
                "블로그 URL*",
                placeholder="https://m.blog.naver.com/blogger_id/12345678   또는   https://m.blog.naver.com/blogger_id",
                help="글 URL 또는 블로그 홈 URL 둘 다 가능",
            )

    with col2:
        manual_campaign = st.text_input(
            "캠페인 종류",
            value="general",
            help=(
                "스크린샷 폴더 분류용 라벨. 임의의 이름 가능 "
                "(예: restaurant, skin, 병원, cafe 등)."
            ),
        )
        manual_month = st.number_input(
            "모집·마케팅 월 (선택)",
            min_value=0,
            max_value=12,
            value=0,
            step=1,
            help=(
                "이 체험단을 모집·마케팅한 월. 0이면 월 없이 저장됩니다. "
                "지정하면 결과 파일의 '월' 컬럼과 스크린샷 폴더('5월 홍길동')에 들어가요."
            ),
        )
        manual_keywords = st.text_area(
            "검수할 키워드들* (한 줄에 하나씩 또는 쉼표로 구분)",
            placeholder="둔산동 회식\n대전 가성비 맛집",
            height=120,
        )

    keywords_list = [
        k.strip()
        for k in manual_keywords.replace(",", "\n").split("\n")
        if k.strip()
    ] if manual_keywords else []

    # 가게명 모드: URL 없이 가게명 + 폴더 + 키워드만 있으면 됨
    if store_mode:
        if manual_business and manual_folder and keywords_list:
            bloggers_to_check = [{
                "business_name": manual_business,
                "store_name": manual_business,   # 제목 매칭 기준 = 가게명
                "folder_name": manual_folder,
                "url": "",
                "campaign": manual_campaign,
                "keywords": ",".join(keywords_list),
                "mode": "store",
                "month": str(int(manual_month)) if manual_month else "",
            }]
            st.success(f"✓ [가게명] '{manual_business}' · {len(keywords_list)}개 키워드 "
                       "— 제목에 가게명 포함 글 수집 예정")
        else:
            st.info("가게명 · 폴더명 · 키워드를 입력하세요.")
    elif manual_url and manual_folder and keywords_list:
        bloggers_to_check = [{
            "business_name": manual_business or "",
            "folder_name": manual_folder,
            "url": manual_url,
            "campaign": manual_campaign,
            "keywords": ",".join(keywords_list),
            "mode": check_mode,
            "month": str(int(manual_month)) if manual_month else "",
        }]
        if check_mode == "business":
            st.success(f"✓ [가게별] 1명, {len(keywords_list)}개 키워드 검수 예정")
        else:
            st.success(f"✓ [단일 블로그] 1명, {len(keywords_list)}개 키워드 검수 예정")

st.divider()

# =============================================================================
# 검수 옵션
# =============================================================================

st.markdown("### ⚙️ 검수 옵션")

col_opt1, col_opt2, col_opt3 = st.columns(3)

with col_opt1:
    show_browser = st.checkbox(
        "🪟 브라우저 창 보기",
        value=False,
        help=(
            "체크하면 검수 중인 브라우저 창이 보입니다. "
            "체크 해제하면 백그라운드에서 실행되어 사용자 작업을 방해하지 않습니다."
        ),
    )

with col_opt2:
    concurrency = st.slider(
        "🚀 동시 처리 수",
        min_value=1,
        max_value=5,
        value=3,
        help=(
            "한 번에 몇 명을 동시에 처리할지. "
            "높을수록 빠르지만 네이버에서 차단할 위험이 있어요. "
            "기본값 3 권장."
        ),
    )

with col_opt3:
    debug_mode = st.checkbox(
        "🔍 디버그 모드",
        value=False,
        help="에러가 났을 때 더 자세한 정보를 보여줍니다.",
    )

st.divider()

# =============================================================================
# 검수 실행
# =============================================================================

st.markdown("### 🚀 검수 시작")

if not bloggers_to_check:
    st.info("👆 위에서 CSV 파일을 업로드하거나 직접 입력해주세요.")
    st.button("검수 시작", disabled=True, type="primary", use_container_width=True)
else:
    # 예상 시간 계산 (블로거 1명당 평균 30초 가정)
    estimated_minutes = (len(bloggers_to_check) * 30) / 60 / concurrency
    
    st.info(
        f"📊 **검수 대상**: {len(bloggers_to_check)}명  \n"
        f"⏱️ **예상 소요 시간**: 약 {estimated_minutes:.1f}분 "
        f"(동시 처리 {concurrency}명 기준)"
    )
    
    if st.button("✅ 검수 시작", type="primary", use_container_width=True):
        # subprocess에 넘길 입력 CSV.
        # 결과 폴더를 더럽히지 않도록 숨김 폴더(.run_inputs)에 저장하고,
        # 하루 지난 오래된 입력 파일은 자동 정리한다. (사용자에게 노출 안 함)
        run_inputs_dir = OUTPUT_DIR / ".run_inputs"
        run_inputs_dir.mkdir(parents=True, exist_ok=True)
        try:
            cutoff = time.time() - 24 * 3600
            for old in run_inputs_dir.glob("input_*.csv"):
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
        except Exception:
            pass
        tmp_csv = run_inputs_dir / f"input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(tmp_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["business_name", "store_name", "folder_name", "month",
                            "url", "campaign", "keywords", "mode"],
            )
            writer.writeheader()
            for row in bloggers_to_check:
                writer.writerow({
                    "business_name": row.get("business_name", ""),
                    "store_name": row.get("store_name", ""),
                    "folder_name": row.get("folder_name", ""),
                    "month": row.get("month", ""),
                    "url": row.get("url", ""),
                    "campaign": row.get("campaign", "general"),
                    "keywords": row.get("keywords", ""),
                    "mode": row.get("mode", check_mode),
                })
        
        # 명령어 구성
        cmd = [
            get_python_executable(),
            str(SRC_DIR / "naver_check" / "checker.py"),
            "--input", str(tmp_csv),
            "--concurrency", str(concurrency),
        ]
        if not show_browser:
            cmd.append("--headless")
        if debug_mode:
            cmd.append("--debug")
        
        # 백그라운드 작업 시작 (페이지 이동해도 계속 실행)
        try:
            job_id = start_job(
                cmd=cmd,
                job_type="검수",
                description=f"{len(bloggers_to_check)}명 블로거 검수",
            )
            st.session_state["current_check_job"] = job_id
            st.success(f"✓ 검수 작업이 백그라운드에서 시작됐습니다! (ID: {job_id})")
            st.info(
                "💡 다른 페이지로 이동하셔도 작업은 계속 진행됩니다. "
                "이 페이지로 돌아오시면 진행 상황을 확인할 수 있어요."
            )
            st.rerun()
        except Exception as e:
            st.error(f"실행 오류: {e}")

# 진행 중인 작업 표시 (page reload마다 자동으로)
st.markdown("---")
st.markdown("### 📺 진행 상황")

# 현재 검수 관련 작업들 표시
all_check_jobs = list_jobs(job_type="검수", limit=5)
active_jobs = [j for j in all_check_jobs if j.get("running")]
recent_jobs = [j for j in all_check_jobs if not j.get("running")][:3]

# 작업 완료 알림 (실행 중 → 완료 전환 감지)
notify_job_completion(active_jobs, recent_jobs, "seen_check_jobs", title="검수")

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
                if st.button("⏹️ 중지", key=f"stop_{job['job_id']}"):
                    if stop_job(job['job_id']):
                        st.success("작업 중지됨")
                        st.rerun()
            
            # 로그 표시
            log = read_log(job['job_id'], max_lines=30)
            st.code(log, language="text")
    
    # 자동 새로고침 (4초마다)
    st.caption("🔄 4초마다 자동 새로고침됩니다.")
    time.sleep(4)
    st.rerun()

elif recent_jobs:
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.markdown("**📋 최근 검수 결과**")
    with col_h2:
        if st.button("🧹 기록 정리", key="clear_check_logs",
                     help="완료된 검수 작업 기록을 모두 지웁니다. 실행 중인 작업은 유지."):
            n = clear_job_logs(job_type="검수")
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
                st.caption(f"사유: {outcome['reason'] or '작업 중 오류'}")
            st.caption(f"완료: {finished_at}")

            with st.expander("로그 보기"):
                log = read_log(job['job_id'], max_lines=100)
                st.code(log, language="text")
else:
    st.info("아직 진행 중이거나 최근 완료된 검수 작업이 없어요.")

st.divider()

# =============================================================================
# 최근 검수 결과 (참고용)
# =============================================================================

with st.expander("📚 최근 검수 결과 보기"):
    recent = list_csv_results()[:5]
    if not recent:
        st.caption("아직 검수한 결과가 없어요.")
    else:
        for csv_path in recent:
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.markdown(
                    f"**{csv_path.name}**  \n"
                    f"<small>{format_relative_time(csv_path.stat().st_mtime)}</small>",
                    unsafe_allow_html=True,
                )
            with col_b:
                with open(csv_path, "rb") as f:
                    st.download_button(
                        "다운로드",
                        data=f.read(),
                        file_name=csv_path.name,
                        mime="text/csv",
                        key=f"recent_{csv_path.name}",
                    )
