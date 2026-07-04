# 🔑 구글 시트 Service Account 설정 가이드

이 가이드를 따라하시면 코드가 사용자 개입 없이 자동으로 구글 시트에 접근할 수 있게 됩니다.
**처음 한 번만** 진행하시면 돼요. 약 10분 정도 걸립니다.

---

## 1단계: 구글 클라우드 프로젝트 만들기

### 1-1. Google Cloud Console 접속
[https://console.cloud.google.com/](https://console.cloud.google.com/) 접속  
→ 본인 구글 계정(`your-email@gmail.com`)으로 로그인

### 1-2. 새 프로젝트 만들기
- 상단 좌측 **프로젝트 선택** 클릭 (현재 프로젝트 이름이 보이는 곳)
- 우측 상단 **새 프로젝트** 클릭
- **프로젝트 이름**: `marketing-automation` (자유롭게)
- **만들기** 클릭
- 잠시 기다린 후, 만든 프로젝트로 자동 전환 (또는 수동으로 선택)

---

## 2단계: 필요한 API 활성화

### 2-1. Google Sheets API 활성화
- 좌측 햄버거 메뉴 → **API 및 서비스** → **라이브러리**
- 검색창에 **`Google Sheets API`** 입력
- 결과에서 **Google Sheets API** 클릭
- **사용** 버튼 클릭 (활성화)

### 2-2. Google Drive API 활성화 (필요)
- 다시 라이브러리로 이동
- 검색창에 **`Google Drive API`** 입력
- **Google Drive API** 클릭 → **사용** 클릭

---

## 3단계: Service Account 만들기

### 3-1. 서비스 계정 생성 페이지로 이동
- 좌측 메뉴 → **API 및 서비스** → **사용자 인증 정보**
- 상단 **+ 사용자 인증 정보 만들기** 클릭
- **서비스 계정** 선택

### 3-2. 서비스 계정 정보 입력
- **서비스 계정 이름**: `sheets-bot` (자유롭게)
- **서비스 계정 ID**: 자동 생성됨
- **만들기 및 계속** 클릭
- **역할(Role)**: 선택 안 해도 됨 (기본 권한으로 충분) → **계속** 클릭
- **완료** 클릭

### 3-3. 서비스 계정 이메일 메모해두기 ⚠️ **중요**
방금 만든 서비스 계정의 **이메일 주소**를 복사해주세요. 이런 형식이에요:
```
sheets-bot@marketing-automation-xxxxx.iam.gserviceaccount.com
```

이 이메일을 **나중에 시트 공유 권한 줄 때** 사용합니다.

---

## 4단계: 키 파일(JSON) 다운로드

### 4-1. 키 만들기
- 만든 서비스 계정 이름 클릭
- 상단 **키** 탭 클릭
- **키 추가** → **새 키 만들기**
- **키 유형**: **JSON** 선택
- **만들기** 클릭

→ JSON 파일이 자동으로 다운로드됩니다 (예: `marketing-automation-xxxxx.json`)

### 4-2. 파일을 프로젝트에 넣기
다운받은 JSON 파일을 **이름을 바꿔서** 프로젝트 폴더에 넣어주세요:

```bash
# 다운로드 폴더에서 프로젝트로 이동 (파일명은 본인 다운로드한 것에 맞게)
mv ~/Downloads/marketing-automation-*.json \
   ~/marketing_automation/config/google_credentials.json
```

또는 Finder로 끌어다 넣으셔도 됩니다.

**⚠️ 이 파일은 절대 공유하면 안 됩니다.**
- `.gitignore`에 등록되어 있어 GitHub에 안 올라감
- 본인 PC에만 두세요

---

## 5단계: 시트에 서비스 계정 권한 부여

이게 **가장 중요한 단계**입니다. 안 하면 권한 에러 납니다.

### 식당 시트와 피부과 시트 둘 다 진행

각 시트에서:
1. 우측 상단 **공유** 버튼 클릭
2. 3단계에서 메모한 **서비스 계정 이메일** 입력
   ```
   sheets-bot@marketing-automation-xxxxx.iam.gserviceaccount.com
   ```
3. 권한: **편집자** 선택
4. **알림 보내기** 체크 해제 (서비스 계정에 이메일 보낼 필요 없음)
5. **공유** 클릭

이 과정을 **두 시트 모두**에 적용해주세요:
- 식당 시트: https://docs.google.com/spreadsheets/d/여기에_구글시트_ID
- 피부과 시트: https://docs.google.com/spreadsheets/d/여기에_구글시트_ID

---

## 6단계: 미달자 시트 만들기

자격 미달 블로거를 자동으로 옮길 별도 시트가 필요합니다.

각 캠페인 시트에서:
1. 하단 시트 탭 **+** 클릭
2. 새 탭 이름: **`미달자`**
3. 1행에 헤더 추가 (원본과 동일하게):
   - 식당 미달자 시트: `[ 가게A ]_5팀 | 연락처 | 블로그주소 | 지수 | 카카오톡 ID | ...`
   - 피부과 미달자 시트: `[ 성형외과 ]_5팀 | 연락처 | 블로그주소 | 지수 | ...`

또는 **첫 행을 그냥 비워두면 코드가 알아서 채워줍니다.** 

---

## 7단계: 설정 파일 만들기 ⚠️ 중요

**두 개의 다른 파일**이 필요합니다. 헷갈리지 마세요:

| 파일명 | 내용 | 누가 만드나 |
|---|---|---|
| `config/google_credentials.json` | Google에서 다운받은 키 (private_key 들어있음) | **4단계에서 다운로드한 그 파일** |
| `config/settings.json` | 시트 ID, 컬럼 정보 등 | **사용자가 직접 작성** |

### 7-1. 키 파일 위치 확인

4단계에서 다운로드한 JSON 파일이 다음 경로에 있는지 확인:
```bash
ls config/google_credentials.json
```
없으면 다운받은 위치에서 복사:
```bash
cp ~/Downloads/marketing-automation-*.json config/google_credentials.json
```

### 7-2. settings.json 새로 작성

```bash
# 터미널에서 (또는 텍스트 에디터로 직접):
cd marketing_automation/config
cp settings.example.json settings.json
```

그리고 `config/settings.json`을 열어서 본인 시트에 맞게 수정:

```json
{
  "google_sheets": {
    "credentials_path": "config/google_credentials.json",
    "campaigns": {
      "restaurant": {
        "spreadsheet_id": "여기에_구글시트_ID",
        "main_sheet_name": "4월",
        "rejected_sheet_name": "미달자",
        "blog_url_column": "C",
        "grade_column": "D"
      },
      "skin": {
        "spreadsheet_id": "여기에_구글시트_ID",
        "main_sheet_name": "5월",
        "rejected_sheet_name": "미달자",
        "blog_url_column": "C",
        "grade_column": "D"
      }
    }
  },
  "blogdex": {
    "qualified_grades": [
      "준최6", "준최7",
      "최적1", "최적2", "최적3",
      "최적1+", "최적2+", "최적3+", "최적4+"
    ],
    "batch_size": 3,
    "wait_seconds_between_batches": 60
  }
}
```

### 7-3. 두 파일 모두 있는지 최종 확인

```bash
ls config/
# 출력에 google_credentials.json 과 settings.json 둘 다 있어야 함
```

**`main_sheet_name`은 본인 시트의 실제 탭 이름**으로 바꿔야 합니다 (예: "4월", "5월", "응답 시트1" 등).

---

## 8단계: 패키지 설치

```bash
cd marketing_automation
source venv/bin/activate
pip install gspread google-auth
```

(이미 `requirements.txt`에 있어서 처음 설치 때 같이 됐을 수도 있어요)

---

## ✅ 완료!

이제 다음 명령어로 동작 테스트:

```bash
python src/blogdex/sheet_pipeline.py --campaign restaurant --dry-run
```

`--dry-run`은 **실제로 시트를 수정하지 않고**, 어떤 작업이 일어날지 미리 보여주는 모드입니다.

문제 없으면 `--dry-run` 빼고 실행하세요.

---

## 🆘 트러블슈팅

### "credentials.json을 찾을 수 없습니다"
→ `config/google_credentials.json` 파일이 정확한 위치에 있는지 확인

### "PERMISSION_DENIED: The caller does not have permission"
→ 5단계에서 시트에 서비스 계정 이메일을 **편집자 권한**으로 공유했는지 확인
→ 두 시트 **모두** 권한을 줘야 함

### "시트 이름을 찾을 수 없습니다"
→ `settings.json`의 `main_sheet_name`이 실제 시트 탭 이름과 일치하는지 확인
→ 구글 시트에서 하단 탭 이름을 확인 (보통 "시트1" 또는 "응답 시트1")

### "API has not been enabled"
→ 2단계에서 **Sheets API**와 **Drive API** 둘 다 활성화했는지 확인
