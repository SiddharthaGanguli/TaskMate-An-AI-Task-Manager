# TaskMate — An AI Task Manager

A terminal app that turns normal sentences into real task actions. Python runs the tools, SQLite saves the tasks, and an LLM decides which tool to call. There is no agent framework.

For example:

```text
You: Add a task to finish my AI project by Friday, high priority, and show my pending tasks.
```

The agent calls `add_task()`, receives the saved task, calls `list_tasks()`, and explains the result. It can ask a follow-up question when a request is unclear.

## Set up

You need Python 3.11 or newer. Choose OpenAI with an API key, or run a downloaded model locally with Ollama. A ChatGPT subscription does not provide this app with an API key.

Run these commands from the project folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

For OpenAI, open `.env` and replace `put_your_api_key_here` with your own key. Do not share this file. For local models, use the Ollama setup below instead.

```dotenv
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
TASK_TIMEZONE=Asia/Kolkata
TASK_DB_PATH=data/tasks.db
```

The model is configurable. Use a model your account can access that supports Responses API function calling. API requests can cost money.

Start the app:

```powershell
.\.venv\Scripts\python.exe -m task_manager
```

On macOS or Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`, and `cp .env.example .env` to copy the settings.

## Use a downloaded model with Ollama

Install [Ollama](https://ollama.com/download), open it, and download a model that supports tool calling:

```powershell
ollama pull qwen3:4b
```

Set these values in `.env`:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_TIMEOUT=180
```

Start the same app with `python -m task_manager` using your virtual environment. No OpenAI API key is needed in Ollama mode. You can also choose the provider and model for one run:

```powershell
ollama list
.\.venv\Scripts\python.exe -m task_manager --provider ollama --model qwen3:4b
```

Replace `qwen3:4b` with the exact name of another downloaded, tool-capable model. Downloading an arbitrary model file is not enough: the model must be available in Ollama and support tool calling. Models also have their own licenses.

[Qwen3 4B](https://ollama.com/library/qwen3:4b) is one starting option with tool support. Its listed download is about 2.5 GB; running it needs additional memory. Speed and accuracy depend on your computer and model. Smaller models may need clearer instructions.

Once Ollama and a local model are installed, local inference can run offline. Keep `OLLAMA_HOST` pointed at your own machine and use a local model rather than a cloud model tag. This app does not fall back to OpenAI if Ollama fails. Both providers use the same task database. To switch back, set `LLM_PROVIDER=openai`.

The adapter in `task_manager/ollama_client.py` uses Ollama's native [tool calling API](https://docs.ollama.com/capabilities/tool-calling). It sends tool results back for follow-up calls and keeps model thinking in conversation memory when returned. Python validates arguments for both providers. Ollama may return several calls in a reply; Python executes them one at a time in their returned order.

If Ollama cannot be reached, open its app or run `ollama serve` in another terminal. If the model is missing, use `ollama pull MODEL_NAME`. For slow first loads, increase `OLLAMA_TIMEOUT` in `.env`; it is a positive number of seconds.

## Things to try

```text
Add my Python assignment for tomorrow, high priority.
Show my high-priority pending tasks.
Move task 1 to next Monday.
Change task 1 to low priority.
Remove the deadline from task 1.
Rename task 1 to Finish the Python assignment.
Mark task 1 as completed.
Show my completed tasks.
Add Read chapter 3 and then show my pending tasks.
```

Task IDs come from SQLite. Replace `1` with an ID in your list. If you refer to a title, the agent should find its ID first and ask you to choose if several tasks match.

Dates are stored as `YYYY-MM-DD`. The model receives today's date in `TASK_TIMEZONE` on every request. For a weekday such as Friday, the app instructs it to use the next occurrence, including today. Unclear dates should lead to a question. Natural language interpretation still depends on the model, so review the saved date.

New tasks default to medium priority, pending status, and no deadline.

## Terminal commands

| Command | What it does |
| --- | --- |
| `/tasks` | Show pending tasks directly from SQLite |
| `/all` | Show pending and completed tasks |
| `/reset` | Clear conversation memory; keep saved tasks |
| `/help` | Show examples and commands |
| `/quit` | Close the app |

You can read tasks without an API key:

```powershell
.\.venv\Scripts\python.exe -m task_manager --list
.\.venv\Scripts\python.exe -m task_manager --list --all
.\.venv\Scripts\python.exe -m task_manager --list --db data/another.db
```

After installation, `task-agent` is also available inside the virtual environment.

## Folder structure

```text
ai-agent/
├── task_manager/
│   ├── __init__.py
│   ├── __main__.py     # Starts the terminal app
│   ├── cli.py          # Input, local commands, and readable errors
│   ├── agent.py        # Model requests and the tool execution loop
│   ├── ollama_client.py # Adapts the local model API to the agent
│   ├── tools.py        # Tool schemas, validation, and dispatch
│   └── storage.py      # SQLite queries and task rules
├── tests/
│   ├── __init__.py
│   ├── test_agent.py
│   ├── test_api_contract.py
│   ├── test_ollama.py
│   └── test_storage.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

The app creates `data/tasks.db` on first use. Relative paths are based on the folder where you start the app. Back up the database file while the app is closed if you want a copy of your tasks.

## How the agent works

1. The terminal passes your sentence to `TaskAgent`.
2. The agent sends the sentence, conversation history, today's date, and four tool definitions to the model.
3. The model returns a tool name and JSON arguments.
4. Python validates the name, fields, types, dates, and task values.
5. The selected storage function runs a parameterized SQLite query.
6. The agent sends the real result back to the model.
7. The model can call another tool or give its final reply.

OpenAI mode follows the [OpenAI function calling flow](https://developers.openai.com/api/docs/guides/function-calling). The app preserves response output items between calls and disables parallel tool calls in OpenAI mode. Ollama uses its native chat format through a small adapter; storage and validation stay the same.

| Tool | Purpose |
| --- | --- |
| `add_task()` | Save a task with a title, optional deadline, and priority |
| `list_tasks()` | Filter tasks by status, priority, or part of a title |
| `update_task()` | Change a title, deadline, or priority |
| `complete_task()` | Mark an existing task completed |

For updates, `change_deadline` separates "leave the deadline alone" from "remove the deadline." The tool schema requires every field, so unchanged title and priority fields use `null`.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

Tests use temporary databases, a fake API client, and the real SDK with a local HTTP stub. They check persistence, filters, ordering, invalid input, safe SQL handling, deadline removal, repeated completion, multi-step calls, API failure recovery, SDK request serialization, and the tool-call limit. They do not spend API credits or prove how a live model will interpret every sentence.

Ollama tests also cover local multi-step calls, follow-up history, model errors, an unreachable server, and starting local mode without an OpenAI key. These use HTTP stubs, so the automated suite does not require Ollama or a downloaded model.

## Notes and troubleshooting

- Tasks persist after closing the app. Conversation history only lasts for the current session. Use `/reset` to start a new conversation or shorten a long one.
- This is a single-user local project. It has no login, reminders, web interface, or integrations yet.
- In OpenAI mode, messages and tool results are sent to OpenAI. Requests set `store=False`; this does not override the provider's other data policies. In Ollama mode, messages go to `OLLAMA_HOST`. The database stays local in both modes.
- If an API request fails after a tool ran, the database change may already be saved. Use `/tasks` or `/all` before repeating a create request. Multiple actions are separate transactions, so a later failure does not undo earlier successful actions.
- Automatic API retries are disabled to keep failures visible. OpenAI requests have a 30-second timeout; Ollama defaults to 180 seconds. Each user turn allows up to 12 model rounds.
- HTTP 401 usually means the API key needs checking. For HTTP 429, check API billing and rate limits. Model access errors may need a different `OPENAI_MODEL` value.
- If the database cannot open, check `TASK_DB_PATH`, folder permissions, and disk space.

The code is written for this project with simple names and short comments around decisions. No plagiarism percentage or AI-detection result can be guaranteed; standard Python and API patterns will naturally resemble other projects.
