"""A disposable server for DOM tests; it never calls an external model."""

import json
import sys

import uvicorn

from task_manager.ollama_client import OllamaError
from task_manager.web import create_app


class TestAgent:
    def __init__(self, provider, model, tools):
        self.tools = tools
        self.history = []

    def run(self, message):
        self.history.append({"role": "user", "content": message})
        if message == "Export my tasks":
            self.tools.execute("export_tasks", json.dumps({"file_format": "csv", "status": "all"}))
            return "Your task export is ready."
        title = "Saved before model failure" if message == "Fail after saving" else "Added from dashboard chat"
        result = self.tools.execute("add_task", json.dumps({"title": title, "category": "study"}))
        if message == "Fail after saving":
            raise OllamaError("Test model disconnected after saving. Check tasks before retrying.")
        return f"Saved task #{result['result']['id']}: {title}."


if __name__ == "__main__":
    app = create_app(sys.argv[1], agent_factory=TestAgent)
    app.state.store.add_task("Write the project README", "2026-10-28", "high", "work")
    app.state.store.add_task("Practice linear algebra", "2026-10-29", "medium", "study")
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="error")
