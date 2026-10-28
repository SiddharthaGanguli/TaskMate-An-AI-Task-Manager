"""A small terminal interface, with a few local commands for checking saved data."""

import argparse
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

from task_manager.agent import TaskAgent
from task_manager.ollama_client import OllamaClient, OllamaError
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
    parser.add_argument("--provider", choices=("openai", "ollama"),
                        default=os.getenv("LLM_PROVIDER", "openai"), help="Choose cloud or local inference.")
    parser.add_argument("--model", help="Override the selected provider's model.")
    args = parser.parse_args()
    try:
        store = TaskStore(Path(args.db))
        if args.list:
            show_tasks(store.list_tasks(status="all" if args.all else "pending"))
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
            agent = TaskAgent(client, TaskTools(store), model,
                              os.getenv("TASK_TIMEZONE", "Asia/Kolkata"))
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
    except ZoneInfoNotFoundError:
        print("TASK_TIMEZONE is invalid. Use a name such as Asia/Kolkata.")
        raise SystemExit(1)
    except (sqlite3.Error, OSError):
        print("Could not open the task database. Check the path, permissions, and disk space.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
