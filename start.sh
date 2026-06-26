#!/usr/bin/env bash
# 一键拉起 后端(8000) + 前端(5173)
# 用法：./start.sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  echo ""
  echo "[stop] 关闭后端 PID=$BE_PID 前端 PID=$FE_PID"
  kill $BE_PID $FE_PID 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "[backend] 启动 uvicorn :8000 ..."
cd "$ROOT"
source backend/.venv/bin/activate
uvicorn backend.app:app --reload --port 8000 --log-level info &
BE_PID=$!

# 等待 backend 可用
for i in $(seq 1 30); do
  if curl -s -o /dev/null http://127.0.0.1:8000/api/health; then
    echo "[backend] OK (pid=$BE_PID)"
    break
  fi
  sleep 0.5
done

echo "[frontend] 启动 vite :5173 ..."
cd "$ROOT/frontend"
npm run dev &
FE_PID=$!

echo ""
echo "============================================="
echo " 🚀 Backend  : http://127.0.0.1:8000  (pid=$BE_PID)"
echo " 🎨 Frontend : http://127.0.0.1:5173  (pid=$FE_PID)"
echo " 按 Ctrl+C 同时关闭"
echo "============================================="
wait
