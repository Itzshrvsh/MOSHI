import os
import sys
import json
import asyncio
import time
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import moshi_manifest
import moshi_doctor
import moshi_process
import moshi_lifecycle
import moshi_config

import httpx
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

ALLOWED_USER_ID = int(
    os.environ["TELEGRAM_ALLOWED_USER_ID"]
)

OPENCODE_URL = os.getenv(
    "OPENCODE_URL",
    "http://127.0.0.1:4096",
)

MEMORY_API = os.getenv(
    "MEMORY_API",
    "http://127.0.0.1:8765",
)

MEMORY_USER_ID = os.getenv(
    "USER_ID",
    "sharvesh",
)

# Rate limiting: 1.5 seconds between Telegram edit API calls
EDIT_THROTTLE_SECONDS = 1.5


# ============================================================
# AGENT STATE MACHINE & METRICS
# ============================================================

STAGES = [
    ("STARTING", "🚀 Initializing agent & session"),
    ("UNDERSTANDING", "🧠 Analyzing user request & context"),
    ("PLANNING", "📋 Creating implementation plan"),
    ("INSPECTING", "🔍 Inspecting workspace & code"),
    ("READING", "📖 Reading target files"),
    ("CODING", "🛠️ Writing code & editing files"),
    ("EXECUTING", "⚙️ Executing tools & commands"),
    ("TESTING", "🧪 Running automated tests"),
    ("DEBUGGING", "🐛 Diagnosing errors & fixing issues"),
    ("VERIFYING", "🔍 Verifying changes on filesystem"),
    ("COMPLETING", "🏁 Finalizing agent output"),
    ("SUCCESS", "✅ Task completed successfully"),
    ("FAILED", "❌ Task execution failed"),
]

STAGE_ORDER = [s[0] for s in STAGES]

sessions = {}
running_tasks = {}
status_messages = {}
status_text = {}
status_locks = {}
last_edit_time = {}
pending_status_tasks = {}
active_sessions = {}  # OpenCode session_id -> Telegram chat_id
queues = {}
worker_tasks = {}
event_router_task = None

# Rich Agent Control Room UI State
task_prompt = {}
task_started_at = {}
task_stage = {}
task_current_activity = {}
task_current_tool = {}
task_current_command = {}
task_files = {}       # list of (icon, relative_path)
task_activity_stream = {} # list of recent activity lines (max 6)
task_tunnel_url = {}
task_bg_processes = {}

# ============================================================
# AUTH
# ============================================================

def authorized(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    return user.id == ALLOWED_USER_ID


# ============================================================
# OPENCODE API INTERFACE
# ============================================================

async def create_session():
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{OPENCODE_URL}/session",
            json={"title": "MOSHI Telegram Live Dashboard"}
        )
        response.raise_for_status()
        return response.json()["id"]


async def send_prompt(session_id, prompt):
    """Run one complete OpenCode turn."""
    async with httpx.AsyncClient(timeout=1800) as client:
        response = await client.post(
            f"{OPENCODE_URL}/session/{session_id}/message",
            json={
                "agent": "build",
                "parts": [{"type": "text", "text": prompt}],
            },
        )
        response.raise_for_status()
        return response.json()


async def abort_session(session_id):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{OPENCODE_URL}/session/{session_id}/abort"
        )
        response.raise_for_status()


async def get_session_status(session_id):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{OPENCODE_URL}/session/status")
            response.raise_for_status()
            data = response.json()

            if not data:
                return {"status": "idle", "type": "idle"}

            if isinstance(data, dict):
                if session_id in data:
                    val = data[session_id]
                    if isinstance(val, dict):
                        return val
                    elif isinstance(val, str):
                        return {"status": val, "type": val}

                if "status" in data or "type" in data:
                    return data

            return {"status": "idle", "type": "idle"}
    except Exception as e:
        return {"status": "unknown", "type": "unknown", "error": str(e)}


async def get_messages(session_id):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{OPENCODE_URL}/session/{session_id}/message")
        response.raise_for_status()
        return response.json()


async def get_diff(session_id):
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{OPENCODE_URL}/session/{session_id}/diff")
        response.raise_for_status()
        return response.json()


# ============================================================
# MEMORY API INTERFACE
# ============================================================

async def search_memory(query, project_id="MOSHI"):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{MEMORY_API}/memory/search",
                json={
                    "user_id": MEMORY_USER_ID,
                    "project_id": project_id,
                    "query": query,
                    "limit": 5,
                },
            )
            response.raise_for_status()
            return response.json().get("results", [])
    except Exception as e:
        print("[MEMORY ERROR]", repr(e))
        return []


# ============================================================
# TELEGRAM THROTTLED STATUS DASHBOARD
# ============================================================

def _shorten(value, limit=160):
    value = str(value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _progress_bar(stage_name):
    try:
        idx = STAGE_ORDER.index(stage_name)
    except ValueError:
        idx = 2
    total = len(STAGE_ORDER) - 2 # exclude SUCCESS/FAILED from bar
    progress_ratio = min(max((idx + 1) / total, 0.1), 1.0)
    filled = int(progress_ratio * 10)
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    return f"`{bar}` Stage {idx + 1} of {total}"


def _tool_badge(tool_name):
    raw = str(tool_name or "").lower().split("/")[-1].split(".")[-1]
    badges = {
        "bash": "💻 PowerShell",
        "powershell": "💻 PowerShell",
        "read": "📖 File Inspect",
        "write": "➕ File Create",
        "edit": "✏️ File Edit",
        "glob": "🔎 Directory Search",
        "grep": "🔍 Code Search",
        "task": "🤖 Subagent Task",
        "todowrite": "📋 Plan Update",
        "todoread": "📋 Plan Read",
    }
    return badges.get(raw, f"⚙️ {raw}")


def _render_status_dashboard(chat_id):
    started = task_started_at.get(chat_id)
    elapsed = int(time.monotonic() - started) if started else 0
    minutes, seconds = divmod(elapsed, 60)
    elapsed_text = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

    prompt_text = task_prompt.get(chat_id, "")
    stage = task_stage.get(chat_id, "STARTING")
    activity = task_current_activity.get(chat_id, "🧠 Processing...")
    tool = task_current_tool.get(chat_id)
    command = task_current_command.get(chat_id)
    files = task_files.get(chat_id, [])
    stream = task_activity_stream.get(chat_id, [])
    tunnel = task_tunnel_url.get(chat_id)

    lines = [
        "🧠 *MOSHI AGENT DASHBOARD*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🎯 *Task:* `{_shorten(prompt_text, 100)}`",
        f"📍 *Current Stage:* `{stage}`",
        f"⏳ *Elapsed:* {elapsed_text}",
        "",
        f"🔄 *Progress:* {_progress_bar(stage)}",
        "",
        f"📍 *Activity:* {activity}",
    ]

    if tool:
        lines.append(f"🛠️ *Tool:* {_tool_badge(tool)}")

    if command:
        lines.extend(["", f"⚙️ *Running Command:*\n`{_shorten(command, 160)}`"])

    if tunnel:
        lines.extend(["", f"🌐 *Public Tunnel Active:*\n`{tunnel}`"])

    if files:
        lines.extend(["", "📁 *Recent Files:*"])
        unique_files = list(dict.fromkeys(files))[-5:]
        for icon, path in unique_files:
            lines.append(f"• {icon} `{_shorten(path, 80)}`")

    if stream:
        lines.extend(["", "📡 *Recent Stream:*"])
        for item in stream[-5:]:
            lines.append(f"• {item}")

    return "\n".join(lines)


async def update_status(bot, chat_id, text, force=False):
    """Safely edit or send Telegram live status message with rate-limiting throttling."""
    lock = status_locks.setdefault(chat_id, asyncio.Lock())

    async with lock:
        message_id = status_messages.get(chat_id)
        previous = status_text.get(chat_id)

        if not force and message_id and previous == text:
            return

        now = time.monotonic()
        last = last_edit_time.get(chat_id, 0)

        # Enforce edit rate limiting (1.5s interval) unless forced
        if not force and message_id and (now - last) < EDIT_THROTTLE_SECONDS:
            return

        try:
            if message_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                )
            else:
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                status_messages[chat_id] = message.message_id

            status_text[chat_id] = text
            last_edit_time[chat_id] = time.monotonic()

        except Exception as e:
            err_str = str(e)
            if "Message is not modified" in err_str:
                pass
            elif "Can't parse entities" in err_str or "markdown" in err_str.lower():
                # Fallback to plain text if markdown error occurs
                try:
                    plain_text = text.replace("*", "").replace("`", "")
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=plain_text,
                    )
                except Exception:
                    pass
            else:
                print("[TELEGRAM STATUS EDIT WARN]", repr(e))


async def push_live_activity(bot, chat_id, stage=None, activity=None, tool=None, command=None, file_op=None, tunnel_url=None, force=False):
    """Update internal agent state and trigger throttled Telegram UI refresh."""
    if stage:
        task_stage[chat_id] = stage

    if tool:
        task_current_tool[chat_id] = tool

    if command:
        task_current_command[chat_id] = command

    if tunnel_url:
        task_tunnel_url[chat_id] = tunnel_url

    if file_op: # tuple: (icon, path)
        task_files.setdefault(chat_id, []).append(file_op)

    if activity:
        task_current_activity[chat_id] = activity
        stream = task_activity_stream.setdefault(chat_id, [])
        if not stream or stream[-1] != activity:
            stream.append(activity)
        del stream[:-10]

    dashboard_text = _render_status_dashboard(chat_id)
    await update_status(bot, chat_id, dashboard_text, force=force)


# ============================================================
# RICH OPENCODE SSE EVENT NORMALIZER
# ============================================================

def describe_event_rich(event):
    """Normalize OpenCode events into structured stage/tool/file updates."""
    event_type = event.get("type", "")
    properties = event.get("properties") or {}

    if event_type == "session.status":
        status = properties.get("status") or {}
        stype = str(status.get("type") or "").lower()

        if stype in ("busy", "running"):
            return {"stage": "INSPECTING", "activity": "🧠 Agent is analyzing and selecting tools"}
        elif stype in ("idle", "completed"):
            return {"stage": "COMPLETING", "activity": "🏁 Agent turn completed"}

    if event_type == "tool.execute.before":
        tool_raw = (
            properties.get("tool")
            or properties.get("name")
            or properties.get("input", {}).get("tool")
            or "tool"
        )
        tool_name = str(tool_raw).lower().split("/")[-1].split(".")[-1]
        input_data = properties.get("input") or {}
        command = input_data.get("command") or properties.get("command")

        if tool_name in ("bash", "powershell"):
            cmd_brief = _shorten(command or "shell command", 120)
            stage = "EXECUTING"
            if any(k in cmd_brief.lower() for k in ("test", "pytest", "unittest")):
                stage = "TESTING"
            elif any(k in cmd_brief.lower() for k in ("build", "compile", "gradle", "npm")):
                stage = "BUILDING"
            
            res = {
                "stage": stage,
                "tool": tool_name,
                "command": cmd_brief,
                "activity": f"⚙️ Executing `{cmd_brief}`",
            }
            return res

        elif tool_name == "read":
            path = input_data.get("path") or input_data.get("file") or "file"
            return {
                "stage": "READING",
                "tool": tool_name,
                "activity": f"📖 Reading `{_shorten(path, 60)}`",
                "file_op": ("📖", str(path)),
            }

        elif tool_name == "write":
            path = input_data.get("path") or input_data.get("file") or "file"
            return {
                "stage": "CODING",
                "tool": tool_name,
                "activity": f"➕ Creating `{_shorten(path, 60)}`",
                "file_op": ("➕", str(path)),
            }

        elif tool_name == "edit":
            path = input_data.get("path") or input_data.get("file") or "file"
            return {
                "stage": "CODING",
                "tool": tool_name,
                "activity": f"✏️ Editing `{_shorten(path, 60)}`",
                "file_op": ("✏️", str(path)),
            }

        elif tool_name in ("glob", "grep"):
            pattern = input_data.get("pattern") or input_data.get("query") or ""
            return {
                "stage": "INSPECTING",
                "tool": tool_name,
                "activity": f"🔍 Searching code `{_shorten(pattern, 40)}`",
            }

        elif tool_name in ("todowrite", "todoread"):
            return {
                "stage": "PLANNING",
                "tool": tool_name,
                "activity": "📋 Updating implementation plan",
            }

        else:
            return {
                "stage": "EXECUTING",
                "tool": tool_name,
                "activity": f"⚙️ Executing `{tool_name}`",
            }

    if event_type == "tool.execute.after":
        tool_name = str(properties.get("tool") or properties.get("name") or "tool").lower()
        output_text = str(properties.get("output") or properties.get("result") or "")

        # Detect Cloudflare Tunnel URL in output
        tunnel_match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", output_text)
        tunnel_url = tunnel_match.group(0) if tunnel_match else None

        res = {
            "stage": "CODING",
            "activity": f"✅ Finished `{tool_name.split('/')[-1]}`",
        }
        if tunnel_url:
            res["tunnel_url"] = tunnel_url
            res["activity"] = f"🌐 Cloudflare Tunnel Active: `{tunnel_url}`"

        return res

    if event_type in ("file.edited", "file.created", "file.written"):
        path = properties.get("path") or properties.get("file") or "file"
        icon = "✏️" if "edited" in event_type else "➕"
        return {
            "stage": "CODING",
            "activity": f"{icon} Touched `{_shorten(path, 60)}`",
            "file_op": (icon, str(path)),
        }

    if event_type in ("session.error", "error"):
        err = properties.get("error") or properties.get("message") or "Unknown error"
        return {
            "stage": "DEBUGGING",
            "activity": f"⚠️ Error: `{_shorten(err, 100)}` -> Attempting recovery",
        }

    return None


async def _event_session_id(data):
    if not isinstance(data, dict):
        return None

    for key in ("sessionID", "sessionId", "session_id"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val

    for key in ("properties", "info", "part", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            val = await _event_session_id(nested)
            if val:
                return val

    return None


async def listen_events_global(bot):
    """Maintain global SSE listener routing events to active Telegram chats."""
    print("[EVENTS] Global OpenCode SSE event listener starting...")

    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    f"{OPENCODE_URL}/event",
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    response.raise_for_status()

                    event_type = None
                    data_lines = []

                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()

                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                            continue

                        if line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                            continue

                        if line != "":
                            continue

                        if not data_lines:
                            continue

                        try:
                            data = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError:
                            event_type = None
                            data_lines = []
                            continue

                        if event_type:
                            data["type"] = event_type

                        data_lines = []
                        event_type = None

                        session_id = await _event_session_id(data)
                        if not session_id:
                            continue

                        chat_id = active_sessions.get(session_id)
                        if not chat_id:
                            continue

                        info = describe_event_rich(data)
                        if info:
                            await push_live_activity(
                                bot,
                                chat_id,
                                stage=info.get("stage"),
                                activity=info.get("activity"),
                                tool=info.get("tool"),
                                command=info.get("command"),
                                file_op=info.get("file_op"),
                                tunnel_url=info.get("tunnel_url"),
                            )

        except asyncio.CancelledError:
            print("[EVENTS] SSE Listener stopped.")
            return
        except Exception as e:
            await asyncio.sleep(2)


# ============================================================
# RESPONSE EXTRACTION & COMPLETION SUMMARY
# ============================================================

async def _wait_for_session_idle(session_id, timeout=15):
    deadline = time.monotonic() + timeout
    consecutive_errors = 0

    while time.monotonic() < deadline:
        try:
            status = await get_session_status(session_id)
            if "error" in status:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    break
            else:
                consecutive_errors = 0

            stype = str(status.get("status") or status.get("type") or "").lower()
            if stype in ("idle", "completed", "stop"):
                return True

            if stype in ("busy", "running", "retry"):
                pass
            elif stype == "error":
                return False

        except Exception:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                break

        await asyncio.sleep(0.5)

    return True


def _extract_latest_completed_text(messages, existing_ids=None):
    existing_ids = existing_ids or set()

    if isinstance(messages, dict):
        messages = messages.get("messages", messages.get("data", []))

    if not isinstance(messages, list):
        return ""

    candidates = []

    for item in messages:
        if not isinstance(item, dict):
            continue

        info = item.get("info") if isinstance(item.get("info"), dict) else item
        parts = item.get("parts") if isinstance(item.get("parts"), list) else []

        if info.get("role") != "assistant":
            continue

        message_id = info.get("id") or item.get("id")
        if existing_ids and message_id in existing_ids:
            continue

        has_tool_call = False
        text_parts = []

        for part in parts:
            if not isinstance(part, dict):
                continue

            ptype = part.get("type")
            if ptype in ("tool", "tool-call", "tool_use", "tool-call-start"):
                has_tool_call = True

            if ptype == "text":
                val = part.get("text")
                if isinstance(val, str) and val.strip():
                    text_parts.append(val.strip())

        text = "\n".join(text_parts).strip()
        if not text and isinstance(item.get("text"), str):
            text = item["text"].strip()

        if text:
            candidates.append({
                "id": message_id,
                "text": text,
                "has_tool_call": has_tool_call,
                "time": (
                    info.get("time", {}).get("completed", 0)
                    if isinstance(info.get("time"), dict)
                    else 0
                ),
            })

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x.get("time") or 0)
    return candidates[-1]["text"]


async def send_long(update, text):
    limit = 4000
    while len(text) > limit:
        split = text.rfind("\n", 0, limit)
        if split <= 0:
            split = limit
        await update.message.reply_text(text[:split])
        text = text[split:].lstrip()

    if text:
        await update.message.reply_text(text)


# ============================================================
# AGENT TASK WORKER
# ============================================================

async def run_agent(update, prompt):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    bot = update.get_bot()

    # Reset UI State
    task_prompt[chat_id] = prompt
    task_started_at[chat_id] = time.monotonic()
    task_stage[chat_id] = "STARTING"
    task_current_activity[chat_id] = "🧠 Starting MOSHI Agent turn"
    task_current_tool[chat_id] = None
    task_current_command[chat_id] = None
    task_files[chat_id] = []
    task_activity_stream[chat_id] = ["📥 Task received"]
    task_tunnel_url[chat_id] = None

    await push_live_activity(bot, chat_id, stage="STARTING", activity="🚀 Session starting", force=True)

    memories = await search_memory(prompt, project_id="MOSHI")
    memory_text = "\n".join(f"- {x.get('memory', '')}" for x in memories)

    session_id = sessions.get(user_id)
    if not session_id:
        session_id = await create_session()
        sessions[user_id] = session_id

    active_sessions[session_id] = chat_id

    # Record existing message IDs
    initial_messages = await get_messages(session_id)
    existing_ids = set()
    if isinstance(initial_messages, list):
        for m in initial_messages:
            if isinstance(m, dict):
                mid = m.get("info", {}).get("id") or m.get("id")
                if mid:
                    existing_ids.add(mid)

    manifest_context = moshi_manifest.get_project_context(str(PROJECT_ROOT))

    agent_prompt = f"""
You are MOSHI, an autonomous coding agent.

User request:
{prompt}

Project root:
{PROJECT_ROOT}

Follow AGENTS.md.

Persistent Project Manifest Context:
{manifest_context if manifest_context else "None (.moshi directory not initialized yet)"}

You have real OpenCode tools.

IMPORTANT:
- Actually perform the requested operation.
- Inspect before modifying.
- Use tools whenever they can answer or perform the task.
- Verify result after changes.
- Use PowerShell syntax on Windows.
- Continue until requested task is complete.

Relevant long-term memory:
{memory_text if memory_text else "None"}
""".strip()

    await push_live_activity(bot, chat_id, stage="UNDERSTANDING", activity="🧠 Analyzing request & memory", force=True)

    try:
        await push_live_activity(bot, chat_id, stage="CODING", activity="⚙️ Starting OpenCode agent turn")

        # Send Prompt & execute agent turn
        result = await send_prompt(session_id, agent_prompt)

        await push_live_activity(bot, chat_id, stage="COMPLETING", activity="🏁 Extracting final agent response")
        await _wait_for_session_idle(session_id, timeout=15)

        # Extract final response
        messages = await get_messages(session_id)
        final_text = _extract_latest_completed_text(messages, existing_ids=existing_ids)

        if not final_text and isinstance(result, dict):
            final_text = _extract_latest_completed_text([result], existing_ids=set())

        if not final_text:
            await asyncio.sleep(1.0)
            messages = await get_messages(session_id)
            final_text = _extract_latest_completed_text(messages, existing_ids=existing_ids)

        # Check diff
        changed_files = []
        try:
            diff = await get_diff(session_id)
            diff_items = diff.get("files", diff.get("diff", [])) if isinstance(diff, dict) else diff
            if isinstance(diff_items, list):
                for item in diff_items:
                    if isinstance(item, dict):
                        p = item.get("file") or item.get("path")
                        if p:
                            changed_files.append(p)
        except Exception:
            pass

        # Check for errors in result or messages
        error_msg = None
        if isinstance(result, dict):
            info = result.get("info") if isinstance(result.get("info"), dict) else result
            err = info.get("error") if isinstance(info, dict) else None
            if err:
                if isinstance(err, dict):
                    error_msg = err.get("data", {}).get("message") or err.get("name") or str(err)
                else:
                    error_msg = str(err)

        if not error_msg and isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict):
                    info = item.get("info") if isinstance(item.get("info"), dict) else item
                    err = info.get("error") if isinstance(info, dict) else None
                    if err:
                        if isinstance(err, dict):
                            error_msg = err.get("data", {}).get("message") or err.get("name") or str(err)
                        else:
                            error_msg = str(err)
                        break

        elapsed = int(time.monotonic() - task_started_at.get(chat_id, time.monotonic()))
        minutes, seconds = divmod(elapsed, 60)
        elapsed_text = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

        if error_msg:
            # Report Error State to User (Do not falsely claim completion!)
            await update_status(
                bot,
                chat_id,
                (
                    "🧠 *MOSHI AGENT DASHBOARD*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "❌ *TASK FAILED*\n"
                    f"🎯 *Task:* `{_shorten(prompt, 100)}`\n"
                    f"⏱️ *Duration:* {elapsed_text}\n\n"
                    f"⚠️ *Error:* `{_shorten(error_msg, 200)}`\n\n"
                    "💡 *Troubleshooting:* If LM Studio returned 'Model is unloaded', ensure LM Studio is running and the model is loaded into memory."
                ),
                force=True,
            )
            await update.message.reply_text(
                f"❌ *MOSHI TASK FAILED*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Task:* {prompt}\n"
                f"⚠️ *Error:* `{error_msg}`\n\n"
                "💡 *Troubleshooting:* Please ensure LM Studio is running and your chosen model is loaded into memory in LM Studio."
            )
            return

        if not final_text:
            if changed_files:
                final_text = f"Executed code changes across {len(changed_files)} file(s)."
            else:
                final_text = "⚠️ OpenCode completed turn, but output no response text or file edits."

        # Edit Dashboard to Final Completed State
        status_header = "✅ *TASK COMPLETED*" if (changed_files or final_text) else "⚠️ *TASK FINISHED (NO CHANGES)*"
        await update_status(
            bot,
            chat_id,
            (
                "🧠 *MOSHI AGENT DASHBOARD*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status_header}\n"
                f"🎯 *Task:* `{_shorten(prompt, 100)}`\n"
                f"⏱️ *Duration:* {elapsed_text}\n\n"
                f"📊 *Result Summary:* {'File edits applied' if changed_files else 'Agent turn finished.'}\n"
                + (f"🌐 *Public URL:* `{task_tunnel_url[chat_id]}`\n" if task_tunnel_url.get(chat_id) else "")
            ),
            force=True,
        )

        # Build Rich Final Report Message
        report_parts = [
            "✅ *MOSHI TASK COMPLETE*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 *Task:* {prompt}",
            f"⏱️ *Duration:* {elapsed_text}",
        ]

        if changed_files:
            report_parts.append("\n📁 *Changed Files:*")
            for f in dict.fromkeys(changed_files):
                report_parts.append(f"• `{f}`")

        if task_tunnel_url.get(chat_id):
            report_parts.append(f"\n🌐 *Public Tunnel URL:*\n{task_tunnel_url[chat_id]}")

        report_parts.extend(["\n🤖 *Agent Response:*", final_text])

        full_report = "\n".join(report_parts)
        await send_long(update, full_report)

    except asyncio.CancelledError:
        try:
            await abort_session(session_id)
        except Exception:
            pass
        raise

    except Exception as e:
        print("[AGENT RUN ERROR]", repr(e))

        await update_status(
            bot,
            chat_id,
            (
                "🧠 *MOSHI AGENT DASHBOARD*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "❌ *TASK FAILED*\n"
                f"⚠️ *Error:* `{type(e).__name__}: {_shorten(e, 180)}`"
            ),
            force=True,
        )

        await update.message.reply_text(
            f"❌ *MOSHI encountered an error:*\n\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )

    finally:
        active_sessions.pop(session_id, None)
        running_tasks.pop(user_id, None)
        task_started_at.pop(chat_id, None)


# ============================================================
# TELEGRAM COMMANDS & MESSAGE HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    await update.message.reply_text(
        "🧠 *MOSHI Live Agent Dashboard Online*\n\n"
        "⚡ OpenCode Agentic Execution Engine\n"
        "🧠 Mem0 Project Vector Memory\n"
        "💾 Qdrant Local Vector Storage\n"
        "🤖 LM Studio Local Model Provider\n\n"
        "Send me any coding or system task to start.",
        parse_mode="Markdown",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session_id = sessions.get(user_id)
    queue = queues.get(user_id)
    queued = queue.qsize() if queue else 0
    running = user_id in running_tasks

    if not session_id:
        await update.message.reply_text("🧠 MOSHI\n\nNo active OpenCode session. Send a task to start.")
        return

    if running and chat_id in task_started_at:
        dash = _render_status_dashboard(chat_id)
        await update.message.reply_text(dash + f"\n\n📥 *Queued Tasks:* {queued}", parse_mode="Markdown")
    else:
        state = "🟡 QUEUED" if queued else "⚪ IDLE"
        await update.message.reply_text(
            f"🧠 *MOSHI Status*\n\nState: `{state}`\nSession: `{session_id}`\nQueued: `{queued}`",
            parse_mode="Markdown",
        )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    session_id = sessions.get(user_id)

    if not session_id:
        await update.message.reply_text("No active session.")
        return

    try:
        await abort_session(session_id)
    except Exception:
        pass

    current = running_tasks.get(user_id)
    if current and not current.done():
        current.cancel()

    queue = queues.get(user_id)
    cleared = 0
    if queue:
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
                cleared += 1
            except asyncio.QueueEmpty:
                break

    await update.message.reply_text(
        f"🛑 MOSHI stopped the active task." + (f" Cleared {cleared} queued task(s)." if cleared else "")
    )


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    old_session = sessions.pop(user_id, None)
    if old_session:
        active_sessions.pop(old_session, None)

    await update.message.reply_text("🆕 Created fresh OpenCode session context for your next task.")


async def doctor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return

    await update.message.reply_text("🩺 Running MOSHI System Diagnostics...")
    diag = moshi_doctor.run_doctor_diagnostics()
    
    lines = ["🩺 *MOSHI SYSTEM HEALTH REPORT*", "━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for service, info in diag["details"].items():
        if isinstance(info, dict):
            st = info.get("status")
            badge = "✓ OK" if st == "ok" else ("⚠️ WARN" if st == "warning" else "❌ ERROR")
            details = info.get("model_loaded") or info.get("version") or info.get("active_sessions") or info.get("message") or ""
            lines.append(f"• *{service}:* `{badge}` {f'({details})' if details else ''}")

    lines.extend(["", f"Overall Health: *{'✅ ALL SYSTEMS OK' if diag['healthy'] else '⚠️ WARNINGS DETECTED'}*"])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    args = context.args
    if args:
        new_m = " ".join(args).strip()
        updated = moshi_config.set_model(new_m)
        await update.message.reply_text(
            f"🎯 *Master Model Updated*\n\n"
            f"New Base Model: `{updated}`\n"
            "Propagated across master config, `opencode.json`, `mem0`, and environment settings.",
            parse_mode="Markdown",
        )
    else:
        current_m = moshi_config.get_model()
        await update.message.reply_text(
            f"🧠 *MOSHI Active Master Model*\n\n"
            f"Current Base Model: `{current_m}`\n\n"
            "To switch model system-wide, send:\n`/model <new_model_name>`",
            parse_mode="Markdown",
        )


async def user_worker(user_id):
    queue = queues[user_id]
    while True:
        update, prompt = await queue.get()
        try:
            task = asyncio.create_task(run_agent(update, prompt))
            running_tasks[user_id] = task
            await task
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("[WORKER ERROR]", repr(e))
        finally:
            running_tasks.pop(user_id, None)
            queue.task_done()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    user_id = update.effective_user.id
    prompt = (update.message.text or "").strip()

    if not prompt:
        return

    queue = queues.setdefault(user_id, asyncio.Queue())
    worker = worker_tasks.get(user_id)

    if worker is None or worker.done():
        worker = asyncio.create_task(user_worker(user_id))
        worker_tasks[user_id] = worker

    is_running = user_id in running_tasks
    position = queue.qsize() + (1 if is_running else 0) + 1

    # Immediate Task Acknowledgement
    if is_running or queue.qsize() > 0:
        await update.message.reply_text(
            f"📥 *MOSHI Received Task*\n\n"
            f"🎯 Task: `{_shorten(prompt, 100)}`\n"
            f"🟡 *Status:* Queued as task #{position}.\n"
            "MOSHI will execute it after the active task finishes.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"🧠 *MOSHI Received Task*\n\n"
            f"🎯 Task: `{_shorten(prompt, 100)}`\n"
            f"🟢 *Status:* Starting agent dashboard...",
            parse_mode="Markdown",
        )

    await queue.put((update, prompt))


# ============================================================
# MAIN APPLICATION LIFECYCLE
# ============================================================

async def post_init(app: Application):
    global event_router_task
    event_router_task = asyncio.create_task(listen_events_global(app.bot))


async def post_shutdown(app: Application):
    global event_router_task
    if event_router_task:
        event_router_task.cancel()
        try:
            await event_router_task
        except asyncio.CancelledError:
            pass

    for task in list(worker_tasks.values()):
        task.cancel()
        try:
            await task
        except Exception:
            pass


def main():
    print("🧠 MOSHI Telegram Live Dashboard starting...")
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("new", new_session))
    app.add_handler(CommandHandler("doctor", doctor_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
