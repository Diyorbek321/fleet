#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 22.04/24.04 DigitalOcean Droplet.
# Installs Docker Engine + Compose plugin and a basic firewall, then leaves you
# ready to clone the repo and run docker-compose.prod.yml.
#
#   ssh root@<droplet-ip>
#   curl -fsSL https://raw.githubusercontent.com/<you>/fleet-watch-pro/main/scripts/droplet-setup.sh | bash
# (or copy this file over and: bash droplet-setup.sh)
set -euo pipefail

echo "==> Updating apt and installing Docker…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git ufw

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Configuring firewall (SSH + HTTP + HTTPS only)…"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Enabling Docker on boot…"
systemctl enable --now docker

echo ""
echo "Docker installed: $(docker --version)"
echo "Compose installed: $(docker compose version)"
echo ""
echo "Next:"
echo "  git clone https://github.com/<you>/fleet-watch-pro.git && cd fleet-watch-pro"
echo "  cp .env.prod.example .env.prod    # fill in domains, passwords, JWT secret"
echo "  docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build"
