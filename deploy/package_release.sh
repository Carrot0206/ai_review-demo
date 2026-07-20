#!/usr/bin/env bash
set -euo pipefail
export COPYFILE_DISABLE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARENT_DIR="$(cd "${APP_DIR}/.." && pwd)"
APP_NAME="$(basename "${APP_DIR}")"
ARCHIVE="${PARENT_DIR}/${APP_NAME}-deploy.tar.gz"

cd "${APP_DIR}"

if [[ -f "backend/.env" ]]; then
  echo "注意：backend/.env 不会被打包，服务器密钥保存在 /etc/trust-rule-engine/backend.env。"
fi

if [[ ! -d "frontend/node_modules" ]]; then
  echo "frontend/node_modules 不存在，正在执行 npm ci..."
  (cd frontend && npm ci)
fi

echo "检查并构建前端..."
(cd frontend && npm run lint && npm run build)

echo "生成部署包：${ARCHIVE}"
tar \
  --no-xattrs \
  --exclude=".git" \
  --exclude=".DS_Store" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude="backend/.env" \
  --exclude="backend/.venv" \
  --exclude="backend/data/materials" \
  --exclude="backend/data/*.db" \
  --exclude="backend/data/*.db-*" \
  --exclude="frontend/node_modules" \
  -czf "${ARCHIVE}" \
  -C "${PARENT_DIR}" \
  "${APP_NAME}"

echo "完成：${ARCHIVE}"
