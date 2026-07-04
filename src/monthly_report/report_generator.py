"""
월간보고서 워드 파일 생성기

샘플 형식 (ruca41_02월_월간보고서_2.docx) 그대로 재현:
- 표지: '월간 성과보고서' / 가게명 / 생성일
- 목차
- 1. 검색순위 요약 (표)
- 2-1. 통합검색 (스크린샷 격자: 3열)
- 2-2. 블로그탭 (스크린샷 격자: 3열)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn, nsmap
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor, Inches, Emu

from data_aggregator import Report, KeywordResult


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# =============================================================================
# 스타일/포맷팅 헬퍼
# =============================================================================

NAVY = RGBColor(0x1F, 0x3A, 0x68)        # 표지/제목 색
HEADING_BLUE = RGBColor(0x2E, 0x75, 0xB6)  # 섹션 제목 색
TABLE_BLUE = "D9E1F2"                     # 표 짝수 행 배경 (HEX)
TABLE_HEAD = "B4C7E7"                     # 표 머리행 배경


def set_cell_shading(cell, hex_color: str) -> None:
    """셀 배경색 설정."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_cell_borders(cell, color: str = "BFBFBF", size: int = 4) -> None:
    """셀 테두리 설정."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(size))
        b.set(qn("w:color"), color)
        tc_borders.append(b)
    tc_pr.append(tc_borders)


def add_horizontal_line(paragraph) -> None:
    """단락 아래에 가로선 추가 (표지의 제목 밑줄용)."""
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "1F3A68")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def set_korean_font(run, font_name: str = "맑은 고딕", size_pt: int = 11) -> None:
    """한글 폰트 적용 (한글은 별도 속성 필요)."""
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), font_name)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)


# =============================================================================
# 보고서 생성
# =============================================================================

def add_cover_page(
    doc: Document,
    name: str,
    blog_url: str = "",
    scope: str = "business",
    year: int = 0,
    month: int = 0,
) -> None:
    """
    표지 페이지.
    
    scope='business' → '가게명: ...'
    scope='blogger'  → '블로거: ...'
    """
    # 위쪽 여백
    for _ in range(4):
        doc.add_paragraph()
    
    # 제목 (월 정보 포함하면 더 명확)
    title_text = "월간 성과보고서"
    if year and month:
        title_text = f"{year}년 {month:02d}월 성과보고서"
    
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title_text)
    title_run.bold = True
    title_run.font.color.rgb = NAVY
    set_korean_font(title_run, "맑은 고딕", 28)
    add_horizontal_line(title_p)
    
    for _ in range(3):
        doc.add_paragraph()
    
    # 가게명/블로거명
    # 가게명/블로거명/블로그
    scope_label_map = {
        "business": "가게명",
        "blogger": "블로거",
        "blog": "블로그",
    }
    label = scope_label_map.get(scope, "이름")
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name_p.add_run(f"{label}: {blog_url or name}")
    set_korean_font(name_run, "맑은 고딕", 13)
    
    # 생성일
    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_run = date_p.add_run(f"생성일: {datetime.now().strftime('%Y-%m-%d')}")
    set_korean_font(date_run, "맑은 고딕", 13)
    
    doc.add_page_break()


def add_toc(doc: Document) -> None:
    """목차."""
    h = doc.add_paragraph()
    h_run = h.add_run("목차")
    h_run.bold = True
    h_run.font.color.rgb = HEADING_BLUE
    set_korean_font(h_run, "맑은 고딕", 18)
    
    items = [
        ("1. 검색순위 요약", 0),
        ("2. 스크린샷", 0),
        ("2-1. 통합검색", 1),
        ("2-2. 블로그탭", 1),
    ]
    for text, level in items:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5 + level * 1.0)
        run = p.add_run(text)
        set_korean_font(run, "맑은 고딕", 12)
    
    doc.add_page_break()


def add_section_heading(doc: Document, text: str) -> None:
    """섹션 제목 (예: '1. 검색순위 요약')."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.color.rgb = HEADING_BLUE
    set_korean_font(run, "맑은 고딕", 16)
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(8)


def add_keyword_summary_table(doc: Document, report: Report) -> None:
    """
    1. 검색순위 요약 표.
    컬럼: 키워드 / 제목 / 작성일자 / 상위노출 / 블로그탭
    """
    rows_data = report.keywords_table_rows
    
    table = doc.add_table(rows=1 + len(rows_data), cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    # 컬럼 너비 설정
    col_widths = [Cm(3.0), Cm(6.0), Cm(2.5), Cm(2.0), Cm(2.0)]
    for i, w in enumerate(col_widths):
        for cell in table.columns[i].cells:
            cell.width = w
    
    # 헤더
    header_cells = table.rows[0].cells
    headers = ["키워드", "제목", "작성일자", "상위노출", "블로그탭"]
    for i, text in enumerate(headers):
        cell = header_cells[i]
        cell.text = ""
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(text)
        run.bold = True
        set_korean_font(run, "맑은 고딕", 11)
        set_cell_shading(cell, TABLE_HEAD)
        set_cell_borders(cell)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    
    # 데이터 행
    for row_idx, row_data in enumerate(rows_data, start=1):
        cells = table.rows[row_idx].cells
        values = [
            row_data["keyword"],
            row_data["title"],
            row_data["date"],
            row_data["integrated"],
            row_data["blog_tab"],
        ]
        # 짝수 행에만 배경색 (샘플처럼)
        is_alt = (row_idx % 2 == 1)
        
        for col_idx, value in enumerate(values):
            cell = cells[col_idx]
            cell.text = ""
            para = cell.paragraphs[0]
            para.alignment = (
                WD_ALIGN_PARAGRAPH.CENTER if col_idx != 1
                else WD_ALIGN_PARAGRAPH.LEFT
            )
            run = para.add_run(str(value))
            set_korean_font(run, "맑은 고딕", 10)
            if is_alt:
                set_cell_shading(cell, TABLE_BLUE)
            set_cell_borders(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    
    doc.add_paragraph()


def add_screenshot_grid(
    doc: Document,
    title: str,
    screenshot_paths: list[Path],
    cols: int = 3,
    image_width_cm: float = 5.5,
) -> None:
    """
    스크린샷을 격자로 배치하는 표 (2-1 통합검색 / 2-2 블로그탭).
    
    cols개씩 행으로 배치. 빈 칸은 빈 셀로 둠.
    """
    add_section_heading(doc, title)
    
    if not screenshot_paths:
        p = doc.add_paragraph()
        run = p.add_run("(해당 항목의 스크린샷 없음)")
        run.italic = True
        set_korean_font(run, "맑은 고딕", 10)
        return
    
    # 행 수 계산
    n = len(screenshot_paths)
    rows = (n + cols - 1) // cols
    
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    # 셀 너비 균일하게
    for col in table.columns:
        for cell in col.cells:
            cell.width = Cm(image_width_cm + 0.5)
    
    for idx, img_path in enumerate(screenshot_paths):
        row_idx = idx // cols
        col_idx = idx % cols
        cell = table.rows[row_idx].cells[col_idx]
        
        # 셀 안 첫 번째 단락에 이미지만 삽입 (캡션 없음)
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run()
        
        try:
            run.add_picture(str(img_path), width=Cm(image_width_cm))
        except Exception as e:
            run.add_text(f"[이미지 로드 실패: {img_path.name}]")
        
        set_cell_borders(cell, color="DDDDDD", size=2)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


# =============================================================================
# 스크린샷 수집
# =============================================================================

def collect_screenshots_for_results(
    screenshot_root: Path,
    keyword_results: list,  # list[KeywordResult]
    kind: str,  # "통합검색" or "블로그탭"
) -> list[Path]:
    """
    필터링된 KeywordResult 목록에 해당하는 스크린샷만 수집.

    두 가지 폴더 구조를 모두 지원:
    - 신형(가게별+월): screenshots/{campaign}/{N}월/  (평면)
        · 통합검색_{키워드}_{블로거}.png
        · 블로그탭_{키워드}_{순위}_{블로거}.png
    - 구형: screenshots/{campaign}/{날짜}/{블로거}/
        · 통합검색_{키워드}.png
        · 블로그탭_{키워드}_{순위}위.png

    매칭 기준: (정규화된 블로거, 정규화된 키워드)

    중복 처리:
    - 같은 (블로거, 파일명)이 여러 폴더에 있으면 → 가장 최근(이름 큰) 폴더 1개만 선택
    """
    if not screenshot_root.exists() or not keyword_results:
        return []

    def _safe(s: str) -> str:
        return re.sub(r"[^\w가-힣]+", "_", (s or "").strip()).strip("_")

    def _normalize_folder(name: str) -> str:
        # 구형 폴더가 'N월 홍길동'으로 저장됐을 수도 있으므로 선행 'N월 ' 접두어 제거
        name = re.sub(r"^\s*\d{1,2}\s*월[\s_]+", "", name.strip())
        return re.sub(r"[\s_]+", "_", name.strip())

    def _blog_id(url: str) -> str:
        # post_url에서 blogId 추출 (가게명 모드 스크린샷 파일명이 blogId로 끝남)
        u = url or ""
        m = re.search(r"blog\.naver\.com/([^/\?]+)", u)
        if m:
            return m.group(1)
        m = re.search(r"blogId=([^&]+)", u)
        return m.group(1) if m else ""

    # 대상 조합 만들기
    # 신형은 파일명 전체가 결정되므로 'stem → 의미키' 맵으로 정확 매칭.
    # 구형은 (폴더, 키워드[, 순위]) 집합으로 매칭.
    # 블로그탭은 순위까지 일치해야 함 → 옛 실행에서 순위가 달랐던 스크린샷은 제외.
    target_integrated = set()                    # 구형 통합검색: (norm_folder, safe_kw)
    target_blogtab = set()                       # 구형 블로그탭: (norm_folder, safe_kw, rank)
    new_map: dict[str, tuple] = {}               # 신형/가게명: stem → 의미키
    for kr in keyword_results:
        safe_kw = _safe(kr.keyword)
        safe_blogger = _safe(kr.blogger_folder)
        norm_folder = _normalize_folder(kr.blogger_folder)
        # 가게명 모드: 스크린샷 파일명이 폴더명이 아니라 '실제 글의 blogId'로 끝남
        safe_blogid = _safe(_blog_id(kr.post_url))
        if kind == "통합검색":
            if not kr.integrated_found:
                continue
            target_integrated.add((norm_folder, safe_kw))
            new_map[f"통합검색_{safe_kw}_{safe_blogger}"] = ("I", safe_kw, safe_blogger)
            if safe_blogid:
                new_map[f"통합검색_{safe_kw}_{safe_blogid}"] = ("I", safe_kw, safe_blogid)
        else:
            if not kr.blog_tab_rank:
                continue
            rank = str(kr.blog_tab_rank)
            target_blogtab.add((norm_folder, safe_kw, rank))
            new_map[f"블로그탭_{safe_kw}_{rank}_{safe_blogger}"] = ("B", safe_kw, safe_blogger, rank)
            if safe_blogid:
                new_map[f"블로그탭_{safe_kw}_{rank}_{safe_blogid}"] = ("B", safe_kw, safe_blogid, rank)

    # 의미 기반 중복 제거. 신형(N월 폴더)을 구형(날짜 폴더)보다 우선.
    best: dict[tuple, tuple] = {}  # sem_key → (sort_token, Path)

    def _consider(sem_key, is_new: int, folder_label: str, img):
        sort_token = (is_new, folder_label)
        cur = best.get(sem_key)
        if cur is None or sort_token > cur[0]:
            best[sem_key] = (sort_token, img)

    for campaign_dir in screenshot_root.iterdir():
        if not campaign_dir.is_dir():
            continue
        for sub in campaign_dir.iterdir():
            if not sub.is_dir():
                continue

            # 신형: 'N월' 폴더 — 파일이 바로 이 폴더에 있고 파일명에 블로거 포함
            if re.fullmatch(r"\d{1,2}월", sub.name):
                for img in sorted(sub.glob(f"{kind}_*.png")):
                    sem_key = new_map.get(img.stem)
                    if sem_key is not None:
                        _consider(sem_key, 1, sub.name, img)
                continue

            # 구형: sub = 날짜 폴더, 그 안에 블로거 폴더들
            date_name = sub.name
            for blogger_dir in sub.iterdir():
                if not blogger_dir.is_dir():
                    continue
                folder_name_norm = _normalize_folder(blogger_dir.name)
                blogger_safe = _safe(folder_name_norm)
                for img in sorted(blogger_dir.glob(f"{kind}_*.png")):
                    # 1) 파일명 전체 매칭 우선 (가게명 모드: 파일명에 blogId 포함)
                    sem = new_map.get(img.stem)
                    if sem is not None:
                        _consider(sem, 0, date_name, img)
                        continue
                    # 2) 구형 단일/가게별: (폴더, 키워드[, 순위]) 매칭
                    text = re.sub(r"^(통합검색|블로그탭)_", "", img.stem)
                    rank_mo = re.search(r"_(\d+)위$", text)
                    rank = rank_mo.group(1) if rank_mo else ""
                    file_keyword = re.sub(r"_\d+위$", "", text)
                    if kind == "통합검색":
                        if (folder_name_norm, file_keyword) not in target_integrated:
                            continue
                        _consider(("I", file_keyword, blogger_safe), 0, date_name, img)
                    else:
                        if (folder_name_norm, file_keyword, rank) not in target_blogtab:
                            continue
                        _consider(("B", file_keyword, blogger_safe, rank), 0, date_name, img)

    # 정렬해서 반환 (상위 폴더명, 파일명 순)
    found = [path for _, path in sorted(best.values(), key=lambda x: (x[1].parent.name, x[1].name))]
    return found


# =============================================================================
# 메인 생성 함수
# =============================================================================

def generate_report(
    report_data: Report,
    output_path: Path,
    year: int,
    month: int,
    screenshot_root: Optional[Path] = None,
) -> Path:
    """월간보고서 워드 파일 생성 (블로거 단위 또는 가게 단위)."""
    if screenshot_root is None:
        screenshot_root = PROJECT_ROOT / "screenshots"
    
    doc = Document()
    
    # 기본 폰트
    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(11)
    
    # 표지 (scope에 따라 '가게명' 또는 '블로거' 라벨)
    add_cover_page(
        doc,
        name=report_data.name,
        blog_url=report_data.blog_url,
        scope=report_data.scope,
        year=year,
        month=month,
    )
    
    # 목차
    add_toc(doc)
    
    # 1. 검색순위 요약
    add_section_heading(doc, "1. 검색순위 요약")
    add_keyword_summary_table(doc, report_data)
    doc.add_page_break()
    
    # 2-1. 통합검색 — 필터링된 결과에 해당하는 스크린샷만
    integrated_imgs = collect_screenshots_for_results(
        screenshot_root, report_data.keyword_results, "통합검색"
    )
    add_screenshot_grid(doc, "2-1. 통합검색", integrated_imgs, cols=3)
    
    # 2-2. 블로그탭
    blog_tab_imgs = collect_screenshots_for_results(
        screenshot_root, report_data.keyword_results, "블로그탭"
    )
    add_screenshot_grid(doc, "2-2. 블로그탭", blog_tab_imgs, cols=3)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path
