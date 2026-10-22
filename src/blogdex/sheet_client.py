"""
구글 시트 클라이언트 (Service Account 인증)

핵심 기능:
- 시트에서 블로그 주소 + 지수 컬럼 읽기
- '지수' 컬럼이 비어있는 행 찾기 (조회할 대상)
- 지수 값 시트에 쓰기
- 미달자 행을 별도 시트로 이동
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# =============================================================================
# 데이터 구조
# =============================================================================

@dataclass
class SheetRow:
    """시트의 한 행을 표현."""
    row_number: int           # 1-indexed (헤더는 1행, 데이터는 2행부터)
    blog_url: str             # 블로그 주소
    grade: str                # 현재 지수 값 (비어있을 수 있음)
    all_values: list          # 행 전체 값 (미달자 이동 시 사용)


@dataclass
class CampaignConfig:
    """한 캠페인의 시트 설정."""
    name: str                          # 'restaurant' 또는 'skin' 등
    spreadsheet_id: str
    main_sheet_name: str               # 메인 시트 이름 ('시트1' 등)
    rejected_sheet_name: str           # 미달자 시트 이름
    blog_url_column: str               # 블로그 주소 컬럼 (예: 'C')
    grade_column: str                  # 지수 컬럼 (예: 'D')


# =============================================================================
# 설정 로드
# =============================================================================

def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {SETTINGS_PATH}\n"
            f"config/settings.example.json을 복사해서 만들어주세요."
        )
    
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        text = f.read()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # JSON 오류를 사용자가 이해하기 쉽게 진단
        lines = text.split("\n")
        error_line = e.lineno  # 1-indexed
        
        msg = [
            "",
            "=" * 60,
            f"❌ settings.json 파일에 문법 오류가 있습니다",
            "=" * 60,
            f"파일: {SETTINGS_PATH}",
            f"위치: {error_line}번째 줄, {e.colno}번째 글자",
            f"오류: {e.msg}",
            "",
            "문제가 되는 줄 (앞뒤 2줄 포함):",
        ]
        
        # 오류 줄 주변 표시
        start = max(1, error_line - 2)
        end = min(len(lines), error_line + 2)
        for i in range(start, end + 1):
            line_text = lines[i - 1] if i <= len(lines) else ""
            marker = "  ❌ " if i == error_line else "     "
            msg.append(f"{marker}{i:3d}: {line_text}")
        
        msg.extend([
            "",
            "🔧 가장 흔한 원인 / 해결 방법:",
            "",
            "  1. 후행 쉼표 (trailing comma):",
            "     문제:  \"key\": \"value\",}    ← 마지막 } 앞에 쉼표 있음",
            "     해결:  \"key\": \"value\"}     ← 쉼표 제거",
            "",
            "  2. 한국어 따옴표 사용 (Pages 등에서 작성 시 자동 변환됨):",
            "     문제:  \u201ckey\u201d: \u201cvalue\u201d   ← \u201c \u201d 같은 둥근 따옴표",
            "     해결:  \"key\": \"value\"     ← 일반 \" 사용",
            "     팁:    텍스트 에디터(VS Code, Sublime 등)에서 작성 권장",
            "",
            "  3. 작은따옴표 사용:",
            "     문제:  'key': 'value'      ← JSON은 큰따옴표만 허용",
            "     해결:  \"key\": \"value\"",
            "",
            "  4. 키 또는 값에 따옴표 빠짐:",
            "     문제:  key: \"value\"          또는   \"key\": value",
            "     해결:  \"key\": \"value\"",
            "",
            "💡 가장 쉬운 해결법:",
            "   1) config/settings.example.json 을 다시 복사",
            "      cp config/settings.example.json config/settings.json",
            "   2) 텍스트 에디터(VS Code 등)로 settings.json 열어서 본인 시트 ID만 변경",
            "",
            "=" * 60,
        ])
        
        raise ValueError("\n".join(msg)) from None


def get_campaign_config(campaign_name: str) -> CampaignConfig:
    """settings.json에서 특정 캠페인 설정 로드."""
    settings = load_settings()
    campaigns = settings.get("google_sheets", {}).get("campaigns", {})
    
    if campaign_name not in campaigns:
        available = list(campaigns.keys())
        raise ValueError(
            f"'{campaign_name}' 캠페인 설정이 없습니다.\n"
            f"settings.json에 등록된 캠페인: {available}"
        )
    
    cfg = campaigns[campaign_name]
    return CampaignConfig(
        name=campaign_name,
        spreadsheet_id=cfg["spreadsheet_id"],
        main_sheet_name=cfg.get("main_sheet_name", "시트1"),
        rejected_sheet_name=cfg.get("rejected_sheet_name", "미달"),
        blog_url_column=cfg.get("blog_url_column", "C"),
        grade_column=cfg.get("grade_column", "D"),
    )


# =============================================================================
# 인증 + 클라이언트
# =============================================================================

def get_client():
    """
    gspread 클라이언트 생성.

    인증 우선순위 (settings.json의 google_sheets.auth_mode):
      - "oauth"  : OAuth 사용자 토큰 (settings.google_sheets.oauth_user 지정)
      - "service" or 미지정: Service Account (.json 키 파일)

    OAuth로 설정됐는데 토큰이 없거나 실패하면 Service Account로 fallback.
    """
    settings = load_settings()
    gs = settings.get("google_sheets", {})
    auth_mode = gs.get("auth_mode", "service")

    # ---- OAuth 우선 ----
    if auth_mode == "oauth":
        oauth_user = gs.get("oauth_user", "default")
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT / "src"))
            from google_oauth.oauth_flow import get_gspread_client  # type: ignore
            client = get_gspread_client(oauth_user)
            if client is not None:
                return client
        except Exception:
            pass
        # fallback
        print(
            f"⚠️ OAuth 토큰을 찾지 못했습니다 (user='{oauth_user}'). "
            "Service Account로 시도합니다."
        )

    # ---- Service Account ----
    creds_path_str = gs.get(
        "credentials_path",
        "config/google_credentials.json"
    )
    creds_path = PROJECT_ROOT / creds_path_str

    if not creds_path.exists():
        raise FileNotFoundError(
            f"인증 정보가 없습니다.\n"
            f"  - Service Account 키 파일: {creds_path} (없음)\n"
            f"  - 또는 설정 페이지에서 OAuth 로그인을 진행하세요."
        )

    creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    return gspread.authorize(creds)


# =============================================================================
# 컬럼 변환 헬퍼
# =============================================================================

def column_to_index(col: str) -> int:
    """엑셀 컬럼명(A, B, ..., AA, AB...)을 0-based 인덱스로."""
    col = col.upper().strip()
    result = 0
    for ch in col:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1  # 0-based


# =============================================================================
# 시트 읽기
# =============================================================================

def get_pending_rows(campaign: CampaignConfig) -> list[SheetRow]:
    """
    지수 컬럼이 비어있는 행들 반환 (= 블덱스로 조회해야 할 대상).
    
    이미 지수가 들어있는 행은 스킵 (사용자 요구: "조회된건 추가 조회 X").
    """
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    ws = sh.worksheet(campaign.main_sheet_name)
    
    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        return []  # 헤더만 있거나 빈 시트
    
    blog_idx = column_to_index(campaign.blog_url_column)
    grade_idx = column_to_index(campaign.grade_column)
    
    pending = []
    for row_num, row in enumerate(all_values[1:], start=2):  # 헤더 제외, 2행부터
        # 행이 충분히 길지 않으면 패딩
        while len(row) <= max(blog_idx, grade_idx):
            row.append("")
        
        blog_url = row[blog_idx].strip()
        grade = row[grade_idx].strip()
        
        # 블로그 주소 없으면 스킵
        if not blog_url:
            continue
        
        # 이미 지수 입력된 행은 스킵
        if grade:
            continue
        
        pending.append(SheetRow(
            row_number=row_num,
            blog_url=blog_url,
            grade=grade,
            all_values=row.copy(),
        ))
    
    return pending


def get_all_rows(campaign: CampaignConfig) -> list[SheetRow]:
    """모든 데이터 행 반환 (디버그용)."""
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    ws = sh.worksheet(campaign.main_sheet_name)
    
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return []
    
    blog_idx = column_to_index(campaign.blog_url_column)
    grade_idx = column_to_index(campaign.grade_column)
    
    rows = []
    for row_num, row in enumerate(all_values[1:], start=2):
        while len(row) <= max(blog_idx, grade_idx):
            row.append("")
        rows.append(SheetRow(
            row_number=row_num,
            blog_url=row[blog_idx].strip(),
            grade=row[grade_idx].strip(),
            all_values=row.copy(),
        ))
    return rows


# =============================================================================
# 시트 쓰기
# =============================================================================

def write_grade(campaign: CampaignConfig, row_number: int, grade: str) -> None:
    """특정 행의 지수 컬럼에 값 쓰기."""
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    ws = sh.worksheet(campaign.main_sheet_name)
    
    cell = f"{campaign.grade_column}{row_number}"
    ws.update_acell(cell, grade)


def batch_write_grades(campaign: CampaignConfig, updates: list[tuple[int, str]]) -> None:
    """
    여러 행의 지수를 한 번의 API 호출로 쓰기 (배치).
    
    Args:
        updates: [(row_number, grade), ...]
    """
    if not updates:
        return
    
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    ws = sh.worksheet(campaign.main_sheet_name)
    
    # gspread batch_update 형식
    data = []
    for row_num, grade in updates:
        data.append({
            "range": f"{campaign.grade_column}{row_num}",
            "values": [[grade]],
        })
    
    ws.batch_update(data)


# =============================================================================
# 미달자 시트로 이동
# =============================================================================

def ensure_rejected_sheet(campaign: CampaignConfig) -> None:
    """미달자 시트가 없으면 생성, 있으면 그대로."""
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    
    # 이미 있는지 확인
    try:
        sh.worksheet(campaign.rejected_sheet_name)
        return  # 이미 있음
    except gspread.exceptions.WorksheetNotFound:
        pass
    
    # 없으면 만들기 (메인 시트와 같은 컬럼 수)
    main_ws = sh.worksheet(campaign.main_sheet_name)
    headers = main_ws.row_values(1)  # 헤더 복사
    
    new_ws = sh.add_worksheet(
        title=campaign.rejected_sheet_name,
        rows=1000,
        cols=max(len(headers), 20),
    )
    if headers:
        new_ws.append_row(headers)


def move_to_rejected(
    campaign: CampaignConfig,
    rows_to_move: list[SheetRow],
    grade_by_row: dict[int, str],
) -> None:
    """
    미달자 행들을 미달자 시트로 이동 (복사 + 메인에서 삭제).
    
    Args:
        rows_to_move: 이동할 SheetRow 리스트
        grade_by_row: {row_number: grade} - 미달자도 어떤 지수인지 기록
    """
    if not rows_to_move:
        return
    
    ensure_rejected_sheet(campaign)
    
    client = get_client()
    sh = client.open_by_key(campaign.spreadsheet_id)
    main_ws = sh.worksheet(campaign.main_sheet_name)
    rejected_ws = sh.worksheet(campaign.rejected_sheet_name)
    
    grade_idx = column_to_index(campaign.grade_column)
    
    # 1) 미달자 시트에 복사 (지수 컬럼은 채워서)
    rows_to_append = []
    for row in rows_to_move:
        values = row.all_values.copy()
        # 지수 컬럼 채우기 (미달자도 무슨 지수였는지 알기 위해)
        while len(values) <= grade_idx:
            values.append("")
        values[grade_idx] = grade_by_row.get(row.row_number, "")
        rows_to_append.append(values)
    
    rejected_ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")
    
    # 2) 메인 시트에서 삭제 (행 번호가 큰 것부터 — 삭제 시 인덱스 밀림 방지)
    sorted_rows = sorted(rows_to_move, key=lambda r: r.row_number, reverse=True)
    for row in sorted_rows:
        main_ws.delete_rows(row.row_number)


# =============================================================================
# 디버그/테스트용
# =============================================================================

def test_connection(campaign_name: str) -> None:
    """연결 테스트 — 시트 정보를 출력해서 권한 확인."""
    print(f"\n🔍 캠페인 '{campaign_name}' 연결 테스트 중...\n")
    
    try:
        cfg = get_campaign_config(campaign_name)
        print(f"  ✓ 설정 로드: spreadsheet_id={cfg.spreadsheet_id}")
        
        client = get_client()
        print(f"  ✓ Service Account 인증 성공")
        
        sh = client.open_by_key(cfg.spreadsheet_id)
        print(f"  ✓ 시트 접근 성공: '{sh.title}'")
        
        ws = sh.worksheet(cfg.main_sheet_name)
        print(f"  ✓ 워크시트 접근: '{cfg.main_sheet_name}' ({ws.row_count}행 x {ws.col_count}열)")
        
        all_rows = get_all_rows(cfg)
        pending = [r for r in all_rows if not r.grade]
        done = [r for r in all_rows if r.grade]
        
        print(f"\n  📊 시트 현황:")
        print(f"     - 전체 데이터 행: {len(all_rows)}")
        print(f"     - 이미 지수 있음: {len(done)}건 (스킵 대상)")
        print(f"     - 지수 비어있음: {len(pending)}건 (조회 대상)")
        
        if pending[:3]:
            print(f"\n  🔎 조회 대상 미리보기 (최대 3건):")
            for row in pending[:3]:
                print(f"     - 행 {row.row_number}: {row.blog_url}")
        
        print(f"\n✅ 모든 점검 통과!")
        
    except Exception as e:
        print(f"\n❌ 연결 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import sys
    campaign = sys.argv[1] if len(sys.argv) > 1 else "restaurant"
    test_connection(campaign)
