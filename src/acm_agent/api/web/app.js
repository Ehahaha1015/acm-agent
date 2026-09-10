const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
let sessionId = localStorage.getItem("acm-agent-session");
let sending = false;

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
  return row;
}

function addTyping() {
  const row = addMessage("assistant", "");
  row.classList.add("typing");
  row.querySelector(".bubble").innerHTML = "<span></span><span></span><span></span>";
  return row;
}

async function sendMessage(text) {
  if (sending) return;
  sending = true;
  addMessage("user", text);
  input.value = "";
  resizeInput();
  input.disabled = true;
  sendButton.disabled = true;
  const typing = addTyping();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90_000);
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    sessionId = data.session_id;
    localStorage.setItem("acm-agent-session", sessionId);
    typing.remove();
    addMessage("assistant", data.answer, data.tool_result);
  } catch (error) {
    typing.remove();
    const reason = error.name === "AbortError" ? "请求超时，请稍后重试" : error.message;
    addMessage("assistant", `请求失败：${reason}`);
  } finally {
    sending = false;
    input.disabled = false;
    sendButton.disabled = false;
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
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt;
    resizeInput();
    input.focus();
  });
});
document.querySelector("#new-chat").addEventListener("click", () => {
  sessionId = null;
  localStorage.removeItem("acm-agent-session");
  location.reload();
});
document.querySelector("#menu-button").addEventListener("click", () => document.body.classList.add("menu-open"));
document.querySelector("#overlay").addEventListener("click", () => document.body.classList.remove("menu-open"));

async function restoreHistory() {
  if (!sessionId) return;
  try {
    const response = await fetch(`/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (response.status === 404) {
      localStorage.removeItem("acm-agent-session");
      sessionId = null;
      return;
    }
    if (!response.ok) return;
    const data = await response.json();
    data.messages.forEach((message) => addMessage(message.role, message.content));
  } catch (_) {
    // The health indicator below communicates connectivity; history can load next refresh.
  }
}

restoreHistory();

fetch("/health")
  .then((response) => {
    if (!response.ok) throw new Error();
    statusDot.className = "online";
    statusText.textContent = "服务运行正常";
  })
  .catch(() => {
    statusDot.className = "offline";
    statusText.textContent = "无法连接服务";
  });
