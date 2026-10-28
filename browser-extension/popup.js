const $ = (selector) => document.querySelector(selector);
let origin = "http://127.0.0.1:8765";
let workspace = null;
let loadVersion = 0;

function element(tag, className, text) {
  const item = document.createElement(tag);
  item.className = className || "";
  if (text !== undefined) item.textContent = text;
  return item;
}

function message(text, error = false) {
  $("#message").textContent = text;
  $("#message").hidden = false;
  $("#message").classList.toggle("error", error);
}

async function request(path, method = "GET", body) {
  const response = await fetch(origin + path, {
    method,
    signal: AbortSignal.timeout(10000),
    headers:
      method === "GET"
        ? {}
        : {
            "Content-Type": "application/json",
            "X-TaskMate-Token": workspace?.token || "",
          },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      Array.isArray(data.detail)
        ? data.detail.map((item) => item.msg).join(". ")
        : data.detail || "Please refresh and try again.",
    );
  return data;
}

function renderTasks() {
  const search = $("#search").value.trim().toLocaleLowerCase();
  const tasks = workspace.tasks.filter(
    (task) =>
      task.status === "pending" &&
      task.title.toLocaleLowerCase().includes(search),
  );
  $("#tasks").replaceChildren();
  $("#list-count").textContent =
    `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;
  $("#more-tasks").textContent =
    tasks.length > 5 ? `+${tasks.length - 5} in your dashboard` : "";
  for (const task of tasks.slice(0, 5)) {
    const row = element("div", "task");
    const button = element("button", "check");
    button.setAttribute("aria-label", `Complete ${task.title}`);
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await request(`/api/tasks/${task.id}/complete`, "POST", {});
        await load();
        message("Task completed. A little win.");
      } catch (error) {
        message(error.message, true);
        button.disabled = false;
      }
    });
    const content = element("div", "task-content");
    content.append(
      element("div", "task-title", task.title),
      element(
        "div",
        "task-meta",
        `${task.deadline === workspace.today ? "Today" : task.deadline || "No deadline"} · ${task.category}`,
      ),
    );
    row.append(
      button,
      content,
      element("span", `priority ${task.priority}`, task.priority),
    );
    $("#tasks").append(row);
  }
  if (!tasks.length)
    $("#tasks").append(
      element(
        "p",
        "empty",
        search
          ? "No pending tasks match your search."
          : "A clear list. Add something new, or enjoy a little breathing room.",
      ),
    );
}

async function load() {
  const version = ++loadVersion;
  $("#brand-link").href = origin;
  try {
    const result = await request("/api/state?include_session=false");
    if (version !== loadVersion) return;
    workspace = result;
    $("#status").textContent = "Connected to your local workspace";
    $("#status-dot").classList.remove("off");
    $("#offline").hidden = true;
    $("#workspace").hidden = false;
    $("#pending-count").textContent = workspace.stats.pending;
    $("#today-count").textContent = workspace.stats.today;
    $("#done-count").textContent = workspace.stats.completed;
    $("#categories").replaceChildren();
    workspace.categories.forEach((item) => {
      const option = element("option");
      option.value = item.category;
      $("#categories").append(option);
    });
    renderTasks();
  } catch {
    if (version !== loadVersion) return;
    workspace = null;
    $("#status").textContent = "Your local server is offline";
    $("#status-dot").classList.add("off");
    $("#offline").hidden = false;
    $("#workspace").hidden = true;
  }
}

$("#quick-add").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#add-task").disabled = true;
  try {
    const result = await request("/api/tasks", "POST", {
      title: $("#title").value.trim(),
      deadline: $("#deadline").value || null,
      priority: $("#priority").value,
      category: $("#category").value.trim(),
    });
    $("#title").value = "";
    await load();
    message(
      result.created
        ? "Task saved. One less thing to remember."
        : `Task #${result.id} already exists. No duplicate added.`,
    );
  } catch (error) {
    message(error.message || "Could not save. Refresh before retrying.", true);
  } finally {
    $("#add-task").disabled = false;
  }
});
$("#undo").addEventListener("click", async () => {
  $("#undo").disabled = true;
  try {
    const result = await request("/api/undo", "POST", {});
    await load();
    message(`Undid ${result.action} for task #${result.task_id}.`);
  } catch (error) {
    message(error.message, true);
  } finally {
    $("#undo").disabled = false;
  }
});
$("#search").addEventListener("input", renderTasks);
$("#refresh").addEventListener("click", () => {
  $("#message").hidden = true;
  load();
});
$("#settings-button").addEventListener("click", () => {
  $("#settings").hidden = !$("#settings").hidden;
  $("#server-url").value = origin;
});
$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const url = new URL($("#server-url").value);
    if (
      url.protocol !== "http:" ||
      !["127.0.0.1", "localhost"].includes(url.hostname) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      throw new Error("Use a local address, such as http://127.0.0.1:8765.");
    origin = url.origin;
    if (globalThis.chrome?.storage?.local)
      await chrome.storage.local.set({ taskmateOrigin: origin });
    $("#settings").hidden = true;
    await load();
  } catch (error) {
    message(error.message, true);
  }
});
$("#open-dashboard").addEventListener("click", async () => {
  if (globalThis.chrome?.tabs?.create)
    await chrome.tabs.create({ url: origin });
  else window.open(origin, "_blank", "noopener");
});

if (globalThis.chrome?.storage?.local) {
  const saved = await chrome.storage.local.get("taskmateOrigin");
  if (saved.taskmateOrigin) {
    try {
      const url = new URL(saved.taskmateOrigin);
      if (
        url.protocol === "http:" &&
        ["127.0.0.1", "localhost"].includes(url.hostname)
      )
        origin = url.origin;
    } catch {
      /* Keep the default if an old setting is invalid. */
    }
  }
}
load();
