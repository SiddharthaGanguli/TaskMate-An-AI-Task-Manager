"""Exercise the real SDK with a local HTTP stub, without making a paid request."""

import json
import tempfile
import unittest
from pathlib import Path

import httpx
from openai import OpenAI

from task_manager.agent import TaskAgent
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class ApiContractTests(unittest.TestCase):
    def test_sdk_serializes_tool_results_on_the_next_request(self):
        requests = []

        def handle(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if len(requests) == 1:
                output = [{
                    "type": "function_call", "id": "fc_1", "call_id": "call_1",
                    "name": "add_task", "status": "completed",
                    "arguments": json.dumps({"title": "SDK test", "deadline": None, "priority": "high"}),
                }]
            else:
                result = json.loads(payload["input"][-1]["output"])
                self.assertTrue(result["ok"])
                self.assertEqual(result["result"]["title"], "SDK test")
                self.assertEqual(payload["input"][-2]["call_id"], "call_1")
                output = [{
                    "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "Saved task 1.", "annotations": []}],
                }]
            return httpx.Response(200, json={
                "id": f"resp_{len(requests)}", "object": "response", "created_at": 0,
                "model": "test-model", "status": "completed", "output": output,
            })

        with tempfile.TemporaryDirectory() as folder:
            with OpenAI(api_key="local-test-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
                store = TaskStore(Path(folder) / "tasks.db")
                agent = TaskAgent(client, TaskTools(store), "test-model")
                self.assertEqual(agent.run("Add SDK test, high priority"), "Saved task 1.")
                self.assertEqual(len(store.list_tasks()), 1)
        self.assertEqual(len(requests), 2)
        self.assertFalse(requests[0]["parallel_tool_calls"])
        self.assertFalse(requests[0]["store"])
