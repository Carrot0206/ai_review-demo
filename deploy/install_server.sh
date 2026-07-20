#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/trust-rule-engine"
DATA_DIR="/opt/trust-rule-engine-data"
APP_USER="trustreview"
APP_GROUP="trustreview"
SERVICE_NAME="trust-rule-engine"
ENV_DIR="/etc/trust-rule-engine"
ENV_FILE="${ENV_DIR}/backend.env"
SYNC_RULES="${SYNC_RULES:-0}"

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
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx curl
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip nginx curl
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip nginx curl
  else
    echo "未识别包管理器，请手动安装 python3、venv、pip、nginx、curl 后重试。"
    exit 1
  fi
}

if ! command -v python3 >/dev/null 2>&1 || ! command -v nginx >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  install_packages
fi

if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${APP_GROUP}"
fi
if ! id "${APP_USER}" >/dev/null 2>&1; then
  NOLOGIN_SHELL="$(command -v nologin || true)"
  useradd --system --gid "${APP_GROUP}" --home-dir "${APP_DIR}" --shell "${NOLOGIN_SHELL:-/usr/sbin/nologin}" "${APP_USER}"
fi

install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 750 "${DATA_DIR}" "${DATA_DIR}/materials"
chown -R "${APP_USER}:${APP_GROUP}" "${DATA_DIR}"

RULE_FILE="${DATA_DIR}/rules.json"
SEED_RULE_FILE="${APP_DIR}/backend/data/rule_library/rules.json"
if [[ ! -f "${RULE_FILE}" || "${SYNC_RULES}" == "1" ]]; then
  if [[ -f "${RULE_FILE}" ]]; then
    cp -a "${RULE_FILE}" "${DATA_DIR}/rules.json.backup-$(date +%Y%m%d-%H%M%S)"
  fi
  install -o "${APP_USER}" -g "${APP_GROUP}" -m 640 "${SEED_RULE_FILE}" "${RULE_FILE}"
  echo "已使用部署包中的规则库初始化/覆盖 ${RULE_FILE}。"
else
  echo "保留服务器现有规则库：${RULE_FILE}。"
fi

install -d -o root -g "${APP_GROUP}" -m 750 "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${APP_DIR}/backend/.env" ]]; then
    install -o root -g "${APP_GROUP}" -m 640 "${APP_DIR}/backend/.env" "${ENV_FILE}"
    echo "已把原 backend/.env 迁移到 ${ENV_FILE}。"
  else
    install -o root -g "${APP_GROUP}" -m 640 "${APP_DIR}/backend/.env.example" "${ENV_FILE}"
    echo "已创建 ${ENV_FILE}，部署后请填写 DEEPSEEK_API_KEY。"
  fi
else
  chown root:"${APP_GROUP}" "${ENV_FILE}"
  chmod 640 "${ENV_FILE}"
fi

echo "创建独立虚拟环境，Python来源：$(command -v python3)"
python3 -m venv --clear --copies "${APP_DIR}/backend/.venv"
"${APP_DIR}/backend/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/backend/.venv/bin/pip" install -r "${APP_DIR}/backend/requirements.txt"
chmod 755 "${APP_DIR}" "${APP_DIR}/backend" "${APP_DIR}/backend/.venv" "${APP_DIR}/backend/.venv/bin"
chmod 755 "${APP_DIR}/backend/.venv/bin/python"
if command -v restorecon >/dev/null 2>&1; then
  restorecon -RF "${APP_DIR}" "${DATA_DIR}" >/dev/null 2>&1 || true
fi

install -m 644 "${APP_DIR}/deploy/${SERVICE_NAME}.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

disable_old_nginx_site() {
  local path="$1"
  if [[ -e "${path}" || -L "${path}" ]]; then
    install -d -m 700 /etc/nginx/trust-platform-backups
    cp -aL "${path}" "/etc/nginx/trust-platform-backups/$(basename "${path}").$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
    rm -f "${path}"
  fi
}

disable_old_nginx_site "/etc/nginx/conf.d/trust-ai-review-demo.conf"
disable_old_nginx_site "/etc/nginx/sites-enabled/trust-ai-review-demo.conf"
disable_old_nginx_site "/etc/nginx/sites-enabled/trust-ai-review-demo"

if [[ -d /etc/nginx/conf.d ]]; then
  install -m 644 "${APP_DIR}/deploy/nginx.trust-platform.conf" "/etc/nginx/conf.d/trust-platform.conf"
elif [[ -d /etc/nginx/sites-available ]]; then
  install -m 644 "${APP_DIR}/deploy/nginx.trust-platform.conf" "/etc/nginx/sites-available/trust-platform.conf"
  ln -sfn "/etc/nginx/sites-available/trust-platform.conf" "/etc/nginx/sites-enabled/trust-platform.conf"
else
  echo "未找到Nginx配置目录，请手动配置 deploy/nginx.trust-platform.conf。"
  exit 1
fi

nginx -t
systemctl enable nginx
systemctl reload nginx

HEALTHY=0
for _ in $(seq 1 40); do
  if curl --fail --silent http://127.0.0.1:18102/api/rule-engine/health >/dev/null; then
    HEALTHY=1
    break
  fi
  sleep 0.5
done
if [[ "${HEALTHY}" != "1" ]]; then
  echo "规则引擎启动失败，输出服务状态和最近日志："
  systemctl status "${SERVICE_NAME}" --no-pager -l || true
  journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
  exit 1
fi
curl --fail --silent --show-error http://127.0.0.1:18102/api/rule-engine/health
echo

check_html_page() {
  local path="$1"
  local headers
  headers="$(curl --fail --silent --show-error --head "http://127.0.0.1:28101${path}" | tr -d '\r')"
  if ! grep -Eqi '^Content-Type:[[:space:]]*text/html' <<<"${headers}"; then
    echo "页面 ${path} 未返回HTML："
    echo "${headers}"
    exit 1
  fi
}

check_html_page "/rule-library/"
check_html_page "/rule-library/review"
echo "规则库和登记审核页面均已返回HTML。"

if grep -Eq '^DEEPSEEK_API_KEY=.+$' "${ENV_FILE}"; then
  echo "DeepSeek API Key 已配置。"
else
  echo "提醒：请编辑 ${ENV_FILE} 填写 DEEPSEEK_API_KEY，然后执行 systemctl restart ${SERVICE_NAME}。"
fi

echo "部署完成："
echo "  规则库：http://192.168.21.103:28101/rule-library/"
echo "  登记审核：http://192.168.21.103:28101/rule-library/review"
