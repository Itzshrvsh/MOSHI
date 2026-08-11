@echo off
setlocal EnableExtensions

title MOSHI AI SYSTEM

echo.
echo ============================================================
echo                    MOSHI AI SYSTEM STARTUP
echo ============================================================
echo.

set "ROOT=C:\projects\MOSHI"
set "VENV=%ROOT%\mem0\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

if not exist "%ROOT%" (
    echo [ERROR] MOSHI project directory not found: %ROOT%
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [ERROR] Python virtual environment not found: %PYTHON%
    pause
    exit /b 1
)

echo [1/5] Running MOSHI Health Doctor...
"%PYTHON%" "%ROOT%\moshi_doctor.py"

echo [2/5] Checking LM Studio...
powershell -Command "$r = Invoke-RestMethod -Uri http://127.0.0.1:1234/v1/models -ErrorAction SilentlyContinue; if ($r) { write-host '       LM Studio API OK' } else { write-host '       [WARNING] LM Studio not responding at http://127.0.0.1:1234/v1' }"

echo.
echo [2/5] Starting Qdrant Vector DB...
docker start mem0-qdrant >nul 2>&1
if errorlevel 1 (
    echo       Creating Qdrant container...
    docker run -d --name mem0-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant >nul 2>&1
)
echo       Qdrant OK (http://127.0.0.1:6333)

echo.
echo [3/5] Checking Memory Server (Port 8765)...
powershell -Command "$conn = Test-NetConnection -ComputerName 127.0.0.1 -Port 8765 -InformationLevel Quiet; if ($conn) { write-host '       Memory Server already running' } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo       Starting Memory Server...
    start "MOSHI Memory Server" cmd /k "cd /d %ROOT% && %PYTHON% memory_server.py"
    timeout /t 3 /nobreak >nul
) else (
    echo       Memory Server OK
)

echo.
echo [4/5] Checking OpenCode Server (Port 4096)...
powershell -Command "$conn = Test-NetConnection -ComputerName 127.0.0.1 -Port 4096 -InformationLevel Quiet; if ($conn) { write-host '       OpenCode Server already running' } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo       Starting OpenCode Server...
    start "MOSHI OpenCode" cmd /k "cd /d %ROOT% && opencode serve --hostname 127.0.0.1 --port 4096"
    timeout /t 4 /nobreak >nul
) else (
    echo       OpenCode Server OK
)

echo.
echo [5/5] Checking Telegram Agent Bot...
powershell -Command "$p = Get-CimInstance Win32_Process -Filter \"name='python.exe' and commandline like '%%bot_agent_final.py%%'\"; if ($p) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo       Starting Telegram Bot...
    start "MOSHI Telegram" cmd /k "cd /d %ROOT%\telegram && %PYTHON% bot_agent_final.py"
    timeout /t 2 /nobreak >nul
) else (
    echo       Telegram Agent Bot already running
)

echo.
echo ============================================================
echo                    MOSHI SYSTEM ONLINE
echo ============================================================
echo.
echo LM Studio : http://127.0.0.1:1234/v1
echo Qdrant    : http://127.0.0.1:6333
echo Memory    : http://127.0.0.1:8765
echo OpenCode  : http://127.0.0.1:4096
echo Telegram  : Active (Polling Telegram API)
echo.
echo Model     : Qwen 2.5 Coder 14B (qwen/qwen2.5-coder-14b)
echo Memory DB : Qdrant + Mem0 (Project Scoped)
echo.
echo Keep all service windows open.
echo ============================================================
echo.
pause

