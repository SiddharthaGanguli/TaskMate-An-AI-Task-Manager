"""Check a complete user session with real tools and a scripted model."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from task_manager.agent import TaskAgent
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class FullWorkflowTests(unittest.TestCase):
    def test_all_features_in_one_session(self):
        # Only the model replies are scripted. Every save, search, undo, and
        # export below goes through the real agent loop and Python tools.
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "tasks.db"
            store = TaskStore(database)
            client = Mock()
            agent = TaskAgent(client, TaskTools(store), "scripted-test-model")
            call_number = 0
            used_tools = set()

            def run(message, *requests):
                nonlocal call_number
                calls = []
                for name, arguments in requests:
                    call_number += 1
                    used_tools.add(name)
                    calls.append(SimpleNamespace(
                        type="function_call", name=name, call_id=f"call_{call_number}",
                        arguments=json.dumps(arguments),
                    ))
                client.responses.create.side_effect = [
                    SimpleNamespace(output=calls, output_text=""),
                    SimpleNamespace(output=[], output_text="Done."),
                ]
                start = len(agent.history)
                reply = agent.run(message)
                results = [json.loads(item["output"]) for item in agent.history[start:]
                           if isinstance(item, dict) and item.get("type") == "function_call_output"]
                self.assertEqual(len(results), len(requests))
                for result in results:
                    self.assertTrue(result["ok"], result)
                return reply, [result["result"] for result in results]

            run("Add my algebra, gym, and project report tasks.",
                ("add_task", {"title": "Study linear algebra", "deadline": "2026-10-29", "priority": "high", "category": "study"}),
                ("add_task", {"title": "Go to the gym at 8 PM", "deadline": "2026-10-28", "priority": "medium", "category": "health"}),
                ("add_task", {"title": "Submit AI project report", "deadline": "2026-10-27", "priority": "high", "category": "work"}))
            original = store.list_tasks(status="all")
            self.assertEqual(len(original), 3)

            reply, results = run("Add my algebra task again.", ("add_task", {
                "title": "  STUDY   linear algebra ", "deadline": "2026-10-29",
                "priority": "low", "category": " STUDY ",
            }))
            self.assertFalse(results[0]["created"])
            self.assertIn("already exists", reply)
            self.assertEqual(store.list_tasks(status="all"), original)

            run("Rename task 1, move it to math, and change its deadline and priority.", ("update_task", {
                "task_id": 1, "changes": {"title": "Study matrices", "category": "math", "priority": "low",
                                          "deadline": "2026-10-31", "change_deadline": True},
            }))
            changed = store.list_tasks(category="math")[0]
            self.assertEqual((changed["title"], changed["deadline"], changed["priority"]),
                             ("Study matrices", "2026-10-31", "low"))
            run("Undo that update.", ("undo_last_action", {}))
            self.assertEqual(store.list_tasks(status="all"), original)

            run("Add a temporary task.", ("add_task", {"title": "Temporary task"}))
            run("Undo that add.", ("undo_last_action", {}))
            self.assertEqual(store.list_tasks(status="all"), original)

            run("Complete my gym task.", ("complete_task", {"task_id": 2}))
            run("Undo that completion.", ("undo_last_action", {}))
            self.assertEqual(store.list_tasks(status="all"), original)
            run("Complete the gym task again.", ("complete_task", {"task_id": 2}))
            self.assertEqual([task["id"] for task in store.list_tasks(status="completed")], [2])
            before_reads = store.list_tasks(status="all")

            reply, results = run("Plan 28 October 2026 with two tasks.", ("plan_day", {
                "day": "2026-10-28", "limit": 2, "category": None,
            }))
            self.assertEqual([task["id"] for task in results[0]["tasks"]], [3, 1])
            self.assertEqual(results[0]["tasks"][0]["plan_reason"], "overdue")
            self.assertIn("Suggested plan for 2026-10-28", reply)

            reply, results = run("Find high-priority pending algebra tasks in study.", ("search_tasks", {
                "search": "ALGEBRA", "category": "study", "status": "pending", "priority": "high",
            }))
            self.assertEqual([task["id"] for task in results[0]], [1])
            self.assertIn("#1 | Study linear algebra", reply)

            _, results = run("Show my categories.", ("list_categories", {}))
            self.assertEqual(results[0], [
                {"category": "health", "total": 1, "pending": 0, "completed": 1},
                {"category": "study", "total": 1, "pending": 1, "completed": 0},
                {"category": "work", "total": 1, "pending": 1, "completed": 0},
            ])

            _, exports = run("Export all tasks as CSV and study tasks as JSON.",
                ("export_tasks", {"file_format": "csv", "status": "all"}),
                ("export_tasks", {"file_format": "json", "status": "all", "category": "study"}))
            with Path(exports[0]["path"]).open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual([int(task["id"]) for task in csv_rows], [3, 1, 2])
            self.assertEqual(csv_rows[-1]["status"], "completed")
            json_rows = json.loads(Path(exports[1]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(json_rows, store.list_tasks(status="all", category="study"))
            self.assertEqual(store.list_tasks(status="all"), before_reads)

            # Reopen the file, then read through a new conversation. This also
            # checks that exports and planning did not replace our undo history.
            reopened = TaskStore(database)
            self.assertEqual(reopened.list_tasks(status="all"), before_reads)
            agent = TaskAgent(client, TaskTools(reopened), "scripted-test-model")
            reply, results = run("Show all saved tasks.", ("list_tasks", {"status": "all"}))
            self.assertEqual([task["id"] for task in results[0]], [3, 1, 2])
            for task in before_reads:
                self.assertIn(f"#{task['id']} | {task['title']}", reply)
            _, results = run("Undo my last saved change after restarting.", ("undo_last_action", {}))
            self.assertEqual(results[0]["action"], "complete")
            self.assertEqual(len(reopened.list_tasks()), 3)
            self.assertEqual(len(list((Path(folder) / "exports").iterdir())), 2)
            self.assertEqual(used_tools, {
                "add_task", "list_tasks", "update_task", "complete_task", "search_tasks",
                "list_categories", "plan_day", "undo_last_action", "export_tasks",
            })
