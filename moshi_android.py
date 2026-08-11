import os
import sys
import shutil
import subprocess
from pathlib import Path

def get_adb_path() -> str:
    adb = shutil.which("adb")
    if adb:
        return adb
    home = Path.home()
    std_paths = [
        home / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        home / "Android" / "Sdk" / "platform-tools" / "adb",
        home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    ]
    for p in std_paths:
        if p.exists():
            return str(p)
    return "adb"

def detect_devices() -> list[dict]:
    adb = get_adb_path()
    devices = []
    try:
        out = subprocess.check_output(f"\"{adb}\" devices -l", shell=True, text=True).strip()
        lines = out.splitlines()[1:]
        for l in lines:
            if not l.strip():
                continue
            parts = l.split()
            dev_id = parts[0]
            status = parts[1] if len(parts) > 1 else "unknown"
            model = "android"
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":")[1]
            devices.append({"id": dev_id, "status": status, "model": model})
    except Exception as e:
        print("[ADB DETECT ERROR]", e)
    return devices

def build_apk(project_path: str) -> dict:
    p = Path(project_path)
    if (p / "gradlew").exists():
        cmd = f"cd \"{project_path}\" && ./gradlew assembleDebug"
    elif (p / "gradlew.bat").exists() and sys.platform == "win32":
        cmd = f"cd /d \"{project_path}\" && gradlew.bat assembleDebug"
    else:
        cmd = f"cd \"{project_path}\" && gradle assembleDebug"

    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT, timeout=300)
        return {"status": "success", "output": out[-1000:] if len(out) > 1000 else out}
    except subprocess.CalledProcessError as e:
        return {"status": "failed", "error": e.output[-1000:] if e.output else str(e)}

def find_apk(project_path: str) -> dict:
    p = Path(project_path)
    apks = list(p.glob("**/*.apk"))
    if not apks:
        return {"found": False, "apk_path": None, "size_bytes": 0}
    
    # Sort by modification time
    apks.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    target = apks[0]
    return {
        "found": True,
        "apk_path": str(target),
        "filename": target.name,
        "size_bytes": target.stat().st_size
    }

def install_apk(apk_path: str, device_id: str = None) -> dict:
    adb = get_adb_path()
    target_flag = f"-s {device_id}" if device_id else ""
    cmd = f"\"{adb}\" {target_flag} install -r \"{apk_path}\""
    
    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT, timeout=60).strip()
        if "Success" in out:
            return {"status": "success", "message": "APK installed successfully"}
        return {"status": "failed", "error": out}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

def launch_app(package_name: str, activity_name: str = None, device_id: str = None) -> dict:
    adb = get_adb_path()
    target_flag = f"-s {device_id}" if device_id else ""
    component = f"{package_name}/{activity_name}" if activity_name else f"{package_name}/.MainActivity"
    cmd = f"\"{adb}\" {target_flag} shell am start -n \"{component}\""
    
    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
        return {"status": "success", "output": out}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

def get_logcat(package_name: str = None, lines: int = 50, device_id: str = None) -> str:
    adb = get_adb_path()
    target_flag = f"-s {device_id}" if device_id else ""
    cmd = f"\"{adb}\" {target_flag} logcat -d -t {lines}"
    
    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
        if package_name:
            filtered = [l for l in out.splitlines() if package_name in l]
            return "\n".join(filtered[-lines:])
        return "\n".join(out.splitlines()[-lines:])
    except Exception as e:
        return f"Logcat Error: {e}"

def take_screenshot(output_path: str, device_id: str = None) -> dict:
    adb = get_adb_path()
    target_flag = f"-s {device_id}" if device_id else ""
    
    try:
        subprocess.check_output(f"\"{adb}\" {target_flag} shell screencap -p /sdcard/screen.png", shell=True)
        subprocess.check_output(f"\"{adb}\" {target_flag} pull /sdcard/screen.png \"{output_path}\"", shell=True)
        return {"status": "success", "file": output_path}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
