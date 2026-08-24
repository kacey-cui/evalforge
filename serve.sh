#!/bin/bash
cd "$(dirname "$0")"

# 清理已有进程
echo "清理旧进程..."
kill $(lsof -ti:9090) 2>/dev/null || true
kill $(lsof -ti:9091) 2>/dev/null || true
sleep 1

# 启动 git_bridge（端口 9091）
echo "启动 git_bridge on http://localhost:9091"
python3 scripts/git_bridge.py &
GIT_BRIDGE_PID=$!

# 等待 git_bridge 就绪
sleep 1

# 启动静态文件服务（端口 9090）
echo "启动静态服务 on http://localhost:9090"
python3 -m http.server 9090 &
STATIC_PID=$!

echo ""
echo "✅ EvalForge 已启动"
echo "   UI:         http://localhost:9090"
echo "   Git Bridge: http://localhost:9091"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待 Ctrl+C，然后清理
trap "echo '停止服务...'; kill $GIT_BRIDGE_PID $STATIC_PID 2>/dev/null" INT TERM
wait