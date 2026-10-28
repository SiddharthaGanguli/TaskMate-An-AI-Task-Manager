"""A small terminal interface, with a few local commands for checking saved data."""

import argparse
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient, OllamaError
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools
from task_manager.exporting import export_tasks
from task_manager.formatting import format_result, task_lines


HELP = """Try: Add my Python assignment for tomorrow, high priority.
Try: Show pending tasks, then complete task 1.
Local commands: /tasks, /all, /search TEXT, /category NAME, /categories,
/plan [YYYY-MM-DD], /undo, /export csv|json, /reset, /help, /quit
/reset clears this conversation. Your saved tasks stay in the database."""


def show_tasks(tasks):
    print("\n".join(task_lines(tasks)))


def local_command(message, tools):
    command, _, text = message.partition(" ")
    text = text.strip()
    if command in ("/undo", "/categories") and text:
        print(f"Use {command} without extra arguments.")
        return True
    if command == "/search":
        name, arguments = "search_tasks", {"search": text, "status": "all"}
    elif command == "/category":
        name, arguments = "list_tasks", {"category": text}
    elif command == "/categories":
        name, arguments = "list_categories", {}
    elif command == "/plan":
        name, arguments = "plan_day", {"day": text or None}
    elif command == "/undo":
        name, arguments = "undo_last_action", {}
    elif command == "/export":
        name, arguments = "export_tasks", {"file_format": text}
    else:
        return False
    result = tools.execute(name, json.dumps(arguments))
    print(format_result(name, result["result"]) if result["ok"] else result["error"])
    return True


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Manage tasks with natural language.")
    parser.add_argument("--list", action="store_true", help="List saved tasks without an API key.")
    parser.add_argument("--all", action="store_true", help="Include completed tasks with --list.")
    parser.add_argument("--db", default=os.getenv("TASK_DB_PATH", "data/tasks.db"))
    parser.add_argument("--provider", choices=("openai", "ollama"),
                        default=os.getenv("LLM_PROVIDER", "openai"), help="Choose cloud or local inference.")
    parser.add_argument("--model", help="Override the selected provider's model.")
    parser.add_argument("--search", help="Find a literal part of a task title.")
    parser.add_argument("--category", help="Filter by category.")
    parser.add_argument("--priority", choices=("low", "medium", "high"))
    parser.add_argument("--status", choices=("pending", "completed", "all"))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--plan", nargs="?", const="today", metavar="DATE", help="Suggest a daily plan without an API key.")
    actions.add_argument("--undo", action="store_true", help="Undo one saved task change.")
    actions.add_argument("--categories", action="store_true", help="Show category counts.")
    actions.add_argument("--export", metavar="PATH", help="Export matching tasks to a new .csv or .json file.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum tasks in a plan (1-20).")
    args = parser.parse_args()
    try:
        store = TaskStore(Path(args.db))
        timezone = os.getenv("TASK_TIMEZONE", "Asia/Kolkata")
        tools = TaskTools(store, timezone)
        filters = {"status": "all" if args.all else args.status or "pending", "priority": args.priority,
                   "search": args.search, "category": args.category}
        if args.undo:
            print(format_result("undo_last_action", store.undo_last_action()))
            return
        if args.categories:
            print(format_result("list_categories", store.list_categories()))
            return
        if args.plan:
            day = datetime.now(ZoneInfo(timezone)).date().isoformat() if args.plan == "today" else args.plan
            print(format_result("plan_day", store.plan_day(day, args.limit, args.category)))
            return
        if args.export:
            print(format_result("export_tasks", export_tasks(store.list_tasks(**filters), args.export)))
            return
        if args.list or args.all or args.search is not None or args.category is not None or args.priority or args.status:
            show_tasks(store.list_tasks(**filters))
            return
        if args.provider not in ("openai", "ollama"):
            print("LLM_PROVIDER must be openai or ollama.")
            raise SystemExit(1)
        if args.provider == "ollama":
            try:
                timeout = float(os.getenv("OLLAMA_TIMEOUT", "180"))
                if not 0 < timeout < float("inf"):
                    raise ValueError
            except ValueError:
                print("OLLAMA_TIMEOUT must be a positive number of seconds.")
                raise SystemExit(1)
            client_context = OllamaClient(os.getenv("OLLAMA_HOST", "http://localhost:11434"), timeout)
            model = args.model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        else:
            key = os.getenv("OPENAI_API_KEY", "").strip()
            if not key or key == "put_your_api_key_here":
                print("Add your OPENAI_API_KEY to .env, or use --provider ollama for a local model.")
                raise SystemExit(1)
            client_context = OpenAI(api_key=key, timeout=30, max_retries=0)
            model = args.model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        with client_context as client:
            agent = TaskAgent(client, tools, model, timezone)
            print(f"TaskMate | {args.provider} | {model}\n" + HELP)
            while True:
                try:
                    message = input("\nYou: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nGoodbye.")
                    return
                if not message:
                    continue
                if message.lower() in ("/quit", "exit", "quit"):
                    print("Goodbye.")
                    return
                if message == "/help":
                    print(HELP)
                elif message in ("/tasks", "/all"):
                    show_tasks(store.list_tasks(status="all" if message == "/all" else "pending"))
                elif message == "/reset":
                    agent.clear_history()
                    print("Conversation cleared.")
                elif message.startswith("/") and local_command(message, tools):
                    pass
                else:
                    try:
                        print("Agent: " + agent.run(message))
                    except OllamaError as error:
                        print(f"{error} Use /tasks before retrying; changes may already be saved.")
                    except APIConnectionError:
                        print("Could not reach the API. Check your connection. Use /tasks before retrying; changes may already be saved.")
                    except APIStatusError as error:
                        print(f"API request failed (HTTP {error.status_code}). Check your key, model access, and API billing. "
                              "Use /tasks before retrying; changes may already be saved.")
    except FileExistsError:
        print("That export file already exists. Choose a new filename.")
        raise SystemExit(1)
    except ValueError as error:
        print(str(error))
        raise SystemExit(1)
    except ZoneInfoNotFoundError:
        print("TASK_TIMEZONE is invalid. Use a name such as Asia/Kolkata.")
        raise SystemExit(1)
    except (sqlite3.Error, OSError):
        print("Could not open the task database. Check the path, permissions, and disk space.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
