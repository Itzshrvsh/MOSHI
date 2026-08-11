import os
import json
import time
import httpx
from pathlib import Path
from datetime import datetime

MEMORY_API = "http://127.0.0.1:8765"
DEFAULT_USER_ID = "sharvesh"

VALID_TASK_STATUSES = [
    "queued", "planning", "executing", "testing",
    "debugging", "recovering", "blocked", "completed", "failed", "cancelled"
]

def get_moshi_dir(project_path: str) -> Path:
    moshi_dir = Path(project_path) / ".moshi"
    moshi_dir.mkdir(parents=True, exist_ok=True)
    (moshi_dir / "logs").mkdir(exist_ok=True)
    (moshi_dir / "checkpoints").mkdir(exist_ok=True)
    return moshi_dir

def init_manifest(project_path: str, name: str, description: str, tech_stack: str = "Python") -> dict:
    moshi_dir = get_moshi_dir(project_path)
    
    # 1. project.json
    project_json = moshi_dir / "project.json"
    if not project_json.exists():
        data = {
            "name": name,
            "description": description,
            "tech_stack": tech_stack,
            "created_at": datetime.now().isoformat(),
            "entry_points": [],
            "build_cmd": "",
            "test_cmd": ""
        }
        with open(project_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # 2. report.md
    report_md = moshi_dir / "report.md"
    if not report_md.exists():
        report_md.write_text(f"""# Project Report: {name}

## Goal
{description}

## Technology
{tech_stack}

## Architecture
- Initial project layout

## Current State
Initialized

## Completed Milestones
- [x] Project manifest initialized

## In Progress Tasks
- Core implementation

## Known Problems
- None

## Important Decisions
- Initialized MOSHI agentic manifest

## Build & Test Status
- Build: Not run yet
- Tests: Not run yet

## Next Steps
- Implement core application components
""".strip(), encoding="utf-8")

    # 3. state.md
    state_md = moshi_dir / "state.md"
    if not state_md.exists():
        state_md.write_text(f"""# Active State: {name}

## Current Task
Project Initialization

## Current Phase
STARTING

## Completed
- Created .moshi manifest directory

## In Progress
- System setup

## Blocked
- None

## Last Successful Verification
- Initial manifest created

## Known Errors
- None

## Next Action
- Implement core modules

## Last Updated
{datetime.now().isoformat()}
""".strip(), encoding="utf-8")

    # 4. requirements.md
    req_md = moshi_dir / "requirements.md"
    if not req_md.exists():
        req_md.write_text(f"# Requirements: {name}\n\n1. {description}\n", encoding="utf-8")

    # 5. architecture.md
    arch_md = moshi_dir / "architecture.md"
    if not arch_md.exists():
        arch_md.write_text(f"# Architecture: {name}\n\n## Tech Stack\n{tech_stack}\n\n## Components\n- TBD\n", encoding="utf-8")

    # 6. decisions.md
    dec_md = moshi_dir / "decisions.md"
    if not dec_md.exists():
        dec_md.write_text(f"# Architectural Decisions: {name}\n\n- [{datetime.now().strftime('%Y-%m-%d')}] Initialized project manifest.\n", encoding="utf-8")

    # 7. tasks.md
    tasks_md = moshi_dir / "tasks.md"
    if not tasks_md.exists():
        tasks_md.write_text(f"# Task Queue: {name}\n\n| ID | Description | Status | Priority | Attempts | Last Error |\n|---|---|---|---|---|---|\n| T1 | Initialize project structure | completed | high | 1 | None |\n", encoding="utf-8")

    # 8. errors.md
    err_md = moshi_dir / "errors.md"
    if not err_md.exists():
        err_md.write_text(f"# Error Log: {name}\n\nNo errors recorded.\n", encoding="utf-8")

    return {"status": "ok", "moshi_dir": str(moshi_dir)}

def update_report(project_path: str, architecture: str = None, completed: str = None, in_progress: str = None, build_status: str = None, next_steps: str = None) -> str:
    moshi_dir = get_moshi_dir(project_path)
    report_md = moshi_dir / "report.md"
    
    project_name = Path(project_path).name
    content = f"# Project Report: {project_name}\n\n"
    if architecture:
        content += f"## Architecture\n{architecture}\n\n"
    if completed:
        content += f"## Completed Milestones\n{completed}\n\n"
    if in_progress:
        content += f"## In Progress Tasks\n{in_progress}\n\n"
    if build_status:
        content += f"## Build & Test Status\n{build_status}\n\n"
    if next_steps:
        content += f"## Next Steps\n{next_steps}\n\n"

    report_md.write_text(content, encoding="utf-8")
    return content

def update_state(project_path: str, task: str = None, phase: str = None, completed: str = None, blocked: str = None, next_action: str = None, errors: str = None) -> str:
    moshi_dir = get_moshi_dir(project_path)
    state_md = moshi_dir / "state.md"
    
    content = f"# Active State\n\n"
    if task:
        content += f"## Current Task\n{task}\n\n"
    if phase:
        content += f"## Current Phase\n{phase}\n\n"
    if completed:
        content += f"## Completed\n{completed}\n\n"
    if blocked:
        content += f"## Blocked\n{blocked}\n\n"
    if next_action:
        content += f"## Next Action\n{next_action}\n\n"
    if errors:
        content += f"## Known Errors\n{errors}\n\n"
    
    content += f"## Last Updated\n{datetime.now().isoformat()}\n"

    state_md.write_text(content, encoding="utf-8")
    return content

def add_decision(project_path: str, decision: str) -> None:
    moshi_dir = get_moshi_dir(project_path)
    dec_md = moshi_dir / "decisions.md"
    with open(dec_md, "a", encoding="utf-8") as f:
        f.write(f"- [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {decision}\n")

def log_error(project_path: str, task_id: str, error_msg: str, solution: str = None) -> None:
    moshi_dir = get_moshi_dir(project_path)
    err_md = moshi_dir / "errors.md"
    with open(err_md, "a", encoding="utf-8") as f:
        f.write(f"\n### [{datetime.now().isoformat()}] Task {task_id}\n")
        f.write(f"**Error:** `{error_msg}`\n")
        if solution:
            f.write(f"**Solution/Repair:** {solution}\n")

def create_checkpoint(project_path: str, checkpoint_name: str = None) -> str:
    moshi_dir = get_moshi_dir(project_path)
    tag = checkpoint_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    ckpt_file = moshi_dir / "checkpoints" / f"ckpt_{tag}.json"
    
    snapshot = {}
    for name in ("project.json", "state.md", "report.md", "architecture.md", "tasks.md"):
        p = moshi_dir / name
        if p.exists():
            snapshot[name] = p.read_text(encoding="utf-8")

    ckpt_file.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return str(ckpt_file)

def sync_checkpoint_to_memory(project_path: str, user_id: str = DEFAULT_USER_ID, project_id: str = "MOSHI") -> bool:
    moshi_dir = get_moshi_dir(project_path)
    state_md = moshi_dir / "state.md"
    report_md = moshi_dir / "report.md"
    
    summary_parts = []
    if report_md.exists():
        summary_parts.append(report_md.read_text(encoding="utf-8"))
    elif state_md.exists():
        summary_parts.append(state_md.read_text(encoding="utf-8"))

    if not summary_parts:
        return False

    checkpoint_text = f"PROJECT CHECKPOINT [{project_id}]:\n" + "\n".join(summary_parts)
    try:
        r = httpx.post(f"{MEMORY_API}/memory/add", json={
            "user_id": user_id,
            "project_id": project_id,
            "text": checkpoint_text
        }, timeout=30.0)
        return r.status_code == 200
    except Exception as e:
        print("[MANIFEST SYNC ERROR]", repr(e))
        return False

def get_project_context(project_path: str) -> str:
    moshi_dir = Path(project_path) / ".moshi"
    if not moshi_dir.exists():
        return ""

    context_parts = []
    
    report_md = moshi_dir / "report.md"
    if report_md.exists():
        context_parts.append(report_md.read_text(encoding="utf-8"))

    state_md = moshi_dir / "state.md"
    if state_md.exists():
        context_parts.append(state_md.read_text(encoding="utf-8"))

    project_json = moshi_dir / "project.json"
    if project_json.exists():
        context_parts.append("Project Config:\n" + project_json.read_text(encoding="utf-8"))

    return "\n\n".join(context_parts)
