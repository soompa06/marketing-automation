# 🚀 시작 가이드 (1순위 기능부터)

이 문서는 **네이버 상위노출 자동 확인 + 스크린샷** 기능을
가장 빠르게 동작시키는 방법을 안내합니다.

---

## 📋 사전 준비

### Python 설치 확인
터미널(macOS) 또는 PowerShell(Windows)에서:
```bash
python3 --version
```
3.10 이상이면 OK. 없으면 [python.org](https://www.python.org)에서 설치.

---

## 1단계: 프로젝트 폴더 받기

### 옵션 A: GitHub 새 레포 생성 (권장)
```bash
# 원하는 위치에서
mkdir marketing_automation
cd marketing_automation

# Claude가 만들어준 모든 파일을 이 폴더에 복사

# Git 초기화
git init
git add .
git commit -m "초기 프로젝트 구조"

# GitHub에 새 레포 만들고 연결 (예: marketing_automation)
git remote add origin https://github.com/soompa06/marketing_automation.git
git branch -M main
git push -u origin main
```

### 옵션 B: 로컬 폴더만 사용
다운로드한 파일들을 적당한 위치(예: `~/projects/marketing_automation`)에 두면 끝.

---

## 2단계: 환경 세팅

### 가상환경 생성 + 패키지 설치
```bash
cd marketing_automation

# 가상환경 만들기
python3 -m venv venv

# 활성화
source venv/bin/activate          # macOS/Linux
# venv\Scripts\activate           # Windows PowerShell

# 패키지 설치
pip install -r requirements.txt

# Playwright 브라우저 설치 (1회만, 약 200MB)
playwright install chromium
```

### 설정 파일 만들기
```bash
cp config/settings.example.json config/settings.json
```
지금은 settings.json을 굳이 수정하지 않아도 1순위 기능은 동작합니다.
(블덱스 로그인 정보는 3순위 작업할 때 입력)

### .gitignore 추가 (GitHub 쓰는 경우)
```bash
cat > .gitignore << 'EOF'
venv/
__pycache__/
*.pyc
config/settings.json
config/google_credentials.json
screenshots/
output/
.DS_Store
EOF
```

---

## 3단계: 첫 실행 — 단건 테스트

블로거 한 명의 포스팅을 테스트해봅니다.

```bash
python src/naver_check/checker.py \
  --url "https://blog.naver.com/실제블로거ID/실제포스트번호" \
  --keywords "둔산동 회식,대전 가성비 맛집" \
  --campaign restaurant \
  --blogger-name "홍길동"
```

**실행되면:**
1. 크롬 창이 열리고 자동으로 네이버 검색을 진행합니다
2. 키워드별로 통합검색 → 블로그탭 순서로 확인합니다
3. 노출된 부분에 빨간 네모를 그린 스크린샷을 저장합니다
4. 마지막에 구글 시트에 붙여넣을 형식의 요약을 출력합니다

**저장 경로:**
```
screenshots/
└── restaurant/
    └── 20260430/
        └── 홍길동/
            ├── 통합검색_둔산동_회식.png
            ├── 블로그탭_둔산동_회식_3위.png
            └── 통합검색_대전_가성비_맛집.png
```

**출력 예시:**
```
📊 결과 요약 (구글 시트 붙여넣기용)
============================================================
상위노출: 둔산동 회식, 대전 가성비 맛집 / 블로그탭 : 둔산동 회식 3위, 대전 가성비 맛집 5위
============================================================
```

---

## 4단계: 여러 명 일괄 처리

### CSV 파일 준비
`src/naver_check/batch_input.example.csv`를 복사해서 `batch_input.csv`로 만들고 실제 데이터 입력:

```csv
blogger_name,url,campaign,keywords
홍길동,https://blog.naver.com/aaa/123,restaurant,"둔산동 회식,대전 가성비 맛집"
김영희,https://blog.naver.com/bbb/456,restaurant,"둔산동 회식,대전 가성비 맛집"
박철수,https://blog.naver.com/ccc/789,skin,"강남 리투오,신논현역 성형외과"
```

### 일괄 실행
```bash
python src/naver_check/batch_check.py --input src/naver_check/batch_input.csv
```

전부 처리 후 `output/check_results_20260430_153022.csv` 같은 결과 파일이 생성됩니다.

---

## 5단계: Claude Code로 더 편하게 쓰기

이미 Claude Code에 익숙하시니, 자주 쓰는 명령을 자동화할 수 있습니다.

### 자주 쓰는 패턴
Claude Code 채팅창에 이렇게 말하면:

> "오늘 받은 블로그 URL 3개 검수해줘. 식당 캠페인이고 키워드는 평소대로야.
> URL은 [붙여넣기]"

Claude Code가 자동으로:
1. URL 파싱
2. 캠페인별 기본 키워드 적용 (settings.json에서 읽음)
3. checker.py 실행
4. 결과를 정리해서 응답

이게 가능하도록 다음 단계에서 `CLAUDE.md` 파일을 만들어드리겠습니다 (Claude Code 전용 작업 지시서).

---

## ⚠️ 주의사항

### 네이버 SERP는 자주 바뀝니다
네이버 검색 결과 페이지의 HTML 구조가 종종 바뀌기 때문에, 어느 날 갑자기 "노출 안 됨"으로
잘못 나올 수 있습니다. 그럴 때는:

1. `--headless` 옵션 빼고 실행해서 브라우저 창을 직접 보기
2. 실제로는 노출되어 있는데 스크립트가 못 찾는다면 → checker.py의 `blog_selectors` 또는
   `item_selectors`를 업데이트 (Claude에게 "셀렉터 업데이트해줘" 요청 OK)

### 너무 빠르게 연속 실행하면 차단될 수 있음
일괄 처리 시에도 키워드 사이에 1.5초 대기를 넣어뒀지만, 한 번에 너무 많이(50건+) 돌리면
일시적으로 차단될 수 있습니다. 30건씩 나눠서 실행하는 것을 권장합니다.

---

## 🆘 문제 해결

### "playwright: command not found"
```bash
# 가상환경 활성화 했는지 확인
source venv/bin/activate
```

### "Browser was not installed"
```bash
playwright install chromium
```

### 한글 폴더 이름이 깨져요
macOS는 정상, Windows에서 깨지면 PowerShell을 UTF-8로 설정:
```powershell
chcp 65001
```

### "노출 안 됨"으로 나오는데 실제로는 됨
1. 브라우저 캐시 문제일 수 있음 → 직접 시크릿 모드에서 같은 키워드로 검색해서 비교
2. 셀렉터 변경 → Claude에게 업데이트 요청

---

## 📌 다음 단계 미리보기

1순위 동작 확인되면 다음 순서로 추가 기능을 만들어드립니다:

- **2순위**: 한 달간 모은 스크린샷들로 자동 월간보고서 생성 (워드 파일)
- **3순위**: 블덱스 자동 로그인 → 지수 확인 → 구글 시트 자동 분류
- **4순위**: 매일 정해진 시간에 카톡 모집문구 알림 + 클립보드 자동 복사
