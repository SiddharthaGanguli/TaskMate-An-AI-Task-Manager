const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const state = {
  data: null,
  view: "overview",
  status: "pending",
  category: null,
  priority: "",
  search: "",
  editId: null,
  planActive: false,
  chatBusy: false,
};
const colors = [
  "#b4bf9d",
  "#d8ac98",
  "#b6abc8",
  "#92b8b0",
  "#d2bd84",
  "#a8b9cc",
];
let toastTimer;
let refreshVersion = 0;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `/assets/icons.svg#${name}`);
  svg.append(use);
  return svg;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.toggle("error", error);
  $("#toast").hidden = false;
  toastTimer = setTimeout(
    () => {
      $("#toast").hidden = true;
    },
    error ? 7000 : 4000,
  );
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers:
      method === "GET"
        ? {}
        : {
            "Content-Type": "application/json",
            "X-TaskMate-Token": state.data?.token || "",
          },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).join(". ")
      : data.detail;
    throw new Error(
      detail || "Something went wrong. Please refresh and try again.",
    );
  }
  return data;
}

function readableDate(iso) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(`${iso}T12:00:00`));
}

function categoryColor(category) {
  let hash = 0;
  for (const letter of category)
    hash = (hash + letter.codePointAt(0)) % colors.length;
  return colors[hash];
}

function categoryDot(category) {
  const dot = node("span", "category-color");
  dot.style.setProperty("--category-color", categoryColor(category));
  return dot;
}

function visibleTasks() {
  return (state.data?.tasks || []).filter((task) => {
    if (state.status !== "all" && task.status !== state.status) return false;
    if (state.priority && task.priority !== state.priority) return false;
    if (state.category && task.category !== state.category) return false;
    if (
      state.search &&
      !task.title.toLocaleLowerCase().includes(state.search.toLocaleLowerCase())
    )
      return false;
    if (state.view === "today" && task.deadline !== state.data.today)
      return false;
    if (
      state.view === "upcoming" &&
      (!task.deadline || task.deadline <= state.data.today)
    )
      return false;
    return true;
  });
}

function renderCategories() {
  $("#category-nav").replaceChildren();
  $("#category-options").replaceChildren();
  const categories = state.data.categories;
  if (!categories.length)
    $("#category-nav").append(
      node(
        "p",
        "quiet sidebar-hint",
        "Add a task to start your first category.",
      ),
    );
  for (const category of categories) {
    const button = node("button", "category-button");
    button.classList.toggle("active", category.category === state.category);
    button.setAttribute(
      "aria-pressed",
      String(category.category === state.category),
    );
    button.append(
      categoryDot(category.category),
      node("span", "", category.category),
      node("span", "nav-count", category.pending),
    );
    button.addEventListener("click", () => {
      state.view = "tasks";
      state.status = "pending";
      state.category = category.category;
      renderView();
      renderCategories();
      closeMenu();
      if (state.planActive) action(null, () => buildPlan(false));
    });
    $("#category-nav").append(button);
    const option = node("option");
    option.value = category.category;
    $("#category-options").append(option);
  }
}

function renderTasks() {
  const tasks = visibleTasks();
  const list = $("#task-list");
  list.replaceChildren();
  $("#task-total").textContent = tasks.length;
  $("#task-footer-count").textContent =
    `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;
  $("#filter-notice").hidden = !(
    state.category ||
    state.search ||
    state.priority
  );
  $("#filter-label").textContent = [
    state.category && `Category: ${state.category}`,
    state.search && `Search: ${state.search}`,
    state.priority && `Priority: ${state.priority}`,
  ]
    .filter(Boolean)
    .join(" · ");
  for (const task of tasks) {
    const row = node(
      "article",
      `task-row ${task.status === "completed" ? "completed" : ""}`,
    );
    const checkbox = node(
      "button",
      `task-checkbox ${task.status === "completed" ? "done" : ""}`,
    );
    checkbox.setAttribute(
      "aria-label",
      task.status === "completed"
        ? `${task.title} is completed`
        : `Complete ${task.title}`,
    );
    checkbox.disabled = task.status === "completed";
    if (task.status === "completed") checkbox.append(icon("check"));
    checkbox.addEventListener("click", () =>
      action(checkbox, async () => {
        await api(`/api/tasks/${task.id}/complete`, "POST", {});
        await refresh();
        toast("A little progress. Task completed.");
      }),
    );
    const content = node("div", "task-content");
    const meta = node("div", "task-meta");
    const dateClass =
      task.deadline &&
      task.status === "pending" &&
      task.deadline < state.data.today
        ? "overdue"
        : task.deadline === state.data.today
          ? "today"
          : "";
    const date = node("span", `task-date ${dateClass}`);
    const dateText = !task.deadline
      ? "No deadline"
      : task.deadline === state.data.today
        ? "Today"
        : readableDate(task.deadline);
    date.append(icon("calendar"), document.createTextNode(dateText));
    if (task.deadline) date.title = task.deadline;
    const category = node("span", "task-category");
    category.append(
      categoryDot(task.category),
      document.createTextNode(task.category),
    );
    meta.append(date, category, node("span", "task-id", `#${task.id}`));
    content.append(node("div", "task-title", task.title), meta);
    const edit = node("button", "icon-button edit-task");
    edit.setAttribute("aria-label", `Edit ${task.title}`);
    edit.append(icon("edit"));
    edit.addEventListener("click", () => openTask(task));
    row.append(
      checkbox,
      content,
      node("span", `priority-badge ${task.priority}`, task.priority),
      edit,
    );
    list.append(row);
  }
  if (!tasks.length) {
    const empty = node("div", "empty-state");
    const mark = node("span", "empty-icon");
    mark.append(icon(state.status === "completed" ? "circle-check" : "box"));
    const isFiltered =
      state.category ||
      state.search ||
      state.priority ||
      state.view !== "overview";
    empty.append(
      mark,
      node("h3", "", isFiltered ? "A clear view." : "A fresh start."),
      node(
        "p",
        "",
        isFiltered
          ? "No tasks match this view. Try another filter, or add something new."
          : "Nothing on your list yet. Add your first task and make a little room in your day.",
      ),
    );
    const add = node("button", "button button-outline", "Add a task");
    add.addEventListener("click", () => openTask());
    empty.append(add);
    list.append(empty);
  }
}

function renderView() {
  const titles = {
    overview: [
      "Agent workspace",
      "Describe the outcome. Let your agent handle the steps.",
      "AI workspace",
    ],
    tasks: [
      state.category
        ? `${state.category.charAt(0).toUpperCase() + state.category.slice(1)} tasks`
        : "Everything, in one place",
      "The big picture, one small task at a time.",
      "All tasks",
    ],
    today: [
      "A little focus for today",
      "Give the things that matter a little space in your day.",
      "Today",
    ],
    upcoming: [
      "A look at what’s next",
      "A clear view of the things coming your way.",
      "Upcoming",
    ],
    completed: [
      "Look how far you’ve come",
      "Every checked box is a little win. These are yours.",
      "Completed",
    ],
  };
  const [title, subtitle, breadcrumb] = titles[state.view];
  $("#page-title").replaceChildren(
    document.createTextNode(title),
    node("span", "", "."),
  );
  $("#page-subtitle").textContent = subtitle;
  $("#breadcrumb-view").textContent = breadcrumb;
  $$("[data-view]").forEach((button) => {
    const active = button.dataset.view === state.view && !state.category;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $$("[data-status]").forEach((button) => {
    button.classList.toggle("active", button.dataset.status === state.status);
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.status === state.status),
    );
  });
  renderTasks();
}

function renderChat(messages) {
  if (state.chatBusy) return;
  $("#chat-messages").replaceChildren();
  if (!messages.length) {
    const welcome = node("section", "agent-welcome");
    const mark = node("div", "welcome-mark");
    mark.append(icon("spark"));
    welcome.append(
      mark,
      node("span", "welcome-kicker", "YOUR PERSONAL AI TASK AGENT"),
      node("h2", "", "From a thought to a done deal."),
      node(
        "p",
        "welcome-description",
        "What’s on your mind? Give TaskMate a goal in your own words. Your model chooses the tools, and your workspace keeps the results.",
      ),
    );
    const cards = node("div", "prompt-grid");
    const prompts = [
      [
        "calendar",
        "Find my focus",
        "Build a plan from my pending tasks.",
        "Plan today with at most 3 tasks.",
      ],
      [
        "plus",
        "Get it off my mind",
        "Turn an idea into a saved task.",
        "Add Study linear algebra for tomorrow, high priority, in category study.",
      ],
      [
        "search",
        "Find what matters",
        "Bring important tasks into view.",
        "Find my high-priority pending tasks.",
      ],
      [
        "download",
        "Take my work with me",
        "Export my task memory.",
        "Export all my tasks as CSV.",
      ],
    ];
    for (const [symbol, title, description, prompt] of prompts) {
      const button = node("button", "prompt-card");
      button.append(
        icon(symbol),
        node("strong", "", title),
        node("small", "", description),
        icon("arrow"),
      );
      button.addEventListener("click", () => {
        $("#chat-input").value = prompt;
        $("#chat-input").focus();
      });
      cards.append(button);
    }
    welcome.append(cards);
    const capabilities = node("div", "capability-line");
    capabilities.append(
      node("span", "", "Natural language"),
      node("span", "", "Real tool calls"),
      node("span", "", "Persistent memory"),
    );
    welcome.append(capabilities);
    $("#chat-messages").append(welcome);
  } else
    messages.forEach((message) =>
      appendMessage(
        message.role,
        message.content,
        message.downloads,
        message.activity,
      ),
    );
}

function executionTime(milliseconds) {
  return milliseconds < 1000
    ? `${milliseconds} ms`
    : `${(milliseconds / 1000).toFixed(1)} s`;
}

function renderActivity(activity = [], run = { phase: "idle", elapsed_ms: 0 }) {
  $("#activity-list").replaceChildren();
  $("#activity-count").textContent = activity.length;
  const phaseLabels = {
    idle: "Idle",
    working: "Running",
    complete: "Complete",
    error: "Needs attention",
  };
  $("#run-phase").textContent = phaseLabels[run.phase] || "Idle";
  $("#run-phase").dataset.phase = run.phase;
  $("#run-time").textContent =
    run.phase === "idle" ? "—" : executionTime(run.elapsed_ms);
  if (!activity.length)
    $("#activity-list").append(
      node(
        "p",
        "activity-empty",
        run.phase === "working"
          ? "Your model is processing the request. Tool calls will appear as they execute."
          : "Send a request to see which tools your model calls and what they return.",
      ),
    );
  for (const event of activity) {
    const item = node("details", `tool-event ${event.status}`);
    const heading = node("summary", "tool-heading");
    const status = node("span", "tool-status");
    status.append(
      icon(
        event.status === "error"
          ? "close"
          : event.status === "running"
            ? "refresh"
            : "check",
      ),
    );
    status.append(node("span", "sr-only", event.status));
    heading.append(
      status,
      node("code", "", `${event.tool}()`),
      node(
        "small",
        "",
        event.duration_ms === null
          ? "running"
          : executionTime(event.duration_ms),
      ),
    );
    item.append(
      heading,
      node("p", "tool-result", event.summary || "Executing tool…"),
      node("pre", "tool-arguments", JSON.stringify(event.arguments, null, 2)),
    );
    $("#activity-list").append(item);
  }
  const running = activity.find((event) => event.status === "running");
  $("#agent-status").textContent =
    run.phase === "working"
      ? running
        ? `Executing ${running.tool}()`
        : activity.length
          ? "Model is preparing a response"
          : "Model is processing your request"
      : run.phase === "complete"
        ? "Request completed"
        : run.phase === "error"
          ? "Request interrupted · review activity"
          : "Ready for your next request";
  $(".live-dot").classList.toggle("working", run.phase === "working");
}

async function refresh() {
  const version = ++refreshVersion;
  const data = await api("/api/state");
  if (version !== refreshVersion) return;
  state.data = data;
  $("#connection-error").hidden = true;
  $("#date-label").textContent = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  })
    .format(new Date(`${data.today}T12:00:00`))
    .toUpperCase();
  for (const name of ["pending", "today", "high", "completed"])
    $(`#stat-${name}`).textContent = data.stats[name];
  $("#nav-all").textContent = data.tasks.length;
  $("#nav-today").textContent = data.stats.today;
  $("#today-note").textContent = data.stats.overdue
    ? `${data.stats.overdue} overdue tasks need a little attention`
    : "Your focus for today";
  const percentage = data.tasks.length
    ? Math.round((data.stats.completed / data.tasks.length) * 100)
    : 0;
  $("#completed-note").textContent = percentage
    ? `${percentage}% of your list, done`
    : "Small wins add up";
  $("#provider-label").textContent =
    data.preferences.provider === "ollama"
      ? "Ollama · local AI"
      : "OpenAI · cloud AI";
  $("#model-label").textContent = data.preferences.model;
  $("#assistant-model").textContent = data.preferences.model.toUpperCase();
  $("#active-model").textContent = data.preferences.model;
  $("#provider-kind").textContent =
    data.preferences.provider === "ollama" ? "LOCAL" : "CLOUD";
  if (!$("#plan-date").value) $("#plan-date").value = data.today;
  renderCategories();
  renderView();
  renderChat(data.messages);
  renderActivity(data.activity, data.run);
  if (state.planActive) await buildPlan(false);
}

async function action(button, callback) {
  if (button) button.disabled = true;
  try {
    await callback();
  } catch (error) {
    toast(
      error.message || "Could not reach TaskMate. Is the server running?",
      true,
    );
  } finally {
    if (button) button.disabled = false;
  }
}

function closeMenu() {
  $("#sidebar").classList.remove("open");
  $("#menu-button").setAttribute("aria-expanded", "false");
}

function openTask(task) {
  state.editId = task?.id || null;
  $("#task-form").reset();
  $("#task-dialog-title").textContent = task
    ? "A little adjustment."
    : "Something to get done.";
  $("#task-title").value = task?.title || "";
  $("#task-deadline").value = task?.deadline || "";
  $("#task-priority").value = task?.priority || "medium";
  $("#task-category").value = task?.category || state.category || "general";
  $("#task-error").hidden = true;
  $("#task-dialog").showModal();
  $("#task-title").focus();
}

async function buildPlan(showMessage = true) {
  if (!$("#plan-date").value) throw new Error("Choose a date for your plan.");
  const parameters = new URLSearchParams({
    day: $("#plan-date").value,
    limit: $("#plan-limit").value,
  });
  if (state.category) parameters.set("category", state.category);
  const plan = await api(`/api/plan?${parameters}`);
  state.planActive = true;
  $("#plan-list").replaceChildren();
  plan.tasks.forEach((task, index) => {
    const row = node("div", "plan-task");
    const text = node("div");
    text.append(
      node("strong", "", task.title),
      node("small", "", `${task.plan_reason} · ${task.priority} priority`),
    );
    row.append(node("span", "plan-number", index + 1), text);
    $("#plan-list").append(row);
  });
  $("#plan-list").append(
    node(
      "p",
      "plan-remaining",
      plan.tasks.length
        ? `${plan.remaining} other pending tasks. One thing at a time.`
        : "No pending tasks for this category. A little breathing room.",
    ),
  );
  if (showMessage) toast("Your daily focus is ready.");
}

function appendMessage(role, text, downloads = [], activity = []) {
  const message = node("div", `chat-message ${role}`);
  message.append(
    node(
      "div",
      "message-author",
      role === "user" ? "YOU" : role === "error" ? "REQUEST ERROR" : "TASKMATE",
    ),
  );
  message.append(node("p", "", text));
  if (activity.length)
    message.append(
      node(
        "div",
        "message-tools",
        `${activity.length} tool call${activity.length === 1 ? "" : "s"} · ${activity.filter((event) => event.status === "success").length} succeeded`,
      ),
    );
  for (const report of downloads) {
    const link = node(
      "a",
      "chat-download",
      `Download ${report.format.toUpperCase()} · ${report.count} tasks`,
    );
    link.href = report.download_url;
    link.download = "";
    message.append(link);
  }
  $("#chat-messages").append(message);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
  return message;
}

$("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#save-task");
  button.disabled = true;
  $("#task-error").hidden = true;
  try {
    const draft = {
      title: $("#task-title").value.trim(),
      deadline: $("#task-deadline").value || null,
      priority: $("#task-priority").value,
      category: $("#task-category").value.trim(),
    };
    const result = await api(
      state.editId ? `/api/tasks/${state.editId}` : "/api/tasks",
      state.editId ? "PATCH" : "POST",
      draft,
    );
    $("#task-dialog").close();
    await refresh();
    toast(
      state.editId
        ? "Task updated. A little clearer."
        : result.created
          ? "Task saved. One less thing to remember."
          : `Task #${result.id} already exists. No duplicate added.`,
    );
  } catch (error) {
    $("#task-error").textContent = error.message;
    $("#task-error").hidden = false;
  } finally {
    button.disabled = false;
  }
});

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.chatBusy) return;
  const text = $("#chat-input").value.trim();
  if (!text) return;
  state.chatBusy = true;
  $(".agent-welcome")?.remove();
  $("#chat-input").value = "";
  $("#send-chat").disabled = true;
  $("#undo-button").disabled = true;
  $("#reset-chat").disabled = true;
  $("#chat-state").textContent =
    "Waiting for your model · watch activity on the right";
  $("#chat-messages").setAttribute("aria-busy", "true");
  appendMessage("user", text);
  const working = appendMessage("assistant", "Processing your request…");
  let polling = false;
  const pollTimer = setInterval(() => {
    if (polling) return;
    polling = true;
    refresh()
      .catch(() => {})
      .finally(() => {
        polling = false;
      });
  }, 1000);
  let failure = "";
  try {
    await api("/api/chat", "POST", { message: text });
  } catch (error) {
    failure = error.message;
    working.remove();
    toast(
      "The assistant request did not finish. Check tasks before retrying.",
      true,
    );
  } finally {
    clearInterval(pollTimer);
    state.chatBusy = false;
    $("#send-chat").disabled = false;
    $("#undo-button").disabled = false;
    $("#reset-chat").disabled = false;
    $("#chat-state").textContent =
      "Enter to send · Shift + Enter for a new line";
    $("#chat-messages").setAttribute("aria-busy", "false");
    // Always reload tasks: a failed model turn may have saved some actions.
    try {
      await refresh();
    } catch (error) {
      toast(error.message, true);
    }
    if (failure) {
      appendMessage("user", text);
      appendMessage("error", failure);
    }
  }
});

$("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#chat-form").requestSubmit();
  }
});
$$("[data-suggestion]").forEach((button) =>
  button.addEventListener("click", () => {
    $("#chat-input").value = button.dataset.suggestion;
    $("#chat-input").focus();
  }),
);
$("#reset-chat").addEventListener("click", () =>
  action($("#reset-chat"), async () => {
    await api("/api/chat/reset", "POST", {});
    await refresh();
    toast("A fresh conversation. Your tasks are still here.");
  }),
);
$$("[data-view]").forEach((button) =>
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    state.category = null;
    state.status =
      state.view === "completed"
        ? "completed"
        : state.view === "tasks"
          ? "all"
          : "pending";
    renderCategories();
    renderView();
    closeMenu();
    if (state.planActive) action(null, () => buildPlan(false));
  }),
);
$$("[data-status]").forEach((button) =>
  button.addEventListener("click", () => {
    state.status = button.dataset.status;
    if (state.view === "completed" && state.status !== "completed")
      state.view = "tasks";
    renderView();
  }),
);
$("#search").addEventListener("input", (event) => {
  state.search = event.target.value.trim();
  renderTasks();
});
$("#priority-filter").addEventListener("change", (event) => {
  state.priority = event.target.value;
  renderTasks();
});
$("#clear-filters").addEventListener("click", () => {
  state.search = "";
  state.priority = "";
  state.category = null;
  $("#search").value = "";
  $("#priority-filter").value = "";
  renderCategories();
  renderView();
  if (state.planActive) action(null, () => buildPlan(false));
});
$("#add-button").addEventListener("click", () => openTask());
$("#add-category").addEventListener("click", () => {
  openTask();
  $("#task-category").value = "";
  $("#task-category").focus();
});
$("#undo-button").addEventListener("click", () =>
  action($("#undo-button"), async () => {
    const result = await api("/api/undo", "POST", {});
    await refresh();
    toast(`Undid ${result.action} for task #${result.task_id}.`);
  }),
);
$("#build-plan").addEventListener("click", () =>
  action($("#build-plan"), () => buildPlan()),
);
$("#focus-plan").addEventListener("click", () =>
  action($("#focus-plan"), async () => {
    await buildPlan();
    $(".plan-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }),
);
$("#refresh-button").addEventListener("click", () =>
  action($("#refresh-button"), async () => {
    await refresh();
    toast("You’re up to date.");
  }),
);
$("#menu-button").addEventListener("click", () => {
  const open = $("#sidebar").classList.toggle("open");
  $("#menu-button").setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    $("#search").focus();
  }
  if (event.key === "Escape") closeMenu();
});
$$("[data-close]").forEach((button) =>
  button.addEventListener("click", () => $(`#${button.dataset.close}`).close()),
);
document.querySelectorAll("dialog").forEach((dialog) =>
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      )
        dialog.close();
    }
  }),
);

async function modelInfo() {
  if ($("#provider").value === "openai")
    $("#model-info").textContent = state.data.openai_configured
      ? "Your API key is configured on the server. Choose a model your account can access."
      : "Add OPENAI_API_KEY to .env and restart the server to use OpenAI. You can use Ollama without a key.";
  else {
    $("#model-info").textContent = "Checking your downloaded models…";
    try {
      const result = await api("/api/models");
      $("#model-options").replaceChildren();
      result.models.forEach((name) => {
        const option = node("option");
        option.value = name;
        $("#model-options").append(option);
      });
      $("#model-info").textContent = result.connected
        ? `${result.models.length} downloaded models found. Choose one with tool-calling support.`
        : "Ollama is not responding. Open the Ollama app, then choose a downloaded model.";
    } catch {
      $("#model-info").textContent =
        "Could not check Ollama. You can still enter your downloaded model name.";
    }
  }
}
$("#connection-button").addEventListener("click", () => {
  if (!state.data) return;
  $("#provider").value = state.data.preferences.provider;
  $("#model").value = state.data.preferences.model;
  $("#settings-error").hidden = true;
  $("#settings-dialog").showModal();
  modelInfo();
});
$("#top-connection").addEventListener("click", () =>
  $("#connection-button").click(),
);
$("#new-conversation").addEventListener("click", () => {
  if (!state.chatBusy) $("#reset-chat").click();
});
$("#provider").addEventListener("change", () => {
  $("#model").value =
    $("#provider").value === "ollama" ? "qwen3:4b" : "gpt-4.1-mini";
  modelInfo();
});
$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    await api("/api/preferences", "POST", {
      provider: $("#provider").value,
      model: $("#model").value.trim(),
    });
    $("#settings-dialog").close();
    await refresh();
    toast("Connection saved. Ready for a fresh conversation.");
  } catch (error) {
    $("#settings-error").textContent = error.message;
    $("#settings-error").hidden = false;
  } finally {
    button.disabled = false;
  }
});
$("#export-button").addEventListener("click", () => {
  $("#export-error").hidden = true;
  $("#export-status").value = state.status;
  $("#export-dialog").showModal();
});
$("#export-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#download-export").disabled = true;
  try {
    const result = await api("/api/exports", "POST", {
      file_format: $("#export-format").value,
      status: $("#export-status").value,
      category: state.category,
      search: state.search || null,
      priority: state.priority || null,
    });
    const link = node("a");
    link.href = result.download_url;
    link.download = "";
    document.body.append(link);
    link.click();
    link.remove();
    $("#export-dialog").close();
    toast(
      `Exported ${result.count} task${result.count === 1 ? "" : "s"}. Your download is ready.`,
    );
  } catch (error) {
    $("#export-error").textContent = error.message;
    $("#export-error").hidden = false;
  } finally {
    $("#download-export").disabled = false;
  }
});

refresh().catch((error) => {
  $("#connection-error").textContent =
    `Could not load your workspace. ${error.message} Use Refresh to try again.`;
  $("#connection-error").hidden = false;
});
