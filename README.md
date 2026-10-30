# TaskMate — An AI Task Manager

A personal task app with a terminal interface, web dashboard, and Chrome/Edge extension. Python runs the tools, SQLite saves the tasks, and an LLM decides which tool to call. There is no agent framework.

For example:

```text
You: Add a task to finish my AI project by Friday, high priority, and show my pending tasks.
```

The agent calls `add_task()`, receives the saved task, calls `list_tasks()`, and explains the result. It can ask a follow-up question when a request is unclear.

TaskMate also supports duplicate detection, categories, daily planning, undo, title search, and CSV or JSON exports. These work with OpenAI and local models. The local commands and command-line options below can run without making a model request.

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

## Web dashboard

The dashboard is an extension of the same Python app. It uses your existing task database, including categories, duplicate detection, planning, undo, and exports. There is no separate cloud database or frontend build step.

Install or update the Python package, then start the server:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m task_manager.web
```

Open **http://127.0.0.1:8765** in Chrome or Edge. The installed `taskmate-web` command starts the same server.

| Dashboard area | What you can do |
| --- | --- |
| Overview | See real pending, due-today, high-priority, and completed counts |
| Task list | Create, edit, complete, search, and filter tasks |
| Navigation | Open all tasks, today, upcoming, completed, or a category |
| Daily focus | Choose a date and task limit, then build a plan |
| Undo | Reverse one saved task change |
| Exports | Download filtered CSV or JSON files |
| Assistant | Chat with the same tool-calling agent; export requests include download links |
| Connection settings | Choose OpenAI or Ollama and a model for this browser session |

Manual task actions, planning, search, undo, and exports do not need a model or an API key. Chat uses the selected provider and your server-side `.env` settings. OpenAI keys are never sent to the browser. Changing models clears conversation memory, while tasks stay saved.

The interface is an AI agent workspace with a dark graphite palette, violet actions, and a large central conversation. Prompt cards help you start a request; the model selector stays visible above the chat. Saved tasks and daily plans sit in a side panel so results stay alongside the conversation. Use **Ctrl+K** or **Cmd+K** to focus search. **Enter** sends a chat message; **Shift+Enter** adds a new line.

### See the agent at work

The Agent activity panel shows real tool names, execution status, measured duration, arguments, and result summaries. It refreshes while a chat request is running. Expand a tool entry to inspect its arguments and outcome. Each assistant message records how many tool calls succeeded, and exports remain downloadable from chat.

The activity panel starts empty and records observable execution rather than model reasoning. A model request can complete without calling tools. Rejected tool arguments are shown as errors; a model failure leaves any successful tool actions visible so you can check your saved tasks before retrying. New conversation clears chat and activity, while saved tasks stay in SQLite.

The server reads `TASK_DB_PATH` and `TASK_TIMEZONE` from `.env`. To use another database or port:

```powershell
.\.venv\Scripts\python.exe -m task_manager.web --db data/my-tasks.db --port 8766
```

Conversation memory and model choices are temporary, separated by browser session, and cleared when the server restarts. Tasks and undo history remain in SQLite. Tabs sharing the same browser cookies share a conversation; overlapping chat requests are rejected while a message is being processed.

This is a single-user local server bound to `127.0.0.1`. It has no public login or hosted service. Mutations require a server-issued request token, foreign web origins are rejected, and task text is rendered as text rather than HTML. The extension is allowed to call the local API with its host permission and request token.

## Chrome and Edge extension

The **Manifest V3** companion is in [browser-extension](browser-extension). It provides a compact workspace in the browser toolbar:

- Add a task with a deadline, priority, and category.
- Search pending tasks and see the next five in priority order.
- Complete tasks or undo the last saved change.
- See real pending, due-today, and completed counts.
- Open the full dashboard in one click.
- Change the local server address and recover from an offline connection.

Start the TaskMate web server first. Then install the extension locally:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the project's `browser-extension` folder.
4. Pin TaskMate to the toolbar, then click its icon.

If you changed the server port, open the popup's connection settings and enter the matching address, such as `http://127.0.0.1:8766`.

The extension requests local storage and access to `localhost` / `127.0.0.1` only. It does not read page contents, browsing history, or API keys. Storage saves only the chosen server address. It needs the local server to be running and does not start Python or Ollama itself.

To make an unpackable ZIP:

```powershell
.\.venv\Scripts\python.exe scripts/package_extension.py
```

This writes `dist/taskmate-extension.zip`. Extract it, then load the extracted folder using the steps above. This project provides an unpacked extension; it is not a Chrome Web Store listing.

### Web and extension verification

The current Python suite passes **48 tests**, including the web API and extension resource checks. Tests cover real SQLite changes, request tokens, origin checks, duplicate detection, filters, planning, exports and downloads, isolated conversations, model outages, and overlapping chat requests.

Two additional **browserless DOM integration tests** run the actual dashboard and popup JavaScript against a disposable Python HTTP server. They cover create/edit/complete/undo, duplicate feedback, filters, plans, downloads, chat, model settings, popup quick add and search, connection settings, and offline recovery. A simulated model failure verifies that partially saved tasks still refresh and the error remains visible. The model is scripted in these tests, and extension storage/tab APIs are mocked.

Node.js is optional and only needed for these interface tests:

```powershell
npm ci
npm run test:web
```

These checks do not measure visual layout or install an extension into Chrome. Windows browser automation could not reliably verify the current URL during this session, so automated visual inspection and a real unpacked-install check remain unverified. The Python API, packaged resources, and browserless interactions passed. Your personal database is not used by the test suite.

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

## Duplicate detection

Adding the same pending task again returns its existing ID instead of saving a second copy. TaskMate compares the title, deadline, and category. Titles ignore letter case and repeated whitespace. Categories also ignore case and extra whitespace.

For example, `Study  algebra` and `study algebra` match when their deadline and category match. The existing priority stays unchanged, even if the repeated request asks for a different priority. Use an update to change it. Different deadlines or categories are separate tasks, and a completed task does not block a new pending task.

The check and save share one database transaction, including when two requests arrive together. Updating a pending task into a duplicate is rejected. Similar meanings with different wording are not automatically merged. Existing duplicates from an older version are preserved.

## Categories

Categories are short names such as `study`, `work`, `health`, and `personal`. You can create a category simply by adding or updating a task with that name. Names are stored in lowercase, with a maximum of 40 characters. New and migrated tasks use `general` by default.

```text
Add Study linear algebra, high priority, due tomorrow, in category study.
Move task 1 to category work.
Show my pending tasks in category study.
Show my categories with pending and completed counts.
```

Local commands:

```text
/category study
/categories
```

## Daily planning

```text
Plan today with at most 3 tasks.
Plan tomorrow with 5 tasks from category study.
```

The planner selects pending tasks in this order: overdue tasks, tasks due on the chosen date, then other pending work. Within each group, high priority comes first, then medium and low; earlier deadlines break ties. Tasks without a deadline follow dated tasks of the same priority. A plan includes a reason for each choice and the number of tasks left out.

The default is five tasks, with a limit of 1 to 20. This is a suggested task list, not a timed calendar or a workload estimate. It does not change your deadlines or mark anything completed. Planning another date evaluates overdue and due tasks relative to that date.

```text
/plan
/plan 2026-10-29
```

## Undo

```text
Undo my last change.
```

Or use `/undo` to undo directly without asking the model. Each undo reverses **one saved add, update, or completion**, across all categories. An add is removed; an update or completion restores the previous saved values. A message that adds ten tasks creates ten separate undo steps.

History is stored in SQLite, so undo works after restarting the app. Searches, plans, exports, duplicate adds, and changes that do nothing do not add undo steps. Undo does not remove exported files and has no redo command. Old tasks remain editable, but changes made before this version had no history to restore. If a task was edited outside TaskMate, undo stops rather than overwriting that edit.

## Search and export

Search matches literal text in task titles, ignoring case. You can combine it with status, priority, and category filters. The `/search` command searches both pending and completed tasks.

```text
Find all tasks containing algebra in category study.
Export my pending high-priority study tasks as CSV.
Export all my tasks as JSON.
```

```text
/search algebra
/export csv
/export json
```

The export tool and `/export` include all statuses by default, and create a new file inside an `exports` folder beside your database. They return the real path and number of exported tasks. Natural-language requests can apply filters. Files are never overwritten. Exports do not change tasks or undo history.

CSV includes a header even when there are no matches. Titles that could be interpreted as spreadsheet formulas are prefixed with an apostrophe in CSV. JSON preserves the original saved text. Both formats include IDs, titles, dates, priorities, status, category, and timestamps.

These options work without an API key or Ollama:

```powershell
.\.venv\Scripts\python.exe -m task_manager --list --all --search algebra --category study
.\.venv\Scripts\python.exe -m task_manager --categories
.\.venv\Scripts\python.exe -m task_manager --plan 2026-10-29 --limit 3 --category study
.\.venv\Scripts\python.exe -m task_manager --export exports/study.csv --category study --priority high
.\.venv\Scripts\python.exe -m task_manager --export exports/all-tasks.json --all
.\.venv\Scripts\python.exe -m task_manager --undo
```

For command-line searches and exports, status defaults to pending. Add `--all` or `--status completed` to change it. Export format comes from the `.csv` or `.json` extension. Choose a new filename for another export.

## Existing databases

The app adds the category column and undo history table when it opens an older database. Task IDs, titles, dates, priorities, statuses, and timestamps are preserved. Existing tasks receive category `general`. Back up your database before upgrading if you want a separate copy. The feature tests use temporary databases and never change your personal tasks.

### Feature test results

The updated automated suite passes **48 tests**. It covers duplicate retries arriving together, Unicode search, combined category filters, planning order, undo after restart, external-edit protection, old-database migration, CSV and JSON contents, offline terminal options, one complete workflow using all nine tools, and the web API.

A live check with **Ollama and `llama3.1:8b`** also passed on 28 October 2026, using a temporary database:

| Request | Verified result |
| --- | --- |
| Add linear algebra in `study`, then repeat the request | One task saved; repeat returned the existing ID |
| Change task 1 to `work` and low priority | Both fields changed in SQLite |
| Undo the change | Category `study` and high priority restored |
| Plan the day with up to three study tasks | Planner tool ran and returned the pending study task |
| Search for `algebra` in `study` | Matching saved task returned |
| Export study tasks as JSON | New file created; its contents matched the saved task |
| Show category counts | `study: 1 pending, 0 completed` |

CSV round-trips, empty exports, protection against overwriting files, and undoing adds and completions are covered by the automated tests. The live check above used JSON export and undo of an update. Natural language behavior can vary between models.

## Folder structure

```text
ai-agent/
├── task_manager/
│   ├── __init__.py
│   ├── __main__.py     # Starts the terminal app
│   ├── cli.py          # Input, local commands, and readable errors
│   ├── agent.py        # Model requests and the tool execution loop
│   ├── ollama_client.py # Adapts the local model API to the agent
│   ├── exporting.py    # Writes CSV and JSON files
│   ├── formatting.py   # Displays database results consistently
│   ├── web.py          # Local dashboard and extension API
│   ├── web_assets/     # Buildless HTML, CSS, JavaScript, and icons
│   ├── tools.py        # Tool schemas, validation, and dispatch
│   └── storage.py      # SQLite queries and task rules
├── tests/
│   ├── __init__.py
│   ├── test_agent.py
│   ├── test_api_contract.py
│   ├── test_features.py
│   ├── test_full_workflow.py
│   ├── test_web.py
│   ├── web/            # Browserless interface tests and their server fixture
│   ├── test_ollama.py
│   └── test_storage.py
├── .env.example
├── browser-extension/  # Chrome/Edge popup, manifest, and icons
├── scripts/            # Live model check and extension packaging
├── package.json        # Optional interface test dependencies
├── .gitignore
├── pyproject.toml
└── README.md
```

The app creates `data/tasks.db` on first use. Relative paths are based on the folder where you start the app. Back up the database file while the app is closed if you want a copy of your tasks.

## How the agent works

1. The terminal passes your sentence to `TaskAgent`.
2. The agent sends the sentence, conversation history, today's date, and the available tool definitions to the model.
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
| `search_tasks()` | Search titles with optional filters |
| `list_categories()` | Count pending and completed tasks by category |
| `plan_day()` | Suggest a limited daily task list without changing it |
| `undo_last_action()` | Reverse one saved task change |
| `export_tasks()` | Write matching tasks to a new CSV or JSON file |

For updates, `change_deadline` separates "leave the deadline alone" from "remove the deadline." The tool schema requires every field, so unchanged title, priority, and category fields use `null`.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

## Complete workflow test: all features together

The test is in [tests/test_full_workflow.py](tests/test_full_workflow.py), named `test_all_features_in_one_session`. It runs a complete session through `TaskAgent` and all nine tools, using a temporary SQLite database and real CSV and JSON files.

Only the model replies are scripted. The test does not need OpenAI, Ollama, an API key, or downloaded model weights. It verifies tool execution and saved results; it does not measure a live model's ability to understand these sentences. The live model results are documented separately below.

Run just this workflow:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_full_workflow -v
```

Sample tasks:

| ID | Title | Deadline | Priority | Category |
| --- | --- | --- | --- | --- |
| 1 | Study linear algebra | 2026-10-29 | high | study |
| 2 | Go to the gym at 8 PM | 2026-10-28 | medium | health |
| 3 | Submit AI project report | 2026-10-27 | high | work |

The planner uses the fixed date **28 October 2026**, so this test stays repeatable on later dates.

| Step | Action | Verified result |
| --- | --- | --- |
| 1 | Add all three tasks in one request | Three records saved with the correct fields |
| 2 | Repeat algebra with different case, spacing, and low priority | Existing ID returned; no duplicate; saved high priority preserved |
| 3 | Rename algebra and change its deadline, priority, and category | New title, date, low priority, and math category saved |
| 4 | Undo the update | All original fields restored |
| 5 | Add a temporary task, then undo its add | Temporary task removed; original three records unchanged |
| 6 | Complete gym, undo completion, then complete it again | Status changes saved and reversed correctly |
| 7 | Plan two tasks for 2026-10-28 | Overdue report first, then algebra; completed gym excluded |
| 8 | Search for ALGEBRA with pending, high priority, and study filters | Only task 1 returned; search ignores case |
| 9 | List categories | health: 1 completed; study: 1 pending; work: 1 pending |
| 10 | Export all tasks as CSV | Three exported rows, including completed gym, in priority order |
| 11 | Export study tasks as JSON | One record matching the saved algebra task exactly |
| 12 | Check records after planning, search, counts, and exports | No saved task data changed |
| 13 | Reopen SQLite and start a new agent conversation | The same three records returned and displayed |
| 14 | Undo after restarting | Last gym completion reversed; reads and exports did not consume undo history |
| 15 | Check the exported files after undo | Both files still exist; undo only changed the task database |

Final database state after the last undo:

| ID | Title | Deadline | Priority | Status | Category |
| --- | --- | --- | --- | --- | --- |
| 3 | Submit AI project report | 2026-10-27 | high | pending | work |
| 1 | Study linear algebra | 2026-10-29 | high | pending | study |
| 2 | Go to the gym at 8 PM | 2026-10-28 | medium | pending | health |

The CSV captured gym as completed when the export was made. Undoing its completion later does not rewrite that exported snapshot.

**Verified result on 28 October 2026:** the complete workflow passed, and the full automated suite passed **34 tests with 0 failures**. All files and database records from this workflow are created in a temporary folder and cleaned up afterward. Your personal task database is untouched.

Tests use temporary databases, a fake API client, and the real SDK with a local HTTP stub. They check persistence, filters, ordering, invalid input, safe SQL handling, deadline removal, repeated completion, multi-step calls, API failure recovery, SDK request serialization, and the tool-call limit. They do not spend API credits or prove how a live model will interpret every sentence.

Ollama tests also cover local multi-step calls, follow-up history, model errors, an unreachable server, and starting local mode without an OpenAI key. These use HTTP stubs, so the automated suite does not require Ollama or a downloaded model.

To check a real downloaded model with ten sample tasks:

```powershell
.\.venv\Scripts\python.exe scripts/check_local_model.py --model qwen3:4b
```

This uses a temporary database and does not change your saved tasks. It checks all ten titles, dates, priorities, pending status, ordering, actual list calls, a misspelled follow-up, duplicates, and persistence. Relative deadlines use the current date in Asia/Kolkata. A failed check exits with an error rather than claiming the run passed.

## Verified sample run

Tested on **28 October 2026**, using **Ollama with `llama3.1:8b`** and the **Asia/Kolkata** timezone. The live test used an empty temporary SQLite database. Your personal task database was not changed.

Input:

```text
Add these tasks: Study linear algebra, high priority, due 2026-10-29; Go to the gym at 8 PM, medium priority, due today; Play cricket match, medium priority, due 10 days from today; Finish Python assignment, high priority, due tomorrow; Review matrix multiplication, high priority, due 2026-10-30; Read 20 pages, low priority, due 2026-10-28; Submit AI project report, high priority, due 2026-11-02; Buy groceries, medium priority, due 2026-10-31; Organize study notes, low priority, due 2026-11-01; Practice Python tool calling, medium priority, due 2026-11-03; then show all pending tasks ordered by priority.
```

Final result, checked against the saved database records:

| ID | Task | Deadline | Priority | Status |
| --- | --- | --- | --- | --- |
| 1 | Study linear algebra | 2026-10-29 | high | pending |
| 4 | Finish Python assignment | 2026-10-29 | high | pending |
| 5 | Review matrix multiplication | 2026-10-30 | high | pending |
| 7 | Submit AI project report | 2026-11-02 | high | pending |
| 2 | Go to the gym at 8 PM | 2026-10-28 | medium | pending |
| 8 | Buy groceries | 2026-10-31 | medium | pending |
| 10 | Practice Python tool calling | 2026-11-03 | medium | pending |
| 3 | Play cricket match | 2026-11-07 | medium | pending |
| 6 | Read 20 pages | 2026-10-28 | low | pending |
| 9 | Organize study notes | 2026-11-01 | low | pending |

**Result: passed.** All ten titles, dates, priorities, and pending statuses matched the sample request. The database returned four high, four medium, and two low priority tasks in priority order. Within each priority, earlier deadlines come first. Ten successful `add_task` calls and one successful `list_tasks` call were recorded.

The follow-up `show me all tsks` made another successful `list_tasks` call and displayed the same ten records. No duplicate tasks were created. Reopening the database returned the same saved data. Task lists now print the database values directly, so a model's final summary cannot leave out records or change their IDs and order.

The gym's **8 PM** stays in its title; this project stores deadlines as dates and does not send timed reminders. On the test date, **today** became `2026-10-28`, **tomorrow** became `2026-10-29`, and **10 days from today** became `2026-11-07`.

The automated suite also passed: **19 tests, 0 failures**. These results describe this recorded run. Other models and later dates can produce different interpretations; the live-check script fails if its saved values do not match the expected sample data.

To repeat the recorded model check:

```powershell
ollama pull llama3.1:8b
.\.venv\Scripts\python.exe scripts/check_local_model.py --model llama3.1:8b
```

## Notes and troubleshooting

- Tasks persist after closing the app. Conversation history only lasts for the current session. Use `/reset` to start a new conversation or shorten a long one.
- This is a single-user local project with terminal, web, and browser extension interfaces. It has no public login, timed reminders, or third-party task integrations.
- In OpenAI mode, messages and tool results are sent to OpenAI. Requests set `store=False`; this does not override the provider's other data policies. In Ollama mode, messages go to `OLLAMA_HOST`. The database stays local in both modes.
- If an API request fails after a tool ran, the database change may already be saved. Use `/tasks` or `/all` before repeating a create request. Multiple actions are separate transactions, so a later failure does not undo earlier successful actions.
- Automatic API retries are disabled to keep failures visible. OpenAI requests have a 30-second timeout; Ollama defaults to 180 seconds. Each user turn allows up to 24 model rounds, enough for ten separate creates followed by a list.
- If a local model returns a complete JSON tool plan instead of native tool calls on its first reply, the adapter accepts only known tool names and runs the arguments through the same validation. It does not extract calls from ordinary prose or recover a plan after tool results. Missing optional creation values and list filters use the normal Python defaults.
- If the first reply does not contain usable tool calls, one retry uses Ollama's [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) to request explicit tool names and arguments. A conversational reply can return an empty plan. No database operation runs from anonymous `[tool_call]` blocks themselves. The repaired plan still goes through tool validation.
- HTTP 401 usually means the API key needs checking. For HTTP 429, check API billing and rate limits. Model access errors may need a different `OPENAI_MODEL` value.
- If the database cannot open, check `TASK_DB_PATH`, folder permissions, and disk space.

The code is written for this project with simple names and short comments around decisions. No plagiarism percentage or AI-detection result can be guaranteed; standard Python and API patterns will naturally resemble other projects.
