// These tests run the real interface scripts against a disposable Python API.
// jsdom checks interactions, not layout or the browser's extension installer.
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

let server, folder, origin;

async function waitFor(check, label) {
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((done) => setTimeout(done, 15));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

before(async () => {
  folder = await mkdtemp(join(tmpdir(), "taskmate-ui-"));
  const socket = createServer();
  socket.listen(0, "127.0.0.1");
  await once(socket, "listening");
  const port = socket.address().port;
  await new Promise((done) => socket.close(done));
  origin = `http://127.0.0.1:${port}`;
  const python =
    process.env.TASKMATE_TEST_PYTHON ||
    (process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python");
  server = spawn(
    python,
    ["tests/web/server_fixture.py", join(folder, "tasks.db"), String(port)],
    {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        LLM_PROVIDER: "ollama",
        OLLAMA_MODEL: "test-local-model",
        TASK_TIMEZONE: "Asia/Kolkata",
      },
    },
  );
  let failure = "";
  server.stderr.on("data", (data) => {
    failure += data;
  });
  server.on("error", (error) => {
    failure += error.message;
  });
  await waitFor(async () => {
    if (server.exitCode !== null)
      throw new Error(failure || "Test server exited early");
    try {
      return (await fetch(origin + "/api/state?include_session=false")).ok;
    } catch {
      return false;
    }
  }, "the disposable API server");
});

after(async () => {
  if (server && server.exitCode === null) {
    const exited = once(server, "exit");
    server.kill();
    await exited;
  }
  // Only remove the temporary directory this test created.
  if (
    folder &&
    dirname(resolve(folder)) === resolve(tmpdir()) &&
    basename(folder).startsWith("taskmate-ui-")
  ) {
    await rm(folder, { recursive: true, force: true });
  }
});

async function openInterface(kind) {
  const extension = kind === "extension";
  const html = await readFile(
    extension
      ? "browser-extension/popup.html"
      : "task_manager/web_assets/index.html",
    "utf8",
  );
  const source = await readFile(
    extension ? "browser-extension/popup.js" : "task_manager/web_assets/app.js",
    "utf8",
  );
  const errors = [],
    downloads = [],
    tabs = [],
    saved = { taskmateOrigin: origin };
  const console = new VirtualConsole();
  console.on("jsdomError", (error) => errors.push(error.message));
  const dom = new JSDOM(html, {
    url: origin + "/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: console,
  });
  const { window } = dom;
  let cookie = "",
    offline = false;
  window.AbortSignal = AbortSignal;
  window.fetch = async (path, options = {}) => {
    if (offline) throw new Error("Test connection offline");
    if (String(path).endsWith("/api/models"))
      return new Response(
        JSON.stringify({ connected: true, models: ["test-local-model"] }),
      );
    const headers = new Headers(options.headers);
    if (extension)
      headers.set("Origin", "chrome-extension://" + "a".repeat(32));
    else if (cookie) headers.set("Cookie", cookie);
    const response = await fetch(new URL(path, origin), {
      ...options,
      headers,
    });
    if (!extension && response.headers.get("set-cookie"))
      cookie = response.headers.get("set-cookie").split(";")[0];
    return response;
  };
  window.chrome = {
    storage: {
      local: {
        get: async () => ({ ...saved }),
        set: async (values) => Object.assign(saved, values),
      },
    },
    tabs: { create: async (tab) => tabs.push(tab) },
  };
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  window.HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  window.HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute("download")) downloads.push(this.href);
  };
  window.eval(extension ? `(async () => { ${source}\n })()` : source);
  const $ = (selector) => window.document.querySelector(selector);
  const $$ = (selector) => [...window.document.querySelectorAll(selector)];
  const fill = (selector, value, type = "input") => {
    $(selector).value = value;
    $(selector).dispatchEvent(new window.Event(type, { bubbles: true }));
  };
  const submit = (selector) => {
    const form = $(selector);
    form.dispatchEvent(
      new window.SubmitEvent("submit", {
        bubbles: true,
        cancelable: true,
        submitter: form.querySelector('[type="submit"]'),
      }),
    );
  };
  return {
    dom,
    window,
    $,
    $$,
    fill,
    submit,
    errors,
    downloads,
    tabs,
    saved,
    setOffline(value) {
      offline = value;
    },
  };
}

test("dashboard: create, duplicate, edit, filters, complete, undo, plan, export, chat, and settings", async () => {
  const ui = await openInterface("dashboard");
  const { $, $$, fill, submit, window } = ui;
  try {
    await waitFor(
      () => $("#stat-pending").textContent === "2",
      "initial tasks",
    );
    $("#add-button").click();
    assert.ok($("#task-dialog").hasAttribute("open"));
    fill("#task-title", "Review the web interface");
    fill("#task-deadline", "2026-10-29");
    fill("#task-priority", "high");
    fill("#task-category", "study");
    submit("#task-form");
    await waitFor(
      () => $("#stat-pending").textContent === "3",
      "task creation",
    );

    $("#add-button").click();
    fill("#task-title", "Review the web interface");
    fill("#task-deadline", "2026-10-29");
    fill("#task-priority", "low");
    fill("#task-category", "study");
    submit("#task-form");
    await waitFor(
      () => $("#toast").textContent.includes("already exists"),
      "duplicate detection",
    );
    assert.equal($("#stat-pending").textContent, "3");

    $('[aria-label="Edit Review the web interface"]').click();
    fill("#task-title", "Review UI integration");
    fill("#task-priority", "low");
    fill("#task-category", "personal");
    fill("#task-deadline", "2026-10-31");
    submit("#task-form");
    await waitFor(
      () => $('[aria-label="Complete Review UI integration"]'),
      "task edit",
    );
    fill("#search", "UI integration");
    assert.equal($$(".task-row").length, 1);
    assert.equal($(".priority-badge").textContent, "low");
    $('[aria-label="Complete Review UI integration"]').click();
    await waitFor(() => $("#stat-completed").textContent === "1", "completion");
    $("#undo-button").click();
    await waitFor(
      () =>
        $("#stat-completed").textContent === "0" &&
        $('[aria-label="Complete Review UI integration"]'),
      "undo completion",
    );

    $$(".category-button")
      .find((button) => button.textContent.startsWith("personal"))
      .click();
    assert.equal($$(".task-row").length, 1);
    $("#clear-filters").click();
    fill("#priority-filter", "high", "change");
    assert.equal($$(".task-row").length, 1);
    fill("#priority-filter", "", "change");
    $('[data-view="completed"]').click();
    assert.equal($$(".task-row").length, 0);
    $('[data-view="overview"]').click();
    fill("#plan-date", "2026-10-28");
    $("#build-plan").click();
    await waitFor(() => $$(".plan-task").length === 3, "daily plan");

    fill("#search", "UI integration");
    $("#export-button").click();
    fill("#export-format", "json");
    fill("#export-status", "all");
    submit("#export-form");
    await waitFor(() => ui.downloads.length === 1, "export download");
    const exported = await (await fetch(ui.downloads[0])).json();
    assert.equal(exported.length, 1);
    assert.equal(exported[0].title, "Review UI integration");
    fill("#search", "");

    fill("#chat-input", "Add a chat task");
    submit("#chat-form");
    await waitFor(
      () =>
        !$("#send-chat").disabled &&
        $("#chat-messages").textContent.includes("Added from dashboard chat"),
      "chat action",
    );
    assert.ok(
      $$(".task-title").some(
        (item) => item.textContent === "Added from dashboard chat",
      ),
    );
    fill("#chat-input", "Export my tasks");
    submit("#chat-form");
    await waitFor(
      () => !$("#send-chat").disabled && $(".chat-download"),
      "chat export link",
    );
    const chatExport = await fetch($(".chat-download").href);
    assert.equal(chatExport.status, 200);
    assert.match(await chatExport.text(), /Added from dashboard chat/);
    fill("#chat-input", "Fail after saving");
    submit("#chat-form");
    await waitFor(
      () => !$("#send-chat").disabled && $(".chat-message.error"),
      "model failure feedback",
    );
    assert.ok(
      $$(".task-title").some(
        (item) => item.textContent === "Saved before model failure",
      ),
    );
    assert.match(
      $(".chat-message.error").textContent,
      /Check tasks before retrying/,
    );

    $("#connection-button").click();
    fill("#model", "test-ui-model");
    submit("#settings-form");
    await waitFor(
      () => $("#model-label").textContent === "test-ui-model",
      "connection preferences",
    );
    $("#reset-chat").click();
    await waitFor(
      () =>
        !$("#reset-chat").disabled &&
        $("#chat-messages").textContent.includes("What’s on your mind?"),
      "conversation reset",
    );
    window.document.dispatchEvent(
      new window.KeyboardEvent("keydown", {
        key: "k",
        ctrlKey: true,
        bubbles: true,
      }),
    );
    assert.equal(window.document.activeElement, $("#search"));
    assert.deepEqual(ui.errors, []);
  } finally {
    ui.dom.window.close();
  }
});

test("extension popup: shared tasks, quick add, search, complete, undo, settings, and offline recovery", async () => {
  const ui = await openInterface("extension");
  const { $, fill, submit } = ui;
  try {
    await waitFor(() => !$("#workspace").hidden, "popup connection");
    const initial = Number($("#pending-count").textContent);
    fill("#title", "Task from the browser extension");
    fill("#category", "personal");
    fill("#priority", "high");
    submit("#quick-add");
    await waitFor(
      () => Number($("#pending-count").textContent) === initial + 1,
      "extension quick add",
    );
    fill("#search", "browser extension");
    assert.equal($("#tasks").querySelectorAll(".task").length, 1);
    $('[aria-label="Complete Task from the browser extension"]').click();
    await waitFor(
      () => Number($("#pending-count").textContent) === initial,
      "extension completion",
    );
    $("#undo").click();
    await waitFor(
      () => Number($("#pending-count").textContent) === initial + 1,
      "extension undo",
    );
    $("#open-dashboard").click();
    await waitFor(() => ui.tabs.length === 1, "dashboard launcher");
    assert.equal(ui.tabs[0].url, origin);
    $("#settings-button").click();
    fill("#server-url", "https://unrelated.example");
    submit("#settings-form");
    await waitFor(
      () => $("#message").textContent.includes("Use a local address"),
      "invalid server address",
    );
    assert.equal(ui.saved.taskmateOrigin, origin);
    fill("#server-url", origin);
    submit("#settings-form");
    await waitFor(() => $("#settings").hidden, "saved connection");
    ui.setOffline(true);
    $("#refresh").click();
    await waitFor(() => !$("#offline").hidden, "offline state");
    assert.ok($("#workspace").hidden);
    ui.setOffline(false);
    $("#refresh").click();
    await waitFor(() => !$("#workspace").hidden, "connection recovery");
    assert.deepEqual(ui.errors, []);
  } finally {
    ui.dom.window.close();
  }
});
