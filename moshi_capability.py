import os
import sys
import shutil
import subprocess
import httpx
from pathlib import Path

def _check_bin(cmd: str, version_args: str = "--version") -> dict:
    executable = shutil.which(cmd)
    if not executable:
        # Check standard Windows paths for adb / android sdk
        if cmd == "adb":
            std_adb = Path(r"C:\Users\itzsh\Downloads\platform-tools-latest-windows\platform-tools\adb.exe")
            if std_adb.exists():
                executable = str(std_adb)
            else:
                std_sdk_adb = Path(r"C:\Users\itzsh\AppData\Local\Android\Sdk\platform-tools\adb.exe")
                if std_sdk_adb.exists():
                    executable = str(std_sdk_adb)

    if not executable:
        return {"available": False, "version": None, "path": None, "status": "unavailable"}

    try:
        out = subprocess.check_output(f"\"{executable}\" {version_args}", shell=True, text=True, stderr=subprocess.STDOUT, timeout=5).strip()
        first_line = out.splitlines()[0] if out else "Available"
        return {"available": True, "version": first_line, "path": executable, "status": "ok"}
    except Exception as e:
        return {"available": True, "version": "Available", "path": executable, "status": "ok"}

def detect_capabilities() -> dict:
    caps = {}
    
    # 1. Base Development Tools
    caps["python"] = _check_bin("python")
    caps["git"] = _check_bin("git")
    caps["node"] = _check_bin("node")
    caps["java"] = _check_bin("java", "-version")
    
    # 2. Android Tools
    caps["adb"] = _check_bin("adb", "version")
    
    sdk_path = Path(r"C:\Users\itzsh\AppData\Local\Android\Sdk")
    if sdk_path.exists():
        caps["android_sdk"] = {"available": True, "version": "Android SDK Installed", "path": str(sdk_path), "status": "ok"}
    else:
        caps["android_sdk"] = {"available": False, "version": None, "path": None, "status": "unavailable"}

    # Wireless ADB check via adb devices
    adb_path = caps["adb"].get("path")
    if adb_path:
        try:
            dev_out = subprocess.check_output(f"\"{adb_path}\" devices", shell=True, text=True).strip()
            devices = [line for line in dev_out.splitlines()[1:] if line.strip() and "device" in line]
            caps["wireless_adb"] = {"available": len(devices) > 0, "devices": devices, "status": "ok" if len(devices) > 0 else "warning"}
        except Exception:
            caps["wireless_adb"] = {"available": False, "devices": [], "status": "warning"}
    else:
        caps["wireless_adb"] = {"available": False, "devices": [], "status": "unavailable"}

    # 3. Docker & Cloudflare
    caps["docker"] = _check_bin("docker")
    caps["cloudflared"] = _check_bin("cloudflared")

    # 4. Local AI & Services
    try:
        r = httpx.get("http://127.0.0.1:1234/v1/models", timeout=2.0)
        caps["lm_studio"] = {"available": r.status_code == 200, "status": "ok" if r.status_code == 200 else "warning"}
    except Exception:
        caps["lm_studio"] = {"available": False, "status": "unavailable"}

    try:
        r = httpx.get("http://127.0.0.1:4096/session", timeout=2.0)
        caps["opencode"] = {"available": r.status_code == 200, "status": "ok" if r.status_code == 200 else "warning"}
    except Exception:
        caps["opencode"] = {"available": False, "status": "unavailable"}

    try:
        r = httpx.get("http://127.0.0.1:8765/health", timeout=2.0)
        caps["memory"] = {"available": r.status_code == 200, "status": "ok" if r.status_code == 200 else "warning"}
    except Exception:
        caps["memory"] = {"available": False, "status": "unavailable"}

    try:
        r = httpx.get("http://127.0.0.1:6333/healthz", timeout=2.0)
        caps["qdrant"] = {"available": r.status_code == 200, "status": "ok" if r.status_code == 200 else "warning"}
    except Exception:
        caps["qdrant"] = {"available": False, "status": "unavailable"}

    return caps

if __name__ == "__main__":
    import json
    print(json.dumps(detect_capabilities(), indent=2))
