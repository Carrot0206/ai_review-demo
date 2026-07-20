#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}

trap cleanup INT TERM EXIT

cd "$ROOT"
python3 -m uvicorn backend.app:app --host 127.0.0.1 --port 8001 --log-level info &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  if curl -s -o /dev/null http://127.0.0.1:8001/api/rule-engine/health; then
    break
  fi
  sleep 0.5
done

cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 &
FRONTEND_PID=$!

echo "规则库前端：http://127.0.0.1:5174/rule-library/"
echo "规则库后端：http://127.0.0.1:8001/docs"
wait
