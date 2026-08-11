import httpx

from mcp.server import MCPServer


mcp = MCPServer("MOSHI Memory")

MEMORY_API = "http://127.0.0.1:8765"
USER_ID = "sharvesh"


async def api_post(path: str, payload: dict):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{MEMORY_API}{path}",
            json=payload,
        )

        response.raise_for_status()
        return response.json()


async def api_get(path: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{MEMORY_API}{path}",
        )

        response.raise_for_status()
        return response.json()


@mcp.tool()
async def memory_search(
    query: str,
    project_id: str = "MOSHI",
    limit: int = 5,
) -> str:
    """Search MOSHI's long-term memory for a user and optional project scope."""

    data = await api_post(
        "/memory/search",
        {
            "user_id": USER_ID,
            "project_id": project_id,
            "query": query,
            "limit": limit,
        },
    )

    results = data.get("results", [])

    if not results:
        return "No relevant memories found."

    lines = []

    for item in results:
        memory = item.get("memory", "")
        score = item.get("score", 0)

        if memory:
            lines.append(
                f"- {memory} (relevance: {score:.2f})"
            )

    return "\n".join(lines)


@mcp.tool()
async def memory_add(text: str, project_id: str = "MOSHI") -> str:
    """Store an important fact or decision in MOSHI's project-scoped long-term memory."""

    await api_post(
        "/memory/add",
        {
            "user_id": USER_ID,
            "project_id": project_id,
            "text": text,
        },
    )

    return "Memory stored successfully."


@mcp.tool()
async def memory_health() -> str:
    """Check whether the MOSHI Memory API is online."""

    try:
        await api_get("/")
        return "MOSHI Memory is online."
    except Exception as e:
        return f"MOSHI Memory is offline: {e}"


if __name__ == "__main__":
    mcp.run()