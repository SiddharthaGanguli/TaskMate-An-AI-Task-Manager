import csv
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from task_manager.ollama_client import OllamaError
from task_manager.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.environment = patch.dict("os.environ", {
            "LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-local-model",
            "TASK_TIMEZONE": "Asia/Kolkata", "OPENAI_API_KEY": "test-key-do-not-expose",
        })
        self.environment.start()
        self.app = create_app(Path(self.folder.name) / "web.db")
        self.client = TestClient(self.app)
        self.state = self.client.get("/api/state").json()
        self.headers = {"X-TaskMate-Token": self.state["token"]}

    def tearDown(self):
        self.client.close()
        self.environment.stop()
        self.folder.cleanup()

    def post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers=self.headers)

    def add(self, title="Study linear algebra", **changes):
        response = self.post("/api/tasks", {"title": title, "category": "study", **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_dashboard_and_packaged_assets_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your day, made simple", response.text)
        for name in ("app.js", "styles.css", "icons.svg", "mark.svg"):
            self.assertEqual(self.client.get("/assets/" + name).status_code, 200, name)
        self.assertIn("script-src 'self'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("test-key-do-not-expose", json.dumps(self.state))

    def test_create_duplicate_edit_complete_undo_and_stats(self):
        task = self.add(deadline=self.state["today"], priority="high")
        self.assertTrue(task["created"])
        duplicate = self.add(" STUDY  linear algebra ", deadline=self.state["today"], priority="low")
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["priority"], "high")
        response = self.client.patch(f"/api/tasks/{task['id']}", json={"category": "work", "deadline": None}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["deadline"])
        self.assertEqual(response.json()["category"], "work")
        self.post(f"/api/tasks/{task['id']}/complete")
        self.assertEqual(self.client.get("/api/state").json()["stats"]["completed"], 1)
        self.assertEqual(self.post("/api/undo").json()["action"], "complete")
        stats = self.client.get("/api/state").json()["stats"]
        self.assertEqual((stats["pending"], stats["high"], stats["today"]), (1, 1, 0))

    def test_search_filters_categories_and_plan(self):
        overdue = self.add("Overdue report", deadline="2026-10-27", category="work", priority="low")
        algebra = self.add(deadline="2026-10-29", priority="high")
        found = self.client.get("/api/tasks", params={"category": "study", "search": "ALGEBRA", "priority": "high"}).json()
        self.assertEqual([task["id"] for task in found], [algebra["id"]])
        plan = self.client.get("/api/plan", params={"day": "2026-10-28", "limit": 1}).json()
        self.assertEqual(plan["tasks"][0]["id"], overdue["id"])
        self.assertEqual(plan["remaining"], 1)
        state = self.client.get("/api/state").json()
        self.assertEqual([row["category"] for row in state["categories"]], ["study", "work"])

    def test_export_downloads_real_filtered_csv_and_json(self):
        self.add()
        self.add("Team meeting", category="work")
        for file_format in ("csv", "json"):
            response = self.post("/api/exports", {"file_format": file_format, "category": "study"})
            self.assertEqual(response.status_code, 200, response.text)
            report = response.json()
            self.assertEqual(report["count"], 1)
            downloaded = self.client.get(report["download_url"])
            self.assertEqual(downloaded.status_code, 200)
            self.assertIn("attachment", downloaded.headers["content-disposition"])
            rows = downloaded.json() if file_format == "json" else list(csv.DictReader(io.StringIO(downloaded.text)))
            self.assertEqual(rows[0]["title"], "Study linear algebra")
            self.assertEqual(rows[0]["category"], "study")
        for path in ("/api/downloads/.env", "/api/downloads/..%2Fweb.db", "/api/downloads/tasks-" + "a" * 32 + ".json"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_writes_require_token_and_reject_foreign_web_origins(self):
        self.assertEqual(self.client.post("/api/tasks", json={"title": "Not saved"}).status_code, 403)
        response = self.client.post("/api/tasks", json={"title": "Not saved"},
                                    headers={**self.headers, "Origin": "https://unrelated.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/tasks").json(), [])
        self.assertEqual(self.client.get("/api/state", headers={"Host": "unrelated.example"}).status_code, 400)

    def test_extension_uses_same_records_without_creating_chat_sessions(self):
        response = self.client.get("/api/state?include_session=false")
        self.assertNotIn("set-cookie", response.headers)
        extension_headers = {"X-TaskMate-Token": response.json()["token"], "Origin": "chrome-extension://" + "a" * 32}
        created = self.client.post("/api/tasks", json={"title": "From the extension"}, headers=extension_headers)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.get("/api/tasks").json()[0]["title"], "From the extension")
        completed = self.client.post(f"/api/tasks/{created.json()['id']}/complete", json={}, headers=extension_headers)
        self.assertEqual(completed.json()["status"], "completed")

    def test_invalid_input_never_creates_a_task(self):
        for body in ({"title": ""}, {"title": 123}, {"title": "Test", "priority": "urgent"},
                     {"title": "Test", "deadline": "2026-02-30"}, {"title": "Test", "extra": True}):
            self.assertIn(self.post("/api/tasks", body).status_code, (400, 422))
        self.assertEqual(self.client.get("/api/tasks").json(), [])
        self.assertEqual(self.client.get("/api/plan?limit=0").status_code, 422)
        self.assertEqual(self.post("/api/undo").status_code, 400)

    def test_preferences_are_private_to_each_browser_session(self):
        changed = self.post("/api/preferences", {"provider": "openai", "model": "chosen-model"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.get("/api/state").json()["preferences"]["model"], "chosen-model")
        self.assertEqual(self.post("/api/preferences", {"provider": "ollama", "model": " "}).status_code, 400)
        with TestClient(self.app) as second:
            self.assertEqual(second.get("/api/state").json()["preferences"]["model"], "test-local-model")
        self.assertEqual(self.client.get("/api/state").json()["preferences"]["model"], "chosen-model")

    def test_chat_uses_real_tools_and_resets_only_conversation(self):
        class SampleAgent:
            def __init__(self, provider, model, tools):
                self.tools = tools
                self.history = []

            def run(self, message):
                result = self.tools.execute("add_task", json.dumps({"title": "Added through chat"}))
                self.history.append({"role": "user", "content": message})
                return f"Saved task #{result['result']['id']}."

        app = create_app(Path(self.folder.name) / "chat.db", agent_factory=SampleAgent)
        with TestClient(app) as client:
            headers = {"X-TaskMate-Token": client.get("/api/state").json()["token"]}
            response = client.post("/api/chat", json={"message": "Add a task"}, headers=headers)
            self.assertEqual(response.status_code, 200)
            state = client.get("/api/state").json()
            self.assertEqual(state["tasks"][0]["title"], "Added through chat")
            self.assertEqual(state["messages"][-1]["content"], "Saved task #1.")
            client.post("/api/chat/reset", json={}, headers=headers)
            state = client.get("/api/state").json()
            self.assertEqual(state["messages"], [])
            self.assertEqual(len(state["tasks"]), 1)

    def test_second_chat_request_cannot_overlap_the_first(self):
        started, release = Event(), Event()

        class SlowAgent:
            history = []

            def run(self, message):
                started.set()
                release.wait(timeout=5)
                return "Finished."

        app = create_app(Path(self.folder.name) / "busy.db", agent_factory=lambda *args: SlowAgent())
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as workers:
            headers = {"X-TaskMate-Token": client.get("/api/state").json()["token"]}
            future = workers.submit(client.post, "/api/chat", json={"message": "First"}, headers=headers)
            try:
                self.assertTrue(started.wait(timeout=3))
                self.assertEqual(client.post("/api/chat", json={"message": "Second"}, headers=headers).status_code, 409)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=3).status_code, 200)

    def test_chat_exports_have_real_download_links(self):
        class ExportAgent:
            def __init__(self, provider, model, tools):
                self.tools = tools
                self.history = []

            def run(self, message):
                self.tools.execute("export_tasks", '{"file_format":"csv"}')
                return "Your export is ready."

        app = create_app(Path(self.folder.name) / "chat-export.db", agent_factory=ExportAgent)
        app.state.store.add_task("Export this task")
        with TestClient(app) as client:
            headers = {"X-TaskMate-Token": client.get("/api/state").json()["token"]}
            result = client.post("/api/chat", json={"message": "Export my tasks"}, headers=headers).json()
            report = result["downloads"][0]
            self.assertEqual(report["count"], 1)
            self.assertIn("Export this task", client.get(report["download_url"]).text)
            self.assertEqual(client.get("/api/state").json()["messages"][-1]["downloads"], result["downloads"])

    def test_model_outage_has_a_readable_error(self):
        class OfflineAgent:
            history = []

            def run(self, message):
                raise OllamaError("Could not reach Ollama.")

        app = create_app(Path(self.folder.name) / "offline.db", agent_factory=lambda *args: OfflineAgent())
        with TestClient(app) as client:
            headers = {"X-TaskMate-Token": client.get("/api/state").json()["token"]}
            response = client.post("/api/chat", json={"message": "Add a task"}, headers=headers)
            self.assertEqual(response.status_code, 502)
            self.assertIn("Check your tasks before retrying", response.json()["detail"])
        with patch("task_manager.web.httpx.Client", side_effect=httpx.ConnectError("offline")):
            self.assertFalse(self.client.get("/api/models").json()["connected"])


class ExtensionTests(unittest.TestCase):
    def test_extension_manifest_and_all_resources_are_present(self):
        root = Path(__file__).parents[1] / "browser-extension"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["permissions"], ["storage"])
        self.assertEqual(set(manifest["host_permissions"]), {"http://127.0.0.1/*", "http://localhost/*"})
        for name in [manifest["action"]["default_popup"], "popup.js", "popup.css", *manifest["icons"].values()]:
            self.assertTrue((root / name).is_file(), name)
        self.assertNotIn("content_scripts", manifest)
        for name in manifest["icons"].values():
            self.assertEqual((root / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
