"""Keep database work separate so the agent never needs to write SQL."""

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path


def check_title(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError("Title must contain 1 to 200 characters.")
    return value.strip()


def check_choice(value, choices, label):
    if value not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(choices)}.")
    return value


def check_deadline(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Deadline must be YYYY-MM-DD or null.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Deadline must be a real date in YYYY-MM-DD format.") from None
    if parsed.isoformat() != value:
        raise ValueError("Deadline must use YYYY-MM-DD format.")
    return value


def check_category(value):
    if not isinstance(value, str):
        raise ValueError("Category must contain 1 to 40 characters.")
    normalized = " ".join(value.casefold().split())
    if not 1 <= len(normalized) <= 40:
        raise ValueError("Category must contain 1 to 40 characters.")
    return normalized


def title_key(value):
    return " ".join(value.casefold().split())


class TaskStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    deadline TEXT,
                    priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'completed')),
                    category TEXT NOT NULL DEFAULT 'general',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
            """)
            # Older databases have no category column. Keep every existing task.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "category" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN category TEXT NOT NULL DEFAULT 'general'")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    before_data TEXT,
                    after_data TEXT NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0
                )
            """)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.create_function("casefold", 1, str.casefold, deterministic=True)
        return connection

    def add_task(self, title, deadline=None, priority="medium", category="general"):
        title = check_title(title)
        deadline = check_deadline(deadline)
        check_choice(priority, ("low", "medium", "high"), "Priority")
        category = check_category(category)
        with closing(self._connect()) as connection, connection:
            # Hold the write lock while checking, so two retries cannot both add it.
            connection.execute("BEGIN IMMEDIATE")
            duplicate = self._duplicate(connection, title, deadline, category)
            if duplicate:
                return {**duplicate, "created": False}
            cursor = connection.execute(
                "INSERT INTO tasks (title, deadline, priority, category) VALUES (?, ?, ?, ?)",
                (title, deadline, priority, category),
            )
            task = self._get(connection, cursor.lastrowid)
            self._record(connection, "add", None, task)
            return {**task, "created": True}

    def list_tasks(self, status="pending", priority=None, search=None, category=None):
        check_choice(status, ("pending", "completed", "all"), "Status")
        conditions, values = [], []
        if status != "all":
            conditions.append("status = ?")
            values.append(status)
        if priority is not None:
            check_choice(priority, ("low", "medium", "high"), "Priority")
            conditions.append("priority = ?")
            values.append(priority)
        if search is not None:
            search = check_title(search)
            conditions.append("instr(casefold(title), casefold(?)) > 0")
            values.append(search)
        if category is not None:
            conditions.append("category = ?")
            values.append(check_category(category))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        # Only fixed SQL fragments go into this string. User text stays in parameters.
        query = "SELECT * FROM tasks" + where + """
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     deadline IS NULL, deadline, id
        """
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(query, values)]

    def update_task(self, task_id, **changes):
        allowed = {"title", "deadline", "priority", "category"}
        if not changes or not changes.keys() <= allowed:
            raise ValueError("Provide title, deadline, priority, or category to update.")
        if "title" in changes:
            changes["title"] = check_title(changes["title"])
        if "deadline" in changes:
            changes["deadline"] = check_deadline(changes["deadline"])
        if "priority" in changes:
            check_choice(changes["priority"], ("low", "medium", "high"), "Priority")
        if "category" in changes:
            changes["category"] = check_category(changes["category"])
        return self._change(task_id, changes)

    def complete_task(self, task_id):
        return self._change(task_id, {"status": "completed"})

    def _change(self, task_id, changes):
        if type(task_id) is not int or task_id < 1:
            raise ValueError("Task ID must be a positive integer.")
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            before = self._get(connection, task_id)
            if before is None:
                raise ValueError(f"Task {task_id} does not exist.")
            after = {**before, **changes}
            if after == before:
                return before
            if after["status"] == "pending" and self._duplicate(
                connection, after["title"], after["deadline"], after["category"], task_id
            ):
                raise ValueError("That change would duplicate an existing pending task.")
            connection.execute(
                f"UPDATE tasks SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (*changes.values(), task_id),
            )
            task = self._get(connection, task_id)
            self._record(connection, "complete" if "status" in changes else "update", before, task)
            return task

    @staticmethod
    def _get(connection, task_id):
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _duplicate(connection, title, deadline, category, exclude_id=0):
        rows = connection.execute(
            "SELECT * FROM tasks WHERE status = 'pending' AND deadline IS ? AND category = ? AND id != ? ORDER BY id",
            (deadline, category, exclude_id),
        )
        return next((dict(row) for row in rows if title_key(row["title"]) == title_key(title)), None)

    @staticmethod
    def _record(connection, action, before, after):
        connection.execute(
            "INSERT INTO task_history (task_id, action, before_data, after_data) VALUES (?, ?, ?, ?)",
            (after["id"], action, json.dumps(before) if before else None, json.dumps(after)),
        )

    def undo_last_action(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            history = connection.execute("SELECT * FROM task_history WHERE undone = 0 ORDER BY id DESC LIMIT 1").fetchone()
            if history is None:
                raise ValueError("There is no saved task action to undo.")
            after = json.loads(history["after_data"])
            if self._get(connection, history["task_id"]) != after:
                raise ValueError("This task changed outside TaskMate. Undo was stopped to protect that change.")
            before = json.loads(history["before_data"]) if history["before_data"] else None
            if before is None:
                connection.execute("DELETE FROM tasks WHERE id = ?", (history["task_id"],))
            else:
                fields = [field for field in before if field != "id"]
                assignments = ", ".join(f"{field} = ?" for field in fields)
                connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ?",
                                   (*[before[field] for field in fields], before["id"]))
            connection.execute("UPDATE task_history SET undone = 1 WHERE id = ?", (history["id"],))
            return {"action": history["action"], "task_id": history["task_id"], "task": before}

    def list_categories(self):
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute("""
                SELECT category, count(*) AS total,
                       sum(status = 'pending') AS pending,
                       sum(status = 'completed') AS completed
                FROM tasks GROUP BY category ORDER BY category
            """)]

    def plan_day(self, day, limit=5, category=None):
        day = check_deadline(day)
        if day is None:
            raise ValueError("Choose a date for the daily plan.")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Plan limit must be between 1 and 20 tasks.")
        tasks = self.list_tasks(category=category)

        def order(task):
            deadline = task["deadline"]
            if deadline and deadline < day:
                urgency = 0
            elif deadline == day:
                urgency = 1
            else:
                urgency = 2
            return (urgency, {"high": 0, "medium": 1, "low": 2}[task["priority"]],
                    deadline or "9999-12-31", task["id"])

        tasks.sort(key=order)
        selected = []
        for task in tasks[:limit]:
            deadline = task["deadline"]
            reason = "overdue" if deadline and deadline < day else "due today" if deadline == day else "next pending task"
            selected.append({**task, "plan_reason": reason})
        return {"day": day, "tasks": selected, "remaining": max(0, len(tasks) - limit)}
