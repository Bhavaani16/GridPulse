#!/usr/bin/env bash
# GridPulse Vultr provisioning — idempotent, safe to re-run.
# Target: fresh Ubuntu 22.04/24.04 instance, run as root.
# Installs Docker Engine + Compose plugin, locks the firewall down to
# SSH/80/443, and creates the app directory. It does NOT deploy — see
# DEPLOY.md for the rsync and compose steps.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/gridpulse}"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo bash deploy/provision.sh)" >&2
    exit 1
fi

echo "==> apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl rsync ufw

echo "==> docker engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends docker.io
    systemctl enable --now docker
fi
if ! docker compose version >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends docker-compose-v2
fi

echo "==> firewall: incoming SSH, 80, 443 only"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable
ufw status verbose

mkdir -p "${APP_DIR}"
echo "provision: done."
echo "next: rsync the repo into ${APP_DIR}, create ${APP_DIR}/deploy/.env"
echo "from deploy/.env.example, then run:"
echo "  cd ${APP_DIR}/deploy && docker compose up -d --build"
