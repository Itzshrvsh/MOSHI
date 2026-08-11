import os
import sys
import time
import json
import subprocess
from pathlib import Path
from typing import Callable, Optional

import moshi_manifest
import moshi_process

MAX_REPAIR_ATTEMPTS = 3

class ProjectLifecycleRunner:
    def __init__(self, project_path: str, user_id: str = "sharvesh", project_id: str = "MOSHI"):
        self.project_path = str(Path(project_path).resolve())
        self.user_id = user_id
        self.project_id = project_id
        self.moshi_dir = moshi_manifest.get_moshi_dir(self.project_path)
        
    def start_lifecycle(self, task_name: str, task_desc: str) -> dict:
        """Initialize project manifest and transition into UNDERSTANDING phase."""
        moshi_manifest.init_manifest(self.project_path, name=Path(self.project_path).name, description=task_desc)
        moshi_manifest.update_state(self.project_path, task=task_name, phase="UNDERSTANDING", next_action="Inspect codebase and requirements")
        return {"status": "ok", "phase": "UNDERSTANDING"}

    def plan_phase(self, plan_summary: str, tasks: list[str]) -> str:
        """Record plan and populate .moshi/tasks.md."""
        moshi_manifest.update_state(self.project_path, phase="PLANNING", next_action="Execute planned tasks")
        
        tasks_md = self.moshi_dir / "tasks.md"
        lines = [f"# Task Queue: {Path(self.project_path).name}\n\n| ID | Description | Status | Priority | Attempts | Last Error |\n|---|---|---|---|---|---|"]
        for idx, t in enumerate(tasks, 1):
            lines.append(f"| T{idx} | {t} | queued | medium | 0 | None |")
        
        tasks_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return plan_summary

    def run_builder_reviewer_loop(self, task_id: str, build_fn: Callable, verify_fn: Callable) -> dict:
        """Execute Builder -> Reviewer verification loop with MAX_REPAIR_ATTEMPTS = 3."""
        attempts = 0
        last_error = ""

        moshi_manifest.update_state(self.project_path, phase="IMPLEMENTING", task=f"Executing Task {task_id}")

        while attempts < MAX_REPAIR_ATTEMPTS:
            attempts += 1
            print(f"[LIFECYCLE] Task {task_id} Attempt {attempts}/{MAX_REPAIR_ATTEMPTS}...")

            # 1. Builder execution
            try:
                build_result = build_fn()
            except Exception as e:
                last_error = f"Build Exception: {e}"
                moshi_manifest.log_error(self.project_path, task_id, last_error)
                moshi_manifest.update_state(self.project_path, phase="DEBUGGING", errors=last_error)
                continue

            # 2. Independent Reviewer Verification
            moshi_manifest.update_state(self.project_path, phase="VERIFYING")
            try:
                verify_ok, verify_msg = verify_fn()
                if verify_ok:
                    # Success
                    moshi_manifest.update_state(
                        self.project_path,
                        phase="CHECKPOINT",
                        completed=f"- Completed Task {task_id}: {verify_msg}",
                        next_action="Continue to next milestone"
                    )
                    moshi_manifest.create_checkpoint(self.project_path, f"task_{task_id}_success")
                    moshi_manifest.sync_checkpoint_to_memory(self.project_path, user_id=self.user_id, project_id=self.project_id)
                    return {
                        "status": "success",
                        "attempts": attempts,
                        "verification": verify_msg
                    }
                else:
                    last_error = f"Verification Failed: {verify_msg}"
                    moshi_manifest.log_error(self.project_path, task_id, last_error)
                    moshi_manifest.update_state(self.project_path, phase="DEBUGGING", errors=last_error)

            except Exception as e:
                last_error = f"Verification Exception: {e}"
                moshi_manifest.log_error(self.project_path, task_id, last_error)

        # Capped attempts reached
        moshi_manifest.update_state(
            self.project_path,
            phase="BLOCKED",
            blocked=f"Task {task_id} failed after {MAX_REPAIR_ATTEMPTS} repair attempts. Last error: {last_error}",
            next_action="Human intervention required"
        )
        return {
            "status": "blocked",
            "attempts": attempts,
            "error": last_error
        }
