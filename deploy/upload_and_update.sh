#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARENT_DIR="$(cd "${APP_DIR}/.." && pwd)"
APP_NAME="$(basename "${APP_DIR}")"
ARCHIVE="${PARENT_DIR}/${APP_NAME}-deploy.tar.gz"
TARGET="${1:-root@192.168.21.103}"
MODE="${2:-}"
REMOTE_ARCHIVE="/tmp/${APP_NAME}-deploy.tar.gz"
SYNC_RULES=0

if [[ -n "${MODE}" && "${MODE}" != "--sync-rules" ]]; then
  echo "用法：$0 [user@host] [--sync-rules]"
  exit 1
fi
if [[ "${MODE}" == "--sync-rules" ]]; then
  SYNC_RULES=1
fi

"${SCRIPT_DIR}/package_release.sh"

echo "上传部署包到 ${TARGET}:${REMOTE_ARCHIVE}"
scp "${ARCHIVE}" "${TARGET}:${REMOTE_ARCHIVE}"

echo "在服务器安装/更新信托登记审查管理中台..."
ssh "${TARGET}" "SYNC_RULES=${SYNC_RULES} bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

APP_NAME="trust-rule-engine"
APP_DIR="/opt/${APP_NAME}"
REMOTE_ARCHIVE="/tmp/${APP_NAME}-deploy.tar.gz"

if [[ "${EUID}" -ne 0 ]]; then
  echo "远程部署需要root权限，请使用 root@服务器地址。"
  exit 1
fi

mkdir -p /opt
if [[ -d "${APP_DIR}" ]]; then
  BACKUP="/opt/${APP_NAME}.backup-$(date +%Y%m%d-%H%M%S).tar.gz"
  tar \
    --exclude="${APP_NAME}/backend/.venv" \
    --exclude="${APP_NAME}/frontend/node_modules" \
    -czf "${BACKUP}" \
    -C /opt \
    "${APP_NAME}"
  echo "已备份现有程序：${BACKUP}"
fi

tar -xzf "${REMOTE_ARCHIVE}" -C /opt
cd "${APP_DIR}"
SYNC_RULES="${SYNC_RULES}" bash deploy/install_server.sh
rm -f "${REMOTE_ARCHIVE}"

curl --fail --silent --show-error http://127.0.0.1:28101/api/rule-engine/health
echo
REMOTE_SCRIPT

echo "部署完成，请强制刷新浏览器："
echo "  http://192.168.21.103:28101/rule-library/"
echo "  http://192.168.21.103:28101/rule-library/review"
if [[ "${SYNC_RULES}" == "0" ]]; then
  echo "服务器现有规则库已保留；如需用本地规则覆盖，请再次执行并追加 --sync-rules。"
fi
