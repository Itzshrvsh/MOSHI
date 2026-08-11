import os
import sys
import json
import subprocess
import httpx
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

LMSTUDIO_URL = "http://127.0.0.1:1234/v1"
OPENCODE_URL = "http://127.0.0.1:4096"
MEMORY_URL = "http://127.0.0.1:8765"
QDRANT_URL = "http://127.0.0.1:6333"

def check_lmstudio() -> dict:
    try:
        r = httpx.get(f"{LMSTUDIO_URL}/models", timeout=3.0)
        if r.status_code == 200:
            models = r.json().get("data", [])
            qwen = next((m for m in models if "qwen" in m.get("id", "").lower()), None)
            return {
                "status": "ok",
                "model_loaded": qwen["id"] if qwen else (models[0]["id"] if models else "No model loaded"),
                "models_count": len(models)
            }
    except Exception as e:
        return {"status": "error", "message": f"LM Studio offline ({e})"}

def check_opencode() -> dict:
    try:
        r = httpx.get(f"{OPENCODE_URL}/session", timeout=3.0)
        if r.status_code == 200:
            return {"status": "ok", "active_sessions": len(r.json())}
    except Exception as e:
        return {"status": "error", "message": f"OpenCode server offline ({e})"}

def check_memory_server() -> dict:
    try:
        r = httpx.get(f"{MEMORY_URL}/health", timeout=3.0)
        if r.status_code == 200:
            return {"status": "ok", "response": r.json()}
    except Exception as e:
        return {"status": "error", "message": f"Memory server offline ({e})"}

def check_qdrant() -> dict:
    try:
        r = httpx.get(f"{QDRANT_URL}/healthz", timeout=3.0)
        if r.status_code == 200:
            return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": f"Qdrant offline ({e})"}

def check_telegram() -> dict:
    env_file = Path(r"C:\projects\MOSHI\telegram\.env")
    if not env_file.exists():
        return {"status": "warning", "message": ".env file missing"}
    content = env_file.read_text(encoding="utf-8")
    if "TELEGRAM_BOT_TOKEN=" in content and "your_bot_token" not in content:
        return {"status": "ok"}
    return {"status": "warning", "message": "TELEGRAM_BOT_TOKEN not configured"}

def check_cli_tools() -> dict:
    tools = {}
    for tool, cmd in [("Python", "python --version"), ("Git", "git --version"), ("PowerShell", "powershell -Command \"$PSVersionTable.PSVersion.Major\"")]:
        try:
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            ver = lines[-1] if lines else "Installed"
            tools[tool] = {"status": "ok", "version": ver}
        except Exception as e:
            tools[tool] = {"status": "warning", "message": str(e)}
    return tools

import moshi_capability

def run_doctor_diagnostics() -> dict:
    print("==================================================")
    print("         MOSHI 2.0 SYSTEM HEALTH DOCTOR           ")
    print("==================================================")
    
    caps = moshi_capability.detect_capabilities()
    all_ok = True

    for tool_name, info in caps.items():
        st = info.get("status", "unavailable")
        avail = info.get("available", False)
        
        if st == "ok" and avail:
            badge = "✓ OK"
            details = info.get("version") or info.get("path") or ""
            print(f"{tool_name.upper():20} : {badge} {f'({details})' if details else ''}")
        elif st == "warning":
            badge = "⚠️ WARN"
            print(f"{tool_name.upper():20} : {badge}")
        else:
            badge = "❌ ABSENT"
            print(f"{tool_name.upper():20} : {badge}")

    print("==================================================")
    print(f"Overall Health: {'✅ MOSHI 2.0 READY' if all_ok else '⚠️ SOME SERVICES ABSENT'}")
    print("==================================================\n")
    return {"healthy": all_ok, "details": caps}

if __name__ == "__main__":
    run_doctor_diagnostics()
