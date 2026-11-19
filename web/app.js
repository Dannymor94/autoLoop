"use strict";

// All credentials are delivered through an HttpOnly SameSite cookie.
// CSRF stays in JS memory only, never in localStorage/sessionStorage.
let csrf = null;
const pendingStops = new Set();
const $ = (id) => document.getElementById(id);

function notice(message) { $("notice").textContent = message; }

async function api(path, { method = "GET", body = null } = {}) {
  const headers = { "Accept": "application/json" };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === null ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function showAuthenticated(authorized) {
  $("login").hidden = authorized;
  $("dashboard").hidden = !authorized;
  $("connection").textContent = authorized ? "Подключено" : "Вход не выполнен";
  $("connection").classList.toggle("ok", authorized);
}

function button(label, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  element.className = className;
  element.addEventListener("click", action);
  return element;
}

async function mutate(task, command) {
  const idempotency_key = crypto.randomUUID();
  try {
    if (command === "stop") pendingStops.add(task.task_id);
    const result = await api(`/api/tasks/${encodeURIComponent(task.task_id)}/${command}`, { method: "POST", body: { idempotency_key } });
    if (command === "stop") notice(`${task.task_id}: ${result.status}; ожидаем подтверждение остановки.`);
    else notice(`${task.task_id}: ${result.state}; можно запускать новую попытку.`);
    await refresh();
  } catch (error) {
    if (command === "stop") pendingStops.delete(task.task_id);
    notice(`Команда ${command} не подтверждена: ${error.message}`);
  }
}

function renderTask(task) {
  const article = document.createElement("article");
  article.className = "task";
  const name = document.createElement("h3");
  name.textContent = task.task_id;
  article.append(name);
  const details = document.createElement("div");
  details.className = "meta";
  details.textContent = `Проект: ${task.project_id} · Статус: ${task.state} · Версия: ${task.version} · Исправления: ${task.repair_count}${task.reason ? ` · Причина: ${task.reason}` : ""}`;
  article.append(details);
  const controls = document.createElement("div");
  controls.className = "buttons";
  if (task.state === "RUNNING") {
    const stop = button(pendingStops.has(task.task_id) ? "Ожидание Stop…" : "Остановить", () => mutate(task, "stop"), "warning");
    stop.disabled = pendingStops.has(task.task_id);
    controls.append(stop);
  } else {
    pendingStops.delete(task.task_id);
  }
  if (task.state === "BLOCKED" && task.reason === "OWNER_STOP") {
    controls.append(button("Возобновить", () => mutate(task, "resume"), "primary"));
  }
  controls.append(button("События", async () => {
    try {
      const events = await api(`/api/tasks/${encodeURIComponent(task.task_id)}/events`);
      const recent = events.slice(-4).map((event) => `${event.event} → ${event.to}`).join("; ");
      notice(recent || "События пока отсутствуют");
    } catch (error) { notice(error.message); }
  }));
  article.append(controls);
  return article;
}

async function refresh() {
  const tasks = await api("/api/tasks");
  const target = $("tasks");
  target.replaceChildren(...tasks.map(renderTask));
  if (tasks.length === 0) notice("Задач пока нет. Создание выполняется через диспетчер API.");
}

async function restore() {
  try {
    const session = await api("/api/session");
    csrf = session.csrf_token;
    showAuthenticated(true);
    await refresh();
  } catch (_error) {
    csrf = null;
    showAuthenticated(false);
  }
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: { password: $("password").value } });
    $("password").value = "";
    await restore();
    notice("Вход выполнен.");
  } catch (error) { notice(`Вход не выполнен: ${error.message}`); }
});
$("logout").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } finally { csrf = null; showAuthenticated(false); notice("Вы вышли."); }
});
$("refresh").addEventListener("click", () => refresh().catch((error) => notice(error.message)));
setInterval(() => { if (csrf) refresh().catch((error) => notice(error.message)); }, 5000);
restore();
