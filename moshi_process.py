import os
import sys
import time
import json
import re
import subprocess
from pathlib import Path

PROCESS_REGISTRY_FILE = Path(r"C:\projects\MOSHI\.moshi\processes.json")

def _load_registry() -> dict:
    if PROCESS_REGISTRY_FILE.exists():
        try:
            return json.loads(PROCESS_REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_registry(registry: dict) -> None:
    PROCESS_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESS_REGISTRY_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")

def start_process(command: str, cwd: str, name: str = "service") -> dict:
    """Start an asynchronous background process with stdout/stderr redirected to a log file."""
    log_dir = Path(cwd) / ".moshi" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}_{int(time.time())}.log"

    # Use PowerShell Start-Process or popen with redirection
    cmd_str = f"Powershell -Command \"Start-Process -FilePath 'cmd.exe' -ArgumentList '/c {command} > {log_file} 2>&1' -PassThru | Select-Object -ExpandProperty Id\""
    
    try:
        res = subprocess.check_output(cmd_str, shell=True, text=True, cwd=cwd).strip()
        pid = int(res) if res.isdigit() else None
    except Exception as e:
        print("[PROCESS START WARN]", e)
        # Fallback to Popen
        with open(log_file, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=out, stderr=out)
            pid = proc.pid

    entry = {
        "name": name,
        "command": command,
        "cwd": cwd,
        "pid": pid,
        "log_file": str(log_file),
        "started_at": time.time(),
        "status": "running"
    }

    registry = _load_registry()
    registry[name] = entry
    _save_registry(registry)

    return entry

def get_process_status(name: str) -> dict:
    registry = _load_registry()
    entry = registry.get(name)
    if not entry:
        return {"status": "not_found"}

    pid = entry.get("pid")
    if pid:
        # Verify process active via tasklist
        out = subprocess.run(f"tasklist /FI \"PID eq {pid}\"", shell=True, capture_output=True, text=True).stdout
        if str(pid) not in out:
            entry["status"] = "stopped"
            _save_registry(registry)

    log_file = entry.get("log_file")
    if log_file and os.path.exists(log_file):
        content = Path(log_file).read_text(encoding="utf-8", errors="ignore")
        tunnel_match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
        if tunnel_match:
            entry["tunnel_url"] = tunnel_match.group(0)

    return entry

def extract_cloudflare_url(log_file: str, timeout: int = 15) -> str:
    """Poll log file for Cloudflare trycloudflare.com URL."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(log_file):
            content = Path(log_file).read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match:
                return match.group(0)
        time.sleep(0.5)
    return ""

def stop_process(name: str) -> bool:
    registry = _load_registry()
    entry = registry.get(name)
    if not entry:
        return False

    pid = entry.get("pid")
    if pid:
        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        entry["status"] = "stopped"
        _save_registry(registry)
        return True
    return False

def list_processes() -> dict:
    return _load_registry()
