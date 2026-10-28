import tempfile
import unittest
from pathlib import Path

from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "tasks.db"
        self.store = TaskStore(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_task_lifecycle_and_persistence(self):
        task = self.store.add_task("  Python assignment  ", "2026-10-29", "high")
        self.assertEqual(TaskStore(self.path).list_tasks()[0]["title"], "Python assignment")
        updated = self.store.update_task(task["id"], deadline=None, priority="low")
        self.assertIsNone(updated["deadline"])
        self.assertEqual(updated["priority"], "low")
        self.store.complete_task(task["id"])
        self.store.complete_task(task["id"])
        self.assertEqual(self.store.list_tasks(), [])
        self.assertEqual(len(self.store.list_tasks(status="completed")), 1)

    def test_filters_order_and_literal_search(self):
        self.store.add_task("Low task", priority="low")
        self.store.add_task("100% Python", priority="high")
        self.store.add_task("Python project", "2026-10-30", "high")
        self.assertEqual(self.store.list_tasks()[0]["title"], "Python project")
        self.assertEqual(len(self.store.list_tasks(priority="high", search="python")), 2)
        self.assertEqual(len(self.store.list_tasks(search="%")), 1)
        title = "Robert'); DROP TABLE tasks;--"
        self.store.add_task(title)
        self.assertEqual(self.store.list_tasks(search=title)[0]["title"], title)

    def test_invalid_changes_leave_data_alone(self):
        task = self.store.add_task("Keep me")
        for changes in ({"deadline": "2026-02-30"}, {"title": " "}, {"priority": "urgent"}, {"status": "completed"}, {}):
            with self.assertRaises(ValueError):
                self.store.update_task(task["id"], **changes)
        self.assertEqual(self.store.list_tasks()[0]["title"], "Keep me")
        for task_id in (True, 0, "1", 999):
            with self.assertRaises(ValueError):
                self.store.complete_task(task_id)

    def test_dispatch_rejects_bad_calls(self):
        tools = TaskTools(self.store)
        for name, arguments in (("delete_task", "{}"), ("add_task", "oops"),
                                ("complete_task", '{"task_id":true}'),
                                ("list_tasks", '{"status":"pending"}'),
                                ("complete_task", '{"task_id":1,"extra":2}')):
            self.assertFalse(tools.execute(name, arguments)["ok"])
        self.assertEqual(self.store.list_tasks(status="all"), [])

    def test_tool_update_can_remove_deadline_without_changing_title(self):
        import json

        task = self.store.add_task("Keep title", "2026-10-30")
        result = TaskTools(self.store).execute("update_task", json.dumps({
            "task_id": task["id"], "changes": {
                "title": None, "priority": "high", "deadline": None, "change_deadline": True,
            },
        }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["title"], "Keep title")
        self.assertIsNone(result["result"]["deadline"])
