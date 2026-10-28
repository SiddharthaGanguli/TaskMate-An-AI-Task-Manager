"""Keep task lists and tool confirmations consistent in the terminal."""


def task_lines(tasks):
    return [f"#{task['id']} | {task['title']} | {task['deadline'] or 'No deadline'} | "
            f"{task['priority']} | {task['status']} | {task['category']}" for task in tasks] or ["No tasks found."]


def task_count(count):
    return f"{count} task{'s' if count != 1 else ''}"


def format_result(name, result):
    if name in ("list_tasks", "search_tasks"):
        return "\n".join(task_lines(result))
    if name == "add_task":
        if not result["created"]:
            return f"Task #{result['id']} already exists. Kept its saved priority and details."
        return f"Saved task #{result['id']}: {result['title']}."
    if name in ("update_task", "complete_task"):
        return "\n".join(task_lines([result]))
    if name == "undo_last_action":
        return f"Undid {result['action']} for task #{result['task_id']}."
    if name == "export_tasks":
        return f"Exported {task_count(result['count'])} as {result['format'].upper()}: {result['path']}"
    if name == "list_categories":
        return "\n".join(f"{row['category']}: {row['pending']} pending, {row['completed']} completed" for row in result) or "No categories yet."
    if name == "plan_day":
        lines = [f"Suggested plan for {result['day']} ({task_count(len(result['tasks']))}):"]
        for task in result["tasks"]:
            lines.extend(task_lines([task]))
            lines.append(f"  Reason: {task['plan_reason']}")
        if not result["tasks"]:
            lines.append("No pending tasks to plan.")
        lines.append(f"Other pending tasks: {result['remaining']}. No deadlines were changed.")
        return "\n".join(lines)
    raise ValueError("Unknown tool result.")
