"""
📁 결과 파일 관리 페이지

사용자가 생성된 모든 파일(CSV, 워드, 스크린샷)을:
- 한눈에 보기
- 다운로드
- 삭제
"""
import io
import sys
import shutil
import zipfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    setup_page,
    render_sidebar,
    ensure_directories,
    OUTPUT_DIR,
    SCREENSHOT_DIR,
    list_csv_results,
    list_reports,
    list_screenshot_folders,
    list_empty_screenshot_campaigns,
    delete_screenshot_date_folder,
    delete_file,
    format_relative_time,
    format_file_size,
    page_header,
)

setup_page("결과 파일", "📁", feature="files")
ensure_directories()
render_sidebar("files")


# =============================================================================
# 헤더
# =============================================================================

page_header("결과 파일 관리", "📁",
            "생성된 모든 파일을 보고, 다운로드하고, 삭제할 수 있습니다.")

st.divider()

# =============================================================================
# 탭으로 구분
# =============================================================================

tab_csv, tab_report, tab_screenshot = st.tabs([
    "📄 검수 결과 CSV",
    "📝 월간보고서 (워드)",
    "📸 스크린샷 폴더",
])


# =============================================================================
# 탭 1: CSV
# =============================================================================

with tab_csv:
    csvs = list_csv_results()

    if not csvs:
        st.info("📭 아직 검수한 결과가 없어요. **① 검수**에서 시작해보세요.")
    else:
        st.markdown(f"**검수 결과 {len(csvs)}개**")

        # 일괄 삭제 (안전 장치 포함)
        with st.expander("⚠️ 일괄 삭제 (조심하세요)"):
            st.warning("아래 버튼은 모든 검수 결과 CSV를 한 번에 삭제합니다.")
            confirm_delete_all_csv = st.checkbox(
                "정말 모두 삭제할 수 있게 해주세요",
                key="confirm_csv",
            )
            if st.button(
                "🗑️ 모든 CSV 삭제",
                disabled=not confirm_delete_all_csv,
                type="secondary",
            ):
                deleted = 0
                for csv in csvs:
                    if delete_file(csv):
                        deleted += 1
                st.success(f"✓ {deleted}개 삭제 완료")
                st.rerun()

        st.markdown("---")

        # 개별 파일 목록
        if csvs:
            st.markdown("#### 📄 검수 결과 CSV")
        for csv in csvs:
            with st.container(border=True):
                col_name, col_meta, col_dl, col_del = st.columns([4, 2, 1, 1])

                with col_name:
                    st.markdown(f"**📄 {csv.name}**")

                with col_meta:
                    size = format_file_size(csv.stat().st_size)
                    time_str = format_relative_time(csv.stat().st_mtime)
                    st.caption(f"{size} · {time_str}")

                with col_dl:
                    with open(csv, "rb") as f:
                        st.download_button(
                            "📥",
                            data=f.read(),
                            file_name=csv.name,
                            mime="text/csv",
                            key=f"dl_csv_{csv.name}",
                            help="다운로드",
                        )

                with col_del:
                    if st.button(
                        "🗑️",
                        key=f"del_csv_{csv.name}",
                        help="삭제",
                    ):
                        if delete_file(csv):
                            st.success(f"✓ 삭제: {csv.name}")
                            st.rerun()


# =============================================================================
# 탭 2: 보고서
# =============================================================================

with tab_report:
    reports = list_reports()
    
    if not reports:
        st.info("📭 아직 만든 보고서가 없어요. **② 월간보고서**에서 시작해보세요.")
    else:
        st.markdown(f"**총 {len(reports)}개 보고서**")
        
        with st.expander("⚠️ 일괄 삭제"):
            st.warning("아래 버튼은 모든 워드 보고서를 한 번에 삭제합니다.")
            confirm_delete_all_report = st.checkbox(
                "정말 모두 삭제할 수 있게 해주세요",
                key="confirm_report",
            )
            if st.button(
                "🗑️ 모든 보고서 삭제",
                disabled=not confirm_delete_all_report,
                type="secondary",
            ):
                deleted = 0
                for r in reports:
                    if delete_file(r):
                        deleted += 1
                st.success(f"✓ {deleted}개 삭제 완료")
                st.rerun()
        
        st.markdown("---")
        
        for report in reports:
            with st.container(border=True):
                col_name, col_meta, col_dl, col_del = st.columns([4, 2, 1, 1])
                
                with col_name:
                    st.markdown(f"**📝 {report.stem}**")
                    st.caption(report.name)
                
                with col_meta:
                    size = format_file_size(report.stat().st_size)
                    time_str = format_relative_time(report.stat().st_mtime)
                    st.caption(f"{size} · {time_str}")
                
                with col_dl:
                    with open(report, "rb") as f:
                        st.download_button(
                            "📥",
                            data=f.read(),
                            file_name=report.name,
                            mime=(
                                "application/vnd.openxmlformats-"
                                "officedocument.wordprocessingml.document"
                            ),
                            key=f"dl_report_{report.name}",
                            help="다운로드",
                        )
                
                with col_del:
                    if st.button(
                        "🗑️",
                        key=f"del_report_{report.name}",
                        help="삭제",
                    ):
                        if delete_file(report):
                            st.success(f"✓ 삭제: {report.name}")
                            st.rerun()


# =============================================================================
# 탭 3: 스크린샷
# =============================================================================

with tab_screenshot:
    folders = list_screenshot_folders()
    empty_campaigns = list_empty_screenshot_campaigns()

    # === 빈 캠페인 폴더 정리 (PNG 0장인 부모 폴더) ===
    if empty_campaigns:
        with st.container(border=True):
            st.warning(
                f"🧹 비어있는 캠페인 폴더가 {len(empty_campaigns)}개 있어요: "
                + ", ".join(f"`{p.name}`" for p in empty_campaigns)
            )
            col_clean, col_each = st.columns([2, 5])
            with col_clean:
                if st.button(
                    f"🧹 {len(empty_campaigns)}개 모두 정리",
                    key="clean_empty_campaigns_all",
                    type="primary",
                ):
                    deleted = 0
                    for p in empty_campaigns:
                        if delete_file(p):
                            deleted += 1
                    st.success(f"✓ {deleted}개 정리 완료")
                    st.rerun()
            with col_each:
                for p in empty_campaigns:
                    if st.button(
                        f"🗑️ `{p.name}` 삭제",
                        key=f"clean_empty_campaign_{p.name}",
                    ):
                        if delete_file(p):
                            st.success(f"✓ 삭제: {p.name}")
                            st.rerun()

        st.markdown("---")

    if not folders:
        st.info("📭 아직 스크린샷이 없어요. **① 검수**를 진행하면 자동 생성됩니다.")
    else:
        total = sum(count for _, count in folders)
        st.markdown(f"**총 {len(folders)}개 폴더, {total}개 스크린샷**")
        
        with st.expander("⚠️ 일괄 삭제"):
            st.warning(
                "아래 버튼은 **모든 스크린샷 폴더를 통째로** 삭제합니다. "
                "월간보고서에 스크린샷이 안 들어갈 수 있으니 주의하세요."
            )
            confirm_delete_all_ss = st.checkbox(
                "정말 모두 삭제할 수 있게 해주세요",
                key="confirm_ss",
            )
            if st.button(
                "🗑️ 모든 스크린샷 폴더 삭제",
                disabled=not confirm_delete_all_ss,
                type="secondary",
            ):
                deleted = 0
                for folder, _ in folders:
                    if delete_screenshot_date_folder(folder):
                        deleted += 1
                # 남아있는 빈 캠페인 폴더도 같이 정리
                for p in list_empty_screenshot_campaigns():
                    delete_file(p)
                st.success(f"✓ {deleted}개 폴더 삭제 완료 (빈 캠페인 폴더 포함 정리)")
                st.rerun()
        
        st.markdown("---")
        
        def _build_zip(root: Path, arc_prefix: str = "") -> bytes:
            """폴더를 메모리에서 zip으로 묶어 bytes 반환."""
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in root.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(root)
                        arc = f"{arc_prefix}/{rel}" if arc_prefix else str(rel)
                        zf.write(p, arcname=arc)
            return buf.getvalue()

        # === 전체 스크린샷 한 번에 zip 다운로드 ===
        with st.container(border=True):
            col_t, col_d = st.columns([4, 2])
            with col_t:
                st.markdown(f"**📦 전체 스크린샷 통합 zip**")
                st.caption(f"{len(folders)}개 폴더, {total}장")
            with col_d:
                if st.button("📦 전체 zip 만들기", key="zip_all_ss"):
                    with st.spinner("zip 생성 중..."):
                        try:
                            data = _build_zip(SCREENSHOT_DIR, arc_prefix="screenshots")
                            st.download_button(
                                "⬇️ 전체 zip 다운로드",
                                data=data,
                                file_name="screenshots_all.zip",
                                mime="application/zip",
                                key="dl_zip_all_ss",
                                use_container_width=True,
                            )
                        except Exception as e:
                            st.error(f"zip 생성 실패: {e}")

        st.markdown("---")

        for folder, count in folders:
            # screenshots/{캠페인}/{날짜} 형식
            campaign = folder.parent.name
            date_str = folder.name

            with st.container(border=True):
                col_name, col_meta, col_dl, col_del = st.columns([4, 2, 1, 1])

                with col_name:
                    st.markdown(f"**📸 {campaign} / {date_str}**")
                    # 폴더 안 블로거들 미리보기
                    bloggers = [b.name for b in folder.iterdir() if b.is_dir()][:5]
                    if bloggers:
                        st.caption("블로거: " + ", ".join(bloggers))

                with col_meta:
                    time_str = format_relative_time(folder.stat().st_mtime)
                    st.caption(f"{count}장 · {time_str}")

                with col_dl:
                    # 이 폴더만 zip
                    try:
                        zip_bytes = _build_zip(folder, arc_prefix=f"{campaign}_{date_str}")
                        zip_name = f"screenshots_{campaign}_{date_str}.zip"
                        st.download_button(
                            "📦 zip",
                            data=zip_bytes,
                            file_name=zip_name,
                            mime="application/zip",
                            key=f"zip_ss_{folder}",
                            help=f"이 폴더 ({count}장)를 zip으로 다운로드",
                        )
                    except Exception as e:
                        st.caption(f"zip 실패: {e}")

                with col_del:
                    if st.button(
                        "🗑️",
                        key=f"del_ss_{folder}",
                        help="이 폴더 삭제 (부모 캠페인 폴더가 비면 같이 정리)",
                    ):
                        if delete_screenshot_date_folder(folder):
                            st.success("✓ 폴더 삭제 완료 (빈 부모 폴더 포함 정리)")
                            st.rerun()
