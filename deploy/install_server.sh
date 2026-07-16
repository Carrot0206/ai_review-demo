#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/trust-ai-review-demo"
APP_USER="trustreview"
APP_GROUP="trustreview"
SERVICE_NAME="trust-ai-review-demo"
ENV_DIR="/etc/trust-ai-review-demo"
ENV_FILE="${ENV_DIR}/backend.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 执行：bash deploy/install_server.sh"
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "未找到 ${APP_DIR}，请先把项目解压到该目录。"
  exit 1
fi

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip nginx
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip nginx
  else
    echo "未识别包管理器，请手动安装 python3、python3-venv/python3-pip、nginx 后重试。"
    exit 1
  fi
}

if ! command -v python3 >/dev/null 2>&1 || ! command -v nginx >/dev/null 2>&1; then
  install_packages
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}/backend/uploads" "${APP_DIR}/backend/out" "${APP_DIR}/backend/data"
chown -R root:root "${APP_DIR}"
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}/backend/uploads" "${APP_DIR}/backend/out" "${APP_DIR}/backend/data"

install -d -m 700 "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 600 "${APP_DIR}/backend/.env.example" "${ENV_FILE}"
  echo "已创建 ${ENV_FILE}，请部署后填入 DEEPSEEK_API_KEY。"
else
  chmod 600 "${ENV_FILE}"
fi

python3 -m venv "${APP_DIR}/backend/.venv"
"${APP_DIR}/backend/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/backend/.venv/bin/pip" install -r "${APP_DIR}/backend/requirements.txt"

install -m 644 "${APP_DIR}/deploy/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

if [[ -d /etc/nginx/conf.d ]]; then
  install -m 644 "${APP_DIR}/deploy/nginx.trust-ai-review-demo.conf" "/etc/nginx/conf.d/${SERVICE_NAME}.conf"
elif [[ -d /etc/nginx/sites-available ]]; then
  install -m 644 "${APP_DIR}/deploy/nginx.trust-ai-review-demo.conf" "/etc/nginx/sites-available/${SERVICE_NAME}.conf"
  ln -sfn "/etc/nginx/sites-available/${SERVICE_NAME}.conf" "/etc/nginx/sites-enabled/${SERVICE_NAME}.conf"
else
  echo "未找到 Nginx 配置目录，请手动配置 deploy/nginx.trust-ai-review-demo.conf。"
  exit 1
fi

nginx -t
systemctl enable nginx
systemctl restart nginx

echo "部署完成。后端健康检查：curl http://127.0.0.1:18101/api/health"
echo "如果未填写 Key，请编辑：${ENV_FILE}，然后执行：systemctl restart ${SERVICE_NAME}"
