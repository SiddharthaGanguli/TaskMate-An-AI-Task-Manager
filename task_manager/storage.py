"""Keep database work separate so the agent never needs to write SQL."""

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


class TaskStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    deadline TEXT,
                    priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'completed')),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
            """)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def add_task(self, title, deadline=None, priority="medium"):
        title = check_title(title)
        deadline = check_deadline(deadline)
        check_choice(priority, ("low", "medium", "high"), "Priority")
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO tasks (title, deadline, priority) VALUES (?, ?, ?)",
                (title, deadline, priority),
            )
            return dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def list_tasks(self, status="pending", priority=None, search=None):
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
            conditions.append("instr(lower(title), lower(?)) > 0")
            values.append(search)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        # Only fixed SQL fragments go into this string. User text stays in parameters.
        query = "SELECT * FROM tasks" + where + """
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     deadline IS NULL, deadline, id
        """
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(query, values)]

    def update_task(self, task_id, **changes):
        allowed = {"title", "deadline", "priority"}
        if not changes or not changes.keys() <= allowed:
            raise ValueError("Provide title, deadline, or priority to update.")
        if "title" in changes:
            changes["title"] = check_title(changes["title"])
        if "deadline" in changes:
            changes["deadline"] = check_deadline(changes["deadline"])
        if "priority" in changes:
            check_choice(changes["priority"], ("low", "medium", "high"), "Priority")
        return self._change(task_id, changes)

    def complete_task(self, task_id):
        return self._change(task_id, {"status": "completed"})

    def _change(self, task_id, changes):
        if type(task_id) is not int or task_id < 1:
            raise ValueError("Task ID must be a positive integer.")
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"UPDATE tasks SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (*changes.values(), task_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Task {task_id} does not exist.")
            return dict(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
