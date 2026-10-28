import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from task_manager.agent import TaskAgent
from task_manager.exporting import export_tasks
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        self.store = TaskStore(self.path / "tasks.db")
        self.tools = TaskTools(self.store)

    def tearDown(self):
        self.folder.cleanup()

    def execute(self, name, **arguments):
        result = self.tools.execute(name, json.dumps(arguments))
        self.assertTrue(result["ok"], result)
        return result["result"]

    def test_duplicate_normalization_preserves_saved_values(self):
        first = self.store.add_task("Study  STRASSE", "2026-10-29", "low", " Study ")
        repeated = self.store.add_task("  study straße  ", "2026-10-29", "high", "study")
        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["priority"], "low")
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_different_dates_categories_and_completed_tasks_are_allowed(self):
        first = self.store.add_task("Read", "2026-10-29", category="study")
        self.store.add_task("Read", "2026-10-30", category="study")
        self.store.add_task("Read", "2026-10-29", category="work")
        self.store.complete_task(first["id"])
        self.assertTrue(self.store.add_task("Read", "2026-10-29", category="study")["created"])
        self.assertEqual(len(self.store.list_tasks(status="all")), 4)

    def test_concurrent_retries_save_only_one_task(self):
        def add(_):
            return TaskStore(self.store.path).add_task("Same task", category="work")
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(add, range(4)))
        self.assertEqual(sum(task["created"] for task in results), 1)
        self.assertEqual(len({task["id"] for task in results}), 1)

    def test_update_cannot_turn_a_task_into_a_duplicate(self):
        self.store.add_task("Read", category="study")
        second = self.store.add_task("Write", category="study")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.store.update_task(second["id"], title=" READ ")
        self.assertEqual(self.store.list_tasks(search="Write")[0]["title"], "Write")

    def test_categories_search_and_filters(self):
        first = self.store.add_task("Straße matrices", priority="high", category=" STUDY ")
        self.store.add_task("Team meeting", category="work")
        self.store.add_task("Study matrices", category="study")
        self.store.complete_task(first["id"])
        found = self.execute("search_tasks", search="STRASSE", status="all", category="Study")
        self.assertEqual([task["id"] for task in found], [first["id"]])
        self.assertEqual(self.execute("list_categories"), [
            {"category": "study", "total": 2, "pending": 1, "completed": 1},
            {"category": "work", "total": 1, "pending": 1, "completed": 0},
        ])
        self.store.update_task(first["id"], category="math")
        self.assertEqual(len(self.store.list_tasks(status="all", category="math")), 1)

    def test_plan_uses_urgency_then_priority_and_leaves_data_alone(self):
        self.store.add_task("Future high", "2026-11-01", "high", "work")
        overdue = self.store.add_task("Overdue low", "2026-10-27", "low", "work")
        due = self.store.add_task("Due today", "2026-10-28", "medium", "work")
        completed = self.store.add_task("Done", "2026-10-20", "high", "work")
        self.store.complete_task(completed["id"])
        self.store.add_task("Other category", "2026-10-01", "high", "study")
        before = self.store.list_tasks(status="all")
        plan = self.execute("plan_day", day="2026-10-28", limit=2, category="work")
        self.assertEqual([task["id"] for task in plan["tasks"]], [overdue["id"], due["id"]])
        self.assertEqual([task["plan_reason"] for task in plan["tasks"]], ["overdue", "due today"])
        self.assertEqual(plan["remaining"], 1)
        self.assertEqual(self.store.list_tasks(status="all"), before)
        self.assertEqual(self.store.plan_day("2026-10-28", category="empty")["tasks"], [])
        for limit in (True, 0, 21):
            with self.assertRaises(ValueError):
                self.store.plan_day("2026-10-28", limit)

    def test_undo_each_change_after_reopening_database(self):
        original = self.store.add_task("Read", "2026-10-29", "high", "study")
        original.pop("created")
        changed = self.store.update_task(original["id"], title="Read notes", deadline=None, category="work")
        self.store.complete_task(original["id"])
        reopened = TaskStore(self.store.path)
        self.assertEqual(reopened.undo_last_action()["task"], changed)
        self.assertEqual(reopened.undo_last_action()["task"], original)
        self.assertIsNone(reopened.undo_last_action()["task"])
        self.assertEqual(reopened.list_tasks(status="all"), [])
        with self.assertRaisesRegex(ValueError, "no saved"):
            reopened.undo_last_action()

    def test_noops_duplicates_reads_and_exports_do_not_consume_undo(self):
        task = self.store.add_task("Read")
        self.store.update_task(task["id"], priority="high")
        self.store.add_task(" READ ")
        self.execute("search_tasks", search="read")
        self.execute("plan_day", day="2026-10-28")
        self.execute("export_tasks", file_format="json")
        self.assertEqual(self.store.undo_last_action()["action"], "update")
        self.assertEqual(self.store.list_tasks()[0]["priority"], "medium")
        self.store.complete_task(task["id"])
        self.store.complete_task(task["id"])
        self.assertEqual(self.store.undo_last_action()["action"], "complete")
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_undo_new_branch_and_external_edit_protection(self):
        task = self.store.add_task("First")
        self.store.update_task(task["id"], priority="high")
        self.store.undo_last_action()
        second = self.store.add_task("Second")
        self.assertEqual(self.store.undo_last_action()["task_id"], second["id"])
        with closing(sqlite3.connect(self.store.path)) as connection, connection:
            connection.execute("UPDATE tasks SET title = 'External edit' WHERE id = ?", (task["id"],))
        with self.assertRaisesRegex(ValueError, "outside TaskMate"):
            self.store.undo_last_action()
        self.assertEqual(self.store.list_tasks()[0]["title"], "External edit")

    def test_exports_roundtrip_and_preserve_existing_files(self):
        self.store.add_task('Read "matrices", café\nchapter 2', category="study")
        self.store.add_task(" =1+1", category="work")
        rows = self.store.list_tasks(status="all")
        json_path = self.path / "tasks.json"
        export_tasks(rows, json_path)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), rows)
        with self.assertRaises(FileExistsError):
            export_tasks([], json_path)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), rows)
        csv_path = self.path / "tasks.csv"
        export_tasks(rows, csv_path)
        with csv_path.open(encoding="utf-8", newline="") as handle:
            exported = list(csv.DictReader(handle))
        self.assertEqual(exported[0]["title"], rows[0]["title"])
        self.assertEqual(exported[1]["title"], "'=1+1")
        report = self.execute("export_tasks", file_format="json", category="study")
        self.assertEqual(report["count"], 1)
        self.assertEqual(json.loads(Path(report["path"]).read_text(encoding="utf-8"))[0]["category"], "study")
        empty_csv = self.path / "empty.csv"
        export_tasks([], empty_csv)
        with empty_csv.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertIn("category", reader.fieldnames)
            self.assertEqual(list(reader), [])

    def test_invalid_feature_arguments_do_not_change_tasks(self):
        task = self.store.add_task("Keep")
        for name, arguments in (
            ("add_task", {"title": "bad", "category": " "}),
            ("add_task", {"title": "bad", "category": "ß" * 21}),
            ("update_task", {"task_id": task["id"], "changes": {"category": None}}),
            ("plan_day", {"day": "2026-02-30"}),
            ("search_tasks", {"search": ""}),
            ("export_tasks", {"file_format": "../../file"}),
            ("undo_last_action", {"task_id": 1}),
        ):
            self.assertFalse(self.tools.execute(name, json.dumps(arguments))["ok"], name)
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_cli_features_work_without_an_api_key(self):
        self.store.add_task("Read notes", category="study")
        env = {**os.environ, "OPENAI_API_KEY": ""}
        for flags, expected in (
            (["--search", "notes", "--category", "study"], "Read notes"),
            (["--plan", "2026-10-28", "--limit", "1"], "Suggested plan"),
            (["--categories"], "study: 1 pending"),
            (["--export", str(self.path / "offline.json")], "Exported 1 task"),
            (["--undo"], "Undid add"),
        ):
            result = subprocess.run([sys.executable, "-m", "task_manager", "--db", str(self.store.path), *flags],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout)

    def test_agent_reports_duplicate_instead_of_claiming_another_save(self):
        self.store.add_task("Read notes", category="study")
        client = Mock()
        client.responses.create.side_effect = [
            SimpleNamespace(output=[SimpleNamespace(type="function_call", name="add_task", call_id="a",
                arguments=json.dumps({"title": "Read notes", "category": "study"}))], output_text=""),
            SimpleNamespace(output=[], output_text="Saved another task!"),
        ]
        reply = TaskAgent(client, self.tools, "test").run("Add Read notes in study")
        self.assertIn("already exists", reply)
        self.assertNotIn("Saved another", reply)
        self.assertEqual(len(self.store.list_tasks()), 1)


class MigrationTests(unittest.TestCase):
    def test_old_database_keeps_records_and_can_use_new_features(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("""CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, deadline TEXT,
                    priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT 'old', updated_at TEXT NOT NULL DEFAULT 'old')""")
                connection.execute("INSERT INTO tasks (id, title, deadline, priority) VALUES (7, 'Existing task', '2026-10-29', 'high')")
            store = TaskStore(path)
            self.assertEqual(store.list_tasks()[0]["category"], "general")
            self.assertEqual(store.list_tasks()[0]["id"], 7)
            self.assertEqual(store.list_tasks()[0]["created_at"], "old")
            TaskStore(path)
            store.update_task(7, category="study")
            store.undo_last_action()
            self.assertEqual(store.list_tasks()[0]["category"], "general")
