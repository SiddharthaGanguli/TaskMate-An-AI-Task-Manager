"""A small terminal interface, with a few local commands for checking saved data."""

import argparse
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

from task_manager.agent import TaskAgent
from task_manager.storage import TaskStore
from task_manager.tools import TaskTools


HELP = """Try: Add my Python assignment for tomorrow, high priority.
Try: Show pending tasks, then complete task 1.
Local commands: /tasks, /all, /reset, /help, /quit
/reset clears this conversation. Your saved tasks stay in the database."""


def show_tasks(tasks):
    if not tasks:
        print("No tasks found.")
    for task in tasks:
        print(f"#{task['id']} | {task['title']} | {task['deadline'] or 'No deadline'} | "
              f"{task['priority']} | {task['status']}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Manage tasks with natural language.")
    parser.add_argument("--list", action="store_true", help="List saved tasks without an API key.")
    parser.add_argument("--all", action="store_true", help="Include completed tasks with --list.")
    parser.add_argument("--db", default=os.getenv("TASK_DB_PATH", "data/tasks.db"))
    args = parser.parse_args()
    try:
        store = TaskStore(Path(args.db))
        if args.list:
            show_tasks(store.list_tasks(status="all" if args.all else "pending"))
            return
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key or key == "put_your_api_key_here":
            print("Add your OPENAI_API_KEY to .env first. See .env.example.")
            raise SystemExit(1)
        client_context = OpenAI(api_key=key, timeout=30, max_retries=0)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        with client_context as client:
            agent = TaskAgent(client, TaskTools(store), model,
                              os.getenv("TASK_TIMEZONE", "Asia/Kolkata"))
            print(f"TaskMate | {model}\n" + HELP)
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
                else:
                    try:
                        print("Agent: " + agent.run(message))
                    except APIConnectionError:
                        print("Could not reach the API. Check your connection. Use /tasks before retrying; changes may already be saved.")
                    except APIStatusError as error:
                        print(f"API request failed (HTTP {error.status_code}). Check your key, model access, and API billing. "
                              "Use /tasks before retrying; changes may already be saved.")
    except ZoneInfoNotFoundError:
        print("TASK_TIMEZONE is invalid. Use a name such as Asia/Kolkata.")
        raise SystemExit(1)
    except (sqlite3.Error, OSError):
        print("Could not open the task database. Check the path, permissions, and disk space.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
