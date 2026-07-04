# 🏠 NAS 배포 가이드 (시놀로지 / QNAP / 일반 Linux Docker)

본인 PC를 24시간 켜두지 않아도 자동 검수·블덱스 분류가 매일 돌아가게 만드는 방법입니다.
시놀로지 NAS / QNAP NAS / 일반 Linux 서버 모두에 적용됩니다.

---

## 1. 시놀로지 NAS (Container Manager)

### 1.1 사전 준비

- DSM 7.2 이상 + Container Manager 패키지 설치
- 사용자 PC에서 한 번 모든 로그인 완료(블덱스, OAuth)
  → `config/` 폴더에 세션·토큰이 저장돼야 함

### 1.2 NAS로 파일 복사

`File Station`을 열고 다음과 같이 업로드:

```
/volume1/docker/marketing_automation/
  ├─ config/                  (PC에서 그대로 복사 — 인증·세션·설정 포함)
  ├─ src/
  ├─ streamlit_app/
  ├─ deploy/
  ├─ requirements.txt
  └─ ...
```

`output/`, `screenshots/`, `venv/`는 복사하지 않아도 됩니다 (NAS에서 자동 생성).

### 1.3 Container Manager에서 빌드 + 실행

1. **Container Manager** → 좌측 **프로젝트** → **생성**
2. 프로젝트 이름: `marketing-automation`
3. 경로: `/volume1/docker/marketing_automation` 선택
4. 소스: **docker-compose.yml 사용** → `deploy/docker-compose.yml` 선택
5. **다음** → **다음** → **완료**
6. 빌드가 끝나면 자동으로 컨테이너 시작 (5~10분 소요)

### 1.4 접속

- NAS 내부: `http://<NAS_IP>:8501`
- 외부 접속(권장): DSM의 **제어판 → 로그인 포털 → 역방향 프록시**에서
  - 소스: `marketing.<your-domain>` (DDNS) HTTPS 443
  - 대상: `localhost:8501` HTTP

→ 무료 ngrok이 필요 없고 매번 주소도 안 바뀝니다.

### 1.5 자동 시작 확인

`docker-compose.yml`의 `restart: unless-stopped` 덕분에 NAS 재부팅 후에도 자동 시작됩니다.

---

## 2. QNAP NAS (Container Station)

거의 시놀로지와 동일하지만 메뉴 이름이 다름:

1. Container Station → **응용 프로그램** → **생성**
2. **YAML 사용** 선택 → `docker-compose.yml` 내용 붙여넣기
3. 빌드/실행

QNAP 역방향 프록시는 **myQNAPcloud**에서 설정.

---

## 3. 일반 Linux 서버 (VPS, 라즈베리파이 등)

```bash
# 1) 코드 동기화
rsync -av --exclude=venv --exclude=output --exclude=screenshots \
    ~/Downloads/marketing_automation/ \
    user@server:/srv/marketing_automation/

# 2) 빌드 + 실행
cd /srv/marketing_automation/deploy
docker compose up -d --build

# 3) 로그 확인
docker compose logs -f
```

---

## 4. 첫 실행 후 체크리스트

NAS 환경에서는 GUI 브라우저가 없어서 **블덱스 로그인은 NAS에서 직접 못 합니다.**
PC에서 미리 로그인하고 세션 파일만 NAS로 옮기는 흐름이 표준:

| 항목 | 어디서? | 어떻게? |
|---|---|---|
| 블덱스 세션 (`config/blogdex_sessions/*.json`) | PC | `python src/blogdex/session.py --user xxx` 실행 후 NAS로 복사 |
| Google OAuth 토큰 (`config/oauth_tokens/*.json`) | PC | 설정 페이지에서 OAuth 로그인 후 NAS로 복사 |
| 서비스 계정 키 (`config/google_credentials.json`) | 어디서든 | Google Cloud Console에서 발급 |
| 설정 (`config/settings.json`) | 어디서든 | 설정 페이지에서 편집 |

**더 쉬운 방법**: PC에서 [⚙️ 설정 → 💾 백업 / 복원]으로 zip을 만든 뒤,
NAS의 같은 페이지에서 업로드 → 복원.

---

## 5. 컨테이너 안에서 블덱스를 돌릴 수 있나?

**기본적으로는 어렵습니다.** 블덱스는 Cloudflare 봇 차단을 쓰는데,
NAS의 헤드리스 환경에선 거의 항상 차단됩니다.

전략:
- **블덱스 조회 = 본인 PC에서 (수동 또는 스케줄)**
- **결과 분류·시트 쓰기·검수·보고서 = NAS에서 자동**

스케줄 작업에서 블덱스 파이프라인을 NAS에서 자동 실행하지 마시고,
PC가 켜져 있을 때만 트리거되도록 두는 것이 안전합니다.

---

## 6. 업데이트 (코드 새 버전 배포)

```bash
# NAS의 SSH로 접속하거나 Container Manager에서 'Recreate' 버튼
cd /volume1/docker/marketing_automation/deploy
docker compose pull        # (이미지 직접 빌드라면 생략)
docker compose up -d --build
```

`config/`, `output/` 등 사용자 데이터는 volume mount이므로 보존됩니다.

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 컨테이너 재시작 무한 반복 | `docker compose logs marketing-automation`로 로그 확인. `requirements.txt` 의존성 빌드 실패가 가장 흔함 |
| 시간이 한국 시간이 아님 | `TZ=Asia/Seoul` 환경변수 확인. NAS의 시스템 시간도 같이 맞추세요 |
| 자동 스케줄이 안 도는 듯 | 컨테이너 안 `/app/output/.scheduler/*.log` 확인. `[⚙️ 설정 → ⏰ 자동 스케줄]` 페이지에서 데몬 상태도 확인 |
| 외부에서 접속 안 됨 | NAS 방화벽에서 8501 포트 또는 역방향 프록시 도메인 허용 확인 |
| 비밀번호 인증이 풀려있음 | `config/auth.json`이 NAS로 복사됐는지 확인 |
