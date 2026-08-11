import os
import sys
import time
import json
import re
import subprocess
from pathlib import Path

import signal

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESS_REGISTRY_FILE = PROJECT_ROOT / ".moshi" / "processes.json"

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

    pid = None
    if sys.platform == "win32":
        cmd_str = f"Powershell -Command \"Start-Process -FilePath 'cmd.exe' -ArgumentList '/c {command} > {log_file} 2>&1' -PassThru | Select-Object -ExpandProperty Id\""
        try:
            res = subprocess.check_output(cmd_str, shell=True, text=True, cwd=cwd).strip()
            pid = int(res) if res.isdigit() else None
        except Exception as e:
            print("[PROCESS START WARN]", e)

    if pid is None:
        # Standard POSIX or fallback Popen
        with open(log_file, "a", encoding="utf-8") as out:
            kwargs = {"shell": True, "cwd": cwd, "stdout": out, "stderr": out}
            if sys.platform != "win32":
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(command, **kwargs)
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
        is_active = False
        if sys.platform == "win32":
            out = subprocess.run(f"tasklist /FI \"PID eq {pid}\"", shell=True, capture_output=True, text=True).stdout
            is_active = str(pid) in out
        else:
            try:
                os.kill(pid, 0)
                is_active = True
            except OSError:
                is_active = False

        if not is_active:
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
        if sys.platform == "win32":
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        entry["status"] = "stopped"
        _save_registry(registry)
        return True
    return False

def list_processes() -> dict:
    return _load_registry()
