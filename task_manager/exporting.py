"""Write readable task exports without overwriting someone's existing file."""

import csv
import json
from pathlib import Path


FIELDS = ("id", "title", "deadline", "priority", "status", "category", "created_at", "updated_at")


def csv_value(value):
    # A task title should stay text when someone opens the CSV in a spreadsheet.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_tasks(tasks, path, file_format=None):
    path = Path(path).expanduser().resolve()
    file_format = file_format or path.suffix.lstrip(".").lower()
    if file_format not in ("csv", "json"):
        raise ValueError("Choose csv or json for the export format.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects us if another export uses the same name.
    with path.open("x", encoding="utf-8", newline="") as handle:
        if file_format == "json":
            json.dump(tasks, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        else:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({key: csv_value(task.get(key)) for key in FIELDS} for task in tasks)
    return {"path": str(path), "count": len(tasks), "format": file_format}
