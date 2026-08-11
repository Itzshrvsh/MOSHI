import os
import os
import json
import asyncio
from pathlib import Path

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


# ============================================================
# STATE
# ============================================================

sessions = {}
running_tasks = {}
status_messages = {}
status_text = {}
status_locks = {}
active_sessions = {}  # OpenCode session_id -> Telegram chat_id
queues = {}
worker_tasks = {}
event_router_task = None


# ============================================================
# AUTH
# ============================================================

def authorized(update: Update) -> bool:

    user = update.effective_user

    if not user:
        return False

    return user.id == ALLOWED_USER_ID


# ============================================================
# OPENCODE
# ============================================================

async def create_session():

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.post(
            f"{OPENCODE_URL}/session",
            json={
                "title": "MOSHI Telegram Agent"
            }
        )

        response.raise_for_status()

        return response.json()["id"]


async def send_prompt(session_id, prompt):
    """Run one complete OpenCode turn and wait for its actual response."""
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
            f"{OPENCODE_URL}/session/"
            f"{session_id}/abort"
        )

        response.raise_for_status()


async def get_status(session_id):

    async with httpx.AsyncClient(timeout=10) as client:

        response = await client.get(
            f"{OPENCODE_URL}/session/status"
        )

        response.raise_for_status()

        data = response.json()

        return data.get(
            session_id,
            {"type": "unknown"}
        )


async def get_messages(session_id):

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.get(
            f"{OPENCODE_URL}/session/"
            f"{session_id}/message"
        )

        response.raise_for_status()

        return response.json()


async def get_diff(session_id):

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.get(
            f"{OPENCODE_URL}/session/"
            f"{session_id}/diff"
        )

        response.raise_for_status()

        return response.json()


# ============================================================
# MEMORY
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

            return response.json().get(
                "results",
                []
            )

    except Exception as e:

        print(
            "[MEMORY ERROR]",
            e
        )

        return []


# ============================================================
# TELEGRAM STATUS
# ============================================================
async def update_status(
    bot,
    chat_id,
    text,
    force=False,
):
    """Update one reusable Telegram status message safely."""
    lock = status_locks.setdefault(chat_id, asyncio.Lock())

    async with lock:
        message_id = status_messages.get(chat_id)
        previous = status_text.get(chat_id)

        if not force and message_id and previous == text:
            return

        try:
            if message_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                )
            else:
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )
                status_messages[chat_id] = message.message_id

            status_text[chat_id] = text

        except Exception as e:
            if "Message is not modified" not in str(e):
                print("[TELEGRAM STATUS]", e)


# ============================================================
# EVENT TRANSLATION
# ============================================================

def describe_event(event):

    event_type = event.get(
        "type",
        ""
    )

    properties = event.get(
        "properties",
        {}
    )

    # --------------------------------------------------------
    # SESSION STATUS
    # --------------------------------------------------------

    if event_type == "session.status":

        status = properties.get(
            "status",
            {}
        )

        status_type = status.get(
            "type"
        )

        if status_type == "busy":

            return "🧠 Thinking..."

        if status_type == "idle":

            return "✅ Agent finished."

    # --------------------------------------------------------
    # TOOL START
    # --------------------------------------------------------

    if event_type == "tool.execute.before":

        tool = (
            properties.get("tool")
            or properties.get("name")
            or properties.get("input", {}).get("tool")
            or "unknown tool"
        )

        return f"⚙️ Running `{tool}`"

    # --------------------------------------------------------
    # TOOL COMPLETE
    # --------------------------------------------------------

    if event_type == "tool.execute.after":

        tool = (
            properties.get("tool")
            or properties.get("name")
            or "tool"
        )

        return f"✅ Finished `{tool}`"

    # --------------------------------------------------------
    # FILE EDIT
    # --------------------------------------------------------

    if event_type == "file.edited":

        path = (
            properties.get("path")
            or properties.get("file")
            or "file"
        )

        return f"🛠️ Edited `{path}`"

    # --------------------------------------------------------
    # TODO
    # --------------------------------------------------------

    if event_type == "todo.updated":

        return "📋 Updated task plan."

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if event_type in (
        "session.error",
        "error",
    ):

        error = (
            properties.get("error")
            or properties.get("message")
            or "Unknown error"
        )

        return f"❌ {error}"

    return None

# ============================================================
# SSE EVENT LISTENER
# ============================================================

async def _event_session_id(data):
    """Extract an OpenCode session ID from different event payload shapes."""
    if not isinstance(data, dict):
        return None

    for key in ("sessionID", "sessionId", "session_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("properties", "info", "part", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            value = await _event_session_id(nested)
            if value:
                return value

    return None


async def listen_events_global(bot):
    """Keep one OpenCode SSE connection and route events to active chats."""
    print("[EVENTS] Global OpenCode event listener starting...")

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
                            data = json.loads("\\n".join(data_lines))
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

                        message = describe_event(data)
                        if message:
                            await update_status(
                                bot,
                                chat_id,
                                "🧠 MOSHI\\n\\n" + message,
                            )

        except asyncio.CancelledError:
            print("[EVENTS] Global listener stopped.")
            return

        except Exception as e:
            print("[EVENT ERROR]", repr(e))
            await asyncio.sleep(2)


# ============================================================
# FINAL RESPONSE
# ============================================================

def extract_final_response(messages):

    for message in reversed(
        messages
    ):

        info = message.get(
            "info",
            {}
        )

        if info.get(
            "role"
        ) != "assistant":

            continue

        parts = message.get(
            "parts",
            []
        )

        texts = []

        for part in parts:

            if part.get(
                "type"
            ) == "text":

                text = part.get(
                    "text",
                    ""
                )

                if text:

                    texts.append(
                        text
                    )

        if texts:

            return "\n".join(
                texts
            ).strip()

    return ""


# ============================================================
# LONG TELEGRAM MESSAGES
# ============================================================

async def send_long(
    update,
    text,
):

    limit = 4000

    while len(text) > limit:

        split = text.rfind(
            "\n",
            0,
            limit
        )

        if split <= 0:
            split = limit

        await update.message.reply_text(
            text[:split]
        )

        text = text[
            split:
        ].lstrip()

    if text:

        await update.message.reply_text(
            text
        )


# ============================================================
# AGENT TASK
# ============================================================

async def run_agent(
    update,
    prompt,
):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    bot = update.get_bot()

    memories = await search_memory(prompt, project_id="MOSHI")

    memory_text = "\\n".join(
        f"- {x.get('memory', '')}"
        for x in memories
    )

    session_id = sessions.get(user_id)

    if not session_id:
        session_id = await create_session()
        sessions[user_id] = session_id

    active_sessions[session_id] = chat_id

    agent_prompt = f"""
You are MOSHI, an autonomous coding agent.

User request:

{prompt}

Project root:

C:\\projects\\MOSHI

Follow AGENTS.md.

You have access to OpenCode's coding tools.

IMPORTANT:

Do not merely explain how to do the task.

Actually perform the requested work.

Inspect existing code first.

Modify the project when necessary.

Run appropriate tests or verification.

If something fails, diagnose and fix it.

Do not modify unrelated files.

When complete, give a concise summary.

Relevant long-term memory:

{memory_text if memory_text else "None"}
""".strip()

    await update_status(
        bot,
        chat_id,
        "🧠 MOSHI\\n\\n📥 Task received\\n🔍 Starting agent...",
        force=True,
    )

    try:
        await update_status(
            bot,
            chat_id,
            "🧠 MOSHI\n\n⚡ Agent is working...\n🔧 Inspecting and modifying the project.",
            force=True,
        )

        # /message waits until the OpenCode agent turn is actually complete.
        # This avoids guessing completion from /session/status, while this
        # background worker keeps Telegram itself responsive.
        result = await send_prompt(session_id, agent_prompt)
        final = extract_final_response([result])

        if not final:
            messages = await get_messages(session_id)
            final = extract_final_response(messages)

        try:
            diff = await get_diff(session_id)

            if isinstance(diff, dict):
                diff_items = diff.get("files", diff.get("diff", []))
            else:
                diff_items = diff

            changed = []

            if isinstance(diff_items, list):
                for item in diff_items:
                    if isinstance(item, dict):
                        path = item.get("file") or item.get("path")
                        if path:
                            changed.append(path)

            if changed:
                final = (
                    (final + "\\n\\n") if final else ""
                ) + "📝 Changed files:\\n" + "\\n".join(
                    f"• {x}" for x in dict.fromkeys(changed)
                )

        except Exception as e:
            print("[DIFF ERROR]", repr(e))

        if not final:
            final = "Task completed. OpenCode returned no final text."

        await update_status(
            bot,
            chat_id,
            "🧠 MOSHI\\n\\n━━━━━━━━━━━━━━\\n✅ TASK COMPLETED",
            force=True,
        )

        await send_long(update, final)

    except asyncio.CancelledError:
        try:
            await abort_session(session_id)
        except Exception:
            pass
        raise

    except Exception as e:
        print("[AGENT ERROR]", repr(e))

        await update_status(
            bot,
            chat_id,
            "🧠 MOSHI\\n\\n❌ TASK FAILED",
            force=True,
        )

        await update.message.reply_text(
            f"❌ {type(e).__name__}: {e}"
        )

    finally:
        active_sessions.pop(session_id, None)
        running_tasks.pop(user_id, None)


# ============================================================
# COMMANDS
# ============================================================

async def start(
    update,
    context,
):
    if not authorized(update):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    await update.message.reply_text(
        "🧠 MOSHI online.\\n\\n"
        "⚡ OpenCode coding agent\\n"
        "🧠 Mem0 memory\\n"
        "💾 Qdrant\\n"
        "🤖 LM Studio\\n\\n"
        "Send me a coding task."
    )


async def status(
    update,
    context,
):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    session_id = sessions.get(user_id)
    queue = queues.get(user_id)
    queued = queue.qsize() if queue else 0
    running = user_id in running_tasks

    if not session_id:
        await update.message.reply_text(
            "🧠 MOSHI\n\nNo OpenCode session yet.\nSend me a coding task to start one."
        )
        return

    state = "🟢 WORKING" if running else ("🟡 QUEUED" if queued else "⚪ IDLE")

    await update.message.reply_text(
        "🧠 MOSHI\n\n"
        f"Status: {state}\n"
        f"Agent running: {'yes' if running else 'no'}\n"
        f"Queued tasks: {queued}\n"
        f"Session: {session_id}"
    )


async def stop(
    update,
    context,
):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    session_id = sessions.get(user_id)

    if not session_id:
        await update.message.reply_text("No active session.")
        return

    try:
        await abort_session(session_id)
    except Exception as e:
        print("[STOP ERROR]", repr(e))

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
        "🛑 MOSHI stopped the current task."
        + (
            f"\\n🧹 Cleared {cleared} queued task(s)."
            if cleared
            else ""
        )
    )


async def new_session(
    update,
    context,
):
    if not authorized(update):
        return

    user_id = update.effective_user.id
    old_session = sessions.pop(user_id, None)

    if old_session:
        active_sessions.pop(old_session, None)

    await update.message.reply_text(
        "🆕 MOSHI will create a fresh OpenCode session on the next task."
    )


# ============================================================
# MESSAGE
# ============================================================

async def user_worker(user_id):
    """Process one user's Telegram tasks sequentially."""
    queue = queues[user_id]

    while True:
        update, prompt = await queue.get()

        try:
            task = asyncio.create_task(
                run_agent(update, prompt)
            )
            running_tasks[user_id] = task
            await task

        except asyncio.CancelledError:
            raise

        except Exception as e:
            print("[WORKER ERROR]", repr(e))
            try:
                await update.message.reply_text(
                    f"❌ MOSHI worker error: {type(e).__name__}: {e}"
                )
            except Exception:
                pass

        finally:
            running_tasks.pop(user_id, None)
            queue.task_done()


async def handle_message(
    update,
    context,
):
    if not authorized(update):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    user_id = update.effective_user.id

    prompt = (
        update.message.text
        or ""
    ).strip()

    if not prompt:
        return

    queue = queues.setdefault(
        user_id,
        asyncio.Queue(),
    )

    worker = worker_tasks.get(user_id)

    if worker is None or worker.done():
        worker = asyncio.create_task(
            user_worker(user_id)
        )
        worker_tasks[user_id] = worker

    position = (
        queue.qsize()
        + (1 if user_id in running_tasks else 0)
        + 1
    )

    await queue.put((update, prompt))

    if position > 1:
        await update.message.reply_text(
            f"📥 Queued as task #{position}.\\n"
            "MOSHI will execute it after the current task."
        )


# ============================================================
# MAIN
# ============================================================

async def post_init(app):
    global event_router_task
    event_router_task = asyncio.create_task(
        listen_events_global(app.bot)
    )


async def post_shutdown(app):
    global event_router_task

    if event_router_task:
        event_router_task.cancel()
        try:
            await event_router_task
        except asyncio.CancelledError:
            pass

    for task in list(worker_tasks.values()):
        task.cancel()

    for task in list(worker_tasks.values()):
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


def main():
    print("🧠 MOSHI Telegram Agent starting...")

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

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
