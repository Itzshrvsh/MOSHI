import os
import json
import hashlib
from pathlib import Path
from datetime import datetime

def register_artifact(project_path: str, artifact_type: str, file_path: str, build_status: str = "SUCCESS") -> dict:
    moshi_dir = Path(project_path) / ".moshi"
    moshi_dir.mkdir(parents=True, exist_ok=True)
    artifacts_file = moshi_dir / "artifacts.json"

    p = Path(file_path)
    if not p.exists():
        return {"status": "error", "message": f"Artifact file {file_path} does not exist"}

    size_bytes = p.stat().st_size
    md5_hash = hashlib.md5(p.read_bytes()).hexdigest()

    entry = {
        "type": artifact_type,
        "name": p.name,
        "path": str(p.resolve()),
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "hash_md5": md5_hash,
        "build_status": build_status,
        "created_at": datetime.now().isoformat()
    }

    registry = []
    if artifacts_file.exists():
        try:
            registry = json.loads(artifacts_file.read_text(encoding="utf-8"))
        except Exception:
            registry = []

    # Update or append
    registry = [r for r in registry if r.get("path") != entry["path"]]
    registry.append(entry)

    artifacts_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return {"status": "ok", "artifact": entry}

def list_artifacts(project_path: str) -> list[dict]:
    artifacts_file = Path(project_path) / ".moshi" / "artifacts.json"
    if artifacts_file.exists():
        try:
            return json.loads(artifacts_file.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []
