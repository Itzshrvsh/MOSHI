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

import moshi_config

def check_lmstudio() -> dict:
    active_model = moshi_config.get_model()
    try:
        r = httpx.get(f"{LMSTUDIO_URL}/models", timeout=3.0)
        if r.status_code == 200:
            try:
                test_resp = httpx.post(
                    f"{LMSTUDIO_URL}/chat/completions",
                    json={"model": active_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    timeout=2.0
                )
                if test_resp.status_code == 400 and "Model is unloaded" in test_resp.text:
                    return {
                        "status": "warning",
                        "message": f"Model '{active_model}' is unloaded in LM Studio! Please load it in LM Studio."
                    }
            except httpx.TimeoutException:
                return {
                    "status": "ok",
                    "model_loaded": f"{active_model} (loading/busy)"
                }
            except Exception:
                pass

            return {
                "status": "ok",
                "model_loaded": active_model,
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
    env_file = Path(__file__).resolve().parent / "telegram" / ".env"
    if not env_file.exists():
        return {"status": "warning", "message": ".env file missing"}
    content = env_file.read_text(encoding="utf-8")
    if "TELEGRAM_BOT_TOKEN=" in content and "your_bot_token" not in content:
        return {"status": "ok"}
    return {"status": "warning", "message": "TELEGRAM_BOT_TOKEN not configured"}

def check_cli_tools() -> dict:
    tools = {}
    shell_tool = ("PowerShell", 'powershell -Command "$PSVersionTable.PSVersion.Major"') if sys.platform == "win32" else ("Bash", "bash --version")
    for tool, cmd in [("Python", "python --version"), ("Git", "git --version"), shell_tool]:
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
    ai_ready = caps.get("lm_studio", {}).get("ai_ready", True)

    for tool_name, info in caps.items():
        st = info.get("status", "unavailable")
        avail = info.get("available", False)
        
        if tool_name in ("python", "git", "lm_studio", "opencode", "memory", "qdrant"):
            if st != "ok":
                all_ok = False

        if st == "ok" and avail:
            badge = "✓ OK"
            details = info.get("version") or info.get("path") or ""
            print(f"{tool_name.upper():20} : {badge} {f'({details})' if details else ''}")
        elif st == "warning":
            badge = "⚠️ WARN"
            details = info.get("version") or info.get("message") or ""
            print(f"{tool_name.upper():20} : {badge} {f'({details})' if details else ''}")
        else:
            badge = "❌ ABSENT"
            print(f"{tool_name.upper():20} : {badge}")

    print("==================================================")
    if all_ok and ai_ready:
        health_text = "✅ MOSHI 2.0 READY"
    elif caps.get("lm_studio", {}).get("available") and not ai_ready:
        health_text = "⚠️ SERVICES RUNNING, AI NOT READY (Model Unloaded in LM Studio)"
    else:
        health_text = "⚠️ SOME SERVICES ABSENT OR UNHEALTHY"
    print(f"Overall Health: {health_text}")
    print("==================================================\n")
    return {"healthy": all_ok and ai_ready, "details": caps}

if __name__ == "__main__":
    run_doctor_diagnostics()
