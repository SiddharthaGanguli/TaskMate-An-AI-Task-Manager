"""Run the ten-task example in a temporary database and print verified results."""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class CheckedTools(TaskTools):
    def __init__(self, store):
        super().__init__(store)
        self.successful_calls = []

    def execute(self, name, arguments):
        result = super().execute(name, arguments)
        if result["ok"]:
            self.successful_calls.append(name)
        return result


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    day = lambda offset: (today + timedelta(days=offset)).isoformat()
    samples = [
        ("Study linear algebra", "high", day(1)),
        ("Go to the gym at 8 PM", "medium", day(0)),
        ("Play cricket match", "medium", day(10)),
        ("Finish Python assignment", "high", day(1)),
        ("Review matrix multiplication", "high", day(2)),
        ("Read 20 pages", "low", day(0)),
        ("Submit AI project report", "high", day(5)),
        ("Buy groceries", "medium", day(3)),
        ("Organize study notes", "low", day(4)),
        ("Practice Python tool calling", "medium", day(6)),
    ]
    parts = [f"{title}, {priority} priority, due {deadline}" for title, priority, deadline in samples]
    parts[1] = "Go to the gym at 8 PM, medium priority, due today"
    parts[2] = "Play cricket match, medium priority, due 10 days from today"
    parts[3] = "Finish Python assignment, high priority, due tomorrow"
    prompt = "Add these tasks: " + "; ".join(parts) + "; then show all pending tasks ordered by priority."

    with tempfile.TemporaryDirectory() as folder:
        store = TaskStore(Path(folder) / "sample.db")
        tools = CheckedTools(store)
        with OllamaClient(timeout=180) as client:
            agent = TaskAgent(client, tools, args.model)
            print("Running ten-task request...", flush=True)
            reply = agent.run(prompt)
            print(reply, flush=True)
            rows = store.list_tasks()
            expected = {(title.lower(), priority, deadline) for title, priority, deadline in samples}
            actual = {(row["title"].lower(), row["priority"], row["deadline"]) for row in rows}
            assert len(rows) == 10 and actual == expected, f"Saved data did not match: {rows}"
            assert all(row["status"] == "pending" for row in rows)
            ranks = [{"high": 0, "medium": 1, "low": 2}[row["priority"]] for row in rows]
            assert ranks == sorted(ranks), "Tasks were not ordered by priority"
            assert tools.successful_calls.count("add_task") == 10, tools.successful_calls
            assert "list_tasks" in tools.successful_calls, tools.successful_calls
            before = len(tools.successful_calls)
            print(agent.run("show me all tsks"), flush=True)
            assert "list_tasks" in tools.successful_calls[before:], "Follow-up did not read the database"
            assert len(store.list_tasks(status="all")) == 10, "Follow-up changed the task count"
            # Reopen the same file to check that the records survive a new connection.
            assert TaskStore(store.path).list_tasks() == rows
            print("VERIFIED_RESULT=" + json.dumps({
                "date": today.isoformat(), "timezone": "Asia/Kolkata", "model": args.model,
                "prompt": prompt, "tasks": rows, "successful_calls": tools.successful_calls,
                "checks": ["10 saved tasks", "exact titles, dates, and priorities", "pending status",
                           "priority order", "list tool called", "misspelled follow-up read",
                           "no duplicate tasks after follow-up", "database persistence"],
            }), flush=True)


if __name__ == "__main__":
    main()
