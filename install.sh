#!/usr/bin/env bash
# financial-report-claw 一键安装（Ubuntu 20.04+ / Debian）
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/fr-agent}"
SERVICE_USER="${SERVICE_USER:-ubuntu}"
PORT="${PORT:-80}"

echo "==> 安装系统依赖"
sudo -n apt-get update -y
sudo -n apt-get install -y python3 python3-venv python3-pip

echo "==> 创建应用目录"
sudo mkdir -p "$APP_DIR" "$APP_DIR/data"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "==> 复制代码"
rsync -a --exclude venv --exclude data --exclude __pycache__ ./ "$APP_DIR/"

echo "==> 创建虚拟环境并安装依赖"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -U pip
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

echo "==> 安装 systemd 单元"
sudo cp deploy/fr-agent.service /etc/systemd/system/fr-agent.service
sudo cp deploy/fr-agent-scan.service /etc/systemd/system/fr-agent-scan.service
sudo cp deploy/fr-agent-scan.timer /etc/systemd/system/fr-agent-scan.timer
sudo systemctl daemon-reload
sudo systemctl enable fr-agent.service fr-agent-scan.timer
sudo systemctl start fr-agent.service
sudo systemctl start fr-agent-scan.timer

echo "==> 完成。验证："
echo "    curl http://localhost:$PORT/api/health"
echo "    curl http://localhost:$PORT/api/tracks"
