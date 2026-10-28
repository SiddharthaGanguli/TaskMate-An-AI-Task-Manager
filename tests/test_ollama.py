import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient, OllamaError
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class OllamaTests(unittest.TestCase):
    def test_local_add_then_list_and_followup(self):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            self.assertEqual(payload["model"], "local-model")
            self.assertEqual(payload["tools"][0]["function"]["name"], "add_task")
            self.assertNotIn("authorization", request.headers)
            if len(requests) == 1:
                message = {"role": "assistant", "content": "", "thinking": "Keep this in history.", "tool_calls": [
                    {"function": {"name": "add_task", "arguments": {
                        "title": "Local assignment", "deadline": None, "priority": "high",
                    }}},
                ]}
            elif len(requests) == 2:
                self.assertEqual(payload["messages"][-2]["thinking"], "Keep this in history.")
                self.assertEqual(payload["messages"][-1]["tool_name"], "add_task")
                message = {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "list_tasks", "arguments": {
                        "status": "pending", "priority": None, "search": None,
                    }}},
                ]}
            else:
                if len(requests) == 3:
                    self.assertEqual(payload["messages"][-1]["tool_name"], "list_tasks")
                    result = json.loads(payload["messages"][-1]["content"])
                    self.assertEqual(result["result"][0]["title"], "Local assignment")
                message = {"role": "assistant", "content": "Your local task is saved."}
            return httpx.Response(200, json={"message": message, "done": True})

        with tempfile.TemporaryDirectory() as folder:
            store = TaskStore(Path(folder) / "tasks.db")
            with OllamaClient(transport=httpx.MockTransport(handle)) as client:
                agent = TaskAgent(client, TaskTools(store), "local-model")
                self.assertIn("saved", agent.run("Add my assignment and list pending tasks"))
                self.assertIn("saved", agent.run("Thanks"))
                self.assertEqual(len(store.list_tasks()), 1)
        self.assertEqual(len(requests), 4)

    def test_errors_are_readable(self):
        cases = [
            (404, {"error": "not found"}, "ollama pull"),
            (400, {"error": "tools unsupported"}, "supports tools"),
            (200, {"message": {"role": "assistant", "tool_calls": [
                {"function": {"name": "add_task", "arguments": "bad"}},
            ]}}, "invalid response"),
        ]
        for status, data, expected in cases:
            with self.subTest(status=status), OllamaClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(status, json=data))
            ) as client:
                with self.assertRaisesRegex(OllamaError, expected):
                    client.create(model="local", instructions="test", tools=[], input=[])

    def test_unreachable_server(self):
        def fail(request):
            raise httpx.ConnectError("offline", request=request)

        with OllamaClient(transport=httpx.MockTransport(fail)) as client:
            with self.assertRaisesRegex(OllamaError, "Could not reach Ollama"):
                client.create(model="local", instructions="test", tools=[], input=[])

    def test_cli_local_mode_needs_no_openai_key(self):
        from task_manager.cli import main

        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"OPENAI_API_KEY": ""}), \
                patch("sys.argv", ["task-agent", "--provider", "ollama", "--db", str(Path(folder) / "tasks.db")]), \
                patch("builtins.input", return_value="/quit"), patch("builtins.print") as output, \
                patch("task_manager.cli.OpenAI") as cloud:
            main()
            cloud.assert_not_called()
            self.assertIn("ollama", output.call_args_list[0].args[0])
