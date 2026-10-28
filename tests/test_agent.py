import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from task_manager.agent import TaskAgent
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


def call(name, arguments, call_id):
    return SimpleNamespace(type="function_call", name=name,
                           arguments=json.dumps(arguments), call_id=call_id)


def response(*items, text=""):
    return SimpleNamespace(output=list(items), output_text=text)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.folder.name) / "tasks.db")
        self.client = Mock()
        self.agent = TaskAgent(self.client, TaskTools(self.store), "test-model")

    def tearDown(self):
        self.folder.cleanup()

    def test_create_then_list_and_preserve_reasoning(self):
        reasoning = SimpleNamespace(type="reasoning")
        self.client.responses.create.side_effect = [
            response(reasoning, call("add_task", {"title": "AI project", "deadline": "2026-10-30", "priority": "high"}, "a")),
            response(call("list_tasks", {"status": "pending", "priority": None, "search": None}, "b")),
            response(text="Saved your task. #1 AI project, high priority."),
        ]
        self.assertIn("Saved", self.agent.run("Add my AI project by Friday and show pending tasks"))
        self.assertEqual(len(self.store.list_tasks()), 1)
        self.assertIn(reasoning, self.agent.history)
        outputs = [item for item in self.agent.history if isinstance(item, dict) and item.get("type") == "function_call_output"]
        self.assertEqual(len(outputs), 2)
        self.assertEqual(json.loads(outputs[1]["output"])["result"][0]["id"], 1)

    def test_failed_api_turn_clears_history_but_keeps_saved_work(self):
        self.client.responses.create.side_effect = [
            response(call("add_task", {"title": "Saved first", "deadline": None, "priority": "medium"}, "a")),
            RuntimeError("Network failed"),
        ]
        with self.assertRaises(RuntimeError):
            self.agent.run("Add a task")
        self.assertEqual(self.agent.history, [])
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_limit_stops_repeated_tool_calls(self):
        self.agent.max_rounds = 2
        self.client.responses.create.return_value = response(
            call("list_tasks", {"status": "pending", "priority": None, "search": None}, "a"))
        self.assertIn("limit", self.agent.run("Show tasks"))
        self.assertEqual(self.client.responses.create.call_count, 2)
        self.assertEqual(self.agent.history, [])
