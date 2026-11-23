const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {} },
};
let sessionId = storage.get("acm-agent-session");
let sending = false;
let restoring = true;
let transcript = [];
const welcomeTemplate = document.querySelector("#welcome").cloneNode(true);

async function fetchJSON(url, options = {}, timeoutMs = 120_000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((e) => e.msg).join("；") : data.detail;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return data;
  } finally { clearTimeout(timer); }
}

function downloadJSON(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showView(view) {
  document.querySelector("#chat-panel").hidden = view !== "chat";
  document.querySelector("#lab-panel").hidden = view !== "lab";
  for (const name of ["chat", "lab"]) {
    const tab = document.querySelector(`#${name}-tab`);
    tab.classList.toggle("active", name === view);
    tab.setAttribute("aria-pressed", String(name === view));
  }
  document.body.classList.remove("menu-open");
}

document.querySelector("#chat-tab").addEventListener("click", () => showView("chat"));
document.querySelector("#lab-tab").addEventListener("click", () => showView("lab"));
document.querySelector(".lab-menu").addEventListener("click", () => document.body.classList.add("menu-open"));

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 260)}px`;
}

function renderContent(container, text) {
  const fencePattern = /```([^\n`]*)\n?([\s\S]*?)```/g;
  let cursor = 0;
  let match;
  while ((match = fencePattern.exec(text)) !== null) {
    if (match.index > cursor) container.append(document.createTextNode(text.slice(cursor, match.index)));
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    if (match[1].trim()) code.dataset.language = match[1].trim();
    code.textContent = match[2].replace(/^\n|\n$/g, "");
    pre.append(code);
    container.append(pre);
    cursor = fencePattern.lastIndex;
  }
  if (cursor < text.length) container.append(document.createTextNode(text.slice(cursor)));
}

function addMessage(role, text, toolResult = null) {
  document.querySelector("#welcome")?.remove();
  const row = document.createElement("article");
  row.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "你" : "AI";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  renderContent(bubble, text);
  if (toolResult) {
    const details = document.createElement("details");
    details.className = "tool-result";
    const summary = document.createElement("summary");
    summary.textContent = `工具执行结果 · ${toolResult.status || "UNKNOWN"}`;
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(toolResult, null, 2);
    details.append(summary, pre);
    bubble.append(details);
  }
  row.append(avatar, bubble);
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
  if (text) {
    transcript.push({ role, content: text, ...(toolResult ? { tool_result: toolResult } : {}) });
    document.querySelector("#export-chat").disabled = false;
  }
  return row;
}

function addTyping() {
  const row = addMessage("assistant", "");
  row.classList.add("typing");
  row.querySelector(".bubble").innerHTML = "<span></span><span></span><span></span>";
  return row;
}

async function sendMessage(text) {
  if (sending || restoring) return;
  sending = true;
  addMessage("user", text);
  input.value = "";
  resizeInput();
  input.disabled = true;
  sendButton.disabled = true;
  document.querySelector("#new-chat").disabled = true;
  const typing = addTyping();
  try {
    const data = await fetchJSON("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });
    sessionId = data.session_id;
    storage.set("acm-agent-session", sessionId);
    typing.remove();
    addMessage("assistant", data.answer, data.tool_result);
    if (data.degraded) addMessage("assistant", "模型暂不可用，以上展示的是本地工具的真实执行结果。");
    await loadSessions();
  } catch (error) {
    typing.remove();
    const reason = error.name === "AbortError" ? "请求超时，请稍后重试" : error.message;
    addMessage("assistant", `请求失败：${reason}`);
    input.value = text;
    resizeInput();
  } finally {
    sending = false;
    input.disabled = false;
    sendButton.disabled = false;
    document.querySelector("#new-chat").disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (text) sendMessage(text);
});
input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (button) {
    input.value = button.dataset.prompt.replaceAll("\\n", "\n");
    resizeInput();
    input.focus();
  }
});
document.querySelector("#new-chat").addEventListener("click", () => {
  if (sending || restoring) return;
  sessionId = null;
  storage.set("acm-agent-session", null);
  transcript = [];
  messages.replaceChildren(welcomeTemplate.cloneNode(true));
  document.querySelector("#export-chat").disabled = true;
  showView("chat");
  loadSessions();
});
document.querySelector("#menu-button").addEventListener("click", () => document.body.classList.add("menu-open"));
document.querySelector("#overlay").addEventListener("click", () => document.body.classList.remove("menu-open"));

async function restoreHistory() {
  if (!sessionId) { restoring = false; return; }
  input.disabled = sendButton.disabled = true;
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}/messages`, { signal: AbortSignal.timeout(10_000) });
    if (response.status === 404) {
      storage.set("acm-agent-session", null);
      sessionId = null;
      return;
    }
    if (!response.ok) return;
    const data = await response.json();
    data.messages.forEach((message) => addMessage(message.role, message.content, message.tool_result));
  } catch (_) {
    // The health indicator below communicates connectivity; history can load next refresh.
  } finally { restoring = false; input.disabled = sendButton.disabled = false; }
}

async function loadSessions() {
  try {
    const data = await fetchJSON("/sessions", {}, 10_000);
    const list = document.querySelector("#session-list");
    list.replaceChildren();
    for (const session of data.sessions) {
      const row = document.createElement("div");
      row.className = "session-row";
      row.classList.toggle("selected", session.id === sessionId);
      const button = document.createElement("button");
      button.textContent = session.title;
      button.title = session.title;
      button.addEventListener("click", async () => {
        if (sending || restoring) return;
        sessionId = session.id;
        storage.set("acm-agent-session", sessionId);
        transcript = [];
        messages.replaceChildren();
        showView("chat");
        await restoreHistory();
        loadSessions();
      });
      const remove = document.createElement("button");
      remove.className = "delete-session";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `删除对话：${session.title}`);
      remove.addEventListener("click", async () => {
        if (sending || restoring || !confirm("删除这段对话及其历史记录？")) return;
        try {
          await fetchJSON(`/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
          if (session.id === sessionId) document.querySelector("#new-chat").click();
          await loadSessions();
        } catch (error) { alert(`删除失败：${error.message}`); }
      });
      row.append(button, remove);
      list.append(row);
    }
    if (!data.sessions.length) {
      const empty = document.createElement("p");
      empty.className = "empty-history";
      empty.textContent = "还没有对话记录";
      list.append(empty);
    }
  } catch { /* The connectivity indicator reports unavailable service. */ }
}

document.querySelector("#export-chat").addEventListener("click", () => downloadJSON({ session_id: sessionId, messages: transcript }, "acm-conversation.json"));
restoreHistory().then(loadSessions);

fetchJSON("/status", {}, 10_000)
  .then((data) => {
    statusDot.className = "online";
    statusText.textContent = "服务运行正常 · v" + data.version;
    document.querySelector("#environment-detail").textContent = data.executor === "docker" ? "Docker 隔离执行" : (data.compiler_available ? "本地 g++ · 已就绪" : "未找到 g++，请安装 C++ 编译器");
    document.querySelector("#model-detail").textContent = data.model_configured ? `模型：${data.model}` : "离线工具模式 · 模型未配置";
    if (!data.trusted_code_only) document.querySelector("#execution-note").textContent = "Docker 隔离执行 · 有限测试不能证明正确性";
  })
  .catch(() => {
    statusDot.className = "offline";
    statusText.textContent = "无法连接服务";
  });
