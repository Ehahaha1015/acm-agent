const modeSelect = document.querySelector("#execute-mode");
const executionForm = document.querySelector("#execute-form");
const resultPanel = document.querySelector("#execution-result");
let lastExecution = null;
let executing = false;

const languageLabels = { cpp: "C++20", c: "C17", python: "Python 3", java: "Java 17" };
const examplesReady = fetchJSON("/static/examples.json", {}, 10_000).catch(() => null);
const languageSelect = document.querySelector("#code-language");
function selectedLanguage(role) {
  const value = document.querySelector(`#${role}-language`)?.value;
  return !value || value === "same" ? languageSelect.value : value;
}
function updateLanguage() {
  const language = languageSelect.value;
  document.querySelector("#language-badge").textContent = languageLabels[language];
  document.querySelector("#candidate-label").textContent = `待验证的 ${languageLabels[language]} 程序`;
  const hints = {
    cpp: "C++20 · g++ -O2 · 单文件程序",
    c: "C17 · gcc -O2 · 已链接数学库 libm",
    python: "Python 3 · 先做语法检查 · 支持标准库 · 隔离模式运行",
    java: "Java 17 · 使用 class Main 和 main 方法，不写 package · 堆上限 128 MiB",
  };
  const status = window.acmRuntimeStatus;
  const unavailable = status?.executor === "local" && status.runtimes?.[language]?.available === false;
  document.querySelector("#language-help").textContent = hints[language] + (unavailable ? " · 本机尚未安装此工具链，请参照 README 配置" : " · 切换语言后可载入对应示例");
  const placeholders = { cpp: "#include <iostream>\nint main() {}", c: "#include <stdio.h>\nint main(void) { return 0; }", python: "print('Hello, ACM!')", java: "public class Main {\n    public static void main(String[] args) {}\n}" };
  document.querySelector("#candidate-code").placeholder = placeholders[language];
  updateMode();
}
window.addEventListener("acm-status", updateLanguage);
for (const id of ["code-language", "reference-language", "generator-language"]) {
  document.getElementById(id).addEventListener("change", updateLanguage);
}

function updateMode() {
  const mode = modeSelect.value;
  document.querySelector("#reference-field").hidden = !["compare", "stress"].includes(mode);
  document.querySelector("#reference-code").required = ["compare", "stress"].includes(mode);
  document.querySelector("#generator-field").hidden = mode !== "stress";
  document.querySelector("#generator-code").required = mode === "stress";
  document.querySelector("#stdin-field").hidden = ["compile", "stress"].includes(mode);
  document.querySelectorAll(".stress-setting").forEach((element) => { element.hidden = mode !== "stress"; });
  document.querySelector("#execute-button").textContent = { compile: languageSelect.value === "python" ? "▶ 语法检查" : "▶ 编译检查", run: "▶ 运行验证", compare: "▶ 差分测试", stress: "▶ 开始对拍" }[mode];
}

async function loadExample() {
  if (executing) return;
  const examples = await examplesReady;
  if (!examples) { resultPanel.textContent = "示例加载失败，请刷新页面后重试。"; return; }
  const candidate = examples[languageSelect.value];
  document.querySelector("#candidate-code").value = ["run", "compile"].includes(modeSelect.value) ? candidate.reference : candidate.candidate;
  document.querySelector("#reference-code").value = examples[selectedLanguage("reference")].reference;
  document.querySelector("#generator-code").value = examples[selectedLanguage("generator")].generator;
  document.querySelector("#stdin").value = "3\n-2 -5 -1\n";
  saveDraft();
}

const draftFields = ["candidate-code", "reference-code", "generator-code", "stdin", "execute-mode", "run-timeout", "iterations", "start-seed", "code-language", "reference-language", "generator-language"];
function saveDraft() {
  storage.set("acm-lab-draft", JSON.stringify(Object.fromEntries(draftFields.map((id) => [id, document.getElementById(id).value]))));
  if (lastExecution && !executing && !document.querySelector("#stale-result")) {
    const hint = document.createElement("p");
    hint.id = "stale-result";
    hint.className = "result-hint";
    hint.textContent = "代码或设置已修改。下方仍为上次执行的结果，请重新验证。";
    resultPanel.prepend(hint);
  }
}
try {
  const draft = JSON.parse(storage.get("acm-lab-draft") || "null");
  if (draft) for (const id of draftFields) {
    if (typeof draft[id] === "string") document.getElementById(id).value = draft[id];
  }
} catch { /* An invalid browser draft should not prevent using the workspace. */ }
if (!modeSelect.value) modeSelect.value = "run";
if (!languageSelect.value) languageSelect.value = "cpp";
for (const id of ["reference-language", "generator-language"]) {
  if (!document.getElementById(id).value) document.getElementById(id).value = "same";
}
for (const id of draftFields) document.getElementById(id).addEventListener("input", saveDraft);
modeSelect.addEventListener("change", updateMode);
document.querySelector("#load-example").addEventListener("click", loadExample);
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-lab]");
  if (!button) return;
  if (executing) { showView("lab"); return; }
  modeSelect.value = button.dataset.lab;
  updateMode();
  if (!document.querySelector("#candidate-code").value) loadExample();
  showView("lab");
});

const verdicts = {
  OK: ["运行完成", "success"], COMPILE_OK: ["编译通过", "success"],
  WRONG_ANSWER_FOUND: ["发现反例", "failure"], ALL_TESTS_PASSED: ["所有样例一致", "success"],
  ALL_STRESS_TESTS_PASSED: ["本轮对拍通过", "success"], STRESS_TIME_LIMIT: ["对拍预算耗尽", "warning"],
  COMPARE_TIME_LIMIT: ["差分预算耗尽", "warning"],
  TIME_LIMIT_EXCEEDED: ["运行超时", "failure"], OUTPUT_LIMIT_EXCEEDED: ["输出超出限制", "failure"],
  COMPILE_ERROR: ["编译失败", "failure"], COMPILE_TIMEOUT: ["编译超时", "failure"],
  RUNTIME_ERROR: ["运行错误", "failure"], SANDBOX_UNAVAILABLE: ["执行环境不可用", "warning"],
  TOOLCHAIN_UNAVAILABLE: ["语言工具链不可用", "warning"],
};

function outputCard(title, value) {
  const card = document.createElement("div");
  card.className = "output-card";
  const bar = document.createElement("div");
  const label = document.createElement("strong");
  label.textContent = title;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "text-button";
  copy.textContent = "复制";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(value); copy.textContent = "已复制"; }
    catch { copy.textContent = "请手动选择复制"; }
  });
  bar.append(label, copy);
  const pre = document.createElement("pre");
  pre.textContent = value || "（空）";
  card.append(bar, pre);
  return card;
}

function renderResult(payload) {
  const result = payload.result;
  let [label, tone] = verdicts[result.status] || [result.status, "failure"];
  if (result.status === "COMPILE_OK" && result.language === "python") label = "语法检查通过";
  resultPanel.replaceChildren();
  const heading = document.createElement("div");
  heading.className = `result-heading ${tone}`;
  const title = document.createElement("h3");
  title.textContent = label;
  const meta = document.createElement("span");
  meta.textContent = `${languageLabels[payload.languages?.candidate] || ""} · ${result.status} · ${(payload.duration_ms / 1000).toFixed(2)}s`;
  heading.append(title, meta);
  resultPanel.append(heading);
  if (payload.languages && ["compare", "stress"].includes(modeSelect.value)) {
    const languages = document.createElement("p");
    languages.className = "result-hint";
    languages.textContent = `Candidate: ${languageLabels[payload.languages.candidate]} · Reference: ${languageLabels[payload.languages.reference]}` + (modeSelect.value === "stress" ? ` · Generator: ${languageLabels[payload.languages.generator]}` : "");
    resultPanel.append(languages);
  }
  if (result.seed !== undefined || result.test_number !== undefined) {
    const seed = document.createElement("p");
    seed.className = "result-hint";
    seed.textContent = result.seed !== undefined ? `复现种子：${result.seed} · 将起始种子设为此值即可复现` : `第 ${result.test_number} 个测试用例发现问题`;
    resultPanel.append(seed);
  }
  const grid = document.createElement("div");
  grid.className = "output-grid";
  for (const [key, titleText] of [["input", "反例输入"], ["candidate_output", "Candidate 输出"], ["reference_output", "Reference 输出"], ["stdout", "标准输出"], ["stderr", "诊断信息"]]) {
    if (result[key] !== undefined && (key !== "stderr" || result[key])) grid.append(outputCard(titleText, result[key]));
  }
  if (result.compile?.stderr && !result.stderr) grid.append(outputCard("编译诊断", result.compile.stderr));
  for (const target of ["candidate", "reference", "generator"]) {
    if (result[target]?.stderr) grid.append(outputCard(`${target} 诊断`, result[target].stderr));
  }
  resultPanel.append(grid);
  const hint = document.createElement("p");
  hint.className = "result-hint";
  hint.textContent = result.message || result.warning || (result.tests_run !== undefined ? `已验证 ${result.tests_run} 个用例。有限测试不能证明正确性。` : result.iterations !== undefined ? `已完成 ${result.iterations} 轮对拍。随机测试不能证明正确性。` : "以上结果来自真实编译器与进程执行。");
  resultPanel.append(hint);
  const details = document.createElement("details");
  details.className = "tool-result";
  const summary = document.createElement("summary");
  summary.textContent = "完整执行记录与工具事件";
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(payload, null, 2);
  details.append(summary, pre);
  resultPanel.append(details);
}

executionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (executing) return;
  executing = true;
  saveDraft();
  const request = {
    language: languageSelect.value,
    reference_language: selectedLanguage("reference"), generator_language: selectedLanguage("generator"),
    mode: modeSelect.value, code: document.querySelector("#candidate-code").value,
    reference_code: document.querySelector("#reference-code").value,
    generator_code: document.querySelector("#generator-code").value,
    input_data: document.querySelector("#stdin").value,
    timeout: Number(document.querySelector("#run-timeout").value),
    iterations: Number(document.querySelector("#iterations").value),
    start_seed: Number(document.querySelector("#start-seed").value),
  };
  executionForm.querySelectorAll("button, input, textarea, select").forEach((element) => { element.disabled = true; });
  resultPanel.textContent = "正在真实编译与执行… 随机对拍包含 30 秒测试预算。";
  resultPanel.setAttribute("aria-busy", "true");
  try {
    const payload = await fetchJSON("/execute", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
    lastExecution = { ...payload, request };
    renderResult(payload);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    resultPanel.textContent = error.name === "AbortError" ? "请求超时，请检查服务运行情况。" : `执行失败：${error.message}`;
  } finally {
    executing = false;
    resultPanel.setAttribute("aria-busy", "false");
    executionForm.querySelectorAll("button, input, textarea, select").forEach((element) => { element.disabled = false; });
    document.querySelector("#download-result").disabled = !lastExecution;
  }
});
document.querySelector("#download-result").addEventListener("click", () => downloadJSON(lastExecution, "acm-verification.json"));
updateLanguage();
