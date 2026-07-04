# Aoostar WTR Pro 통합 배포 가이드

> **목적**: 한 대의 Aoostar N100에서 ①공개용 마케팅 자동화 도구 ②개인 파일(사진/문서)
> 두 영역을 **네트워크 단에서 완전 분리**해서 운영합니다.

## 최종 구조

```
인터넷
  │
  ├─ Cloudflare Tunnel ──→ automation.도메인.com → marketing(8501)
  │                        (외부 사용자 누구나 — 로그인 필요)
  │
  └─ Tailscale VPN ──────→ photos.사용자.ts.net  → immich(2283)
                          files.사용자.ts.net  → nextcloud(8082)
                          (내 아이폰/맥북만)
```

- 인터넷에서 직접 들어오는 포트: **없음** (포트포워딩 불필요)
- 외부 사용자는 Cloudflare 통해 마케팅 도구만 도달, 개인 파일 서버는 **DNS/IP가 보이지 않음**

---

## 0️⃣ 하드웨어 구성 (Aoostar WTR Pro 도착 시)

권장:
- **WTR Pro N100** 본체 (16GB RAM 모델)
- **NVMe SSD 512GB** — OS + 컨테이너 이미지·메타데이터
- **HDD 4TB × 2** (RAID 1, 미러링) — 사진/영상/문서 + 마케팅 결과물 백업

장착:
1. NVMe 슬롯 1번에 OS용 SSD
2. SATA 베이 1·2번에 HDD 2개
3. 베이 3·4번은 추후 확장 (RAID 5/10 갈 때)

---

## 1️⃣ Ubuntu Server 24.04 LTS 설치

1. 다른 PC에서 [Ubuntu Server 24.04 LTS](https://ubuntu.com/download/server) ISO 받기
2. Rufus/balenaEtcher로 USB 부팅 디스크 만들기
3. Aoostar에 USB 꽂고 부팅 → "Install Ubuntu Server"
4. 설치 옵션:
   - 호스트명: `aoostar` (자유)
   - 사용자: 본인 (예: `soom`) — uid는 1000 자동
   - **Install OpenSSH server 체크**
   - 저장소: NVMe SSD 통째 (HDD는 무시)
   - 다른 옵션은 기본값 유지
5. 설치 완료 후 재부팅. 모니터 떼고 SSH로 접속:
   ```bash
   ssh youruser@aoostar.local         # 같은 공유기일 때
   ```

---

## 2️⃣ 초기 셋업 스크립트 실행

이 프로젝트를 NAS에 복사 (PC에서):
```bash
# 맥에서
scp -r /path/to/marketing_automation youruser@aoostar.local:/tmp/
# 또는 git clone (private repo 미러를 하나 만들고)
ssh youruser@aoostar.local
sudo mv /tmp/marketing_automation /opt/marketing
cd /opt/marketing
sudo bash deploy/aoostar/setup.sh
```

이 스크립트가 자동으로 처리:
- Docker + Compose 설치
- Tailscale 설치
- UFW 방화벽 (외부 차단 / SSH는 Tailscale만)
- 데이터 디렉토리 `/srv/{immich,nextcloud}` 권한 설정

> ⚠️ `setup.sh`가 끝나면 **재로그인** 해야 `sudo` 없이 `docker` 명령이 됩니다.

---

## 3️⃣ Tailscale 가입 (개인 파일 VPN)

NAS에서:
```bash
sudo tailscale up
```
화면에 URL이 뜸 → 다른 PC 브라우저에서 열어 **Google/Microsoft 계정으로 무료 가입**
→ 같은 계정으로 **아이폰·맥북에도 Tailscale 앱 설치 후 로그인** → 끝.

확인:
```bash
tailscale status
# 모든 기기가 100.x.x.x IP로 보임
```

---

## 4️⃣ Cloudflare Tunnel 셋업 (마케팅 도구 외부 공개)

### 4-1. Cloudflare에 도메인 추가
1. [Cloudflare](https://dash.cloudflare.com) 가입 (무료)
2. 도메인이 없으면 가비아/AWS Route53/네임칩에서 도메인 구입(연 1~2만원)
3. Cloudflare → "Add a site" → 본인 도메인 → Free 플랜 → 네임서버 변경 안내대로

### 4-2. Tunnel 생성
1. Cloudflare 대시보드 → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**
2. Cloudflared 선택 → 이름: `aoostar` → Save tunnel
3. Docker 탭의 토큰(`eyJh...` 긴 문자열) **복사**
4. NAS에서:
   ```bash
   cd /opt/marketing/deploy/aoostar
   cp .env.example .env
   vi .env       # CLOUDFLARE_TUNNEL_TOKEN 에 붙여넣기
   ```
5. 같은 화면 "Public Hostnames" 탭:
   - Subdomain: `automation`
   - Domain: 내 도메인
   - Service: `HTTP` `marketing:8501`
   - Save

### 4-3. (필수) Cloudflare Access로 로그인 강제
1. Zero Trust → **Access** → **Applications** → **Add an application** → Self-hosted
2. Application name: `marketing` / domain: `automation.내도메인.com`
3. Identity providers: One-time PIN(이메일) 또는 Google OAuth 추가
4. Policies → **Allow** 정책 만들기:
   - Include: Emails → 본인·팀원 이메일들 추가
   - 또는 "Emails ending in" → `@회사.com`
5. Save

→ 이제 `automation.내도메인.com` 접속하면 Cloudflare 이메일 인증을 거쳐야 마케팅 앱에 들어옴.

---

## 5️⃣ 스택 실행

```bash
cd /opt/marketing/deploy/aoostar
# .env가 채워져 있어야 함
docker compose up -d --build
docker compose ps        # 모두 healthy 확인
docker compose logs -f marketing   # 첫 부팅 로그 확인
```

5~10분 안에:
- 마케팅 자동화: `https://automation.내도메인.com` (Cloudflare 인증 후)
- Immich/Nextcloud는 다음 단계에서 노출

---

## 6️⃣ Immich · Nextcloud를 Tailscale로 노출 (외부 차단 유지)

NAS에서:
```bash
# Immich를 443번 https로 (tailnet 안에서만)
sudo tailscale serve --bg --https=443 http://localhost:2283
# Nextcloud를 444번으로
sudo tailscale serve --bg --https=444 http://localhost:8082
tailscale serve status
```

결과 URL (예):
- `https://aoostar.사용자.ts.net`           → Immich
- `https://aoostar.사용자.ts.net:444`       → Nextcloud

이 URL은 **Tailscale 가입자(나)만 접근 가능**. 인터넷에 노출 안 됨.

---

## 7️⃣ 아이폰 자동 백업 설정

### 사진/영상 (Immich)
1. App Store에서 **"Immich"** 앱 설치
2. 서버: `https://aoostar.사용자.ts.net` (Tailscale 켜져 있어야 함)
3. 이메일/비번 가입 → 로그인
4. 설정 → **Backup** → "Foreground/Background Backup" 둘 다 ON
5. 백업할 앨범 선택 (전체 라이브러리 OK)
6. 즉시 업로드 시작. Wi-Fi에서만 백업 옵션 권장.

### 문서 (Nextcloud)
1. App Store에서 **"Nextcloud"** 앱 설치
2. 서버: `https://aoostar.사용자.ts.net:444`
3. 가입 → 로그인 (admin 계정으로 들어가 별도 사용자 추가 권장)
4. 설정 → **Auto upload** → 카메라 롤 또는 특정 폴더 동기화

---

## 8️⃣ 맥북 동기화

### Tailscale
[Tailscale 맥 앱](https://tailscale.com/download/mac) 설치 → 같은 계정 로그인.

### 사진/영상
**Immich** 데스크톱 앱 (Electron) — Releases 페이지에서 dmg 다운로드 → 서버 입력.
또는 macOS 사진 라이브러리 → CLI `immich-cli` 로 일괄 업로드.

### 문서
**Nextcloud 데스크톱 클라이언트**:
1. https://nextcloud.com/install/#install-clients → macOS .pkg
2. 서버: `https://aoostar.사용자.ts.net:444`
3. 동기화할 로컬 폴더 선택 (예: `~/Documents/NAS`)
4. Dropbox처럼 양방향 동기화

### Time Machine (옵션)
NAS에 SMB 공유 폴더를 만들고 Time Machine 백업 대상으로 지정 가능.
필요시 별도 가이드.

---

## 9️⃣ 마케팅 자동화 다중 사용자 운영

현재 이 앱은 `streamlit_app/auth.py`에 비밀번호 인증 훅이 있고,
`auth.json`이 있을 때만 활성화됩니다.

**옵션 A — Cloudflare Access만 사용 (권장)**
- 위 4-3에서 설정한 이메일 화이트리스트로 충분.
- 코드 안의 추가 인증은 끔.

**옵션 B — 앱 내부 비번도 추가**
- `config/auth.json` 만들기:
   ```json
   { "users": { "soom": "비번해시", "팀원1": "비번해시" } }
   ```
- 컨테이너 재시작.

신규 외부 사용자 추가: Cloudflare Zero Trust → Access → Policies에서 이메일 추가만 하면 끝.

---

## 🔟 운영 명령

```bash
# 상태
docker compose ps
docker compose logs -f marketing
docker stats              # CPU/RAM 사용량

# 재시작
docker compose restart marketing
docker compose down && docker compose up -d --build

# 업데이트
git pull
docker compose build marketing
docker compose up -d marketing

# 백업 (HDD가 mount된 /srv 통째)
sudo rsync -aHAX /srv/ /mnt/backup-hdd/srv-$(date +%F)/
```

---

## ⚠️ 보안 체크리스트

- [ ] UFW 활성 + `ufw status` 가 `Status: active`
- [ ] SSH는 Tailscale 대역(`100.x.x.x`)에서만 접속됨 (외부 22번 차단)
- [ ] Immich/Nextcloud 컨테이너 포트가 `127.0.0.1:`로만 바인딩 (`docker compose ps`에서 확인)
- [ ] 모든 `.env` 비밀번호 기본값(`change_me_*`) 다 바꿈
- [ ] Cloudflare Access 정책 적용됨 (`automation.도메인` 접속 시 이메일 화면 뜸)
- [ ] Tailscale ACL — 본인·가족 외 invite 안 됨
- [ ] 정기 백업 cron 설정

---

## 트러블슈팅

**Q. `tailscale serve`가 "permission denied" 뜸**
→ `sudo`로 실행하거나 `sudo usermod -aG tailscale $USER` 후 재로그인.

**Q. 마케팅 컨테이너에서 Playwright가 메모리 부족**
→ N100 16GB 기준 검수 concurrency를 3 이하로. `config/settings.json`의 batch 설정 보수적으로.

**Q. Immich에 사진이 업로드되는데 미리보기 안 뜸**
→ ML(머신러닝) 컨테이너는 빠져 있어요. 필요하면 `immich-machine-learning` 서비스 compose에 추가.

**Q. Nextcloud `Trusted domain` 에러**
→ `.env`의 `NEXTCLOUD_TRUSTED_DOMAINS`에 Tailscale 도메인 추가.

**Q. Cloudflare Tunnel이 자꾸 끊김**
→ `docker compose logs cloudflared` 확인. 토큰 만료/변경 가능성.

---

## 비용 요약 (참고)

| 항목 | 가격(추정) |
|---|---|
| Aoostar WTR Pro N100 16GB | 45~60만원 |
| NVMe SSD 512GB | 5~8만원 |
| HDD 4TB × 2 (WD Red Plus) | 24~28만원 |
| Cloudflare Free | 0원 |
| Tailscale Free (개인 100대) | 0원 |
| 도메인 | 연 1~2만원 |
| **합계 (초기)** | **75~98만원** |

시놀로지 DS423+(120만원~) + Photos + Drive + 자동화 PC(별도) 대비 **30~40% 절감**, 그리고 Immich가 시놀로지 Photos보다 사진 검색·얼굴인식이 더 우수합니다.
