# 📊 블덱스 지수 자동 조회 가이드 (3순위)

## 핵심 개념

블덱스(blogdex.space)에서 블로그 지수를 자동으로 조회합니다.
체험단 신청자 중 **자격 등급(준최6, 준최7, 최적1~4+)**에 해당하는 블로거만 자동 분류합니다.

---

## ⚠️ 사용 전 한 번만 — 첫 로그인

블덱스는 구글 OAuth 로그인을 사용합니다. 자동화 도구로 구글 로그인을 직접 처리하면
구글이 보안 차단을 하므로, **사용자가 직접 한 번 로그인**한 후 그 세션을 저장해서 재사용합니다.

### 첫 로그인 방법

```bash
cd marketing_automation
source venv/bin/activate
python src/blogdex/session.py
```

실행하면:

1. **브라우저 창이 자동으로 열림** (블덱스 페이지)
2. **사용자가 직접 '구글로 로그인' 버튼 클릭** → 본인 구글 계정으로 로그인
3. 로그인 완료 후 **터미널로 돌아와서 Enter 키 누르기**
4. ✅ 세션 저장 완료

**저장되는 위치**: `config/blogdex_session.json` (로그인 쿠키)
- `.gitignore`에 등록되어 GitHub에 안 올라감
- 이 PC에만 저장됨
- 며칠~몇 주 유효 (만료되면 다시 로그인)

---

## 사용법

### 한 명만 조회

```bash
python src/blogdex/blogdex_checker.py --url "https://blog.naver.com/blogger_id"
```

### 여러 명 한 번에 (세미콜론으로 구분)

```bash
python src/blogdex/blogdex_checker.py \
  --urls "https://blog.naver.com/aaa;https://blog.naver.com/bbb;https://blog.naver.com/ccc"
```

### 텍스트 파일로 일괄 조회

`urls.txt` 파일을 만들고:
```
# 한 줄에 하나씩, # 으로 시작하면 주석
https://blog.naver.com/blogger1
https://blog.naver.com/blogger2
https://m.blog.naver.com/blogger3/123456
```

실행:
```bash
python src/blogdex/blogdex_checker.py --input urls.txt
```

---

## 출력 예시

```
📥 블덱스에서 5명 조회 시작
  [1/5] hodudaily 조회 중... ✅ 최적3+
  [2/5] s112j 조회 중... ⚪ 준최5
  [3/5] tngml96 조회 중... ✅ 준최7
  [4/5] yezzang3353 조회 중... ✅ 최적2
  [5/5] haempa 조회 중... ⚪ 일반

============================================================
📊 조회 결과 요약 (전체 5명)
============================================================
  ✅ 자격 충족: 3명
      - hodudaily            → 최적3+
      - tngml96              → 준최7
      - yezzang3353          → 최적2

  ⚪ 자격 미충족: 2명
      - s112j                → 준최5
      - haempa               → 일반
============================================================

✅ 결과 CSV 저장: output/blogdex_지수_20260502_120000.csv
```

생성되는 CSV (Excel에서 바로 열림):

| 블로그ID | 블로그 URL | 지수 | 자격 여부 | 확인일시 |
|---|---|---|---|---|
| hodudaily | https://blog.naver.com/hodudaily | 최적3+ | 자격 | 2026-05-02T12:00:00 |
| s112j | https://blog.naver.com/s112j | 준최5 | 미자격 | ... |

---

## 자격 등급 변경하기

기본 자격 등급:
- 준최6, 준최7
- 최적1, 최적2, 최적3
- 최적1+, 최적2+, 최적3+, 최적4+

이 목록을 변경하려면 `config/settings.json`을 편집:

```json
{
  "blogdex": {
    "qualified_grades": [
      "준최7",
      "최적1",
      "최적1+", "최적2+", "최적3+", "최적4+"
    ]
  }
}
```

---

## 트러블슈팅

### "세션이 만료되었습니다"
→ `python src/blogdex/session.py`를 다시 실행해서 재로그인

### "지수 정보를 찾을 수 없음"
가능한 원인:
1. 블덱스에 처음 검색되는 블로그 → 다음날 다시 조회
2. 블로그가 비공개거나 글이 10개 미만 → 조회 불가
3. 블덱스 사이트 구조가 변경됨 → `--show-browser` 옵션으로 확인

### "구글 로그인이 차단됐어요"
→ Google이 자동화 브라우저를 차단한 것. 수동 로그인 시:
1. 본인 PC의 일반 Chrome에서 평소처럼 블덱스 → 구글 로그인 한 번 해두기
2. 그 후 `session.py`에서 자동화 브라우저로 다시 시도

### 디버그 모드 (브라우저 보면서 실행)
```bash
python src/blogdex/blogdex_checker.py \
  --url "https://blog.naver.com/blogger_id" \
  --show-browser
```

---

## 개발자 — 코드 어디를 수정하면 되나

| 변경하고 싶은 것 | 수정할 파일 / 함수 |
|---|---|
| 자격 등급 목록 (코드 차원) | `blogdex_checker.py` → `load_qualified_grades()` |
| 블덱스 사이트 구조 변경 대응 | `blogdex_checker.py` → `search_blog_index()` |
| 검색창 셀렉터 변경 | `blogdex_checker.py` → `search_blog_index()` 안의 input 찾는 부분 |
| 지수 파싱 패턴 | `blogdex_checker.py` → `search_blog_index()` 안의 `patterns` 배열 |
| 로그인 만료 감지 | `session.py` → `is_logged_in()` |

블덱스는 사이트 구조가 종종 변경될 수 있어서, 이 부분을 가장 자주 수정하게 됩니다.
