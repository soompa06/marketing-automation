# 체험단 마케팅 자동화 시스템

식당·피부과 체험단 모집/관리 업무를 자동화하는 **Streamlit 웹앱**입니다.
네이버 상위노출 확인, 월간보고서 생성, 블덱스 지수 조회, 모집 댓글까지 한 곳에서 처리합니다.

## ✨ 주요 기능

| # | 기능 | 설명 |
|---|------|------|
| 1 | **네이버 상위노출 확인** | 블로그 글이 통합검색·블로그탭 몇 위인지 확인 + 스크린샷 자동 저장 |
| 2 | **월간보고서 자동 생성** | 검수 결과를 모아 워드(.docx) 보고서로 (표지·순위표·스크린샷 포함) |
| 3 | **블덱스 지수 조회** | 블로그 지수 자동 조회 후 구글 시트 등급 분류 |
| 4 | **네이버 모집 댓글** | 키워드 상위 글에 모집글을 비밀댓글로 (실제 Chrome 연결 방식) |
| + | 카톡 리마인더 · 자동 스케줄러 · 백업/복원 · Google 연동 | 부가 기능 |

## 🚀 빠른 시작 (로컬)

```bash
# 1) 가상환경 + 패키지 설치
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium         # 최초 1회

# 2) 설정 파일 준비
cp config/settings.example.json config/settings.json   # 열어서 값 입력

# 3) 웹앱 실행
streamlit run streamlit_app/홈.py
```

> 💡 비개발자는 루트의 **`install.command`**(Mac) / **`install.bat`**(Windows)를 더블클릭해
> 설치하고, **`run.sh`** / **`run.bat`** 더블클릭으로 실행할 수 있습니다.

## ☁️ 무료 공개 배포

다른 사람도 쓸 수 있게 **무료 클라우드(Streamlit Community Cloud)** 로 띄우는 방법은
👉 **[docs/DEPLOY_STREAMLIT.md](docs/DEPLOY_STREAMLIT.md)** 참고.

## 📁 폴더 구조

```
marketing_automation/
├── README.md                 # 이 파일
├── CLAUDE.md                 # 개발/작업 규칙
├── LICENSE                   # MIT
├── requirements.txt          # Python 패키지
├── packages.txt              # 클라우드 배포용 시스템 패키지
├── install.* / run.*         # 설치·실행 스크립트 (더블클릭)
├── config/                   # 설정·세션 (민감정보, .gitignore)
├── docs/                     # 📚 모든 사용 가이드 (아래 참고)
├── src/                      # 핵심 로직
│   ├── naver_check/          #  ① 네이버 상위노출 확인
│   ├── monthly_report/       #  ② 월간보고서
│   ├── blogdex/              #  ③ 블덱스 지수
│   ├── naver_comment/        #  ④ 모집 댓글
│   ├── reminder/ scheduler/  #  카톡 리마인더 · 스케줄러
│   ├── backup/ google_oauth/ #  백업 · 구글 연동
│   └── licensing/            #  설치형 판매용 라이선스
├── streamlit_app/            # 웹 UI (홈.py + pages/)
├── deploy/                   # NAS(Docker)·설치빌드 배포 패키지
├── screenshots/              # 결과 스크린샷 (.gitignore)
└── output/                   # 결과 CSV·보고서 (.gitignore)
```

## 📚 가이드 (`docs/`)

| 문서 | 내용 |
|------|------|
| [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) | 처음 설치/환경 설정 |
| [SHEET_SETUP_GUIDE.md](docs/SHEET_SETUP_GUIDE.md) | 구글 시트 연동 (블덱스용) |
| [BLOGDEX_GUIDE.md](docs/BLOGDEX_GUIDE.md) | 블덱스 지수 조회 사용법 |
| [MONTHLY_REPORT_GUIDE.md](docs/MONTHLY_REPORT_GUIDE.md) | 월간보고서 작성법 |
| [SCHEDULER_GUIDE.md](docs/SCHEDULER_GUIDE.md) | 자동 스케줄러 |
| [DEPLOY_STREAMLIT.md](docs/DEPLOY_STREAMLIT.md) | **무료 클라우드 배포 + 다른 사용자 접속** |

## 📄 라이선스

[MIT](LICENSE) — 자유롭게 사용·수정·배포 가능.
