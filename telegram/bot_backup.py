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

last_status_update = {}

event_tasks = {}

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


async def send_prompt(
    session_id,
    prompt,
):

    async with httpx.AsyncClient(timeout=30) as client:

        response = await client.post(
            f"{OPENCODE_URL}/session/"
            f"{session_id}/prompt_async",
            json={
                "agent": "build",
                "parts": [
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ],
            },
        )

        response.raise_for_status()


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

async def search_memory(query):

    try:

        async with httpx.AsyncClient(timeout=15) as client:

            response = await client.post(
                f"{MEMORY_API}/memory/search",
                json={
                    "user_id": MEMORY_USER_ID,
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
):

    # Prevent rapid Telegram API spam.
    now = asyncio.get_running_loop().time()

    previous_time = last_status_update.get(
        chat_id,
        0
    )

    if now - previous_time < 0.8:

        return

    last_status_update[
        chat_id
    ] = now

    message_id = status_messages.get(
        chat_id
    )

    try:

        if message_id:

            current = status_messages.get(
                f"{chat_id}:text"
            )

            if current == text:

                return

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

            status_messages[
                chat_id
            ] = message.message_id

        status_messages[
            f"{chat_id}:text"
        ] = text

    except Exception as e:

        if (
            "Message is not modified"
            not in str(e)
        ):

            print(
                "[TELEGRAM STATUS]",
                e
            )
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

async def listen_events(
    chat_id,
    session_id,
    bot,
):

    print(
        "[EVENTS] Listening for OpenCode events..."
    )

    try:

        async with httpx.AsyncClient(
            timeout=None
        ) as client:

            async with client.stream(
                "GET",
                f"{OPENCODE_URL}/event",
                headers={
                    "Accept":
                    "text/event-stream"
                },
            ) as response:

                response.raise_for_status()

                event_type = None

                async for line in response.aiter_lines():

                    line = line.strip()

                    if not line:

                        continue

                    if line.startswith(
                        "event:"
                    ):

                        event_type = line[
                            6:
                        ].strip()

                    elif line.startswith(
                        "data:"
                    ):

                        try:

                            data = json.loads(
                                line[5:].strip()
                            )

                            if event_type:
                                data[
                                    "type"
                                ] = event_type

                            message = describe_event(
                                data
                            )

                            if message:

                                await update_status(
                                    bot,
                                    chat_id,
                                    (
                                        "🧠 MOSHI\n\n"
                                        + message
                                    ),
                                )

                        except json.JSONDecodeError:

                            pass

    except asyncio.CancelledError:

        return

    except Exception as e:

        print(
            "[EVENT ERROR]",
            e
        )


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

    # --------------------------------------------------------
    # MEMORY
    # --------------------------------------------------------

    memories = await search_memory(
        prompt
    )

    memory_text = "\n".join(
        f"- {x.get('memory', '')}"
        for x in memories
    )

    # --------------------------------------------------------
    # SESSION
    # --------------------------------------------------------

    session_id = sessions.get(
        user_id
    )

    if not session_id:

        session_id = await create_session()

        sessions[
            user_id
        ] = session_id

    # --------------------------------------------------------
    # PROMPT
    # --------------------------------------------------------

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
"""

    # --------------------------------------------------------
    # INITIAL STATUS
    # --------------------------------------------------------

    status_messages.pop(
        chat_id,
        None
    )

    await update_status(
        update.get_bot(),
        chat_id,
        "🧠 MOSHI\n\n📥 Task received\n🔍 Starting agent...",
    )

    # --------------------------------------------------------
    # EVENT STREAM
    # --------------------------------------------------------

    event_task = asyncio.create_task(
        listen_events(
            chat_id,
            session_id,
            update.get_bot(),
        )
    )

    event_tasks[
        chat_id
    ] = event_task

    try:

        # ----------------------------------------------------
        # SEND TASK
        # ----------------------------------------------------

        await send_prompt(
            session_id,
            agent_prompt
        )

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        for _ in range(
            900
        ):

            await asyncio.sleep(
                2
            )

            state = await get_status(
                session_id
            )

            if state.get(
                "type"
            ) == "idle":

                break

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        messages = await get_messages(
            session_id
        )

        final = extract_final_response(
            messages
        )

        # ----------------------------------------------------
        # DIFF
        # ----------------------------------------------------

        try:

            diff = await get_diff(
                session_id
            )

            changed = []

            for item in diff:

                path = (
                    item.get("file")
                    or item.get("path")
                )

                if path:

                    changed.append(
                        path
                    )

            if changed:

                final += (
                    "\n\n📝 Changed files:\n"
                    + "\n".join(
                        f"• {x}"
                        for x in changed
                    )
                )

        except Exception:

            pass

        if not final:

            final = (
                "Task completed."
            )

        # ----------------------------------------------------
        # DONE
        # ----------------------------------------------------

        await update_status(
            update.get_bot(),
            chat_id,
            "🧠 MOSHI\n\n"
            "━━━━━━━━━━━━━━\n"
            "✅ TASK COMPLETED",
        )

        await send_long(
            update,
            final
        )

    except Exception as e:

        print(
            "[AGENT ERROR]",
            e
        )

        await update_status(
            update.get_bot(),
            chat_id,
            "🧠 MOSHI\n\n❌ TASK FAILED",
        )

        await update.message.reply_text(
            str(e)
        )

    finally:

        event_task.cancel()

        event_tasks.pop(
            chat_id,
            None
        )


# ============================================================
# COMMANDS
# ============================================================

async def start(
    update,
    context,
):

    if not authorized(update):

        await update.message.reply_text(
            "🚫 Unauthorized."
        )

        return

    await update.message.reply_text(
        "🧠 MOSHI online.\n\n"
        "⚡ OpenCode coding agent\n"
        "🧠 Mem0 memory\n"
        "💾 Qdrant\n"
        "🤖 LM Studio\n\n"
        "Send me a coding task."
    )


async def status(
    update,
    context,
):

    if not authorized(update):

        return

    session_id = sessions.get(
        update.effective_user.id
    )

    if not session_id:

        await update.message.reply_text(
            "No active session."
        )

        return

    state = await get_status(
        session_id
    )

    await update.message.reply_text(
        f"🧠 MOSHI\n\n"
        f"Status: {state.get('type')}\n"
        f"Session: {session_id}"
    )


async def stop(
    update,
    context,
):

    if not authorized(update):

        return

    session_id = sessions.get(
        update.effective_user.id
    )

    if not session_id:

        return

    await abort_session(
        session_id
    )

    await update.message.reply_text(
        "🛑 MOSHI stopped the current task."
    )


async def new_session(
    update,
    context,
):

    if not authorized(update):

        return

    sessions.pop(
        update.effective_user.id,
        None
    )

    await update.message.reply_text(
        "🆕 New MOSHI coding session created on your next task."
    )


# ============================================================
# MESSAGE
# ============================================================

async def handle_message(
    update,
    context,
):

    if not authorized(update):

        await update.message.reply_text(
            "🚫 Unauthorized."
        )

        return

    user_id = update.effective_user.id

    if user_id in running_tasks:

        await update.message.reply_text(
            "⏳ MOSHI is already working.\n"
            "Use /status or /stop."
        )

        return

    prompt = (
        update.message.text
        or ""
    ).strip()

    if not prompt:

        return

    task = asyncio.create_task(
        run_agent(
            update,
            prompt
        )
    )

    running_tasks[
        user_id
    ] = task

    try:

        await task

    finally:

        running_tasks.pop(
            user_id,
            None
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "🧠 MOSHI Telegram Agent starting..."
    )

    app = (
        Application.builder()
        .token(
            TELEGRAM_TOKEN
        )
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    app.add_handler(
        CommandHandler(
            "stop",
            stop
        )
    )

    app.add_handler(
        CommandHandler(
            "new",
            new_session
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_message
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()