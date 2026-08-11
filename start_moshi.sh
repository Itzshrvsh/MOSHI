#!/usr/bin/env bash

echo ""
echo "============================================================"
echo "                   MOSHI AI SYSTEM STARTUP                  "
echo "============================================================"
echo ""

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -f "$ROOT/mem0/.venv/bin/python" ]; then
    PYTHON="$ROOT/mem0/.venv/bin/python"
elif [ -f "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "[1/5] Running MOSHI Health Doctor..."
$PYTHON "$ROOT/moshi_doctor.py"

echo ""
echo "[2/5] Checking LM Studio..."
if curl -s http://127.0.0.1:1234/v1/models >/dev/null 2>&1; then
    echo "       LM Studio API OK"
else
    echo "       [WARNING] LM Studio not responding at http://127.0.0.1:1234/v1"
fi

echo ""
echo "[3/5] Starting Qdrant Vector DB..."
if command -v docker >/dev/null 2>&1; then
    docker start mem0-qdrant >/dev/null 2>&1 || docker run -d --name mem0-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant >/dev/null 2>&1
    echo "       Qdrant OK (http://127.0.0.1:6333)"
else
    echo "       [NOTICE] Docker not found; skipping Qdrant container check."
fi

echo ""
echo "[4/5] Checking Memory Server (Port 8765)..."
if curl -s http://127.0.0.1:8765/health >/dev/null 2>&1; then
    echo "       Memory Server already running"
else
    echo "       Starting Memory Server..."
    nohup $PYTHON "$ROOT/memory_server.py" > "$ROOT/.moshi/logs/memory_server.log" 2>&1 &
    sleep 2
    echo "       Memory Server started"
fi

echo ""
echo "[5/5] Checking OpenCode Server (Port 4096)..."
if curl -s http://127.0.0.1:4096/session >/dev/null 2>&1; then
    echo "       OpenCode Server already running"
else
    if command -v opencode >/dev/null 2>&1; then
        echo "       Starting OpenCode Server..."
        nohup opencode serve --hostname 127.0.0.1 --port 4096 > "$ROOT/.moshi/logs/opencode.log" 2>&1 &
        sleep 2
        echo "       OpenCode Server started"
    else
        echo "       [NOTICE] opencode CLI not found in PATH"
    fi
fi

echo ""
echo "Checking Telegram Agent Bot..."
if pgrep -f "bot_agent_final.py" >/dev/null 2>&1; then
    echo "       Telegram Agent Bot already running"
else
    if [ -f "$ROOT/telegram/.env" ]; then
        echo "       Starting Telegram Bot..."
        cd "$ROOT/telegram"
        nohup $PYTHON "$ROOT/telegram/bot_agent_final.py" > "$ROOT/.moshi/logs/telegram.log" 2>&1 &
        sleep 2
        echo "       Telegram Agent Bot started"
    else
        echo "       [NOTICE] telegram/.env not configured yet"
    fi
fi

echo ""
echo "============================================================"
echo "                   MOSHI SYSTEM ONLINE                      "
echo "============================================================"
echo ""
echo "LM Studio : http://127.0.0.1:1234/v1"
echo "Qdrant    : http://127.0.0.1:6333"
echo "Memory    : http://127.0.0.1:8765"
echo "OpenCode  : http://127.0.0.1:4096"
echo "Telegram  : Active"
ACTIVE_MODEL=$($PYTHON -c "import moshi_config; print(moshi_config.get_model())" 2>/dev/null || echo "gemma-4-12b-coder-fable5-composer2.5-v1")
echo "Model     : $ACTIVE_MODEL"
echo "============================================================"
echo ""
