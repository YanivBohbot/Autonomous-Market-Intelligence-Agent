#!/usr/bin/env bash
# Fresh Ubuntu 22.04/24.04 server -> running demo stack. Safe to rerun.
#   curl -fsSL https://raw.githubusercontent.com/YanivBohbot/Autonomous-Market-Intelligence-Agent/master/market-intelligence-agent/deploy/demo/setup.sh | sudo bash
# Optional: BRANCH=feat/demo-deployment (default: master).
set -euo pipefail

REPO_URL="https://github.com/YanivBohbot/Autonomous-Market-Intelligence-Agent.git"
BRANCH="${BRANCH:-master}"
INSTALL_DIR="/opt/market-desk"
DEMO_DIR="$INSTALL_DIR/market-intelligence-agent/deploy/demo"

# 1. Swap: Chromium + MCP servers + Python are comfortable with headroom.
if ! swapon --show | grep -q .; then
  echo "==> Creating a 2 GB swap file"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 2. Docker Engine + compose plugin (official repository).
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  apt-get update
  apt-get install -y ca-certificates curl git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
command -v git >/dev/null 2>&1 || apt-get install -y git

# 3. Code.
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> Updating $INSTALL_DIR ($BRANCH)"
  git -C "$INSTALL_DIR" fetch origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
  echo "==> Cloning into $INSTALL_DIR ($BRANCH)"
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# 4. Data: seed the CRM database once; later imports must not be overwritten.
cd "$DEMO_DIR"
mkdir -p data
[ -f data/customers.db ] || cp ../../customers.db data/customers.db

# 5. Settings: the operator fills .env by hand (keys, DOMAIN, password hash).
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo
  echo "==> Created $DEMO_DIR/.env"
  echo "    Fill it (DOMAIN, DEMO_PASSWORD_HASH, API keys, VOICE_ALLOWED_ORIGINS), then rerun this script."
  exit 0
fi

# 6. Start.
echo "==> Building and starting (first build takes several minutes)"
docker compose up -d --build
DOMAIN_VALUE="$(grep -E '^DOMAIN=' .env | cut -d= -f2-)"
echo
echo "==> Up: https://${DOMAIN_VALUE}"
