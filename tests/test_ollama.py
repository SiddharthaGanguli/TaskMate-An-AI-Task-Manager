import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient, OllamaError, recover_tool_plan
from task_manager.tools import TOOLS
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class OllamaTests(unittest.TestCase):
    def test_anonymous_blocks_get_one_structured_retry_before_execution(self):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                content = '[tool_call]\n{"title":"Read notes"}\n[/tool_call]'
            else:
                self.assertEqual(payload["format"]["type"], "array")
                self.assertNotIn("tools", payload)
                content = '[{"function":"add_task","arguments":{"title":"Read notes","deadline":null,"priority":"medium"}}]'
            return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

        with OllamaClient(transport=httpx.MockTransport(handle)) as client:
            response = client.create(model="local", instructions="test", tools=TOOLS,
                                     input=[{"role": "user", "content": "Add Read notes"}])
        calls = [item for item in response.output if item.type == "function_call"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "add_task")
        self.assertEqual(len(requests), 2)

    def test_invalid_structured_retry_does_not_execute_anything(self):
        content = '[tool_call]\n{}\n[/tool_call]'
        with OllamaClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "message": {"role": "assistant", "content": content},
        }))) as client:
            with self.assertRaisesRegex(OllamaError, "invalid response"):
                client.create(model="local", instructions="test", tools=TOOLS,
                              input=[{"role": "user", "content": "Add a task"}])

    def test_text_plan_executes_ten_tasks_then_lists_real_results(self):
        requests = []
        plan = [{"function": "add_task", "arguments": {
            "title": f"Test task {number}", "priority": "high", "deadline": "2026-10-29",
        }} for number in range(10)]
        plan.append({"function": "list_tasks", "arguments": {"status": "pending"}})

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                message = {"role": "assistant", "content": json.dumps(plan)}
            else:
                messages = payload["messages"]
                self.assertEqual(len(messages[-12]["tool_calls"]), 11)
                self.assertEqual(messages[-12]["content"], "")
                tasks = json.loads(messages[-1]["content"])["result"]
                self.assertEqual(len(tasks), 10)
                message = {"role": "assistant", "content": "Saved 10 tasks and listed pending tasks."}
            return httpx.Response(200, json={"message": message})

        with tempfile.TemporaryDirectory() as folder:
            store = TaskStore(Path(folder) / "tasks.db")
            with OllamaClient(transport=httpx.MockTransport(handle)) as client:
                agent = TaskAgent(client, TaskTools(store), "local")
                self.assertIn("Saved 10", agent.run("Add ten tasks and show pending tasks"))
            self.assertEqual(len(store.list_tasks()), 10)
        self.assertEqual(len(requests), 2)

    def test_recovery_accepts_only_complete_known_tool_plans(self):
        valid = '{"function":"list_tasks","arguments":{"status":"all"}}'
        self.assertEqual(len(recover_tool_plan(valid, TOOLS)), 1)
        self.assertEqual(len(recover_tool_plan("```json\n" + valid + "\n```", TOOLS)), 1)
        for text in ("Here is an example: " + valid, "[]", '[{"function":"delete_task","arguments":{}}]',
                     '[{"function":"list_tasks","arguments":{}},{"function":"unknown","arguments":{}}]'):
            self.assertEqual(recover_tool_plan(text, TOOLS), [])

    def test_text_plan_is_not_replayed_after_tool_results(self):
        plan = json.dumps({"function": "add_task", "arguments": {"title": "Only once"}})
        with OllamaClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "message": {"role": "assistant", "content": plan},
        }))) as client:
            response = client.create(model="local", instructions="test", tools=TOOLS, input=[
                {"role": "user", "content": "Add a task"},
                {"role": "assistant", "content": "Already saved"},
            ])
            self.assertFalse(any(item.type == "function_call" for item in response.output))

    def test_local_add_then_list_and_followup(self):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            self.assertEqual(payload["model"], "local-model")
            if "format" in payload:
                return httpx.Response(200, json={"message": {"role": "assistant", "content": "[]"}})
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
                self.assertIn("Local assignment", agent.run("Add my assignment and list pending tasks"))
                self.assertIn("saved", agent.run("Thanks"))
                self.assertEqual(len(store.list_tasks()), 1)
        self.assertEqual(len(requests), 5)

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
