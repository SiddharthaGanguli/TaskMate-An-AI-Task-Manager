"""Describe the four tools and check every request before running it."""

import json


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

TOOLS = [
    tool("add_task", "Save a new task. Default to medium priority and no deadline if unspecified.",
         {"title": TITLE, "deadline": DEADLINE, "priority": PRIORITY}),
    tool("list_tasks", "Find tasks and their IDs. Default to pending tasks. Null filters mean no filter.", {
        "status": {"type": "string", "enum": ["pending", "completed", "all"]},
        "priority": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
        "search": {"type": ["string", "null"], "description": "Literal part of the title, or null."},
    }),
    tool("update_task", "Change selected fields. Omitted fields stay unchanged. A null deadline removes it.", {
        "task_id": TASK_ID,
        "changes": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "title": {"type": ["string", "null"]},
                "priority": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                "deadline": DEADLINE,
                "change_deadline": {"type": "boolean", "description": "True to set or remove deadline; false to leave it alone."},
            },
            "required": ["title", "priority", "deadline", "change_deadline"],
        },
    }),
    tool("complete_task", "Mark one existing task completed. Repeating this is safe.", {"task_id": TASK_ID}),
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
    def __init__(self, store):
        self.store = store

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
                    "add_task": {"deadline": None, "priority": "medium"},
                    "list_tasks": {"status": "pending", "priority": None, "search": None},
                }.get(name, {})
                arguments = {**defaults, **arguments}
            validate(arguments, definition["parameters"])
            if name == "update_task":
                requested = arguments["changes"]
                changes = {key: requested[key] for key in ("title", "priority") if requested[key] is not None}
                if requested["change_deadline"]:
                    changes["deadline"] = requested["deadline"]
                elif requested["deadline"] is not None:
                    raise ValueError("Set change_deadline to true when providing a deadline.")
                result = self.store.update_task(arguments["task_id"], **changes)
            else:
                functions = {"add_task": self.store.add_task, "list_tasks": self.store.list_tasks,
                             "complete_task": self.store.complete_task}
                result = functions[name](**arguments)
            return {"ok": True, "result": result}
        except (ValueError, TypeError) as error:
            return {"ok": False, "error": str(error)}
