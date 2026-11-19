import {
  ACTION, auditView, authView, beijingInput, bookingList, bookingView, bookView,
  commandDialog, editView, failedView, favoritesView, frame, managedProduct, marketView,
  pathWith, photosView, productList, publicProduct, recoveryView, rolesView, statsView,
} from "./views.js";

const site = document.getElementById("site");
const dialog = document.getElementById("action-dialog");
const toast = document.getElementById("notice");
const publicPages = new Set(["market", "product", "login", "register"]);
const adminPages = new Set(["review", "moderation", "platform-bookings", "accounts", "platform-audit", "platform-stats"]);
const actionsWithReason = new Set(["ban", "mark_violation", "reject_review", "reject_reservation"]);
const pendingInMemory = new Map();
let actor = null;
let renderVersion = 0;
let toastTimer;
let openAction;

class RequestError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, { method = "GET", data, file } = {}) {
  const headers = { Accept: "application/json" };
  if (data !== undefined) headers["Content-Type"] = "application/json";
  if (file) headers["Content-Type"] = file.type;
  let response;
  try {
    response = await fetch("/api" + path, {
      method, headers, body: file || (data !== undefined ? JSON.stringify(data) : undefined),
      credentials: "same-origin", signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new RequestError(0, "connection_lost", "服务暂不可用，请检查连接后重试。");
  }
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    throw new RequestError(response.status, detail?.code, detail?.message || "操作未完成，请刷新后重试。");
  }
  return payload;
}

function pendingKey(id) {
  return "whale-market:pending:" + id;
}

function readPending() {
  if (!actor) return null;
  const key = pendingKey(actor.id);
  try {
    return JSON.parse(sessionStorage.getItem(key) || "null") || pendingInMemory.get(key) || null;
  } catch {
    return pendingInMemory.get(key) || null;
  }
}

function writePending(id, command) {
  const key = pendingKey(id);
  if (command) pendingInMemory.set(key, command);
  else pendingInMemory.delete(key);
  try {
    if (command) sessionStorage.setItem(key, JSON.stringify(command));
    else sessionStorage.removeItem(key);
  } catch {
    // The current page can retain an unfinished command in memory.
  }
}

async function sendCommand(values, retry = false) {
  if (!actor) throw new RequestError(401, "login_required", "请登录后继续。");
  const id = actor.id;
  const previous = readPending();
  if (!retry && previous) throw new RequestError(409, "pending_result", "请先查询上一笔提交结果。");
  const command = retry ? previous : { ...values, submission_key: crypto.randomUUID() };
  if (!command) throw new RequestError(404, "no_pending", "当前没有待确认的提交。");
  writePending(id, command);
  try {
    const response = await api("/commands", { method: "POST", data: command });
    writePending(id, null);
    return response;
  } catch (error) {
    if (error.status > 0 && error.status < 500 && error.status !== 401) {
      writePending(id, null);
    }
    throw error;
  }
}

function route() {
  const full = window.location.hash.slice(1) || "market";
  const divider = full.indexOf("?");
  const path = divider < 0 ? full : full.slice(0, divider);
  const params = Object.fromEntries(new URLSearchParams(divider < 0 ? "" : full.slice(divider + 1)));
  const [name, id] = path.split("/");
  return { name, id, path, params, full };
}

function go(path) {
  const next = "#" + (path || "market");
  if (window.location.hash === next) void render(true);
  else window.location.hash = next;
}

function currentDay(delta = 0) {
  return beijingInput(Date.now() + delta * 86400000).slice(0, 10);
}

async function loadPage(current) {
  const { name, id, params } = current;
  if (name === "login" || name === "register") return authView(name === "register", params.next);
  if (!publicPages.has(name) && actor === null) return authView(false, current.full);
  if (adminPages.has(name) && !actor?.is_admin) return failedView("请使用有管理权限的账号访问。");
  switch (name) {
    case "market":
      return marketView(await api(pathWith("/products", { ...params, scope: "public" })), actor, current);
    case "product":
      return publicProduct(await api("/products/" + encodeURIComponent(id)), actor, current);
    case "favorites":
      return favoritesView(await api(pathWith("/favorites", { page: params.page })), actor, current);
    case "sell":
      return productList(await api(pathWith("/products", { ...params, scope: "mine" })), current);
    case "manage": {
      const product = await api("/products/" + encodeURIComponent(id));
      if (product.seller_id !== actor.id) throw new RequestError(403, "forbidden", "只能管理本人发布的商品。");
      return managedProduct(product, actor, current);
    }
    case "edit": {
      const product = id === "new" ? null : await api("/products/" + encodeURIComponent(id));
      if (product && product.seller_id !== actor.id) throw new RequestError(403, "forbidden", "只能编辑自己的商品。");
      return editView(product);
    }
    case "book":
      return bookView(await api("/products/" + encodeURIComponent(id)), actor);
    case "bookings":
    case "platform-bookings": {
      const admin = name === "platform-bookings";
      const scope = admin ? "all" : params.scope === "sell" ? "sell" : "buy";
      return bookingList(await api(pathWith("/reservations", { ...params, scope })), current, admin);
    }
    case "booking":
      return bookingView(await api("/reservations/" + encodeURIComponent(id)), actor);
    case "review":
    case "moderation": {
      if (id) return managedProduct(await api("/products/" + encodeURIComponent(id)), actor, current);
      const state = name === "review" ? "PENDING" : params.state;
      return productList(await api(pathWith("/products", { ...params, scope: "all", state })), current, true);
    }
    case "accounts":
      return rolesView(await api(pathWith("/admin/accounts", params)), current);
    case "audit":
    case "platform-audit": {
      const admin = name === "platform-audit";
      return auditView(await api(pathWith("/audit", { ...params, scope: admin ? "all" : "mine" })), current, admin);
    }
    case "stats":
    case "platform-stats": {
      const admin = name === "platform-stats";
      const filters = { start: params.start || currentDay(-7), end: params.end || currentDay(1) };
      return statsView(await api(pathWith("/statistics", { ...filters, scope: admin ? "all" : "mine" })), current, admin);
    }
    case "recover":
      return recoveryView(readPending());
    default:
      return failedView("请使用导航选择页面。");
  }
}

async function render(moveFocus = false) {
  const version = ++renderVersion;
  const current = route();
  let content;
  try {
    content = await loadPage(current);
  } catch (error) {
    if (error.status === 401) {
      actor = null;
      content = authView(false, current.full);
    } else {
      content = failedView(error.message);
    }
  }
  if (version !== renderVersion) return;
  site.innerHTML = frame(actor, current, content, Boolean(readPending()));
  if (moveFocus) document.getElementById("main-content").focus();
}

function notify(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  if (readPending()) addRecoveryLink(toast);
  toastTimer = setTimeout(() => { toast.hidden = true; }, readPending() ? 12000 : 4200);
}

function addRecoveryLink(container) {
  const link = document.createElement("a");
  link.href = "#recover";
  link.className = "btn secondary small";
  link.textContent = "查询原提交结果";
  link.addEventListener("click", () => { if (dialog.open) dialog.close(); });
  container.append(" ", link);
}

function showError(form, message) {
  const box = form.querySelector("[data-error]");
  if (!box) return notify(message);
  box.textContent = message;
  box.hidden = false;
  if (readPending()) addRecoveryLink(box);
  box.focus();
}

function formBusy(form, busy) {
  form.toggleAttribute("aria-busy", busy);
  const submit = form.querySelector('button:not([type]), button[type="submit"]');
  if (submit) submit.disabled = busy;
}

function commandFinished(action, response) {
  const result = response.operation;
  notify(response.replayed ? "已恢复原提交结果。" : (ACTION[action] || "操作") + "已保存。");
  if (action === "reserve") go("booking/" + result.reservation_id);
  else if (action === "draft" || action === "edit") go("manage/" + result.product_id);
  else if (route().name === "recover" && result.reservation_id) go("booking/" + result.reservation_id);
  else if (route().name === "recover") go("market");
  else void render(true);
}

function submitFilter(form, fields) {
  for (const value of [fields.minimum, fields.maximum].filter(Boolean)) {
    if (!/^[0-9]{1,6}(?:\.[0-9]{1,2})?$/.test(value.trim()) || Number(value) > 100000) {
      throw new Error("请输入 0 至 100000.00 元，最多两位小数，再筛选。");
    }
  }
  if (fields.minimum && fields.maximum && Number(fields.minimum) > Number(fields.maximum)) {
    throw new Error("最低价不能高于最高价，请修改筛选区间。");
  }
  const strictRange = ["stats", "platform-stats"].includes(form.dataset.filter);
  if (fields.start && fields.end && (fields.start > fields.end || (strictRange && fields.start === fields.end))) {
    throw new Error("请选择有效的开始和结束日期。");
  }
  go(pathWith(form.dataset.filter, fields));
}

async function submitForm(form) {
  const fields = Object.fromEntries(new FormData(form));
  if (form.matches("[data-filter]")) return submitFilter(form, fields);
  const action = form.dataset.form;
  if (action === "register" || action === "login") {
    const credentials = { username: fields.username, password: fields.password };
    if (action === "register") {
      if (fields.password !== fields.confirm) throw new Error("两次输入的密码不一致，请重新填写。");
      await api("/auth/register", { method: "POST", data: credentials });
    }
    actor = await api("/auth/login", { method: "POST", data: credentials });
    notify("已登录。");
    go(form.dataset.next || "market");
    return;
  }
  const existing = form.dataset.id;
  const basedOnProduct = { product_id: Number(existing), version: Number(form.dataset.version) };
  if (action === "edit") {
    const content = {
      title: fields.title, description: fields.description, category: fields.category,
      condition: fields.condition, price: fields.price, image_ids: JSON.parse(form.dataset.images),
    };
    const command = existing ? { action: "edit", ...basedOnProduct, content } : { action: "draft", content };
    return commandFinished(command.action, await sendCommand(command));
  }
  if (action === "reserve") {
    const delivery = { location: fields.location, meeting_at: fields.meeting_at + ":00+08:00" };
    return commandFinished(action, await sendCommand({ action, ...basedOnProduct, delivery }));
  }
}

site.addEventListener("submit", async (event) => {
  const form = event.target.closest("form");
  if (!form || !(form.dataset.form || form.dataset.filter)) return;
  event.preventDefault();
  if (form.hasAttribute("aria-busy")) return;
  formBusy(form, true);
  try {
    await submitForm(form);
  } catch (error) {
    showError(form, error.message);
  } finally {
    formBusy(form, false);
  }
});

function replacePhotos(form, ids) {
  form.dataset.images = JSON.stringify(ids);
  form.querySelector("[data-photos]").innerHTML = photosView(ids);
}

site.addEventListener("change", async (event) => {
  const input = event.target.closest('input[type="file"][name="photos"]');
  if (!input || !input.files.length) return;
  const form = input.form;
  if (form.hasAttribute("aria-busy")) return;
  const previous = JSON.parse(form.dataset.images);
  const files = Array.from(input.files);
  input.value = "";
  if (previous.length + files.length > 5) return showError(form, "最多添加 5 张图片。");
  formBusy(form, true);
  input.disabled = true;
  try {
    for (const file of files) {
      if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 5 * 1024 * 1024) {
        throw new Error("请选择 5 MiB 以内的 JPEG 或 PNG 图片。");
      }
      const image = await api("/images", { method: "POST", file });
      previous.push(image.id);
      replacePhotos(form, previous);
    }
    form.querySelector("[data-error]").hidden = true;
  } catch (error) {
    showError(form, error.message);
  } finally {
    formBusy(form, false);
    input.disabled = false;
  }
});

function showDialog(command, requiredReason = false) {
  openAction = command;
  dialog.innerHTML = commandDialog(command, requiredReason || actionsWithReason.has(command.action));
  dialog.showModal();
}

dialog.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-dialog]")) dialog.close();
});

dialog.addEventListener("cancel", (event) => {
  if (dialog.querySelector("[aria-busy]")) event.preventDefault();
});

dialog.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-dialog-form]");
  if (!form || !openAction) return;
  event.preventDefault();
  if (form.hasAttribute("aria-busy")) return;
  const fields = new FormData(form);
  const command = { ...openAction };
  formBusy(form, true);
  try {
    if (command.action === "grant_admin" || command.action === "revoke_admin") {
      await api("/admin/accounts/" + command.accountId + "/role", {
        method: "PUT", data: { is_admin: command.action === "grant_admin" },
      });
      actor = await api("/auth/me");
      dialog.close();
      notify("管理权限已更新。");
      if (!actor.is_admin) go("market");
      else void render(true);
    } else {
      if (fields.has("reason")) command.reason = fields.get("reason");
      if (command.action === "complete") command.received = fields.has("received");
      const success = await sendCommand(command);
      dialog.close();
      commandFinished(command.action, success);
    }
  } catch (error) {
    showError(form, error.message);
  } finally {
    formBusy(form, false);
  }
});

site.addEventListener("click", async (event) => {
  const element = event.target.closest("button");
  if (!element || element.disabled) return;
  const data = element.dataset;
  if (data.command) return showDialog(JSON.parse(data.command), "requiresReason" in data);
  if (data.role) {
    return showDialog({ action: data.grant === "true" ? "grant_admin" : "revoke_admin", accountId: data.role });
  }
  if (data.removePhoto) {
    const form = element.closest("form");
    if (form.hasAttribute("aria-busy")) return;
    const images = JSON.parse(form.dataset.images).filter((id) => id !== data.removePhoto);
    replacePhotos(form, images);
    form.querySelector('input[name="photos"]').focus();
    return;
  }
  if (data.photo) {
    const main = document.querySelector("[data-main-photo] img");
    main.src = "/api/images/" + encodeURIComponent(data.photo);
    for (const thumb of site.querySelectorAll("[data-photo]")) {
      thumb.setAttribute("aria-pressed", String(thumb === element));
    }
    return;
  }
  element.disabled = true;
  try {
    if ("logout" in data) {
      await api("/auth/logout", { method: "POST" });
      actor = null;
      go("market");
    } else if (data.favorite) {
      if (!actor) return go(pathWith("login", { next: route().full }));
      const saved = element.getAttribute("aria-pressed") === "true";
      await api("/favorites/" + data.favorite, { method: saved ? "DELETE" : "PUT" });
      notify(saved ? "已取消收藏。" : "已收藏商品。");
      await render();
      const next = Array.from(site.querySelectorAll("[data-favorite]"))
        .find((item) => item.dataset.favorite === data.favorite);
      (next || document.getElementById("main-content")).focus();
    } else if (data.delivery) {
      const record = await api("/reservations/" + data.delivery + "/delivery", { method: "POST" });
      if (route().name === "booking" && route().id === data.delivery) {
        site.innerHTML = frame(actor, route(), bookingView(record, actor), Boolean(readPending()));
        document.getElementById("main-content").focus();
      }
    } else if ("retryCommand" in data) {
      const action = readPending()?.action;
      commandFinished(action, await sendCommand({}, true));
    }
  } catch (error) {
    notify(error.message);
    if ("retryCommand" in data && !readPending()) void render(true);
  } finally {
    element.disabled = false;
  }
});

document.querySelector("[data-skip]").addEventListener("click", (event) => {
  const main = document.getElementById("main-content");
  if (main) {
    event.preventDefault();
    main.focus();
  }
});

window.addEventListener("hashchange", () => {
  if (dialog.open) dialog.close();
  void render(true);
});

try {
  actor = await api("/auth/me");
} catch (error) {
  if (error.status !== 401) notify(error.message);
}
await render();
