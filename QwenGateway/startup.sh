#!/bin/bash
# startup.sh — Start all QwenGateway services
set -e

echo "=== QwenGateway Startup ==="

# Start Nginx in background
echo "[1/3] Starting Nginx..."
nginx -g "daemon off;" &
NGINX_PID=$!

# Start Python backend
echo "[2/3] Starting Python backend (port 7860)..."
cd /app
uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 7860 \
    --workers 4 \
    --log-level info &
PYTHON_PID=$!

# Wait for Python to be ready
echo "Waiting for Python backend..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:7860/health > /dev/null 2>&1; then
        echo "Python backend ready."
        break
    fi
    sleep 1
done

# Start Go gateway
echo "[3/3] Starting Go gateway (port 8080)..."
GATEWAY_ADDR=":8080" \
REDIS_ADDR="${REDIS_ADDR:-redis:6379}" \
REDIS_PASSWORD="${REDIS_PASSWORD:-}" \
PYTHON_INTERNAL="http://localhost:7860/internal" \
GATEWAY_API_KEY="${GATEWAY_API_KEY:-}" \
gateway &
GATEWAY_PID=$!

echo ""
echo "=== All services started ==="
echo "  Nginx:   PID $NGINX_PID  (port 80)"
echo "  Python:  PID $PYTHON_PID (port 7860)"
echo "  Gateway: PID $GATEWAY_PID (port 8080)"
echo ""

# Wait for any service to exit (failure = restart needed)
wait -n $NGINX_PID $PYTHON_PID $GATEWAY_PID
echo "A service exited — container will restart."
exit 1
