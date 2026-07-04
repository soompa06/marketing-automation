#!/usr/bin/env bash
# Aoostar WTR Pro 초기 셋업 — Ubuntu 24.04 LTS 기준
# 한 번만 실행: sudo bash setup.sh
#
# 결과:
#   - Docker + Docker Compose v2
#   - Tailscale (가입은 별도 — 아래 안내 따라가야 함)
#   - UFW 방화벽: 외부 차단 / Tailscale·Cloudflare Tunnel만 허용
#   - 데이터 디렉토리 (/srv/{immich,nextcloud}) 권한 설정
#
# 실행 후:
#   1) sudo tailscale up           # 발급된 링크 열어서 본인 계정 연결
#   2) cd /opt/marketing/deploy/aoostar && cp .env.example .env && vi .env
#   3) docker compose up -d --build
#   4) 아래 README의 'Tailscale Serve로 노출' 단계 진행

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "❌ sudo로 실행해주세요: sudo bash setup.sh"
    exit 1
fi

echo "==[1/6] 시스템 업데이트=="
apt-get update -qq
apt-get upgrade -y -qq

echo "==[2/6] 기본 도구 + 한글/시간대=="
apt-get install -y -qq \
    curl wget git vim ca-certificates apt-transport-https gnupg lsb-release \
    htop iotop tzdata ufw fail2ban
timedatectl set-timezone Asia/Seoul
locale-gen ko_KR.UTF-8 || true

echo "==[3/6] Docker 설치=="
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# 일반 유저(첫 번째 계정)도 docker 그룹에 추가
PRIMARY_USER=$(getent passwd 1000 | cut -d: -f1 || echo "")
if [[ -n "$PRIMARY_USER" ]]; then
    usermod -aG docker "$PRIMARY_USER" || true
fi

echo "==[4/6] Tailscale 설치=="
if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

echo "==[5/6] UFW 방화벽 (deny incoming / SSH는 Tailscale만)=="
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
# SSH는 Tailscale CGNAT 대역에서만 허용 (외부 접속 차단)
ufw allow in on tailscale0 to any port 22 proto tcp
# Cloudflare Tunnel은 outbound 전용이라 ufw 룰 불필요
ufw --force enable
ufw status verbose

echo "==[6/6] 데이터 디렉토리 생성=="
mkdir -p /srv/immich/upload /srv/immich/postgres
mkdir -p /srv/nextcloud/data /srv/nextcloud/db
# Immich는 일반 uid 1000, Nextcloud는 www-data(33)이 권장
chown -R 1000:1000 /srv/immich
chown -R 33:33     /srv/nextcloud/data
chown -R 999:999   /srv/nextcloud/db    # mariadb uid

echo ""
echo "✅ 셋업 완료. 다음 단계:"
echo ""
echo "  1) Tailscale 가입:    sudo tailscale up"
echo "     → 터미널에 뜨는 https 링크를 PC 브라우저에서 열고 본인 계정으로 로그인"
echo "     → 아이폰/맥북에도 Tailscale 앱 설치 + 같은 계정 로그인"
echo ""
echo "  2) Cloudflare Tunnel 토큰 발급 후 .env에 채우기:"
echo "     cd /opt/marketing/deploy/aoostar"
echo "     cp .env.example .env"
echo "     vi .env"
echo ""
echo "  3) 스택 실행:"
echo "     docker compose up -d --build"
echo ""
echo "  4) Immich/Nextcloud를 Tailscale로 노출 (README의 4️⃣ 참고):"
echo "     sudo tailscale serve --bg --https=443 http://localhost:2283"
echo "     sudo tailscale serve --bg --https=444 http://localhost:8082"
echo ""
echo "  5) 재로그인해서 docker 그룹 권한 적용 (sudo 없이 docker 사용 가능)"
