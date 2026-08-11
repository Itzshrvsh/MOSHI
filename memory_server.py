from fastapi import FastAPI
from pydantic import BaseModel

import sys
import os

os.environ["MEM0_TELEMETRY"] = "false"
os.environ["POSTHOG_DISABLED"] = "1"

# Allow importing memory.py from the mem0 directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mem0"))

from memory import memory


app = FastAPI(
    title="MOSHI Memory",
    version="1.0"
)


class MemoryRequest(BaseModel):
    user_id: str
    project_id: str = "MOSHI"
    text: str


class SearchRequest(BaseModel):
    user_id: str
    project_id: str = "MOSHI"
    query: str
    limit: int = 5


@app.get("/")
def root():
    return {
        "service": "MOSHI Memory",
        "status": "online"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "MOSHI Memory"
    }


@app.post("/memory/add")
def add_memory(request: MemoryRequest):
    metadata = {}
    if request.project_id:
        metadata["project_id"] = request.project_id

    result = memory.add(
        request.text,
        user_id=request.user_id,
        metadata=metadata if metadata else None
    )

    return {
        "success": True,
        "result": result
    }


@app.post("/memory/search")
def search_memory(request: SearchRequest):
    filters = {"user_id": request.user_id}
    if request.project_id:
        filters["project_id"] = request.project_id

    result = memory.search(
        request.query,
        filters=filters,
        limit=request.limit
    )

    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)