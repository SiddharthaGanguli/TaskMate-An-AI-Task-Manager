"""Serve the dashboard and extension from the same local task database."""

import argparse
import math
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient, OllamaError
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


ASSETS = Path(__file__).parent / "web_assets"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TaskDraft(Input):
    title: str = Field(min_length=1, max_length=200)
    deadline: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    category: str = Field(default="general", min_length=1, max_length=40)


class TaskChange(Input):
    title: str | None = None
    deadline: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    category: str | None = None


class Preferences(Input):
    provider: Literal["openai", "ollama"]
    model: str = Field(min_length=1, max_length=128)


class ChatMessage(Input):
    message: str = Field(min_length=1, max_length=4000)


class ExportRequest(Input):
    file_format: Literal["csv", "json"]
    status: Literal["pending", "completed", "all"] = "all"
    priority: Literal["low", "medium", "high"] | None = None
    category: str | None = None
    search: str | None = None


def download_report(report):
    return {"download_url": "/api/downloads/" + Path(report["path"]).name,
            "count": report["count"], "format": report["format"]}


class BrowserTools(TaskTools):
    def __init__(self, store, timezone):
        super().__init__(store, timezone)
        self.downloads = []

    def execute(self, name, arguments):
        result = super().execute(name, arguments)
        if name == "export_tasks" and result["ok"]:
            self.downloads.append(download_report(result["result"]))
        return result


@dataclass
class Conversation:
    provider: str
    model: str
    history: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    touched: float = field(default_factory=time.monotonic)


def create_app(db_path=None, agent_factory=None):
    store = TaskStore(db_path or os.getenv("TASK_DB_PATH", "data/tasks.db"))
    timezone = os.getenv("TASK_TIMEZONE", "Asia/Kolkata")
    zone = ZoneInfo(timezone)
    tools = TaskTools(store, timezone)
    token = secrets.token_urlsafe(32)
    sessions = {}
    session_lock = Lock()
    default_provider = os.getenv("LLM_PROVIDER", "ollama")
    if default_provider not in ("openai", "ollama"):
        raise ValueError("LLM_PROVIDER must be openai or ollama.")

    app = FastAPI(title="TaskMate", docs_url=None, redoc_url=None)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    def today():
        return datetime.now(zone).date().isoformat()

    def session(request, response):
        session_id = request.cookies.get("taskmate_session")
        now = time.monotonic()
        with session_lock:
            # Chat memory is temporary; saved tasks live in SQLite.
            for old_id, old in list(sessions.items()):
                if now - old.touched > 4 * 60 * 60 and not old.lock.locked():
                    del sessions[old_id]
            if session_id not in sessions:
                if len(sessions) >= 64:
                    raise HTTPException(503, "Too many open conversations. Close unused sessions and restart the server.")
                session_id = secrets.token_urlsafe(24)
                model = os.getenv("OLLAMA_MODEL", "qwen3:4b") if default_provider == "ollama" else os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
                sessions[session_id] = Conversation(default_provider, model)
                response.set_cookie("taskmate_session", session_id, httponly=True, samesite="strict", max_age=14400)
            current = sessions[session_id]
            current.touched = now
            return current

    @app.middleware("http")
    async def protect_local_api(request, call_next):
        if request.method in ("POST", "PATCH", "DELETE"):
            supplied = request.headers.get("x-taskmate-token", "")
            origin = request.headers.get("origin")
            extension_origin = bool(origin and re.fullmatch(r"chrome-extension://[a-p]{32}", origin))
            if not secrets.compare_digest(supplied, token) or (
                origin and origin != str(request.base_url).rstrip("/") and not extension_origin
            ):
                return JSONResponse({"detail": "Refresh TaskMate before making changes."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse({"detail": "Could not update the database. Refresh your tasks before retrying."}, status_code=500)

    @app.get("/")
    def index():
        return FileResponse(ASSETS / "index.html")

    @app.get("/api/state")
    def state(request: Request, response: Response, include_session: bool = True):
        if include_session:
            current = session(request, response)
        else:
            model = os.getenv("OLLAMA_MODEL", "qwen3:4b") if default_provider == "ollama" else os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
            current = Conversation(default_provider, model)
        tasks = store.list_tasks(status="all")
        pending = [task for task in tasks if task["status"] == "pending"]
        return {
            "tasks": tasks, "categories": store.list_categories(), "today": today(), "timezone": timezone,
            "stats": {"pending": len(pending), "completed": len(tasks) - len(pending),
                      "today": sum(task["deadline"] == today() for task in pending),
                      "high": sum(task["priority"] == "high" for task in pending),
                      "overdue": sum(bool(task["deadline"] and task["deadline"] < today()) for task in pending)},
            "preferences": {"provider": current.provider, "model": current.model},
            "messages": current.messages[-40:],
            "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip() not in ("", "put_your_api_key_here")),
            "token": token,
        }

    @app.get("/api/tasks")
    def tasks(status: str = "pending", priority: str | None = None, category: str | None = None, search: str | None = None):
        return store.list_tasks(status, priority, search, category)

    @app.post("/api/tasks")
    def add_task(task: TaskDraft):
        return store.add_task(**task.model_dump())

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: int, task: TaskChange):
        return store.update_task(task_id, **task.model_dump(exclude_unset=True))

    @app.post("/api/tasks/{task_id}/complete")
    def complete_task(task_id: int):
        return store.complete_task(task_id)

    @app.post("/api/undo")
    def undo():
        return store.undo_last_action()

    @app.get("/api/plan")
    def plan(day: str | None = None, limit: int = Query(default=5, ge=1, le=20), category: str | None = None):
        return store.plan_day(day or today(), limit, category)

    @app.post("/api/exports")
    def export(body: ExportRequest):
        result = tools.execute("export_tasks", body.model_dump_json())
        if not result["ok"]:
            raise HTTPException(400, result["error"])
        return download_report(result["result"])

    @app.get("/api/downloads/{filename}")
    def download(filename: str):
        if not re.fullmatch(r"tasks-[a-f0-9]{32}\.(csv|json)", filename):
            raise HTTPException(404, "Export not found.")
        root = (store.path.parent / "exports").resolve()
        path = (root / filename).resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(404, "Export not found.")
        suffix = path.suffix
        return FileResponse(path, filename=f"taskmate-{today()}{suffix}",
                            media_type="text/csv" if suffix == ".csv" else "application/json")

    @app.get("/api/models")
    def models():
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.get(os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/tags")
                response.raise_for_status()
                names = [item["name"] for item in response.json().get("models", [])]
            return {"models": names, "connected": True}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {"models": [], "connected": False}

    @app.post("/api/preferences")
    def preferences(body: Preferences, request: Request, response: Response):
        current = session(request, response)
        model = body.model.strip()
        if not model:
            raise HTTPException(400, "Enter a model name.")
        with current.lock:
            current.provider, current.model = body.provider, model
            current.history.clear()
            current.messages.clear()
        return {"provider": current.provider, "model": current.model}

    @app.post("/api/chat/reset")
    def reset_chat(request: Request, response: Response):
        current = session(request, response)
        with current.lock:
            current.history.clear()
            current.messages.clear()
        return {"ok": True}

    @app.post("/api/chat")
    def chat(body: ChatMessage, request: Request, response: Response):
        current = session(request, response)
        if not body.message.strip():
            raise HTTPException(400, "Write a message first.")
        if not current.lock.acquire(blocking=False):
            raise HTTPException(409, "TaskMate is still working on your previous message.")
        try:
            chat_tools = BrowserTools(store, timezone)
            if agent_factory is not None:
                agent = agent_factory(current.provider, current.model, chat_tools)
                agent.history = current.history
                reply = agent.run(body.message)
            else:
                if current.provider == "ollama":
                    timeout = float(os.getenv("OLLAMA_TIMEOUT", "180"))
                    if not math.isfinite(timeout) or timeout <= 0:
                        raise ValueError("OLLAMA_TIMEOUT must be a positive number.")
                    context = OllamaClient(os.getenv("OLLAMA_HOST", "http://localhost:11434"), timeout)
                else:
                    key = os.getenv("OPENAI_API_KEY", "").strip()
                    if key in ("", "put_your_api_key_here"):
                        raise HTTPException(400, "Add OPENAI_API_KEY to .env and restart, or choose Ollama in connection settings.")
                    context = OpenAI(api_key=key, timeout=30, max_retries=0)
                with context as client:
                    agent = TaskAgent(client, chat_tools, current.model, timezone)
                    agent.history = current.history
                    reply = agent.run(body.message)
            current.history = agent.history
            current.messages.extend([{"role": "user", "content": body.message},
                                     {"role": "assistant", "content": reply, "downloads": chat_tools.downloads}])
            current.messages = current.messages[-40:]
            return {"reply": reply, "downloads": chat_tools.downloads}
        except OllamaError as error:
            raise HTTPException(502, f"{error} Check your tasks before retrying.") from None
        except (APIConnectionError, APIStatusError):
            raise HTTPException(502, "The model request failed. Check the connection, model access, and API billing. Refresh tasks before retrying.") from None
        finally:
            current.touched = time.monotonic()
            current.lock.release()

    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
    return app


def main():
    import uvicorn

    load_dotenv()
    parser = argparse.ArgumentParser(description="Open the TaskMate web dashboard.")
    parser.add_argument("--db", default=os.getenv("TASK_DB_PATH", "data/tasks.db"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    print(f"TaskMate dashboard: http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
