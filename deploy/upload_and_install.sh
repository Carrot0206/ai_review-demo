#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARENT_DIR="$(cd "${APP_DIR}/.." && pwd)"
APP_NAME="$(basename "${APP_DIR}")"
ARCHIVE="${PARENT_DIR}/${APP_NAME}-deploy.tar.gz"
TARGET="${1:-root@192.168.21.103}"
REMOTE_ARCHIVE="/tmp/${APP_NAME}-deploy.tar.gz"

"${SCRIPT_DIR}/package_release.sh"

echo "上传部署包到 ${TARGET}:${REMOTE_ARCHIVE}"
scp "${ARCHIVE}" "${TARGET}:${REMOTE_ARCHIVE}"

echo "在服务器安装/更新服务..."
ssh "${TARGET}" "set -euo pipefail
mkdir -p /opt
if [ -d /opt/${APP_NAME} ]; then
  tar -czf /opt/${APP_NAME}.backup-\$(date +%Y%m%d-%H%M%S).tar.gz -C /opt ${APP_NAME}
fi
tar -xzf ${REMOTE_ARCHIVE} -C /opt
cd /opt/${APP_NAME}
bash deploy/install_server.sh
"

echo "完成。请访问：http://192.168.21.103:28101"
