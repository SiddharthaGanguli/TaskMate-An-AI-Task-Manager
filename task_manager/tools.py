"""Describe our tools and check every request before running it."""

import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from task_manager.exporting import export_tasks


def tool(name, description, properties):
    return {
        "type": "function", "name": name, "description": description, "strict": True,
        "parameters": {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        },
    }


TITLE = {"type": "string", "description": "Short, clear task title, up to 200 characters."}
DEADLINE = {"type": ["string", "null"], "description": "Date in YYYY-MM-DD format, or null for no deadline."}
PRIORITY = {"type": "string", "enum": ["low", "medium", "high"]}
TASK_ID = {"type": "integer", "description": "Existing task ID. Look it up first if unknown."}
CATEGORY = {"type": "string", "description": "Category name, up to 40 characters. Use general unless specified."}
FILTERS = {
    "status": {"type": "string", "enum": ["pending", "completed", "all"]},
    "priority": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
    "search": {"type": ["string", "null"], "description": "Literal part of the title, or null."},
    "category": {"type": ["string", "null"], "description": "Category to filter by, or null for all categories."},
}

TOOLS = [
    tool("add_task", "Save a new task. Default to medium priority and no deadline if unspecified.",
         {"title": TITLE, "deadline": DEADLINE, "priority": PRIORITY, "category": CATEGORY}),
    tool("list_tasks", "Find tasks and their IDs. Default to pending tasks. Null filters mean no filter.", FILTERS),
    tool("update_task", "Change selected fields. Use null for unchanged title, priority, and category. Set change_deadline true to change or remove a deadline.", {
        "task_id": TASK_ID,
        "changes": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "title": {"type": ["string", "null"]},
                "category": {"type": ["string", "null"]},
                "priority": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                "deadline": DEADLINE,
                "change_deadline": {"type": "boolean", "description": "True to set or remove deadline; false to leave it alone."},
            },
            "required": ["title", "priority", "deadline", "change_deadline", "category"],
        },
    }),
    tool("complete_task", "Mark one existing task completed. Repeating this is safe.", {"task_id": TASK_ID}),
    tool("search_tasks", "Search task titles, optionally filtering status, priority, and category.", {
        **FILTERS, "search": {"type": "string", "description": "Text to find in task titles."},
    }),
    tool("list_categories", "Show categories with pending and completed task counts.", {}),
    tool("plan_day", "Suggest a limited daily plan. Overdue tasks come first, then tasks due that day, then other pending work. Does not change tasks.", {
        "day": {"type": ["string", "null"], "description": "YYYY-MM-DD, or null for today."},
        "limit": {"type": "integer", "description": "Maximum tasks, from 1 to 20. Default 5."},
        "category": FILTERS["category"],
    }),
    tool("undo_last_action", "Undo the most recent saved add, update, or completion. One action at a time, not the entire user message.", {}),
    tool("export_tasks", "Export matching saved tasks to a new CSV or JSON file. Returns the real file path. Default to all statuses.", {
        **FILTERS, "file_format": {"type": "string", "enum": ["csv", "json"]},
    }),
]


def validate(value, schema):
    kinds = schema["type"]
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {"null": value is None, "string": isinstance(value, str),
               "integer": type(value) is int, "boolean": type(value) is bool,
               "object": isinstance(value, dict)}
    if not any(matches[kind] for kind in kinds):
        raise ValueError("Tool argument has the wrong type.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Tool argument has an unsupported value.")
    if isinstance(value, dict):
        missing = set(schema["required"]) - set(value)
        unknown = set(value) - set(schema["properties"])
        if missing or unknown:
            raise ValueError(f"Missing fields: {', '.join(sorted(missing)) or 'none'}. "
                             f"Unknown fields: {', '.join(sorted(unknown)) or 'none'}.")
        for key, item in value.items():
            validate(item, schema["properties"][key])


class TaskTools:
    def __init__(self, store, timezone="Asia/Kolkata"):
        self.store = store
        self.timezone = ZoneInfo(timezone)

    def execute(self, name, raw_arguments):
        try:
            definition = next((item for item in TOOLS if item["name"] == name), None)
            if definition is None:
                raise ValueError("Unknown tool.")
            arguments = json.loads(raw_arguments)
            # Local models sometimes leave out optional filters. These defaults
            # match our Python functions; required IDs and titles stay required.
            if isinstance(arguments, dict):
                defaults = {
                    "add_task": {"deadline": None, "priority": "medium", "category": "general"},
                    "list_tasks": {"status": "pending", "priority": None, "search": None, "category": None},
                    "search_tasks": {"status": "pending", "priority": None, "category": None},
                    "plan_day": {"day": None, "limit": 5, "category": None},
                    "export_tasks": {"status": "all", "priority": None, "search": None, "category": None},
                }.get(name, {})
                arguments = {**defaults, **arguments}
                if name == "update_task" and isinstance(arguments.get("changes"), dict):
                    arguments["changes"] = {"category": None, **arguments["changes"]}
            validate(arguments, definition["parameters"])
            if name == "update_task":
                requested = arguments["changes"]
                changes = {key: requested[key] for key in ("title", "priority", "category") if requested[key] is not None}
                if requested["change_deadline"]:
                    changes["deadline"] = requested["deadline"]
                elif requested["deadline"] is not None:
                    raise ValueError("Set change_deadline to true when providing a deadline.")
                result = self.store.update_task(arguments["task_id"], **changes)
            elif name == "plan_day":
                arguments["day"] = arguments["day"] or datetime.now(self.timezone).date().isoformat()
                result = self.store.plan_day(**arguments)
            elif name == "export_tasks":
                file_format = arguments.pop("file_format")
                tasks = self.store.list_tasks(**arguments)
                path = self.store.path.parent / "exports" / f"tasks-{uuid4().hex}.{file_format}"
                result = export_tasks(tasks, path, file_format)
            else:
                functions = {"add_task": self.store.add_task, "list_tasks": self.store.list_tasks,
                             "complete_task": self.store.complete_task, "search_tasks": self.store.list_tasks,
                             "list_categories": self.store.list_categories,
                             "undo_last_action": self.store.undo_last_action}
                result = functions[name](**arguments)
            return {"ok": True, "result": result}
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": str(error)}
        except OSError:
            return {"ok": False, "error": "Could not write the export. Check folder permissions and disk space."}
