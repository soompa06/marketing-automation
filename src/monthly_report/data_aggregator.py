"""
월간보고서 데이터 집계 모듈

워크플로우:
1. output/check_results_*.csv 들을 모두 읽음 (검수가 언제 됐든 무관)
2. 각 블로그 포스트 URL의 메타정보(제목, 작성일자) 자동 추출
3. **포스트 작성일자**가 보고 대상 월에 해당하는 항목만 필터링
4. 블로거별 또는 가게별로 그룹핑

이 방식의 핵심: "검수 시점"이 아니라 "포스트 작성일자" 기준으로 필터링.
→ 4월에 1월에 쓴 글을 검수했어도, 1월 보고서로 들어감.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# =============================================================================
# URL 정규화 헬퍼
# =============================================================================

def _extract_blog_id_post(url: str) -> tuple[str, str]:
    """
    네이버 블로그 URL에서 (블로그ID, 포스트번호) 추출.
    
    지원 형식:
    - https://blog.naver.com/blogId/postNo
    - https://m.blog.naver.com/blogId/postNo
    - https://blog.naver.com/PostView.naver?blogId=xxx&logNo=yyy
    """
    if not url:
        return "", ""
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
    except Exception:
        return "", ""
    
    host = parsed.netloc.lower()
    if "blog.naver.com" not in host:
        return "", ""
    
    # PostView 형식
    if "postview" in parsed.path.lower():
        params = parse_qs(parsed.query)
        bid = params.get("blogId", [""])[0]
        pno = params.get("logNo", [""])[0]
        return bid.strip(), pno.strip()
    
    # /blogId/postNo 형식
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[0], parts[1]
    
    return "", ""


# =============================================================================
# 데이터 구조
# =============================================================================

@dataclass
class KeywordResult:
    """한 블로거의 한 키워드 결과 (포스트 메타정보 포함)."""
    keyword: str
    integrated_found: bool         # 통합검색 노출 여부
    blog_tab_rank: Optional[int]   # 블로그탭 순위 (1~10), 없으면 None
    blogger_folder: str            # 폴더명 (예: 가게A_홍길동)
    post_url: str
    business_name: str = ""        # 체험명/가게명 (CSV의 '체험명' 컬럼, 신규)
    post_title: str = ""           # 블로그 글 제목 (자동 추출)
    post_date: str = ""            # 작성일자 'YYYY.MM.DD' (자동 추출)
    checked_at: str = ""           # 검수 일시
    
    @property
    def post_year_month(self) -> Optional[tuple[int, int]]:
        """작성일자에서 (year, month) 추출. 없으면 None."""
        if not self.post_date:
            return None
        m = re.match(r"^(\d{4})\.(\d{2})\.", self.post_date)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None


@dataclass
class Report:
    """보고서 데이터 (블로거 단위 또는 가게 단위)."""
    name: str                          # 가게명 또는 블로거명
    scope: str                         # 'business' 또는 'blogger'
    blog_url: str = ""                 # 표지에 표시할 URL
    keyword_results: list[KeywordResult] = field(default_factory=list)
    year: int = 0
    month: int = 0
    
    @property
    def keywords_table_rows(self) -> list[dict]:
        """검색순위 요약표용 행 데이터."""
        rows = []
        for r in self.keyword_results:
            rows.append({
                "keyword": r.keyword,
                "title": r.post_title or "(제목 추출 실패)",
                "date": r.post_date or "-",
                "integrated": "노출" if r.integrated_found else "-",
                "blog_tab": f"{r.blog_tab_rank}위" if r.blog_tab_rank else "-",
                "blogger": r.blogger_folder,
                "url": r.post_url,
            })
        # 키워드 → 작성일자 순 정렬
        rows.sort(key=lambda x: (x["keyword"], x["date"]))
        return rows


# =============================================================================
# CSV 파싱
# =============================================================================

def _read_with_encoding(path: Path) -> str:
    """여러 인코딩 자동 시도."""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"{path.name} 인코딩 인식 실패")


def parse_summary(summary: str) -> tuple[list[str], dict[str, int]]:
    """
    결과 요약 문자열 파싱.
    
    예시: "상위노출: 둔산동 회식, 대전 가성비 맛집 / 블로그탭 : 둔산동 회식 4위, 대전 가성비 맛집 4위"
    """
    integrated = []
    blog_tab = {}
    
    parts = summary.split("/")
    for part in parts:
        part = part.strip()
        if part.startswith("상위노출"):
            content = part.split(":", 1)[1].strip()
            if content and content != "없음":
                integrated = [k.strip() for k in content.split(",") if k.strip()]
        elif part.startswith("블로그탭"):
            content = part.split(":", 1)[1].strip()
            if content and content != "없음":
                for item in content.split(","):
                    m = re.match(r"^(.+?)\s+(\d+)위$", item.strip())
                    if m:
                        blog_tab[m.group(1).strip()] = int(m.group(2))
    
    return integrated, blog_tab


def parse_folder_name(folder: str) -> tuple[str, str]:
    """
    폴더명에서 (가게명, 블로거명) 분리.
    
    예시:
        '가게A_홍길동' → ('가게A', '홍길동')
        '가게B_김영희_얼굴전체' → ('가게B', '김영희_얼굴전체')
        '가게A 홍길동' → ('가게A', '홍길동')
    """
    folder = folder.strip()
    for sep in ["_", " "]:
        if sep in folder:
            parts = folder.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return folder, ""


def load_all_check_results(
    output_dir: Path,
    csv_files: Optional[list[Path]] = None,
) -> list[KeywordResult]:
    """
    output/ 폴더의 모든 check_results_*.csv를 통합해서 로드.

    Args:
        output_dir: 결과 폴더 (csv_files가 None일 때만 사용)
        csv_files: 명시적으로 사용할 CSV 파일 리스트. 주어지면 output_dir 스캔 무시.
                   단일 블로거만 보고서로 만들고 싶을 때 유용.

    검수 시점에 관계없이 모두 가져옴 (포스트 작성일자 기준 필터는 나중에).

    중복 처리:
    - 같은 (폴더, URL, 키워드) 조합이 여러 CSV에 있을 수 있음
    - 가장 좋은 결과(노출 됨 + 더 높은 순위)를 채택
    - 검수 시점은 가장 최근 것을 기록
    """
    if csv_files is None and not output_dir.exists():
        return []
    
    # key=(정규화된 folder, 정규화된 url, keyword) → 가장 좋은 KeywordResult 저장
    # 정규화 이유:
    # - '가게A_홍길동' vs '가게A 홍길동' (스페이스/언더스코어 차이) → 같은 사람
    # - 'https://m.blog.naver.com/...' vs 'https://blog.naver.com/...' → 같은 글
    best: dict[tuple[str, str, str], KeywordResult] = {}
    files_loaded = 0
    rows_total = 0
    
    def _normalize_folder(name: str) -> str:
        """폴더명 정규화: 스페이스/언더스코어 통일."""
        return re.sub(r"[\s_]+", "_", name.strip())
    
    def _normalize_url(url: str) -> str:
        """URL 정규화: blogId/postNo만 추출해서 통일된 형식으로."""
        bid, pno = _extract_blog_id_post(url)
        if bid and pno:
            return f"https://blog.naver.com/{bid}/{pno}"
        return url.strip()
    
    # 두 가지 파일명 패턴 모두 지원:
    # - 신규: '{가게명}_노출결과_YYYYMMDD_HHMMSS.csv' (가게별 분리 저장)
    # - 구버전: 'check_results_YYYYMMDD_HHMMSS.csv' (전체 통합 저장)
    # 파일명이 macOS NFD(자모 분리)면 한글 패턴 glob이 놓치므로 NFC 정규화 후 부분일치.
    if csv_files is None:
        matched = []
        for p in output_dir.glob("*.csv"):
            name = unicodedata.normalize("NFC", p.name)
            if name.startswith("_temp_input_"):
                continue
            if "_노출결과_" in name or name.startswith("check_results_"):
                matched.append(p)
        csv_files = sorted(set(matched))
    else:
        csv_files = [Path(p) for p in csv_files]
    
    for csv_file in csv_files:
        try:
            text = _read_with_encoding(csv_file)
            reader = csv.DictReader(io.StringIO(text))
            file_rows = 0
            for row in reader:
                # 신형 CSV: '체험명' '작성일자' '제목' '모드' 컬럼 추가, 구형엔 없음
                business_name = (row.get("체험명") or "").strip()
                folder = (row.get("폴더명") or "").strip()
                url = (row.get("포스트 URL") or "").strip()
                summary = (row.get("결과 요약") or "").strip()
                checked_at = (row.get("확인일시") or "").strip()
                csv_post_date = (row.get("작성일자") or "").strip()
                csv_post_title = (row.get("제목") or "").strip()

                if not folder or not url or not summary or summary.startswith("오류"):
                    continue

                # business_name이 CSV에 없으면 파일명에서 추출 시도
                # 예: '가게A_노출결과_*.csv' → '가게A'
                if not business_name:
                    fname_match = re.match(r"^(.+?)_노출결과_", csv_file.name)
                    if fname_match:
                        business_name = fname_match.group(1)

                integrated_keywords, blog_tab_ranks = parse_summary(summary)
                all_keywords = set(integrated_keywords) | set(blog_tab_ranks.keys())

                # 정규화된 폴더명/URL을 결과 객체에도 저장 (그룹핑 시 일관성)
                norm_folder = _normalize_folder(folder)
                norm_url = _normalize_url(url)

                for keyword in all_keywords:
                    new_result = KeywordResult(
                        keyword=keyword,
                        integrated_found=(keyword in integrated_keywords),
                        blog_tab_rank=blog_tab_ranks.get(keyword),
                        blogger_folder=norm_folder,
                        post_url=norm_url,
                        business_name=business_name,
                        post_date=csv_post_date,
                        post_title=csv_post_title,
                        checked_at=checked_at,
                    )
                    
                    # 중복 제거 키:
                    # (정규화된 폴더, URL, 키워드, 통합검색 결과, 블로그탭 순위)
                    # → 결과값(통합/블로그탭)까지 키에 포함시키므로,
                    #   같은 블로거의 같은 키워드라도 결과가 다르면 별도 항목으로 보존됨
                    # 예: 5/2 검수 6위, 5/4 검수 5위 → 두 항목 모두 표에 들어감
                    #     5/2 검수 6위, 5/4 검수 6위 → 1개만 (더 최근 것)
                    key = (
                        norm_folder, norm_url, keyword.strip(),
                        new_result.integrated_found,
                        new_result.blog_tab_rank,
                    )
                    existing = best.get(key)
                    
                    # 같은 결과값은 가장 최근 검수 시점 것만 보존
                    if existing is None or new_result.checked_at > existing.checked_at:
                        best[key] = new_result
                
                file_rows += 1
            
            files_loaded += 1
            rows_total += file_rows
            print(f"  📄 {csv_file.name}: {file_rows}행")
        except Exception as e:
            print(f"  ⚠️  {csv_file.name} 로드 실패: {e}")
    
    results = list(best.values())
    print(f"   → 총 {files_loaded}개 파일에서 {rows_total}행 읽음")
    print(f"   → 중복 제거 후 {len(results)}건 (같은 결과값은 1개로 통합, 순위 변동은 별도 항목으로 유지)")
    return results


def _is_better_result(new: KeywordResult, old: KeywordResult) -> bool:
    """
    같은 (폴더, URL, 키워드) 조합에서 어느 결과가 더 좋은지 판정.
    
    우선순위:
    1. 통합검색 노출 여부 (노출이 더 좋음)
    2. 블로그탭 순위 (낮은 숫자 = 더 좋음, None은 가장 나쁨)
    3. 검수 시점 (더 최근이 더 좋음, 둘 다 동일할 때만 적용)
    """
    # 1. 통합검색 노출
    if new.integrated_found != old.integrated_found:
        return new.integrated_found  # 새것이 노출됨이면 True
    
    # 2. 블로그탭 순위 (None < 10위 < 9위 < ... < 1위)
    new_rank = new.blog_tab_rank if new.blog_tab_rank else 999
    old_rank = old.blog_tab_rank if old.blog_tab_rank else 999
    if new_rank != old_rank:
        return new_rank < old_rank
    
    # 3. 검수 시점 (최근이 더 좋음)
    return new.checked_at > old.checked_at


# =============================================================================
# 블로그 메타정보 보강
# =============================================================================

def enrich_with_blog_meta(
    results: list[KeywordResult],
    cache_path: Optional[Path] = None,
    headless: bool = True,
) -> list[KeywordResult]:
    """
    각 KeywordResult의 post_url에서 제목·작성일자를 추출해서 채워넣음.
    
    캐시 사용:
    - cache_path가 주어지면 URL→메타 매핑을 JSON으로 저장/로드
    - 같은 URL을 여러 번 다시 추출하지 않음 (월간보고서를 여러 번 만들어도 빠름)
    """
    import json
    
    # 캐시 로드
    cache: dict[str, dict] = {}
    if cache_path and cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            print(f"  💾 캐시 로드: {len(cache)}건")
        except Exception:
            cache = {}
    
    # CSV 자체에 이미 작성일자가 들어있는 항목은 캐시로 옮겨두기
    # (검수 단계에서 메타를 같이 뽑아둔 신형 CSV의 경우)
    for r in results:
        if r.post_url and r.post_date and r.post_url not in cache:
            cache[r.post_url] = {
                "title": r.post_title or "",
                "date": r.post_date,
                "from_csv": True,
            }

    # 추출이 필요한 URL만 추리기
    # - cache에 없는 URL
    # - cache에 있어도 date가 비어 있고 manual/from_csv override가 아닌 경우엔 재시도
    unique_urls = list({r.post_url for r in results if r.post_url})

    def _needs_fetch(u: str) -> bool:
        if u not in cache:
            return True
        entry = cache.get(u, {}) or {}
        if entry.get("manual") or entry.get("from_csv"):
            return False  # 사용자 지정 / CSV에 이미 있는 값은 덮어쓰지 않음
        return not entry.get("date")

    urls_to_fetch = [u for u in unique_urls if _needs_fetch(u)]
    
    if urls_to_fetch:
        from blog_meta import extract_many_sync
        new_meta = extract_many_sync(urls_to_fetch, headless=headless)
        # manual=True인 캐시 항목은 보존하면서 새 메타만 적용
        for url, meta in new_meta.items():
            existing = cache.get(url, {}) or {}
            if existing.get("manual"):
                # 사용자 지정 우선 — date는 보존, title만 새것이 있으면 채움
                if not existing.get("title") and meta.get("title"):
                    existing["title"] = meta["title"]
                cache[url] = existing
            else:
                cache[url] = meta
        
        # 캐시 저장
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"  💾 캐시 저장: {cache_path.name} ({len(cache)}건)")
    else:
        print(f"  💾 모든 메타정보 캐시에서 사용 (재추출 불필요)")
    
    # 결과에 메타 적용
    for r in results:
        meta = cache.get(r.post_url, {})
        r.post_title = meta.get("title", "")
        r.post_date = meta.get("date", "")
    
    return results


# =============================================================================
# 작성일 기준 필터링
# =============================================================================

def filter_by_post_month(
    results: list[KeywordResult],
    year: int,
    month: int,
) -> list[KeywordResult]:
    """포스트 작성일자가 (year, month)에 해당하는 항목만 반환."""
    target = (year, month)
    filtered = []
    for r in results:
        ym = r.post_year_month
        if ym == target:
            filtered.append(r)
    return filtered


def group_by_blog(
    results: list[KeywordResult],
    target_blog_url: Optional[str] = None,
    year: int = 0,
    month: int = 0,
) -> list[Report]:
    """
    블로그(blogId) 단위로 그룹핑.
    
    한 블로그(예: 본인의 ruca41)의 모든 글을 한 보고서에 담을 때 사용.
    여러 블로거의 글이 한 시트에 섞여있어도, blogId 기준으로 묶음.
    
    Args:
        target_blog_url: 특정 블로그 URL이 주어지면 그것만 추출.
                        예: 'https://blog.naver.com/ruca41'
                        없으면 모든 블로그를 각각의 보고서로.
    """
    # 타겟 blog_id 추출
    target_blog_id = None
    if target_blog_url:
        target_blog_id, _ = _extract_blog_id_post(target_blog_url)
        # 포스트 URL 아니라 블로그 홈 URL인 경우
        if not target_blog_id:
            from urllib.parse import urlparse
            parsed = urlparse(target_blog_url if target_blog_url.startswith("http") else "https://" + target_blog_url)
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                target_blog_id = parts[0]
    
    # blog_id별로 그룹핑
    grouped: dict[str, list[KeywordResult]] = defaultdict(list)
    for r in results:
        bid, _ = _extract_blog_id_post(r.post_url)
        if not bid:
            continue
        # 타겟 필터링
        if target_blog_id and bid != target_blog_id:
            continue
        grouped[bid].append(r)
    
    reports = []
    for blog_id, items in grouped.items():
        blog_url = f"https://blog.naver.com/{blog_id}"
        reports.append(Report(
            name=blog_id,
            scope="blog",
            blog_url=blog_url,
            keyword_results=items,
            year=year,
            month=month,
        ))
    
    reports.sort(key=lambda x: x.name)
    return reports


# =============================================================================
# 단위별 그룹핑
# =============================================================================

def group_by_business(
    results: list[KeywordResult],
    business_blog_urls: Optional[dict[str, str]] = None,
    year: int = 0,
    month: int = 0,
) -> list[Report]:
    """
    가게 단위로 그룹핑.
    
    그룹핑 키 우선순위:
    1. KeywordResult.business_name (CSV의 '체험명' 컬럼 또는 파일명에서 추출)
    2. parse_folder_name으로 폴더명에서 가게명 추출 (구버전 호환)
    """
    grouped = defaultdict(list)
    for r in results:
        # business_name이 있으면 그것을 우선 사용
        if r.business_name:
            business = r.business_name
        else:
            business, _ = parse_folder_name(r.blogger_folder)
        grouped[business].append(r)
    
    reports = []
    for business, items in grouped.items():
        reports.append(Report(
            name=business,
            scope="business",
            blog_url=(business_blog_urls or {}).get(business, ""),
            keyword_results=items,
            year=year,
            month=month,
        ))
    
    reports.sort(key=lambda x: x.name)
    return reports


def group_by_blogger(
    results: list[KeywordResult],
    blogger_blog_urls: Optional[dict[str, str]] = None,
    year: int = 0,
    month: int = 0,
) -> list[Report]:
    """블로거 단위로 그룹핑."""
    grouped = defaultdict(list)
    for r in results:
        # 블로거 단위 키 = 폴더명 그대로 (가게A_홍길동, 가게B_김영희_얼굴전체)
        grouped[r.blogger_folder].append(r)
    
    reports = []
    for blogger, items in grouped.items():
        # 블로그 URL은 첫 결과의 post_url에서 블로거 홈만 추출 (또는 매핑)
        blog_url = (blogger_blog_urls or {}).get(blogger, "")
        if not blog_url and items:
            # 자동: post_url에서 블로거 홈 URL 추출
            from urllib.parse import urlparse
            try:
                parsed = urlparse(items[0].post_url)
                parts = [p for p in parsed.path.split("/") if p]
                if parts and parsed.netloc:
                    blog_url = f"https://blog.naver.com/{parts[0]}"
            except Exception:
                pass
        
        reports.append(Report(
            name=blogger,
            scope="blogger",
            blog_url=blog_url,
            keyword_results=items,
            year=year,
            month=month,
        ))
    
    reports.sort(key=lambda x: x.name)
    return reports
