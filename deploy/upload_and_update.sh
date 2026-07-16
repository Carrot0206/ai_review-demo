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

echo "上传更新包到 ${TARGET}:${REMOTE_ARCHIVE}"
scp "${ARCHIVE}" "${TARGET}:${REMOTE_ARCHIVE}"

echo "在服务器更新应用..."
ssh "${TARGET}" "set -euo pipefail
APP_DIR=/opt/${APP_NAME}
SERVICE_NAME=trust-ai-review-demo
BACKUP=/opt/${APP_NAME}.backup-\$(date +%Y%m%d-%H%M%S).tar.gz
STATE_DIR=\$(mktemp -d /tmp/${APP_NAME}-state.XXXXXX)

cleanup() {
  rm -rf \"\${STATE_DIR}\"
}
trap cleanup EXIT

if [ ! -d \"\${APP_DIR}\" ]; then
  echo \"未找到 \${APP_DIR}。请先执行首次部署脚本 deploy/upload_and_install.sh。\"
  exit 1
fi

tar -czf \"\${BACKUP}\" -C /opt ${APP_NAME}

# These files are changed through the web/API and must not be replaced by a code update.
for path in backend/data/rule_sets backend/data/rule_library/rules.json backend/data/user_rules.json; do
  if [ -e \"\${APP_DIR}/\${path}\" ]; then
    mkdir -p \"\${STATE_DIR}/\$(dirname \"\${path}\")\"
    cp -a \"\${APP_DIR}/\${path}\" \"\${STATE_DIR}/\${path}\"
  fi
done

tar -xzf ${REMOTE_ARCHIVE} -C /opt

for path in backend/data/rule_sets backend/data/rule_library/rules.json backend/data/user_rules.json; do
  if [ -e \"\${STATE_DIR}/\${path}\" ]; then
    rm -rf \"\${APP_DIR}/\${path}\"
    mkdir -p \"\$(dirname \"\${APP_DIR}/\${path}\")\"
    cp -a \"\${STATE_DIR}/\${path}\" \"\${APP_DIR}/\${path}\"
  fi
done

\"\${APP_DIR}/backend/.venv/bin/pip\" install -r \"\${APP_DIR}/backend/requirements.txt\"
systemctl restart \"\${SERVICE_NAME}\"
curl --fail --silent http://127.0.0.1:18101/api/health
curl --fail --silent http://127.0.0.1:28101/api/health
echo
echo \"更新完成。备份文件：\${BACKUP}\"
"

echo "完成。请在浏览器中强制刷新：http://192.168.21.103:28101"
