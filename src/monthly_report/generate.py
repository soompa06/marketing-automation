"""
월간보고서 자동 생성 CLI

핵심 동작:
1. output/check_results_*.csv 모두 로드 (검수 시점 무관)
2. 각 블로그 포스트 URL의 제목·작성일자 자동 추출 (캐시 사용)
3. **포스트 작성일자**가 보고 월에 해당하는 항목만 필터링
4. 블로거 단위 또는 가게 단위로 그룹핑
5. 워드 보고서 생성

사용 예시:
    # 가장 흔한 사용: 이번 달, 모든 가게
    python generate.py
    
    # 특정 월
    python generate.py --year 2026 --month 4
    
    # 블로거 단위로 (가게가 아닌 블로거별 보고서)
    python generate.py --scope blogger
    
    # 특정 블로거만
    python generate.py --scope blogger --name "가게A_홍길동"
    
    # 특정 가게만
    python generate.py --scope business --name "가게A"
    
    # 가게 블로그 URL 매핑 (보고서 표지에 표시)
    python generate.py --blog-urls config/businesses.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

# 같은 폴더 모듈 import
sys.path.insert(0, str(Path(__file__).parent))
from data_aggregator import (
    PROJECT_ROOT,
    load_all_check_results,
    enrich_with_blog_meta,
    filter_by_post_month,
    group_by_business,
    group_by_blogger,
    group_by_blog,
    _read_with_encoding,
)
from report_generator import generate_report


def load_blog_urls(csv_path: Path) -> dict:
    """가게/블로거명 → 블로그 URL 매핑 CSV 로드."""
    if not csv_path.exists():
        return {}
    
    text = _read_with_encoding(csv_path)
    reader = csv.DictReader(io.StringIO(text))
    mapping = {}
    for row in reader:
        # 컬럼명 유연하게 (business_name 또는 blogger_name 또는 name)
        name = (
            (row.get("name") or "").strip()
            or (row.get("business_name") or "").strip()
            or (row.get("blogger_name") or "").strip()
        )
        url = (row.get("blog_url") or "").strip()
        if name and url:
            mapping[name] = url
    return mapping


def main():
    now = datetime.now()
    
    parser = argparse.ArgumentParser(
        description="월간보고서 자동 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:

  [1] 이번 달, 모든 가게 (가장 흔함)
    python src/monthly_report/generate.py

  [2] 특정 월
    python src/monthly_report/generate.py --year 2026 --month 4

  [3] 블로거 단위 보고서
    python src/monthly_report/generate.py --scope blogger

  [4] 특정 가게만
    python src/monthly_report/generate.py --scope business --name 가게A

  [5] 특정 블로거만
    python src/monthly_report/generate.py --scope blogger --name "가게A_홍길동"

  [6] 가게 블로그 URL 매핑 (표지에 표시)
    python src/monthly_report/generate.py --blog-urls config/businesses.csv
    
    businesses.csv 형식:
        name,blog_url
        가게A,https://blog.naver.com/example-store-a
        가게B,https://blog.naver.com/example-store-b
"""
    )
    
    parser.add_argument("--year", type=int, default=now.year, help=f"보고 연도 (기본: {now.year})")
    parser.add_argument("--month", type=int, default=now.month, help=f"보고 월 (기본: {now.month})")
    parser.add_argument(
        "--scope",
        choices=["business", "blogger", "blog"],
        default="business",
        help=(
            "보고서 단위 선택:\n"
            "  - business: 가게(체험명) 기준 — 한 가게에 1개 보고서 (기본)\n"
            "  - blogger: 블로거 폴더 기준 — 블로거 1명당 1개 보고서\n"
            "  - blog: 블로그(blogId) 기준 — 한 블로그(예: 본인 블로그)의 모든 글을 1개 보고서로"
        )
    )
    parser.add_argument("--name", help="특정 이름만 생성 (가게명/블로거명/blogId)")
    parser.add_argument(
        "--blog-url",
        help="(--scope blog 전용) 특정 블로그 URL만 보고서로. 예: https://blog.naver.com/ruca41"
    )
    parser.add_argument("--blog-urls", help="이름→블로그URL 매핑 CSV 파일 (선택)")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output" / "reports"),
        help="보고서 저장 경로 (기본: output/reports/)"
    )
    parser.add_argument(
        "--no-meta",
        action="store_true",
        help="블로그 메타 자동 추출 스킵 (제목·작성일자 비움, 빠름)"
    )
    parser.add_argument(
        "--include-undated",
        action="store_true",
        help="작성일자 추출 실패한 글도 보고서에 포함 (메타 추출이 실패한 경우)"
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="메타 추출 시 브라우저 창 보기 (기본: 숨김)"
    )
    parser.add_argument(
        "--input-csv",
        action="append",
        default=None,
        help=(
            "사용할 검수 결과 CSV를 명시 (여러 번 지정 가능). "
            "지정 시 output/ 폴더 전체 스캔 대신 이 파일들만 사용. "
            "단일 블로거만 보고서로 만들 때 유용."
        ),
    )

    args = parser.parse_args()
    
    scope_labels = {"business": "가게", "blogger": "블로거", "blog": "블로그"}
    scope_label = scope_labels[args.scope]
    
    print(f"\n{'='*60}")
    print(f"📊 월간보고서 자동 생성: {args.year}년 {args.month}월 (단위: {scope_label})")
    print(f"{'='*60}\n")
    
    # === 1) 모든 검수 결과 로드 ===
    output_dir = PROJECT_ROOT / "output"
    if args.input_csv:
        csv_paths = []
        for p in args.input_csv:
            pp = Path(p)
            if not pp.is_absolute():
                pp = PROJECT_ROOT / p
            if not pp.exists():
                print(f"⚠️  지정한 CSV가 존재하지 않습니다: {pp}")
                sys.exit(1)
            csv_paths.append(pp)
        print(f"📥 [1/4] 검수 결과 CSV 로드 중... (지정된 {len(csv_paths)}개 파일만)")
        all_results = load_all_check_results(output_dir, csv_files=csv_paths)
    else:
        print(f"📥 [1/4] 검수 결과 CSV 로드 중... (output/ 전체 스캔)")
        all_results = load_all_check_results(output_dir)
    
    if not all_results:
        print(f"\n⚠️  검수 결과가 하나도 없습니다.")
        print(f"   먼저 1순위 도구(naver_check)로 검수를 진행해주세요.")
        sys.exit(1)
    
    print(f"\n   총 {len(all_results)}건의 키워드 결과 로드\n")
    
    # === 2) 블로그 메타정보 보강 ===
    if args.no_meta:
        print(f"📥 [2/4] 메타 추출 스킵 (--no-meta)\n")
    else:
        print(f"📥 [2/4] 블로그 포스트 메타정보 추출 중...")
        cache_path = PROJECT_ROOT / "output" / ".blog_meta_cache.json"
        all_results = enrich_with_blog_meta(
            all_results,
            cache_path=cache_path,
            headless=not args.show_browser,
        )
        print()
    
    # === 3) 작성월 필터링 ===
    print(f"📥 [3/4] {args.year}년 {args.month}월 작성 글만 필터링 중...")
    filtered = filter_by_post_month(all_results, args.year, args.month)
    
    # 메타 추출 실패 통계 (디버그)
    from collections import Counter
    months = Counter()
    failed_urls = []
    for r in all_results:
        ym = r.post_year_month
        if ym:
            months[ym] += 1
        else:
            months[("?", "?")] += 1
            if r.post_url not in [u for u in failed_urls]:
                failed_urls.append(r.post_url)
    
    # 추출 실패 항목 진단 출력
    if months.get(("?", "?"), 0) > 0:
        print(f"\n   ⚠️  작성일자 추출 실패: {months[('?', '?')]}건")
        for url in failed_urls[:10]:
            print(f"      - {url}")
        if len(failed_urls) > 10:
            print(f"      ... 외 {len(failed_urls) - 10}개")
        print()
        print(f"   💡 이 글들이 {args.year}년 {args.month}월에 작성된 게 맞다면 다음 옵션으로 포함시킬 수 있습니다:")
        print(f"      python src/monthly_report/generate.py --year {args.year} --month {args.month} --include-undated")
        print()
    
    # --include-undated: 작성일자 추출 실패한 항목도 포함
    if args.include_undated:
        undated = [r for r in all_results if r.post_year_month is None]
        if undated:
            print(f"   📌 --include-undated: 작성일자 미상 {len(undated)}건도 포함")
            filtered = filtered + undated
    
    if not filtered:
        print(f"\n⚠️  {args.year}년 {args.month}월에 작성된 블로그 글이 없습니다.")
        print(f"\n   현재 데이터의 작성월 분포:")
        for (y, m), count in sorted(months.items()):
            label = f"{y}년 {m}월" if isinstance(y, int) else "(작성일 추출 실패)"
            print(f"      {label}: {count}건")
        print(f"\n   해결 방법:")
        print(f"   1. --include-undated 옵션으로 추출 실패 글도 포함")
        print(f"   2. --no-meta 옵션으로 작성일자 필터링 자체 스킵")
        sys.exit(1)
    
    print(f"   필터링 후: {len(filtered)}건\n")
    
    # === 4) 그룹핑 + 워드 생성 ===
    blog_urls = {}
    if args.blog_urls:
        blog_urls = load_blog_urls(Path(args.blog_urls))
        print(f"📋 블로그 URL 매핑: {len(blog_urls)}개 로드")
    
    if args.scope == "business":
        reports = group_by_business(filtered, blog_urls, args.year, args.month)
    elif args.scope == "blogger":
        reports = group_by_blogger(filtered, blog_urls, args.year, args.month)
    else:  # blog
        reports = group_by_blog(filtered, args.blog_url, args.year, args.month)
    
    if args.name:
        reports = [r for r in reports if r.name == args.name]
        if not reports:
            print(f"\n⚠️  '{args.name}' 항목을 찾을 수 없습니다.")
            print(f"   사용 가능한 {scope_label} 목록:")
            if args.scope == "business":
                all_groups = group_by_business(filtered, blog_urls, args.year, args.month)
            elif args.scope == "blogger":
                all_groups = group_by_blogger(filtered, blog_urls, args.year, args.month)
            else:
                all_groups = group_by_blog(filtered, None, args.year, args.month)
            for r in all_groups:
                print(f"      - {r.name} ({len(r.keyword_results)}건)")
            sys.exit(1)
    
    print(f"\n📁 {scope_label} 수: {len(reports)}")
    for r in reports:
        print(f"   - {r.name}: 키워드 {len(r.keyword_results)}건")
    
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📝 [4/4] 워드 보고서 생성 중...\n")
    success_count = 0
    for report in reports:
        # 파일명에 안전하지 않은 문자 제거
        safe_name = report.name.replace("/", "_").replace("\\", "_")
        filename = f"{safe_name}_{args.year}년_{args.month:02d}월_월간보고서.docx"
        output_path = output_root / filename
        
        try:
            generate_report(
                report_data=report,
                output_path=output_path,
                year=args.year,
                month=args.month,
            )
            print(f"   ✅ {output_path.name}")
            success_count += 1
        except Exception as e:
            print(f"   ❌ {report.name} 실패: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"✅ 완료! {success_count}/{len(reports)}개 보고서 생성")
    print(f"   저장 위치: {output_root}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
