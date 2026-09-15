# Claude Code 작업 지시서

이 문서는 Claude Code가 이 프로젝트에서 작업할 때 따라야 할 규칙입니다.

## 프로젝트 개요

체험단 마케팅 자동화 시스템입니다. 사용자는 식당/피부과 체험단을
모집·관리하는 겸업 프로젝트를 운영하고 있으며, 다음 작업들을 자동화합니다:

1. **네이버 블로그 포스팅 상위노출 확인** (가장 자주 사용)
2. **월간보고서 워드 파일 자동 생성**
3. **블덱스 지수 자동 조회 + 구글 시트 분류**
4. **카톡 모집문구 매일 발송 알림**

## 기본 컨벤션

### 언어
- 모든 응답은 **한국어**로
- 코드 주석도 한국어 우선 (영어 혼용 가능)
- 변수/함수명은 영어 (예: `check_integrated_search`)

### 코드 스타일
- Python 3.10+
- 비동기 작업은 `asyncio` + `playwright.async_api`
- 동기 작업은 `selenium` + `webdriver-manager`
- 타입 힌트 사용 권장
- 중요한 함수에는 docstring 필수

### 파일/폴더 명명
- 스크린샷 폴더:
  - `--month` 지정 시: `screenshots/{campaign}/{N}월/` (가게별/business 모드)
  - `--month` 없을 때: `screenshots/{campaign}/{YYYYMMDD}/{폴더명}/`
- 결과 CSV: `output/{체험명}_노출결과_{YYYYMMDD_HHMMSS}.csv` (예: `계인기_노출결과_20260903_185519.csv`)

### 캠페인 코드 ↔ 실제 가게 매핑
| 코드 | 가게명 | 업종 | 구글시트 탭 |
|------|--------|------|-------------|
| `restaurant` | **계인기** | 만년동/월평동 숯불닭구이·회식 술집 | settings.json `google_sheets.campaigns.restaurant` |
| `skin` | **에딧** | 서초/강남 성형외과 (리투오 스킨부스터) | settings.json `google_sheets.campaigns.skin` |
- `--campaign` 값은 자유 입력이며 스크린샷/결과 폴더 라벨로만 쓰인다. 과거 데이터엔 `계인기`/`에딧`/`general`이 섞여 있음.
- 블덱스 파이프라인(`sheet_pipeline.py --campaign`)은 `restaurant`/`skin` 코드를 그대로 사용.

## 자주 쓰는 명령어 패턴

> ⚠️ 검수는 `checker.py` **하나로** 단건·일괄 모두 처리한다. `batch_check.py`는 존재하지 않는다.
> 실제 인자: `--urls`(복수형, `;`구분) · `--folder-names`(`;`구분) · `--keywords`(`,`구분) · `--campaign` · `--month` · `--input` · `--concurrency`. (`--url`/`--blogger-name`은 없음)

### 단건 검수
```bash
python src/naver_check/checker.py \
  --urls "<URL>" \
  --folder-names "<블로거이름>" \
  --keywords "<쉼표 구분 키워드>" \
  --campaign restaurant \
  --month 9
```
- URL을 빼고 `--folder-names`만 주면 "가게명 검색" 모드 (블로그 글 없이 키워드 순위만 확인)
- 여러 명: `--urls "u1;u2" --folder-names "이름1;이름2"` (키워드·캠페인은 공통)

### 일괄 검수 (블로거별 캠페인·키워드 다르게)
```bash
python src/naver_check/checker.py --input <csv파일>
```
CSV 형식: `business_name,folder_name,month,url,campaign,keywords`
(템플릿: `src/naver_check/batch_input.example.csv`)

## 자주 나오는 사용자 요청 처리법

### "블로그 URL 검수해줘" 패턴
사용자가 블로그 URL을 붙여넣고 검수를 요청하면:

1. URL이 식당(계인기)인지 피부과(에딧)인지 물어보기 (대화 맥락에서 추론 가능하면 생략)
2. 키워드가 명시되지 않으면 `config/settings.json`의 `campaigns.{restaurant|skin}.default_keywords` 사용
3. 블로거 이름(`--folder-names`)이 없으면 사용자에게 한 번 묻기
4. `checker.py --urls ... --folder-names ... --keywords ... --campaign ...` 실행
5. 결과 요약을 보여주고, 구글 시트에 붙여넣을 텍스트는 따로 강조

### 기본 키워드 (`config/settings.json`의 `campaigns.{name}.default_keywords`)
- 식당(restaurant) = **계인기**: "월평동 술집", "월평동 회식", "만년동 닭구이", "대전 한밭수목원 맛집"
- 피부과(skin) = **에딧**: "강남 리투오", "강남 리투오 후기", "강남 리투오 효과"
- (위 값은 과거 `output/*_노출결과_*.csv`에서 실제로 순위가 잡힌 키워드 기준. 매달 바뀔 수 있으니 사용자에게 확인)

### "가이드 문구 / 모집 문구 알려줘" 패턴
별도 가이드 md 파일은 없다. 문구는 아래 JSON에 저장돼 있음:
- 카톡 모집문구: `config/kakao_templates.json` — 계인기(restaurant)·에딧(skin)별 `name`·`body`
- 네이버 비밀댓글 문구: `config/comment_templates.json` — `default` + `by_keyword`

## 절대 하지 말아야 할 것

1. **카카오톡 자동 발송 시도하지 말 것** — 사용자가 명시적으로 수동 처리를 원함
2. **블덱스 로그인 정보를 코드에 하드코딩하지 말 것** — 항상 `config/settings.json` (gitignore 됨)을 통해 읽기
3. **민감한 블로거 개인정보(연락처, 카톡 ID)를 출력 로그에 남기지 말 것** — 디버그 출력 시 마스킹
4. **네이버 셀렉터를 임의로 바꾸지 말 것** — 변경이 필요하면 사용자에게 확인 후 진행

## 네이버 SERP 셀렉터 디버깅

네이버 검색 결과 페이지가 변경되어 노출 확인이 실패할 때:

1. `--headless` 옵션 없이 실행해서 실제 화면 확인
2. 개발자 도구로 새 셀렉터 파악
3. `src/naver_check/checker.py`의 `blog_selectors` / `item_selectors` 리스트 상단에 추가
4. 기존 셀렉터는 호환성을 위해 유지

## 우선순위별 진행 상황

- [x] 1순위: 네이버 상위노출 확인 (`src/naver_check/`)
- [x] 2순위: 월간보고서 (`src/monthly_report/`)
- [x] 3순위: 블덱스 지수 확인 (`src/blogdex/`)
- [x] 4순위: 카톡 발송 리마인더 (`src/reminder/`) — 자동 발송 X, 알림+클립보드 복사

부가 기능:
- [x] 백업/복원 (`src/backup/`, 설정 페이지)
- [x] Google OAuth (`src/google_oauth/`)
- [x] 자동 스케줄러 (`src/scheduler/`, ⏰ 페이지)
- [x] NAS 배포 (`deploy/`) — 작성만 완료, 실제 NAS 테스트 보류
- [x] 네이버 모집 비밀댓글 (`src/naver_comment/`, 💬 네이버_댓글모집 페이지)
  - 키워드 블로그탭 1~20위 포스팅에 모집글을 **비밀댓글**로 작성
  - 블로거(blogId) 단위 **3개월 이내 중복 방지** (`history_store`)
  - 키워드별 문구 (`templates_store`), 없으면 기본 문구
  - 로그인은 블덱스식 **수동 1회 → 세션 재사용** (`naver_session.py`, 비번 저장 안 함)
    - ⚠️ 파일명은 `naver_session.py` (블덱스 `session.py`와 모듈명 충돌 방지 — 한 프로세스에서 둘 다 import되므로 고유 이름 필수)
  - **사람처럼**: 댓글 간 랜덤 대기(기본 2~5분)·회당/하루 한도 → 스팸/차단 회피
  - 댓글창 없음/차단은 안전하게 건너뜀
  - ⚠️ **자동화 브라우저(Playwright Chromium)는 입력 방식(타이핑/붙여넣기/execCommand)과 무관하게**
    네이버가 사후에 비밀댓글을 삭제함이 검증됨 (사용자 수동 작성은 안 지워짐).
  - ✅ **해결: 실제 Chrome 연결(CDP) 방식** (`chrome_cdp.py`, `--use-chrome`)
    - 사용자가 `start_chrome_mac.sh`/`start_chrome_win.bat`로 진짜 Chrome을 디버그 포트(9222)로 1회 실행 + 네이버 로그인
    - 도구가 `connect_over_cdp`로 그 Chrome에 붙어 댓글 작성 → 진짜 사람 브라우저라 탐지/삭제 회피
    - CDP 모드는 그 Chrome 단일 계정만 사용(로테이션 X), 작업 종료 시 사용자 Chrome은 닫지 않음
    - 댓글 입력은 실제 클립보드 복사 + Cmd/Ctrl+V (trusted paste), 폴백: 키보드 타이핑 → JS 주입
  - 검증 도구: `verifier.py` — 작성한 비밀댓글이 살아있는지(삭제 여부) 사후 확인

## 네이버 댓글창(cbox) 셀렉터 디버깅

현재 동작하는 모바일(m.blog.naver.com) 댓글 구조 (2026-05 기준, 검증 완료):
- 처음엔 입력창이 없음 → **"댓글" 버튼(`button[class*="comment_btn"]`) 클릭**해야 댓글 영역 생성
- 입력창은 textarea가 아니라 **contenteditable DIV** (`#naverComment__write_textarea`, class `u_cbox_text`)
  - 일반 클릭이 '보임/안정'에서 막히면 `scroll_into_view` + `force=True` 클릭, 안 되면 JS `focus()` 폴백
- 비밀 체크박스(`input.u_cbox_secret_check`)는 커스텀 스타일이라 Playwright 클릭이 막힘 → **JS로 라벨/체크박스 click + checked 검증** (`_ensure_secret_on`)
- 등록: `button.u_cbox_btn_upload`

작성이 실패할 때:
1. UI에서 "브라우저 창 보기" 켜고 실행해 실제 댓글창 확인
2. `OPEN_COMMENT_SELECTORS` / `COMMENT_TEXT_SELECTORS` / `SUBMIT_SELECTORS` 리스트 상단에 새 셀렉터 추가
3. 기존 셀렉터는 호환성 위해 유지 (네이버 SERP 셀렉터 규칙과 동일)
4. 비밀 체크가 확인 안 되면(`_ensure_secret_on`이 False) **공개 등록을 막기 위해 작성하지 않고 건너뜀** — 의도된 안전장치
