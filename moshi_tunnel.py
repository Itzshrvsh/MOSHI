import os
import re
import time
import subprocess
import httpx
from pathlib import Path
import moshi_process

PROJECT_ROOT = str(Path(__file__).resolve().parent)

def start_tunnel(port: int, cwd: str = None) -> dict:
    """Asynchronously launch Cloudflare tunnel for port."""
    if cwd is None:
        cwd = PROJECT_ROOT
    cmd = f"cloudflared tunnel --url http://127.0.0.1:{port}"
    process_entry = moshi_process.start_process(cmd, cwd=cwd, name=f"tunnel_{port}")
    return process_entry

def extract_and_verify_url(log_file: str, timeout: int = 20) -> str:
    """Poll log file for trycloudflare.com URL and send HTTP GET health check with DNS retry."""
    deadline = time.time() + timeout
    discovered_url = ""

    while time.time() < deadline:
        if os.path.exists(log_file):
            content = Path(log_file).read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if match:
                discovered_url = match.group(0)
                break
        time.sleep(0.5)

    if not discovered_url:
        return ""

    # Allow up to 10s for Cloudflare DNS propagation
    dns_deadline = time.time() + 10.0
    while time.time() < dns_deadline:
        try:
            r = httpx.get(discovered_url, timeout=5.0, follow_redirects=True)
            if r.status_code in (200, 301, 302, 404, 405, 422):
                return discovered_url
        except Exception as e:
            time.sleep(1.0)

    return discovered_url

def stop_tunnel(port: int) -> bool:
    return moshi_process.stop_process(f"tunnel_{port}")
