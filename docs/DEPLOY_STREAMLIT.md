# 무료 클라우드 배포 가이드 (Streamlit Community Cloud)

이 문서는 **무료로 1개 인스턴스를 띄워 여러 명이 같은 주소(`https://<앱이름>.streamlit.app`)로
접속해 쓰는** 방법입니다. 비용은 0원이고, GitHub 공개 저장소에서 자동 배포됩니다.

> ⚠️ **먼저 알아둘 것 (공유 방식의 한계)**
> - 모든 접속자가 **같은 네이버 세션·결과 파일·설정**을 공유합니다. 로그인/계정 분리가 안 됩니다.
> - **네이버 댓글모집(CDP/실제 크롬)** 기능은 클라우드에 데스크톱 크롬이 없어 **작동하지 않습니다.**
>   (이 기능은 본인 PC에서만 쓰세요.)
> - 검수·블덱스는 Playwright Chromium을 쓰는데 무료 클라우드는 메모리(약 1GB)가 작아
>   동시 처리 수를 **1~2**로 낮춰야 안정적입니다. 대량 처리는 느리거나 실패할 수 있습니다.
> - 공개 주소이므로 **아무나 접속**합니다. 외부에 공개하기 싫으면 7번(비밀번호)·8번(비공개)을 보세요.

---

## 1. GitHub에 코드 올리기

```bash
cd /path/to/marketing_automation

# (최초 1회) git 저장소 초기화
git init
git add .
git status   # ← config/settings.json, *_session.json 등이 목록에 없어야 정상! (.gitignore가 막음)

git commit -m "체험단 마케팅 자동화 공개 버전"
```

GitHub에서 **새 공개 저장소**(예: `marketing-automation`)를 만든 뒤:

```bash
git branch -M main
git remote add origin https://github.com/<당신아이디>/marketing-automation.git
git push -u origin main
```

> 🔒 **비밀정보 확인 (중요):** `git status`에 아래 파일들이 **절대 보이면 안 됩니다.**
> `config/settings.json`, `config/*_session.json`, `.streamlit/secrets.toml`,
> `config/license.key`, `~/.soom_marketing_keys/`.
> 이미 `.gitignore`가 막고 있지만, push 전에 꼭 눈으로 확인하세요.

## 2. Streamlit Community Cloud 연결

1. <https://share.streamlit.io> 접속 → GitHub 계정으로 로그인
2. **"Create app" → "Deploy a public app from GitHub"**
3. 입력:
   - Repository: `<당신아이디>/marketing-automation`
   - Branch: `main`
   - **Main file path: `streamlit_app/홈.py`**
4. **Deploy** 클릭

## 3. Secrets(설정) 넣기

클라우드에는 `config/settings.json`이 없으므로(커밋 안 됨) 설정을 Secrets로 넣습니다.

App 화면 우측 하단 **⋮ → Settings → Secrets** 에 아래를 붙여넣고 저장:

```toml
settings_json = '''
{
  "campaigns": {
    "restaurant": { "default_keywords": ["둔산동 회식", "대전 가성비 맛집"] },
    "skin":       { "default_keywords": ["강남 리투오", "신논현역 성형외과"] }
  },
  "blogdex": {
    "query_delay_seconds": 2,
    "rate_limit_wait_seconds": 60,
    "max_rate_limit_retries": 5
  }
}
'''
```

> 예시 템플릿은 `.streamlit/secrets.toml.example` 에 있습니다.
> 본인 `config/settings.json` 내용을 그대로 `settings_json = '''...'''` 안에 넣으면 됩니다.
> (단, 블덱스 로그인 비밀번호 등 민감 항목은 공개 인스턴스에 넣지 않는 걸 권장합니다.)

## 4. 첫 실행 시 브라우저 설치

검수/블덱스를 처음 실행하면 앱이 자동으로 Playwright Chromium을 1회 설치합니다
(`utils._bootstrap_cloud_browsers`). 처음만 약 30초~1분 걸리고, 이후에는 빠릅니다.

## 5. 동시 처리 수 조정 (권장)

무료 메모리가 작으니 **검수 페이지의 '동시 처리 수'를 1~2로** 낮추세요.

## 6. 업데이트 방법

코드를 고친 뒤 `git push` 하면 Streamlit Cloud가 **자동으로 재배포**합니다.

## 7. (선택) 비밀번호로 접근 제한

링크를 아는 사람이라도 **비밀번호를 아는 사람만** 들어오게 하려면,
3번 Secrets에 아래 한 줄을 추가하세요 (앱의 `auth.py`가 자동으로 로그인 화면을 띄움):

```toml
app_password = "원하는비밀번호"
```

> 클라우드는 재배포 시 파일이 초기화되므로 **반드시 Secrets**에 넣어야 비밀번호가 유지됩니다.
> (앱 안 ⚙️설정 → 보안 탭의 비밀번호 폼은 로컬 PC 전용입니다.)
> 비밀번호를 없애려면 Secrets에서 `app_password` 줄을 지우면 됩니다.

## 8. (선택) 검색엔진 노출 막기 / 비공개

- Streamlit Community Cloud 무료 플랜은 **공개 앱만** 지원합니다(비공개는 유료).
- 완전 비공개가 필요하면 본인 NAS(이미 준비된 `deploy/aoostar/`) 또는
  유료 호스팅을 쓰세요.

---

## 문제 해결(FAQ)

| 증상 | 원인/해결 |
|---|---|
| 검수가 계속 실패 | 메모리 부족 — 동시 처리 수 1로, 한 번에 적은 인원만 |
| "설정이 비었다" | 3번 Secrets의 `settings_json`을 다시 확인 |
| 댓글모집이 안 됨 | 정상 — 클라우드엔 데스크톱 크롬이 없음. 본인 PC에서 사용 |
| 첫 검수가 오래 걸림 | 브라우저 1회 설치 중. 잠시 후 다시 시도 |
| 한글 깨짐 | `packages.txt`의 `fonts-nanum`이 적용됐는지 재배포 확인 |
